"""Tests for ipper.events.adapters: cache -> SeenSnapshot extraction."""

import json
from pathlib import Path

import pytest

from ipper.events.adapters import ADAPTERS, flink, github, kafka
from ipper.events.models import SeenSnapshot


@pytest.fixture
def kip_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "kip_wiki_cache.json"
    cache.write_text(
        json.dumps(
            {
                "1": {
                    "kip_id": 1,
                    "title": "KIP-1 - Remove support of request.required.acks",
                    "state": "accepted",
                    "created_on": "2015-01-16T02:11:02.000Z",
                    "last_modified_on": "2015-07-18T04:58:41.000Z",
                    "vote_thread": "not set",
                },
                "2": {
                    "kip_id": 2,
                    "title": "KIP-2 - Voting now",
                    "state": "under discussion",
                    "created_on": "2015-02-01T00:00:00.000Z",
                    "last_modified_on": "2015-02-10T00:00:00.000Z",
                    "vote_thread": "https://lists.apache.org/vote",
                },
            }
        ),
        encoding="utf-8",
    )
    return cache


@pytest.fixture
def flip_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "flip_wiki_cache.json"
    cache.write_text(
        json.dumps(
            {
                "1": {
                    "id": 1,
                    "title": "FLIP-1: Fine Grained Recovery",
                    "state": "completed",
                    "created_on": "2020-01-01T00:00:00.000Z",
                    "last_modified_on": "2020-02-01T00:00:00.000Z",
                    "vote_thread": None,
                }
            }
        ),
        encoding="utf-8",
    )
    return cache


@pytest.fixture
def sip_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "sip_proposals_cache.json"
    cache.write_text(
        json.dumps(
            {
                "last_updated": "2026-10-05T09:30:00+00:00",
                "proposals": {
                    "157": {
                        "pr_number": 245,
                        "id": 157,
                        "title": "Kafka Exporter re-implementation",
                        "state": "accepted",
                        "created_on": "2026-01-10",
                        "created_at": "2026-01-10T00:00:00Z",
                        "merged_on": "2026-02-01T00:00:00Z",
                        "last_activity": None,
                        "reviews": {
                            "accepted": [
                                {"name": "alice", "timestamp": "2026-01-20T10:00:00Z"}
                            ],
                            "commented": [],
                            "changes_requested": [],
                        },
                    },
                    "pr-247": {
                        "pr_number": 247,
                        "id": None,
                        "title": "Another proposal",
                        "state": "under discussion",
                        "created_on": "2026-02-01",
                        "last_activity": "2026-09-28T15:57:21Z",
                        "reviews": {
                            "accepted": [],
                            "commented": [
                                {"name": "bob", "timestamp": "2026-09-28T15:57:21Z"}
                            ],
                            "changes_requested": [],
                        },
                    },
                    "pr-248": {
                        "pr_number": 248,
                        "id": None,
                        "title": "Rejected proposal",
                        "state": "not accepted",
                        "created_on": "2026-02-02",
                        "closed_on": "2026-03-01T00:00:00Z",
                        "last_activity": "2026-03-01T00:00:00Z",
                        "reviews": None,
                    },
                },
                "pr_index": {},
                "watermark": "2026-10-05T09:30:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return cache


class TestWikiAdapters:
    def test_kafka_snapshot_fields(self, kip_cache: Path):
        snaps = kafka.load_snapshots(kip_cache)
        assert len(snaps) == 2
        first = snaps[0]
        assert isinstance(first, SeenSnapshot)
        assert first.key == "kafka:kip-1"
        assert first.reference == "KIP-1"
        assert first.title == "Remove support of request.required.acks"
        assert first.state == "accepted"
        assert first.created_on == "2015-01-16T02:11:02.000Z"
        assert first.last_modified_on == "2015-07-18T04:58:41.000Z"
        assert first.vote_thread is None  # 'not set' sentinel
        assert first.pr_number is None and first.proposal_id is None

    def test_kafka_vote_thread_preserved(self, kip_cache: Path):
        snaps = kafka.load_snapshots(kip_cache)
        assert snaps[1].vote_thread == "https://lists.apache.org/vote"

    def test_flink_snapshot_fields(self, flip_cache: Path):
        snaps = flink.load_snapshots(flip_cache)
        assert snaps[0].key == "flink:flip-1"
        assert snaps[0].reference == "FLIP-1"
        assert snaps[0].title == "Fine Grained Recovery"
        assert snaps[0].state == "completed"
        assert snaps[0].vote_thread is None


class TestGithubAdapter:
    def test_github_snapshot_fields(self, sip_cache: Path):
        snaps = github.load_snapshots("strimzi", sip_cache)
        by_key = {s.key: s for s in snaps}
        assert set(by_key) == {"strimzi:pr-245", "strimzi:pr-247", "strimzi:pr-248"}

        merged = by_key["strimzi:pr-245"]
        assert merged.reference == "SIP-157"
        assert merged.proposal_id == 157
        assert merged.pr_number == 245
        # full-ISO created_at preferred over date-only created_on
        assert merged.created_on == "2026-01-10T00:00:00Z"
        assert merged.merged_on == "2026-02-01T00:00:00Z"
        assert merged.reviews is not None
        assert merged.reviews["accepted"][0].name == "alice"

        open_prop = by_key["strimzi:pr-247"]
        assert open_prop.reference == "SIP-PR-247"
        assert open_prop.proposal_id is None
        assert open_prop.last_activity == "2026-09-28T15:57:21Z"
        assert open_prop.reviews is not None
        assert open_prop.reviews["commented"][0].timestamp == "2026-09-28T15:57:21Z"

        rejected = by_key["strimzi:pr-248"]
        assert rejected.closed_on == "2026-03-01T00:00:00Z"
        assert rejected.reviews is None

    def test_github_created_at_fallback_to_created_on(self, sip_cache: Path, tmp_path):
        data = json.loads(sip_cache.read_text())
        del data["proposals"]["157"]["created_at"]
        cache = tmp_path / "old.json"
        cache.write_text(json.dumps(data), encoding="utf-8")
        snaps = github.load_snapshots("strimzi", cache)
        merged = next(s for s in snaps if s.pr_number == 245)
        assert merged.created_on == "2026-01-10"  # date-only fallback


class TestRegistry:
    def test_registry_covers_all_five_projects(self):
        assert set(ADAPTERS) == {
            "kafka",
            "flink",
            "strimzi",
            "streamshub",
            "kroxylicious",
        }

    def test_registry_dispatches_github_by_project(self, sip_cache: Path):
        # the lambdas route the cache path to the right project
        assert ADAPTERS["strimzi"](sip_cache)[0].project == "strimzi"
