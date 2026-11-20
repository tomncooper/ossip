"""Tests for the update-command hooks into the event log (all five projects)."""

from argparse import Namespace
from pathlib import Path

import pytest

import ipper.common.github_cli as github_cli
import ipper.events.store as store
import ipper.flink.main as flink_main
import ipper.kafka.main as kafka_main
from ipper.common.github_config import STRIMZI_CONFIG
from ipper.events.store import EventsVersionError

KAFKA_CACHE = Path("cache/kip_wiki_cache.json")
FLINK_CACHE = Path("cache/flip_wiki_cache.json")


@pytest.fixture
def event_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(store, "EVENTS_DIR", events_dir)
    monkeypatch.setattr(store, "EVENTS_FILE", events_dir / "events.jsonl")
    monkeypatch.setattr(store, "SEEN_FILE", events_dir / "last_seen.json")
    monkeypatch.setattr(store, "LOCK_FILE", events_dir / ".lock")
    return events_dir


class TestKafkaHook:
    def test_update_calls_events_with_project_and_cache(self, monkeypatch, event_dirs):
        calls = {}

        def fake_update_from_cache(project, cache_path):
            calls["args"] = (project, cache_path)
            return []

        monkeypatch.setattr("ipper.events.update_from_cache", fake_update_from_cache)
        monkeypatch.setattr(kafka_main, "setup_wiki_download", lambda args: None)
        monkeypatch.setattr(kafka_main, "setup_mail_download", lambda args: [])
        monkeypatch.setattr(kafka_main, "update_kip_mentions_cache", lambda *a: None)

        args = Namespace()
        kafka_main.run_update_cmd(args)
        assert calls["args"] == ("kafka", KAFKA_CACHE)

    def test_events_failure_does_not_fail_update(self, monkeypatch, event_dirs):
        def exploding_update(project, cache_path):
            raise RuntimeError("boom")

        monkeypatch.setattr("ipper.events.update_from_cache", exploding_update)
        monkeypatch.setattr(kafka_main, "setup_wiki_download", lambda args: None)
        monkeypatch.setattr(kafka_main, "setup_mail_download", lambda args: [])
        monkeypatch.setattr(kafka_main, "update_kip_mentions_cache", lambda *a: None)

        kafka_main.run_update_cmd(Namespace())  # no exception

    def test_version_error_propagates(self, monkeypatch, event_dirs):
        def version_error(project, cache_path):
            raise EventsVersionError("version mismatch")

        monkeypatch.setattr("ipper.events.update_from_cache", version_error)
        monkeypatch.setattr(kafka_main, "setup_wiki_download", lambda args: None)
        monkeypatch.setattr(kafka_main, "setup_mail_download", lambda args: [])
        monkeypatch.setattr(kafka_main, "update_kip_mentions_cache", lambda *a: None)

        with pytest.raises(EventsVersionError):
            kafka_main.run_update_cmd(Namespace())


class TestFlinkHook:
    def test_update_calls_events_with_project_and_cache(self, monkeypatch, event_dirs):
        calls = {}

        def fake_update_from_cache(project, cache_path):
            calls["args"] = (project, cache_path)
            return []

        monkeypatch.setattr("ipper.events.update_from_cache", fake_update_from_cache)
        monkeypatch.setattr(flink_main, "process_wiki", lambda args: None)
        monkeypatch.setattr(flink_main, "setup_mail_download", lambda args: [])
        monkeypatch.setattr(flink_main, "update_flip_mentions_cache", lambda *a: None)

        flink_main.run_update_cmd(Namespace())
        assert calls["args"] == ("flink", FLINK_CACHE)

    def test_events_failure_does_not_fail_update(self, monkeypatch, event_dirs):
        def exploding_update(project, cache_path):
            raise RuntimeError("boom")

        monkeypatch.setattr("ipper.events.update_from_cache", exploding_update)
        monkeypatch.setattr(flink_main, "process_wiki", lambda args: None)
        monkeypatch.setattr(flink_main, "setup_mail_download", lambda args: [])
        monkeypatch.setattr(flink_main, "update_flip_mentions_cache", lambda *a: None)

        flink_main.run_update_cmd(Namespace())  # no exception

    def test_version_error_propagates(self, monkeypatch, event_dirs):
        def version_error(project, cache_path):
            raise EventsVersionError("version mismatch")

        monkeypatch.setattr("ipper.events.update_from_cache", version_error)
        monkeypatch.setattr(flink_main, "process_wiki", lambda args: None)
        monkeypatch.setattr(flink_main, "setup_mail_download", lambda args: [])
        monkeypatch.setattr(flink_main, "update_flip_mentions_cache", lambda *a: None)

        with pytest.raises(EventsVersionError):
            flink_main.run_update_cmd(Namespace())


class TestGithubHook:
    def _run_update(self, monkeypatch, event_dirs, update_from_cache_impl):
        calls = {}

        monkeypatch.setattr("ipper.events.update_from_cache", update_from_cache_impl)
        monkeypatch.setattr(
            github_cli, "load_cache", lambda path: {"proposals": {}, "pr_index": {}}
        )
        monkeypatch.setattr(
            github_cli, "migrate_cache", lambda config, cache, client=None: cache
        )
        monkeypatch.setattr(
            github_cli,
            "update_cache",
            lambda config, cache, client: {"proposals": {}, "pr_index": {}},
        )
        saved = {}
        monkeypatch.setattr(
            github_cli, "save_cache", lambda cache, path: saved.setdefault("path", path)
        )

        github_cli.run_update_cmd(STRIMZI_CONFIG, Namespace())
        return calls, saved

    def test_update_calls_events_with_project_and_cache(self, monkeypatch, event_dirs):
        calls = {}

        def fake_update_from_cache(project, cache_path):
            calls["args"] = (project, cache_path)
            return []

        _, saved = self._run_update(monkeypatch, event_dirs, fake_update_from_cache)
        assert calls["args"] == ("strimzi", saved["path"])
        assert saved["path"].name == "sip_proposals_cache.json"

    def test_events_failure_does_not_fail_update(self, monkeypatch, event_dirs):
        def exploding_update(project, cache_path):
            raise RuntimeError("boom")

        self._run_update(monkeypatch, event_dirs, exploding_update)  # no exception

    def test_version_error_propagates(self, monkeypatch, event_dirs):
        def version_error(project, cache_path):
            raise EventsVersionError("version mismatch")

        with pytest.raises(EventsVersionError):
            self._run_update(monkeypatch, event_dirs, version_error)
