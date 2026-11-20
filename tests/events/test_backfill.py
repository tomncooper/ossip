"""Tests for ipper.events.backfill: one-time historical synthesis."""

import json
import logging
from pathlib import Path

import pytest

import ipper.events.backfill
import ipper.events.store as store
from ipper.events.backfill import backfill
from ipper.events.models import EventType
from ipper.events.store import load_events, load_seen

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


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Caches for all five projects under tmp."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.chdir(tmp_path)
    return cache


def write_kafka(cache_dir: Path) -> None:
    (cache_dir / "kip_wiki_cache.json").write_text(
        json.dumps(
            {
                "1": {
                    "kip_id": 1,
                    "title": "KIP-1 - One",
                    "state": "accepted",
                    "created_on": "2015-01-01T00:00:00.000Z",
                    "last_modified_on": "2015-06-01T00:00:00.000Z",
                },
                "2": {
                    "kip_id": 2,
                    "title": "KIP-2 - Two",
                    "state": "under discussion",
                    "created_on": "2020-01-01T00:00:00.000Z",
                    "last_modified_on": "2020-02-01T00:00:00.000Z",
                },
            }
        ),
        encoding="utf-8",
    )


def write_flink(cache_dir: Path) -> None:
    (cache_dir / "flip_wiki_cache.json").write_text(
        json.dumps(
            {
                "1": {
                    "id": 1,
                    "title": "FLIP-1: One",
                    "state": "not accepted",
                    "created_on": "2017-01-01T00:00:00.000Z",
                    "last_modified_on": "2017-03-01T00:00:00.000Z",
                }
            }
        ),
        encoding="utf-8",
    )


