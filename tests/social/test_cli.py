"""Tests for the social announce CLI (v2: event-log consumer)."""

import json
from pathlib import Path

import pytest

import ipper.events.store as store
from ipper.events.models import EventRecord
from ipper.social.cli import (
    load_state,
    run_announce_cmd,
    seed_state,
)
from ipper.social.models import SocialState

NOW = "2026-10-01T09:30:00+00:00"


@pytest.fixture
def event_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(store, "EVENTS_DIR", events_dir)
    monkeypatch.setattr(store, "EVENTS_FILE", events_dir / "events.jsonl")
    monkeypatch.setattr(store, "SEEN_FILE", events_dir / "last_seen.json")
    monkeypatch.setattr(store, "LOCK_FILE", events_dir / ".lock")
    return events_dir


def make_args(**kwargs):
    """Namespace of announce arguments with test-friendly defaults."""
    from argparse import Namespace

    defaults = {
        "post_to": "console",
        "projects": "kafka",
        "dry_run": False,
        "demo": False,
        "max_posts": 5,
        "max_attempts": 5,
        "state_file": str(Path("state.json")),
        "reseed": False,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


_USED_IDS: set[str] = set()


def write_event(
    seq: int,
    key: str = "kafka:kip-123",
    project: str = "kafka",
    event_type: str = "new",
    state_before: str | None = None,
    state_after: str | None = "under discussion",
    reference: str = "KIP-123",
    backfilled: bool = False,
    **kwargs,
) -> EventRecord:
    stable_id = f"{key}/{event_type}@2026-10-01"
    if stable_id in _USED_IDS:
        suffix = 2
        while f"{stable_id}-{suffix}" in _USED_IDS:
            suffix += 1
        stable_id = f"{stable_id}-{suffix}"
    _USED_IDS.add(stable_id)
    record = EventRecord(
        seq=seq,
        stable_id=stable_id,
        project=project,
        key=key,
        event_type=event_type,
        reference=reference,
        title="Exactly-once semantics",
        state_before=state_before,
        state_after=state_after,
        observed_at=NOW,
        detail_url=f"https://ossip.dev/kips/{reference}.html",
        backfilled=backfilled,
        **kwargs,
    )
    with open(store.EVENTS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.model_dump()) + "\n")
    return record


def load_state_file(path: Path) -> SocialState:
    return SocialState.model_validate_json(path.read_text(encoding="utf-8"))


class TestSeeding:
    def test_absent_state_nonempty_log_no_posts_cursors_at_head(
        self, event_dirs, tmp_path, capsys
    ):
        write_event(1)
        write_event(2, key="kafka:kip-124", reference="KIP-124")
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))
        out = capsys.readouterr().out
        assert "[console]" not in out
        state = load_state_file(state_file)
        assert state.version == 2
        assert state.cursors == {"console": 2}
        assert state.pending == []

    def test_v1_state_file_treated_as_seed(self, event_dirs, tmp_path, capsys):
        write_event(1)
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({"version": 1, "baselines": {}, "pending": []}),
            encoding="utf-8",
        )
        run_announce_cmd(make_args(state_file=str(state_file)))
        out = capsys.readouterr().out
        assert "[console]" not in out  # nothing historical posted
        state = load_state_file(state_file)
        assert state.version == 2
        assert state.cursors == {"console": 1}

    def test_empty_log_seeds_at_zero(self, event_dirs, tmp_path, capsys):
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))
        state = load_state_file(state_file)
        assert state.cursors == {"console": 0}

    def test_dry_run_first_run_never_writes_state(self, event_dirs, tmp_path, capsys):
        write_event(1)
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(dry_run=True, state_file=str(state_file)))
        assert "Would seed" in capsys.readouterr().out
        assert not state_file.exists()


