"""Tests for Flink JSON API conversion functions."""

import datetime as dt
from pathlib import Path

import pytest

from ipper.flink.output import flip_to_detail, flip_to_summary, generate_flink_json_api


def _make_enriched_flip(flip_id=42):
    """Factory for creating enriched FLIP test data.

    Simulates the output of enrich_flip_wiki_info_with_votes().
    """
    return {
        "id": flip_id,
        "title": f"FLIP-{flip_id}: Test Flink Proposal",
        "web_url": f"https://cwiki.apache.org/confluence/display/FLINK/FLIP-{flip_id}",
        "content_url": "https://example.com/api/content/67890",
        "created_on": "2025-03-01T09:00:00.000Z",
        "created_by": "Alice",
        "last_modified_on": "2025-04-15T16:20:00.000Z",
        "last_modified_by": "Bob",
        "state": "in progress",
        "discussion_thread": "https://lists.apache.org/thread/xyz789",
        "vote_thread": "not set",
        "release_component": "Flink",
        "release_version": "1.18",
        "jira_id": "FLINK-54321",
        "jira_link": "https://issues.apache.org/jira/browse/FLINK-54321",
        "+1": [{"name": "Charlie", "timestamp": "Mar 10, 2025 09:00 UTC"}],
        "0": [],
        "-1": [],
    }


class TestFlipToDetail:
    """Tests for flip_to_detail function."""

    def test_basic_conversion(self):
        """Test basic FLIP detail conversion."""
        flip_data = _make_enriched_flip()

        result = flip_to_detail(flip_data)

        assert result.id == 42
        assert result.title == "FLIP-42: Test Flink Proposal"
        assert result.state == "in progress"
        assert result.created_by == "Alice"
        assert result.created_on == "2025-03-01"
        assert result.last_modified_on == "2025-04-15T16:20:00Z"
        assert result.last_modified_by == "Bob"
        assert result.discussion_thread == "https://lists.apache.org/thread/xyz789"
        assert result.vote_thread is None
        assert result.jira == "https://issues.apache.org/jira/browse/FLINK-54321"
        assert result.web_url == f"https://cwiki.apache.org/confluence/display/FLINK/FLIP-42"
        assert result.activity_status is None

    def test_sentinel_values_to_none(self):
        """Test that sentinel values ('not set', 'unknown') are converted to None."""
        flip_data = _make_enriched_flip()
        flip_data["discussion_thread"] = "not set"
        flip_data["vote_thread"] = "unknown"
        flip_data["jira_link"] = "not set"
        flip_data["release_version"] = "unknown"
        flip_data["release_component"] = "not set"
        flip_data["jira_id"] = "unknown"

        result = flip_to_detail(flip_data)

        assert result.discussion_thread is None
        assert result.vote_thread is None
        assert result.jira is None
        assert result.release_version is None
        assert result.release_component is None
        assert result.jira_id is None
        assert result.jira_link is None

    def test_vote_timestamps_converted_to_iso(self):
        """Test that vote timestamps are converted to ISO 8601 format."""
        flip_data = _make_enriched_flip()
        flip_data["+1"] = [
            {"name": "Charlie", "timestamp": "Mar 10, 2025 09:00 UTC"},
            {"name": "David", "timestamp": "Jan 05, 2025 14:30 UTC"},
        ]
        flip_data["-1"] = [
            {"name": "Eve", "timestamp": "Feb 09, 2025 11:00 UTC"}
        ]

        result = flip_to_detail(flip_data)

        assert len(result.votes.plus_one) == 2
        assert result.votes.plus_one[0].name == "Charlie"
        assert result.votes.plus_one[0].timestamp == "2025-03-10T09:00:00Z"
        assert result.votes.plus_one[1].name == "David"
        assert result.votes.plus_one[1].timestamp == "2025-01-05T14:30:00Z"
        assert len(result.votes.minus_one) == 1
        assert result.votes.minus_one[0].name == "Eve"
        assert result.votes.minus_one[0].timestamp == "2025-02-09T11:00:00Z"

    def test_activity_status_always_none(self):
        """Test that activity_status is always None for FLIPs."""
        flip_data = _make_enriched_flip()
        flip_data["state"] = "under discussion"

        result = flip_to_detail(flip_data)

        assert result.activity_status is None

    def test_flink_specific_fields_populated(self):
        """Test that Flink-specific fields are populated correctly."""
        flip_data = _make_enriched_flip()
        flip_data["release_version"] = "1.18"
        flip_data["release_component"] = "Runtime"
        flip_data["jira_id"] = "FLINK-12345"
        flip_data["jira_link"] = "https://issues.apache.org/jira/browse/FLINK-12345"

        result = flip_to_detail(flip_data)

        assert result.release_version == "1.18"
        assert result.release_component == "Runtime"
        assert result.jira_id == "FLINK-12345"
        assert result.jira_link == "https://issues.apache.org/jira/browse/FLINK-12345"

    def test_string_id_converted_to_int(self):
        """Test that string ID is converted to int."""
        flip_data = _make_enriched_flip()
        flip_data["id"] = "42"  # String ID

        result = flip_to_detail(flip_data)

        assert result.id == 42
        assert isinstance(result.id, int)

    def test_no_votes_produces_empty_lists(self):
        """Test that FLIPs with no votes have empty vote lists."""
        flip_data = _make_enriched_flip()
        flip_data["+1"] = []
        flip_data["0"] = []
        flip_data["-1"] = []

        result = flip_to_detail(flip_data)

        assert result.votes.plus_one == []
        assert result.votes.zero == []
        assert result.votes.minus_one == []


