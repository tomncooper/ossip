"""Tests for ipper.events.store: loading, append semantics, locking, version guard."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import ipper.events.store as store
from ipper.events.models import EventCandidate, EventRecord, SeenState
from ipper.events.store import (
    EventsVersionError,
    append_events,
    load_events,
    load_seen,
    save_seen,
    update_from_cache,
)

NOW = "2026-10-01T09:30:00+00:00"


def make_candidate(
    key: str = "kafka:kip-1",
    event_type: str = "new",
    state_after: str | None = "under discussion",
    effective_at: str | None = None,
    **kwargs,
) -> EventCandidate:
    defaults = {
        "project": "kafka",
        "key": key,
        "event_type": event_type,
        "reference": "KIP-1",
        "title": "T",
        "observed_at": NOW,
        "effective_at": effective_at,
        "effective_at_source": None,
        "detail_url": "https://x",
        "state_after": state_after,
    }
    defaults.update(kwargs)
    return EventCandidate(**defaults)


def as_record_dict(candidate: EventCandidate, seq: int = 1) -> dict:
    """Candidate dict with the append-time fields filled in (for log fixtures)."""
    base = {
        "seq": seq,
        "stable_id": f"{candidate.key}/{candidate.event_type}@{candidate.observed_at[:10]}",
    }
    base.update(candidate.model_dump())
    return base


@pytest.fixture
def event_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the events store to a tmp directory."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(store, "EVENTS_DIR", events_dir)
    monkeypatch.setattr(store, "EVENTS_FILE", events_dir / "events.jsonl")
    monkeypatch.setattr(store, "SEEN_FILE", events_dir / "last_seen.json")
    monkeypatch.setattr(store, "LOCK_FILE", events_dir / ".lock")
    return events_dir


# ---------------------------------------------------------------------------
# load_events
# ---------------------------------------------------------------------------


class TestLoadEvents:
    def test_absent_file_returns_empty(self, event_dirs):
        assert load_events(store.EVENTS_FILE) == []

    def test_golden_fixture_loads(self, event_dirs):
        import shutil

        golden = Path(__file__).parent / "fixtures" / "golden_events.jsonl"
        shutil.copy(golden, store.EVENTS_FILE)
        events = load_events(store.EVENTS_FILE)
        assert len(events) == 7
        assert [e.seq for e in events] == list(range(1, 8))

    def test_corrupt_middle_line_skipped(self, event_dirs):
        good1 = as_record_dict(make_candidate(key="kafka:kip-1"))
        good2 = as_record_dict(
            make_candidate(
                key="kafka:kip-2",
                reference="KIP-2",
                effective_at="2026-09-01T00:00:00+00:00",
            ),
            seq=2,
        )
        store.EVENTS_FILE.write_text(
            json.dumps(good1) + "\n" + "{not json at all\n" + json.dumps(good2) + "\n",
            encoding="utf-8",
        )
        events = load_events(store.EVENTS_FILE)
        assert [e.key for e in events] == ["kafka:kip-1", "kafka:kip-2"]

    def test_validation_failure_skipped(self, event_dirs):
        good = as_record_dict(make_candidate())
        bad = {
            **good,
            "key": "kafka:kip-bad",
            "observed_at": None,
        }  # required field None
        store.EVENTS_FILE.write_text(
            json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8"
        )
        events = load_events(store.EVENTS_FILE)
        assert len(events) == 1

    def test_torn_final_line_dropped(self, event_dirs):
        good = as_record_dict(make_candidate())
        store.EVENTS_FILE.write_text(
            json.dumps(good) + "\n" + '{"seq": 99, "stable_id": "tear',
            encoding="utf-8",
        )
        events = load_events(store.EVENTS_FILE)
        assert len(events) == 1
        assert events[0].seq == 1

    def test_unknown_fields_and_types_tolerated(self, event_dirs):
        line = json.dumps(
            {
                **as_record_dict(make_candidate(key="kafka:kip-9")),
                "event_type": "brand_new_type",
                "mystery_field": 42,
                "schema_version": 99,
            }
        )
        store.EVENTS_FILE.write_text(line + "\n", encoding="utf-8")
        events = load_events(store.EVENTS_FILE)
        assert len(events) == 1
        assert events[0].event_type == "brand_new_type"


# ---------------------------------------------------------------------------
# append_events
# ---------------------------------------------------------------------------


class TestAppendEvents:
    def test_appends_and_returns_records(self, event_dirs):
        events = []
        appended = append_events(events, [make_candidate()], store.EVENTS_FILE)
        assert len(appended) == 1
        assert appended[0].seq == 1
        assert appended[0].stable_id == "kafka:kip-1/new@2026-10-01"

    def test_seqs_strictly_increase_across_calls(self, event_dirs):
        events: list[EventRecord] = []
        first = append_events(
            events,
            [make_candidate(), make_candidate(key="kafka:kip-2", reference="KIP-2")],
            store.EVENTS_FILE,
        )
        second = append_events(
            first,
            [make_candidate(key="kafka:kip-3", reference="KIP-3")],
            store.EVENTS_FILE,
        )
        all_events = load_events(store.EVENTS_FILE)
        assert [e.seq for e in all_events] == [1, 2, 3]
        assert first[0].seq == 1 and second[0].seq == 3

    def test_replay_dedup_drops_identical_candidate(self, event_dirs):
        events = append_events(events := [], [make_candidate()], store.EVENTS_FILE)
        replay = append_events(events, [make_candidate()], store.EVENTS_FILE)
        assert replay == []
        assert len(load_events(store.EVENTS_FILE)) == 1

    def test_identity_includes_state_and_reference_before(self, event_dirs):
        events = append_events(
            [],
            [
                make_candidate(
                    event_type="state_changed", state_before="a", state_after="b"
                )
            ],
            store.EVENTS_FILE,
        )
        # different state_before -> different identity, same day
        again = append_events(
            events,
            [
                make_candidate(
                    event_type="state_changed", state_before="a", state_after="c"
                )
            ],
            store.EVENTS_FILE,
        )
        assert len(again) == 1
        assert again[0].stable_id.endswith("-2")

    def test_stable_id_suffix_increments_on_collision(self, event_dirs):
        # same key/type/day but different content (state_after differs), so
        # identity dedup does not apply and only stable_id collides
        events = append_events(
            [],
            [
                make_candidate(),
                make_candidate(
                    state_after="unknown", effective_at="2026-10-01T08:00:00+00:00"
                ),
            ],
            store.EVENTS_FILE,
        )
        assert [e.stable_id for e in events] == [
            "kafka:kip-1/new@2026-10-01",
            "kafka:kip-1/new@2026-10-01-2",
        ]

    def test_lines_are_byte_identical_json(self, event_dirs):
        candidate = make_candidate()
        append_events([], [candidate], store.EVENTS_FILE)
        raw = store.EVENTS_FILE.read_bytes()
        assert raw.endswith(b"\n")
        line = raw.decode().strip()
        parsed = json.loads(line)
        record = EventRecord.model_validate(parsed)
        assert json.dumps(record.model_dump()) == line

    def test_empty_candidates_noop(self, event_dirs):
        assert append_events([], [], store.EVENTS_FILE) == []
        assert not store.EVENTS_FILE.exists()


# ---------------------------------------------------------------------------
# last_seen
# ---------------------------------------------------------------------------


class TestSeenState:
    def test_absent_returns_default(self, event_dirs):
        state = load_seen(store.SEEN_FILE)
        assert state.version == 1
        assert state.projects == {}

    @pytest.mark.parametrize("version", [0, 2, 99])
    def test_version_mismatch_hard_error(self, event_dirs, version):
        state = SeenState(version=version)
        state.projects["kafka"] = {}
        store.SEEN_FILE.write_text(state.model_dump_json(), encoding="utf-8")
        with pytest.raises(EventsVersionError, match=f"version {version}"):
            load_seen(store.SEEN_FILE)
        # message is actionable
        with pytest.raises(EventsVersionError, match="Update your checkout"):
            load_seen(store.SEEN_FILE)

    def test_save_seen_atomic_roundtrip(self, event_dirs):
        state = SeenState()
        state.projects["kafka"] = {}
        state.last_run = NOW
        save_seen(state)
        assert not store.SEEN_FILE.with_suffix(".json.tmp").exists()
        loaded = load_seen(store.SEEN_FILE)
        assert loaded.last_run == NOW

    def test_save_seen_preserves_original_on_failure(self, event_dirs, monkeypatch):
        original = SeenState(last_run="2026-09-30T00:00:00+00:00")
        save_seen(original)

        broken = SeenState(last_run="2026-10-01T00:00:00+00:00")
        real_replace = __import__("os").replace

        def failing_replace(src, dst):
            if str(dst) == str(store.SEEN_FILE):
                raise OSError("disk full")
            return real_replace(src, dst)

        monkeypatch.setattr(store.os, "replace", failing_replace)
        with pytest.raises(OSError):
            save_seen(broken)
        # original content intact
        assert load_seen(store.SEEN_FILE).last_run == original.last_run


# ---------------------------------------------------------------------------
# update_from_cache
# ---------------------------------------------------------------------------


class TestUpdateFromCache:
    def test_missing_cache_skips_project(self, event_dirs, tmp_path, caplog):
        result = update_from_cache("kafka", tmp_path / "nope.json", now=NOW)
        assert result == []
        assert load_seen(store.SEEN_FILE).projects == {}  # baseline untouched

    def test_end_to_end_append_and_baseline(self, event_dirs, tmp_path, monkeypatch):
        cache = tmp_path / "kip_wiki_cache.json"
        cache.write_text(
            json.dumps(
                {
                    "1": {
                        "kip_id": 1,
                        "title": "KIP-1 - First",
                        "state": "under discussion",
                        "created_on": "2026-01-01T00:00:00.000Z",
                        "last_modified_on": "2026-02-01T00:00:00.000Z",
                    }
                }
            ),
            encoding="utf-8",
        )
        appended = update_from_cache("kafka", cache, now=NOW)
        assert len(appended) == 1
        assert appended[0].event_type == "new"
        seen = load_seen(store.SEEN_FILE)
        assert "kafka:kip-1" in seen.projects["kafka"]
        assert seen.last_run == NOW

        # second run: no changes -> no new events
        assert update_from_cache("kafka", cache, now=NOW) == []

    def test_version_error_propagates(self, event_dirs, tmp_path, monkeypatch):
        # pre-seed a bad-version seen file
        store.SEEN_FILE.write_text('{"version": 2, "projects": {}}', encoding="utf-8")
        cache = tmp_path / "cache.json"
        cache.write_text("{}", encoding="utf-8")
        monkeypatch.setitem(store.ADAPTERS, "kafka", lambda p: [])
        with pytest.raises(EventsVersionError):
            update_from_cache("kafka", cache, now=NOW)


# ---------------------------------------------------------------------------
# locking
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_parallel_updates_no_duplicate_seqs(self, event_dirs, tmp_path):
        """Two threads updating different projects concurrently produce no dup seqs."""
        for project, prefix in (("kafka", "KIP"), ("flink", "FLIP")):
            cache = tmp_path / f"{project}_cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "1": {
                            "kip_id" if project == "kafka" else "id": 1,
                            "title": f"{prefix}-1 - One",
                            "state": "under discussion",
                        }
                    }
                ),
                encoding="utf-8",
            )

        import ipper.events.adapters as adapters

        def kafka_loader(path):
            return [
                __import__(
                    "ipper.events.adapters.kafka", fromlist=["load_snapshots"]
                ).load_snapshots(path)
            ]

        # register tiny fake loaders so both projects share the tmp dir
        def fake_kafka(cache_path):
            data = json.loads(Path(cache_path).read_text())
            return [
                __import__(
                    "ipper.events.models", fromlist=["SeenSnapshot"]
                ).SeenSnapshot(
                    key=f"kafka:kip-{e['kip_id']}",
                    project="kafka",
                    reference=f"KIP-{e['kip_id']}",
                    title=e["title"],
                    state=e["state"],
                    detail_url="https://x",
                )
                for e in data.values()
            ]

        def fake_flink(cache_path):
            data = json.loads(Path(cache_path).read_text())
            return [
                __import__(
                    "ipper.events.models", fromlist=["SeenSnapshot"]
                ).SeenSnapshot(
                    key=f"flink:flip-{e['id']}",
                    project="flink",
                    reference=f"FLIP-{e['id']}",
                    title=e["title"],
                    state=e["state"],
                    detail_url="https://x",
                )
                for e in data.values()
            ]

        adapters.ADAPTERS.update({"kafka": fake_kafka, "flink": fake_flink})

        errors: list[Exception] = []

        def run(project: str) -> None:
            try:
                for cache_name in (f"{project}_cache.json",):
                    update_from_cache(project, tmp_path / cache_name, now=NOW)
            except Exception as ex:  # pragma: no cover - surfaced below
                errors.append(ex)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, "kafka"), pool.submit(run, "flink")]
            for f in futures:
                f.result()

        assert errors == []
        events = load_events(store.EVENTS_FILE)
        seqs = [e.seq for e in events]
        assert sorted(seqs) == list(range(1, len(seqs) + 1))
        assert len(seqs) == 2
