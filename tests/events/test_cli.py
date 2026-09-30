"""Tests for the events CLI (tail / backfill / stats)."""

import json
from pathlib import Path

import pytest

import ipper.events.store as store
from ipper.events.cli import setup_events_parser
from ipper.events.models import EventRecord

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


def make_parser():
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    setup_events_parser(sub)
    return parser


def write_record(seq: int, project: str, event_type: str, **kwargs) -> None:
    record = EventRecord(
        seq=seq,
        stable_id=f"{project}:k-1/{event_type}@2026-10-01",
        project=project,
        key=f"{project}:k-1",
        event_type=event_type,
        reference="REF-1",
        title="T",
        observed_at=NOW,
        detail_url="https://x",
        **kwargs,
    )
    with open(store.EVENTS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.model_dump()) + "\n")


class TestParser:
    def test_subcommands_registered(self, capsys):
        parser = make_parser()
        args = parser.parse_args(["events", "tail"])
        assert args.events_command == "tail"
        assert hasattr(args, "func")
        args = parser.parse_args(["events", "stats"])
        args = parser.parse_args(["events", "backfill"])

    def test_tail_defaults(self):
        parser = make_parser()
        args = parser.parse_args(["events", "tail"])
        assert args.limit == 20
        assert args.project is None
        assert args.type is None


class TestTail:
    def test_tail_prints_newest_last(self, event_dirs, capsys):
        for seq in (1, 2, 3):
            write_record(seq, "kafka", "new")
        parser = make_parser()
        args = parser.parse_args(["events", "tail"])
        args.func(args)
        out = capsys.readouterr().out
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert len(lines) == 3
        assert lines[0].startswith("     1")
        assert lines[-1].startswith("     3")

    def test_tail_limit(self, event_dirs, capsys):
        for seq in range(1, 6):
            write_record(seq, "kafka", "new")
        parser = make_parser()
        args = parser.parse_args(["events", "tail", "--limit", "2"])
        args.func(args)
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 2
        assert lines[0].startswith("     4")

    def test_tail_project_filter(self, event_dirs, capsys):
        write_record(1, "kafka", "new")
        write_record(2, "flink", "new")
        parser = make_parser()
        args = parser.parse_args(["events", "tail", "--project", "flink"])
        args.func(args)
        out = capsys.readouterr().out
        assert "flink" in out
        assert "kafka" not in out

    def test_tail_type_filter(self, event_dirs, capsys):
        write_record(1, "kafka", "new")
        write_record(2, "kafka", "state_changed", state_before="a", state_after="b")
        parser = make_parser()
        args = parser.parse_args(["events", "tail", "--type", "state_changed"])
        args.func(args)
        out = capsys.readouterr().out
        assert "state_changed" in out
        assert "new " not in out

    def test_tail_empty_log_friendly_message(self, event_dirs, capsys):
        parser = make_parser()
        args = parser.parse_args(["events", "tail"])
        args.func(args)
        out = capsys.readouterr().out
        assert "backfill" in out


class TestStats:
    def test_stats_absent_log(self, event_dirs, capsys):
        parser = make_parser()
        args = parser.parse_args(["events", "stats"])
        args.func(args)
        out = capsys.readouterr().out
        assert "backfill" in out

    def test_stats_summary(self, event_dirs, capsys):
        write_record(1, "kafka", "new")
        write_record(2, "kafka", "state_changed", state_before="a", state_after="b")
        write_record(3, "flink", "new")
        store.save_seen_seen = None  # sentinel; not used
        parser = make_parser()
        args = parser.parse_args(["events", "stats"])
        args.func(args)
        out = capsys.readouterr().out
        assert "Total events: 3" in out
        assert "Head seq: 3" in out
        assert "kafka: 2" in out
        assert "flink: 1" in out
        assert "new: 2" in out
        assert "state_changed: 1" in out


class TestBackfillCmd:
    def test_backfill_cmd_runs_and_prints_counts(
        self, event_dirs, tmp_path, monkeypatch, capsys
    ):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "kip_wiki_cache.json").write_text(
            json.dumps(
                {
                    "1": {
                        "kip_id": 1,
                        "title": "KIP-1 - One",
                        "state": "accepted",
                        "created_on": "2015-01-01T00:00:00.000Z",
                        "last_modified_on": "2015-06-01T00:00:00.000Z",
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "ipper.events.cli.backfill", lambda cache_dir: _fake_backfill(cache_dir)
        )
        parser = make_parser()
        args = parser.parse_args(["events", "backfill"])
        args.func(args)
        out = capsys.readouterr().out
        assert "Backfilled" in out

    def test_backfill_refusal_exits_1(self, event_dirs, monkeypatch, capsys):
        def refuse(cache_dir):
            raise RuntimeError(
                "events.jsonl already contains 5 records; backfill runs only once."
            )

        monkeypatch.setattr("ipper.events.cli.backfill", refuse)
        parser = make_parser()
        args = parser.parse_args(["events", "backfill"])
        with pytest.raises(SystemExit) as exc:
            args.func(args)
        assert exc.value.code == 1
        assert "runs only once" in capsys.readouterr().out


def _fake_backfill(cache_dir):
    """Minimal stand-in so the CLI test needs no real caches."""
    import ipper.events.store as s

    return s.append_events(
        s.load_events(s.EVENTS_FILE),
        [],
        s.EVENTS_FILE,
    )