class TestFlipToSummary:
    """Tests for flip_to_summary function."""

    def test_basic_conversion(self):
        """Test basic FLIP summary conversion."""
        flip_data = _make_enriched_flip()

        result = flip_to_summary(flip_data)

        assert result.id == 42
        assert result.title == "FLIP-42: Test Flink Proposal"
        assert result.state == "in progress"
        assert result.created_by == "Alice"
        assert result.created_on == "2025-03-01"
        assert result.detail_url == "flips/42.json"
        assert result.web_url == f"https://cwiki.apache.org/confluence/display/FLINK/FLIP-42"

    def test_created_on_is_iso_date(self):
        """Test that created_on is converted to ISO date format."""
        flip_data = _make_enriched_flip()
        flip_data["created_on"] = "2025-03-15T08:20:00.000Z"

        result = flip_to_summary(flip_data)

        assert result.created_on == "2025-03-15"

    def test_vote_count_has_integer_counts(self):
        """Test that vote_count contains integer counts."""
        flip_data = _make_enriched_flip()
        flip_data["+1"] = [
            {"name": "Alice", "timestamp": "Mar 10, 2025 09:00 UTC"},
            {"name": "Bob", "timestamp": "Mar 11, 2025 10:00 UTC"},
        ]
        flip_data["0"] = [
            {"name": "Charlie", "timestamp": "Mar 12, 2025 11:00 UTC"}
        ]
        flip_data["-1"] = []

        result = flip_to_summary(flip_data)

        assert result.vote_count.plus_one == 2
        assert result.vote_count.zero == 1
        assert result.vote_count.minus_one == 0

    def test_detail_url_format(self):
        """Test that detail_url follows the correct format."""
        flip_data = _make_enriched_flip(flip_id=100)

        result = flip_to_summary(flip_data)

        assert result.detail_url == "flips/100.json"

    def test_activity_status_always_none(self):
        """Test that activity_status is always None for FLIPs."""
        flip_data = _make_enriched_flip()
        flip_data["state"] = "under discussion"

        result = flip_to_summary(flip_data)

        assert result.activity_status is None

    def test_string_id_converted_to_int(self):
        """Test that string ID is converted to int."""
        flip_data = _make_enriched_flip()
        flip_data["id"] = "100"

        result = flip_to_summary(flip_data)

        assert result.id == 100
        assert isinstance(result.id, int)


class TestGenerateFlinkJsonApi:
    """Tests for generate_flink_json_api function."""

    def test_creates_summary_and_detail_files(self, tmp_path):
        """Test that function creates flips.json and individual detail files."""
        api_dir = tmp_path / "api"
        flip_data = _make_enriched_flip(flip_id=42)
        enriched_wiki_cache = {"42": flip_data}

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        # Check that flips.json exists
        assert (api_dir / "flips.json").exists()

        # Check that flips/42.json exists
        assert (api_dir / "flips" / "42.json").exists()

    def test_summary_file_structure(self, tmp_path):
        """Test that flips.json has correct structure."""
        api_dir = tmp_path / "api"
        flip_data = _make_enriched_flip(flip_id=42)
        enriched_wiki_cache = {"42": flip_data}

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        import json

        with open(api_dir / "flips.json") as f:
            summary = json.load(f)

        assert summary["project"] == "flink"
        assert summary["proposal_type"] == "FLIP"
        assert summary["count"] == 1
        assert len(summary["proposals"]) == 1
        assert summary["proposals"][0]["id"] == 42
        assert "last_updated" in summary

    def test_string_keys_sorted_by_int_descending(self, tmp_path):
        """Test that FLIPs are sorted by numeric ID in descending order."""
        api_dir = tmp_path / "api"
        flip_10 = _make_enriched_flip(flip_id=10)
        flip_100 = _make_enriched_flip(flip_id=100)
        flip_5 = _make_enriched_flip(flip_id=5)
        # String keys, not in numeric order
        enriched_wiki_cache = {"10": flip_10, "100": flip_100, "5": flip_5}

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        import json

        with open(api_dir / "flips.json") as f:
            summary = json.load(f)

        # Should be sorted 100, 10, 5
        assert summary["count"] == 3
        assert len(summary["proposals"]) == 3
        assert summary["proposals"][0]["id"] == 100
        assert summary["proposals"][1]["id"] == 10
        assert summary["proposals"][2]["id"] == 5

    def test_multiple_flips(self, tmp_path):
        """Test handling multiple FLIPs."""
        api_dir = tmp_path / "api"
        flip_42 = _make_enriched_flip(flip_id=42)
        flip_100 = _make_enriched_flip(flip_id=100)
        enriched_wiki_cache = {"42": flip_42, "100": flip_100}

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        import json

        with open(api_dir / "flips.json") as f:
            summary = json.load(f)

        assert summary["count"] == 2
        assert len(summary["proposals"]) == 2
        assert (api_dir / "flips" / "42.json").exists()
        assert (api_dir / "flips" / "100.json").exists()

    def test_empty_cache_creates_empty_api(self, tmp_path):
        """Test that empty cache creates valid empty API."""
        api_dir = tmp_path / "api"
        enriched_wiki_cache = {}

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        import json

        with open(api_dir / "flips.json") as f:
            summary = json.load(f)

        assert summary["project"] == "flink"
        assert summary["proposal_type"] == "FLIP"
        assert summary["count"] == 0
        assert len(summary["proposals"]) == 0