class TestPosting:
    def test_new_event_posts_once_then_cursor_advances(
        self, event_dirs, tmp_path, capsys
    ):
        write_event(1)
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))  # seed
        write_event(
            2,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        run_announce_cmd(make_args(state_file=str(state_file)))
        out = capsys.readouterr().out
        assert out.count("[console]") == 1
        assert "KIP-123 ✅ accepted" in out
        state = load_state_file(state_file)
        assert state.cursors == {"console": 2}
        assert state.pending == []
        # next run: nothing new
        run_announce_cmd(make_args(state_file=str(state_file)))
        assert capsys.readouterr().out.count("[console]") == 0

    def test_one_destination_down_only_it_retries(
        self, event_dirs, tmp_path, capsys, monkeypatch
    ):
        from ipper.social.posters.base import PostResult

        write_event(1)
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))  # seed

        class FlakyPoster:
            name = "flaky"
            fail = True
            calls = 0

            @classmethod
            def from_env(cls):
                return cls()

            def post(self, event):
                type(self).calls += 1
                return (
                    PostResult(ok=False, error="down")
                    if self.fail
                    else PostResult(ok=True, post_id="1")
                )

        monkeypatch.setitem(
            __import__(
                "ipper.social.posters.base", fromlist=["POSTER_REGISTRY"]
            ).POSTER_REGISTRY,
            "flaky",
            FlakyPoster,
        )

        write_event(
            2,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        run_announce_cmd(make_args(post_to="console,flaky", state_file=str(state_file)))
        state = load_state_file(state_file)
        assert state.cursors["console"] == 2  # console advanced
        assert state.cursors["flaky"] == 1  # flaky held back
        assert len(state.pending) == 1

        # retry run: console NOT re-posted, flaky is
        capsys.readouterr()  # discard earlier runs' output
        FlakyPoster.fail = False
        run_announce_cmd(make_args(post_to="console,flaky", state_file=str(state_file)))
        out = capsys.readouterr().out
        assert out.count("[console]") == 0
        final = load_state_file(state_file)
        assert final.cursors == {"console": 2, "flaky": 2}
        assert final.pending == []

    def test_new_destination_starts_at_head_no_history(
        self, event_dirs, tmp_path, capsys, monkeypatch
    ):
        from ipper.social.posters.base import PostResult

        class NullPoster:
            name = "newdest"

            @classmethod
            def from_env(cls):
                return cls()

            def post(self, event):
                return PostResult(ok=True, post_id="n")

        import ipper.social.posters.base as poster_base

        monkeypatch.setitem(poster_base.POSTER_REGISTRY, "newdest", NullPoster)
        write_event(1)
        state_file = tmp_path / "state.json"
        run_announce_cmd(
            make_args(post_to="console", state_file=str(state_file))
        )  # seed
        write_event(2)
        write_event(3, key="kafka:kip-125", reference="KIP-125")
        capsys.readouterr()  # discard run-2 output
        run_announce_cmd(make_args(post_to="console", state_file=str(state_file)))
        capsys.readouterr()
        # now add a destination; it must not replay events 1-3
        run_announce_cmd(
            make_args(post_to="console,newdest", state_file=str(state_file))
        )
        out = capsys.readouterr().out
        assert out.count("[console]") == 0
        state = load_state_file(state_file)
        assert state.cursors["newdest"] == 3  # starts at head


class TestCoalescing:
    def test_two_events_one_proposal_single_post_latest(
        self, event_dirs, tmp_path, capsys
    ):
        write_event(1)  # seed
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))
        write_event(
            2,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        write_event(
            3,
            event_type="state_changed",
            state_before="accepted",
            state_after="not accepted",
        )
        run_announce_cmd(make_args(state_file=str(state_file)))
        out = capsys.readouterr().out
        assert out.count("[console]") == 1
        assert "❌ not accepted" in out  # the LATEST event wins
        state = load_state_file(state_file)
        assert state.pending == []
        assert state.cursors == {"console": 3}

    def test_max_posts_overflow_stays_pending(self, event_dirs, tmp_path, capsys):
        write_event(1)  # seed
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))
        for seq, key, ref in (
            (2, "kafka:kip-201", "KIP-201"),
            (3, "kafka:kip-202", "KIP-202"),
            (4, "kafka:kip-203", "KIP-203"),
        ):
            write_event(seq, key=key, reference=ref)
        run_announce_cmd(make_args(max_posts=2, state_file=str(state_file)))
        out = capsys.readouterr().out
        assert out.count("[console]") == 2
        state = load_state_file(state_file)
        assert len(state.pending) == 1  # overflow stays pending
        assert state.cursors["console"] == 3  # held just below the pending seq-4 event
        # next run: overflow is re-discovered and posted
        run_announce_cmd(make_args(max_posts=2, state_file=str(state_file)))
        assert capsys.readouterr().out.count("[console]") == 1
        assert load_state_file(state_file).pending == []


