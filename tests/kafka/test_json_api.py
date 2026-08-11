"""Tests for Kafka JSON API conversion functions."""

import datetime as dt
from pathlib import Path

import pytest

from ipper.kafka.output import KIPStatus, kip_to_detail, kip_to_summary, generate_kafka_json_api


def _make_kip_wiki_info_entry(kip_id=100):
    """Factory for creating test KIP wiki info entries."""
    return {
        "kip_id": kip_id,
        "title": f"KIP-{kip_id}: Test Proposal",
        "web_url": f"https://wiki.apache.org/confluence/display/KAFKA/KIP-{kip_id}",
        "content_url": "https://example.com/api/content/12345",
        "created_on": "2025-01-15T10:30:00.000Z",
        "created_by": "Alice",
        "last_modified_on": "2025-02-20T14:45:00.000Z",
        "last_modified_by": "Bob",
        "state": "under discussion",
        "jira": "https://issues.apache.org/jira/browse/KAFKA-12345",
        "discussion_thread": "https://lists.apache.org/thread/abc123",
        "vote_thread": "not set",
    }


def _make_kip_status_entry(kip_id=100):
    """Factory for creating test KIP status entries."""
    return {
        "id": kip_id,
        "text": "Test Proposal",
        "url": f"https://wiki.apache.org/confluence/display/KAFKA/KIP-{kip_id}",
        "created_by": "Alice",
        "state": "under discussion",
        "age": "1 year",
        "status": KIPStatus.GREEN,
        "last_mention_age": "2 weeks",
        "emoji": None,
        "+1": [{"name": "Charlie", "timestamp": "Feb 10, 2025 09:00 UTC"}],
        "0": [],
        "-1": [{"name": "Eve", "timestamp": "Feb 09, 2025 11:00 UTC"}],
    }


class TestKipToDetail:
    """Tests for kip_to_detail function."""

    def test_basic_conversion(self):
        """Test basic KIP detail conversion."""
        wiki_entry = _make_kip_wiki_info_entry()
        status_entry = _make_kip_status_entry()

        result = kip_to_detail(wiki_entry, status_entry)

        assert result.id == 100
        assert result.title == "KIP-100: Test Proposal"
        assert result.state == "under discussion"
        assert result.created_by == "Alice"
        assert result.created_on == "2025-01-15"
        assert result.last_modified_on == "2025-02-20T14:45:00Z"
        assert result.last_modified_by == "Bob"
        assert result.discussion_thread == "https://lists.apache.org/thread/abc123"
        assert result.vote_thread is None
        assert result.jira == "https://issues.apache.org/jira/browse/KAFKA-12345"
        assert result.web_url == f"https://wiki.apache.org/confluence/display/KAFKA/KIP-100"
        assert result.activity_status == "green"

    def test_sentinel_fields_to_none(self):
        """Test that sentinel values ('not set', 'unknown') are converted to None."""
        wiki_entry = _make_kip_wiki_info_entry()
        wiki_entry["jira"] = "not set"
        wiki_entry["discussion_thread"] = "unknown"
        wiki_entry["vote_thread"] = "not set"
        status_entry = _make_kip_status_entry()

        result = kip_to_detail(wiki_entry, status_entry)

        assert result.jira is None
        assert result.discussion_thread is None
        assert result.vote_thread is None

    def test_vote_timestamps_converted_to_iso(self):
        """Test that vote timestamps are converted to ISO 8601 format."""
        wiki_entry = _make_kip_wiki_info_entry()
        status_entry = _make_kip_status_entry()
        status_entry["+1"] = [
            {"name": "Charlie", "timestamp": "Feb 10, 2025 09:00 UTC"},
            {"name": "David", "timestamp": "Jan 05, 2025 14:30 UTC"},
        ]
        status_entry["-1"] = [
            {"name": "Eve", "timestamp": "Feb 09, 2025 11:00 UTC"}
        ]

        result = kip_to_detail(wiki_entry, status_entry)

        assert len(result.votes.plus_one) == 2
        assert result.votes.plus_one[0].name == "Charlie"
        assert result.votes.plus_one[0].timestamp == "2025-02-10T09:00:00Z"
        assert result.votes.plus_one[1].name == "David"
        assert result.votes.plus_one[1].timestamp == "2025-01-05T14:30:00Z"
        assert len(result.votes.minus_one) == 1
        assert result.votes.minus_one[0].name == "Eve"
        assert result.votes.minus_one[0].timestamp == "2025-02-09T11:00:00Z"

    def test_activity_status_for_discussion_kip(self):
        """Test activity_status is status.text for discussion KIPs."""
        wiki_entry = _make_kip_wiki_info_entry()
        status_entry = _make_kip_status_entry()
        status_entry["state"] = "under discussion"
        status_entry["status"] = KIPStatus.YELLOW

        result = kip_to_detail(wiki_entry, status_entry)

        assert result.activity_status == "yellow"

    def test_activity_status_none_for_non_discussion(self):
        """Test activity_status is None for non-discussion KIPs."""
        wiki_entry = _make_kip_wiki_info_entry()
        wiki_entry["state"] = "accepted"
        status_entry = _make_kip_status_entry()
        status_entry["state"] = "accepted"
        status_entry["status"] = None

        result = kip_to_detail(wiki_entry, status_entry)

        assert result.activity_status is None

    def test_no_votes_produces_empty_lists(self):
        """Test that KIPs with no votes have empty vote lists."""
        wiki_entry = _make_kip_wiki_info_entry()
        status_entry = _make_kip_status_entry()
        status_entry["+1"] = []
        status_entry["0"] = []
        status_entry["-1"] = []

        result = kip_to_detail(wiki_entry, status_entry)

        assert result.votes.plus_one == []
        assert result.votes.zero == []
        assert result.votes.minus_one == []