def write_github(cache_dir: Path, project: str, filename: str) -> None:
    (cache_dir / filename).write_text(
        json.dumps(
            {
                "proposals": {
                    "157": {
                        "pr_number": 245,
                        "id": 157,
                        "title": "Merged proposal",
                        "state": "accepted",
                        "created_at": "2026-01-10T00:00:00Z",
                        "merged_on": "2026-02-01T00:00:00Z",
                        "reviews": {},
                    },
                    "pr-247": {
                        "pr_number": 247,
                        "id": None,
                        "title": "Open proposal",
                        "state": "under discussion",
                        "created_at": "2026-02-01T00:00:00Z",
                        "reviews": {},
                    },
                    "pr-248": {
                        "pr_number": 248,
                        "id": None,
                        "title": "Rejected proposal",
                        "state": "not accepted",
                        "created_at": "2026-02-02T00:00:00Z",
                        "closed_on": "2026-03-01T00:00:00Z",
                        "last_activity": "2026-03-01T00:00:00Z",
                        "reviews": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )


class TestBackfill:
    def test_chronological_per_project_with_backfill_flag(self, event_dirs, cache_dir):
        write_kafka(cache_dir)
        appended = backfill(cache_dir, now=NOW)

        kafka_events = [e for e in appended if e.project == "kafka"]
        # KIP-1: new + state_changed; KIP-2: new only
        assert len(kafka_events) == 3
        times = [e.effective_at for e in kafka_events]
        assert times == sorted(times, key=lambda t: t or NOW)  # chronological
        assert all(e.backfilled for e in kafka_events)
        assert all(e.observed_at == NOW for e in kafka_events)

        # per proposal: NEW first (created 2015) then STATE_CHANGED (2015-06)
        kip1 = [e for e in kafka_events if e.key == "kafka:kip-1"]
        assert [e.event_type for e in kip1] == [
            EventType.NEW,
            EventType.STATE_CHANGED,
        ]
        assert kip1[1].state_before is None
        assert kip1[1].state_after == "accepted"
        assert kip1[1].effective_at == "2015-06-01T00:00:00.000Z"
        assert kip1[1].effective_at_source == "last_modified_on"

        kip2 = [e for e in kafka_events if e.key == "kafka:kip-2"]
        assert [e.event_type for e in kip2] == [EventType.NEW]

    def test_github_renumbered_and_rejected(self, event_dirs, cache_dir):
        write_github(cache_dir, "strimzi", "sip_proposals_cache.json")
        appended = backfill(cache_dir, now=NOW)
        sip = [e for e in appended if e.project == "strimzi"]

        merged = [e for e in sip if e.key == "strimzi:pr-245"]
        assert [e.event_type for e in merged] == [
            EventType.NEW,
            EventType.STATE_CHANGED,
            EventType.RENUMBERED,
        ]
        renum = merged[2]
        assert renum.reference == "SIP-157"
        assert renum.reference_before == "SIP-PR-245"
        assert renum.effective_at == "2026-02-01T00:00:00Z"
        assert renum.effective_at_source == "merged_on"
        assert merged[1].state_after == "accepted"

        rejected = [e for e in sip if e.key == "strimzi:pr-248"]
        assert [e.event_type for e in rejected] == [
            EventType.NEW,
            EventType.STATE_CHANGED,
        ]
        assert rejected[1].state_after == "not accepted"
        assert rejected[1].effective_at == "2026-03-01T00:00:00Z"
        assert rejected[1].effective_at_source == "closed_on"

        open_prop = [e for e in sip if e.key == "strimzi:pr-247"]
        assert [e.event_type for e in open_prop] == [EventType.NEW]

    def test_pr_number_numbering_projects_get_no_renumbered(
        self, event_dirs, cache_dir, monkeypatch
    ):
        """KDP-style pr_number projects are numbered from birth — no renumbered."""
        from ipper.common.github_config import GithubProjectConfig

        monkeypatch.setitem(
            ipper.events.backfill.GITHUB_PROJECT_CONFIGS,
            "strimzi",
            GithubProjectConfig(
                key="strimzi",
                name="Strimzi",
                owner="o",
                repo="r",
                prefix="SIP",
                proposal_dir="",
                numbering="pr_number",
                proposal_pattern=__import__("re").compile(r"(\d+)-.+\.md"),
                excluded_files=frozenset(),
                cache_filename="sip_proposals_cache.json",
            ),
        )
        write_github(cache_dir, "strimzi", "sip_proposals_cache.json")
        appended = backfill(cache_dir, now=NOW)
        assert all(e.event_type != EventType.RENUMBERED for e in appended)

    def test_no_review_events_backfilled(self, event_dirs, cache_dir):
        write_kafka(cache_dir)
        write_github(cache_dir, "strimzi", "sip_proposals_cache.json")
        appended = backfill(cache_dir, now=NOW)
        types = {e.event_type for e in appended}
        assert not types & {
            EventType.FIRST_APPROVAL,
            EventType.CHANGES_REQUESTED,
            EventType.VOTE_STARTED,
        }

    def test_refuses_non_empty_log(self, event_dirs, cache_dir):
        write_kafka(cache_dir)
        backfill(cache_dir, now=NOW)
        first_len = len(load_events())
        with pytest.raises(RuntimeError, match="backfill runs only once"):
            backfill(cache_dir, now=NOW)
        assert len(load_events()) == first_len  # nothing appended

    def test_missing_cache_skipped_with_warning(self, event_dirs, cache_dir, caplog):
        write_kafka(cache_dir)  # only kafka present
        with caplog.at_level(logging.WARNING):
            appended = backfill(cache_dir, now=NOW)
        assert all(e.project == "kafka" for e in appended)
        assert any(
            "flink" in r.message or "skip" in r.message.lower() for r in caplog.records
        )

    def test_last_seen_seeded_from_snapshots(self, event_dirs, cache_dir):
        write_kafka(cache_dir)
        backfill(cache_dir, now=NOW)
        seen = load_seen()
        assert set(seen.projects["kafka"]) == {"kafka:kip-1", "kafka:kip-2"}
        assert seen.last_run == NOW
        assert seen.version == 1

    def test_projects_in_config_order_not_interleaved(self, event_dirs, cache_dir):
        write_kafka(cache_dir)
        write_flink(cache_dir)
        write_github(cache_dir, "strimzi", "sip_proposals_cache.json")
        appended = backfill(cache_dir, now=NOW)
        projects_seen = []
        for e in appended:
            if not projects_seen or projects_seen[-1] != e.project:
                projects_seen.append(e.project)
        assert projects_seen == ["kafka", "flink", "strimzi"]