class TestMapping:
    def test_accepted_completed_flip_not_announced(self, event_dirs, tmp_path, capsys):
        write_event(1, state_after="accepted")  # seed at head
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))
        write_event(
            2,
            event_type="state_changed",
            state_before="accepted",
            state_after="completed",
        )
        run_announce_cmd(make_args(state_file=str(state_file)))
        assert capsys.readouterr().out.count("[console]") == 0

    def test_reopen_not_announced(self, event_dirs, tmp_path, capsys):
        write_event(1)  # seed
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))
        write_event(
            2,
            event_type="state_changed",
            state_before="not accepted",
            state_after="under discussion",
        )
        run_announce_cmd(make_args(state_file=str(state_file)))
        assert capsys.readouterr().out.count("[console]") == 0

    def test_renumbered_not_announced_but_cooccurring_acceptance_is(
        self, event_dirs, tmp_path, capsys
    ):
        write_event(
            1, project="strimzi", key="strimzi:pr-245", reference="SIP-PR-245"
        )  # seed
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(projects="strimzi", state_file=str(state_file)))
        write_event(
            2,
            project="strimzi",
            key="strimzi:pr-245",
            event_type="renumbered",
            state_before="under discussion",
            state_after="accepted",
            reference="SIP-46",
            reference_before="SIP-PR-245",
        )
        write_event(
            3,
            project="strimzi",
            key="strimzi:pr-245",
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        run_announce_cmd(make_args(projects="strimzi", state_file=str(state_file)))
        out = capsys.readouterr().out
        assert out.count("[console]") == 1
        assert "✅ accepted" in out

    def test_backfilled_events_never_posted(self, event_dirs, tmp_path, capsys):
        write_event(1, backfilled=True)
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))  # seed at head 1
        assert "[console]" not in capsys.readouterr().out
        # seeding at head means backfilled events are behind the cursor anyway
        state = load_state_file(state_file)
        assert state.cursors == {"console": 1}


class TestReseedAndDryRun:
    def test_reseed_clears_pending_and_seeds(self, event_dirs, tmp_path, capsys):
        write_event(1)
        state_file = tmp_path / "state.json"
        run_announce_cmd(
            make_args(post_to="failing", state_file=str(state_file))
        )  # seed
        write_event(
            2,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        # produce a pending event via a failing destination
        from ipper.social.posters.base import PostResult

        class FailingPoster:
            name = "failing"

            @classmethod
            def from_env(cls):
                return cls()

            def post(self, event):
                return PostResult(ok=False, error="down")

        import ipper.social.posters.base as poster_base

        poster_base.POSTER_REGISTRY["failing"] = FailingPoster
        run_announce_cmd(make_args(post_to="failing", state_file=str(state_file)))
        assert len(load_state_file(state_file).pending) == 1

        run_announce_cmd(
            make_args(post_to="failing", reseed=True, state_file=str(state_file))
        )
        final = load_state_file(state_file)
        assert final.pending == []
        assert final.cursors == {"failing": 2}

    def test_dry_run_never_writes_state_midflow(self, event_dirs, tmp_path, capsys):
        write_event(1)  # seed
        state_file = tmp_path / "state.json"
        run_announce_cmd(make_args(state_file=str(state_file)))
        write_event(
            2,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        run_announce_cmd(make_args(dry_run=True, state_file=str(state_file)))
        out = capsys.readouterr().out
        assert "\u2705 accepted" in out
        # state unchanged (no cursor advance)
        assert load_state_file(state_file).cursors == {"console": 1}


class TestDemo:
    def test_demo_empty_log(self, event_dirs, capsys):
        run_announce_cmd(make_args(demo=True))
        assert "Event log is empty" in capsys.readouterr().out

    def test_demo_prints_samples(self, event_dirs, capsys):
        write_event(1)
        write_event(
            2,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        write_event(
            3,
            event_type="state_changed",
            state_before="accepted",
            state_after="not accepted",
        )
        run_announce_cmd(make_args(demo=True))
        out = capsys.readouterr().out
        assert "new proposal" in out
        assert "\u2705 accepted" in out
        assert "\u274c not accepted" in out


def test_load_state_unparseable_file_is_seed(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("not json at all", encoding="utf-8")
    assert load_state(state_file) is None


def test_seed_state_shape():
    state = seed_state(7, ["mastodon", "bluesky"], NOW)
    assert state.version == 2
    assert state.cursors == {"mastodon": 7, "bluesky": 7}
    assert state.pending == []