class TestKipToSummary:
    """Tests for kip_to_summary function."""

    def test_basic_conversion(self):
        """Test basic KIP summary conversion."""
        wiki_entry = _make_kip_wiki_info_entry()
        status_entry = _make_kip_status_entry()

        result = kip_to_summary(status_entry, wiki_entry)

        assert result.id == 100
        assert result.title == "KIP-100: Test Proposal"
        assert result.state == "under discussion"
        assert result.created_by == "Alice"
        assert result.created_on == "2025-01-15"
        assert result.detail_url == "kips/100.json"
        assert result.web_url == f"https://wiki.apache.org/confluence/display/KAFKA/KIP-100"

    def test_title_uses_full_wiki_title(self):
        """Test that title uses full wiki title, not cleaned status text."""
        wiki_entry = _make_kip_wiki_info_entry()
        wiki_entry["title"] = "KIP-100: Full Title With Details"
        status_entry = _make_kip_status_entry()
        status_entry["text"] = "Shortened Title"

        result = kip_to_summary(status_entry, wiki_entry)

        assert result.title == "KIP-100: Full Title With Details"

    def test_created_on_is_iso_date(self):
        """Test that created_on is converted to ISO date format."""
        wiki_entry = _make_kip_wiki_info_entry()
        wiki_entry["created_on"] = "2025-03-15T08:20:00.000Z"
        status_entry = _make_kip_status_entry()

        result = kip_to_summary(status_entry, wiki_entry)

        assert result.created_on == "2025-03-15"

    def test_vote_count_has_integer_counts(self):
        """Test that vote_count contains integer counts."""
        wiki_entry = _make_kip_wiki_info_entry()
        status_entry = _make_kip_status_entry()
        status_entry["+1"] = [
            {"name": "Alice", "timestamp": "Feb 10, 2025 09:00 UTC"},
            {"name": "Bob", "timestamp": "Feb 11, 2025 10:00 UTC"},
        ]
        status_entry["0"] = [
            {"name": "Charlie", "timestamp": "Feb 12, 2025 11:00 UTC"}
        ]
        status_entry["-1"] = []

        result = kip_to_summary(status_entry, wiki_entry)

        assert result.vote_count.plus_one == 2
        assert result.vote_count.zero == 1
        assert result.vote_count.minus_one == 0

    def test_detail_url_format(self):
        """Test that detail_url follows the correct format."""
        wiki_entry = _make_kip_wiki_info_entry(kip_id=42)
        status_entry = _make_kip_status_entry(kip_id=42)

        result = kip_to_summary(status_entry, wiki_entry)

        assert result.detail_url == "kips/42.json"


