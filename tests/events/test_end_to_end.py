"""End-to-end chain test: real cache -> update_from_cache -> log -> social announce.

The producer side (``tests/events/test_store.py``) and the consumer side
(``tests/social/test_cli.py``) are each tested against the log independently.
This stitches them together with no mocking of detection, so a divergence in the
on-disk event contract between producer and consumer would be caught here.
"""

import json
from argparse import Namespace
from pathlib import Path

import pytest

import ipper.events.store as store
from ipper.events.store import load_events, update_from_cache
from ipper.social.cli import run_announce_cmd


@pytest.fixture
def event_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(store, "EVENTS_DIR", events_dir)
    monkeypatch.setattr(store, "EVENTS_FILE", events_dir / "events.jsonl")
    monkeypatch.setattr(store, "SEEN_FILE", events_dir / "last_seen.json")
    monkeypatch.setattr(store, "LOCK_FILE", events_dir / ".lock")
    return events_dir


def make_args(**kwargs) -> Namespace:
    defaults = {
        "post_to": "console",
        "projects": "all",
        "dry_run": False,
        "demo": False,
        "max_posts": 5,
        "max_attempts": 5,
        "reseed": False,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


def write_kafka(cache: Path, state: str) -> None:
    cache.write_text(
        json.dumps(
            {
                "1": {
                    "kip_id": 1,
                    "title": "KIP-1 - Exactly-once",
                    "state": state,
                    "created_on": "2026-01-01T00:00:00.000Z",
                    "last_modified_on": "2026-02-01T00:00:00.000Z",
                }
            }
        ),
        encoding="utf-8",
    )


def write_strimzi(cache: Path) -> None:
    cache.write_text(
        json.dumps(
            {
                "proposals": {
                    "pr-247": {
                        "pr_number": 247,
                        "id": None,
                        "title": "Open proposal",
                        "state": "under discussion",
                        "created_at": "2026-02-01T00:00:00Z",
                        "reviews": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_cache_to_log_to_announcement(event_dirs, tmp_path, capsys):
    kafka_cache = tmp_path / "kip_wiki_cache.json"
    strimzi_cache = tmp_path / "sip_proposals_cache.json"
    write_kafka(kafka_cache, "under discussion")
    write_strimzi(strimzi_cache)
    state_file = tmp_path / "state.json"

    # 1. Producers: real detection writes NEW events for both projects.
    update_from_cache("kafka", kafka_cache, now="2026-03-01T00:00:00+00:00")
    update_from_cache("strimzi", strimzi_cache, now="2026-03-01T00:00:00+00:00")
    events = load_events(store.EVENTS_FILE)
    assert {e.project for e in events} == {"kafka", "strimzi"}
    assert {e.event_type for e in events} == {"new"}

    # 2. Consumer seeds cursors at head; nothing historical is posted.
    run_announce_cmd(make_args(state_file=str(state_file)))
    assert "[console]" not in capsys.readouterr().out

    # 3. A real state change flows through detection into the log...
    write_kafka(kafka_cache, "accepted")
    appended = update_from_cache("kafka", kafka_cache, now="2026-04-01T00:00:00+00:00")
    assert [e.event_type for e in appended] == ["state_changed"]
    assert appended[0].state_after == "accepted"

    # 4. ...and the consumer announces it end to end.
    run_announce_cmd(make_args(state_file=str(state_file)))
    out = capsys.readouterr().out
    assert out.count("[console]") == 1
    assert "KIP-1 ✅ accepted" in out