class TestGenerateKafkaJsonApi:
    """Tests for generate_kafka_json_api function."""

    def test_creates_summary_and_detail_files(self, tmp_path):
        """Test that function creates kips.json and individual detail files."""
        api_dir = tmp_path / "api"
        wiki_entry = _make_kip_wiki_info_entry(kip_id=100)
        status_entry = _make_kip_status_entry(kip_id=100)
        kip_wiki_info = {100: wiki_entry}
        kip_status = [status_entry]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        # Check that kips.json exists
        assert (api_dir / "kips.json").exists()

        # Check that kips/100.json exists
        assert (api_dir / "kips" / "100.json").exists()

    def test_summary_file_structure(self, tmp_path):
        """Test that kips.json has correct structure."""
        api_dir = tmp_path / "api"
        wiki_entry = _make_kip_wiki_info_entry(kip_id=100)
        status_entry = _make_kip_status_entry(kip_id=100)
        kip_wiki_info = {100: wiki_entry}
        kip_status = [status_entry]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        import json

        with open(api_dir / "kips.json") as f:
            summary = json.load(f)

        assert summary["project"] == "kafka"
        assert summary["proposal_type"] == "KIP"
        assert summary["count"] == 1
        assert len(summary["proposals"]) == 1
        assert summary["proposals"][0]["id"] == 100
        assert "last_updated" in summary

    def test_skips_kips_missing_from_wiki_info(self, tmp_path):
        """Test that KIPs not in wiki_info are skipped."""
        api_dir = tmp_path / "api"
        wiki_entry = _make_kip_wiki_info_entry(kip_id=100)
        status_entry_100 = _make_kip_status_entry(kip_id=100)
        status_entry_200 = _make_kip_status_entry(kip_id=200)
        kip_wiki_info = {100: wiki_entry}  # Only KIP-100
        kip_status = [status_entry_100, status_entry_200]  # Both KIP-100 and KIP-200

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        import json

        with open(api_dir / "kips.json") as f:
            summary = json.load(f)

        # Should only have KIP-100
        assert summary["count"] == 1
        assert len(summary["proposals"]) == 1
        assert summary["proposals"][0]["id"] == 100

        # KIP-100 detail file should exist
        assert (api_dir / "kips" / "100.json").exists()

        # KIP-200 detail file should not exist
        assert not (api_dir / "kips" / "200.json").exists()

    def test_multiple_kips(self, tmp_path):
        """Test handling multiple KIPs."""
        api_dir = tmp_path / "api"
        wiki_100 = _make_kip_wiki_info_entry(kip_id=100)
        wiki_200 = _make_kip_wiki_info_entry(kip_id=200)
        status_100 = _make_kip_status_entry(kip_id=100)
        status_200 = _make_kip_status_entry(kip_id=200)
        kip_wiki_info = {100: wiki_100, 200: wiki_200}
        kip_status = [status_100, status_200]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        import json

        with open(api_dir / "kips.json") as f:
            summary = json.load(f)

        assert summary["count"] == 2
        assert len(summary["proposals"]) == 2
        assert (api_dir / "kips" / "100.json").exists()
        assert (api_dir / "kips" / "200.json").exists()
