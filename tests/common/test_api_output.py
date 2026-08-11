"""Tests for ipper.common.api_output module."""

import datetime as dt
import json
from pathlib import Path

import pytest

from ipper.common.api_output import (
    VOTE_TIMESTAMP_FORMAT,
    confluence_date_to_iso_date,
    confluence_date_to_iso_datetime,
    generate_api_index,
    sentinel_to_none,
    vote_timestamp_to_iso,
    write_json_file,
    write_project_summary,
    write_proposal_details,
    write_schemas,
)
from ipper.common.constants import NOT_SET_STR, UNKNOWN_STR
from ipper.common.models import (
    ApiIndex,
    FlipDetail,
    KipDetail,
    ProjectMeta,
    ProjectSummary,
    ProposalSummary,
    VoteCount,
    VoterInfo,
    VoteSummary,
)


class TestDateConversions:
    """Tests for date conversion functions."""

    def test_confluence_date_to_iso_date(self):
        """Test Confluence date to ISO date conversion."""
        result = confluence_date_to_iso_date("2025-01-15T14:30:00.000Z")
        assert result == "2025-01-15"

    def test_confluence_date_to_iso_date_preserves_date_only(self):
        """Test that time component is dropped correctly."""
        result = confluence_date_to_iso_date("2025-12-31T23:59:59.000Z")
        assert result == "2025-12-31"

    def test_confluence_date_to_iso_datetime(self):
        """Test Confluence date to ISO datetime conversion."""
        result = confluence_date_to_iso_datetime("2025-01-15T14:30:00.000Z")
        assert result == "2025-01-15T14:30:00Z"

    def test_confluence_date_to_iso_datetime_preserves_time(self):
        """Test that time component is preserved correctly."""
        result = confluence_date_to_iso_datetime("2025-12-31T23:59:59.000Z")
        assert result == "2025-12-31T23:59:59Z"

    def test_vote_timestamp_to_iso(self):
        """Test vote timestamp to ISO conversion."""
        result = vote_timestamp_to_iso("Jan 02, 2025 10:00 UTC")
        assert result == "2025-01-02T10:00:00Z"

    def test_vote_timestamp_to_iso_various_months(self):
        """Test vote timestamp conversion with different months."""
        assert vote_timestamp_to_iso("Dec 31, 2024 23:59 UTC") == "2024-12-31T23:59:00Z"
        assert vote_timestamp_to_iso("Jun 15, 2025 12:30 UTC") == "2025-06-15T12:30:00Z"


class TestSentinelToNone:
    """Tests for sentinel_to_none function."""

    def test_not_set_returns_none(self):
        """Test that 'not set' sentinel returns None."""
        assert sentinel_to_none(NOT_SET_STR) is None

    def test_unknown_returns_none(self):
        """Test that 'unknown' sentinel returns None."""
        assert sentinel_to_none(UNKNOWN_STR) is None

    def test_real_values_preserved(self):
        """Test that real values are preserved."""
        assert sentinel_to_none("https://example.com") == "https://example.com"
        assert sentinel_to_none("KAFKA-12345") == "KAFKA-12345"
        assert sentinel_to_none("") == ""

    def test_similar_values_not_filtered(self):
        """Test that similar but not exact sentinel values are preserved."""
        assert sentinel_to_none("not set yet") == "not set yet"
        assert sentinel_to_none("Unknown") == "Unknown"
        assert sentinel_to_none("UNKNOWN") == "UNKNOWN"


class TestWriteJsonFile:
    """Tests for write_json_file function."""

    def test_writes_valid_json(self, tmp_path):
        """Test that valid JSON is written."""
        model = ProjectMeta(
            name="Kafka",
            proposal_type="KIP",
            count=100,
            summary_url="kafka/kips.json",
        )
        file_path = tmp_path / "test.json"

        write_json_file(model, file_path)

        assert file_path.exists()
        with open(file_path) as f:
            data = json.load(f)
        assert data["name"] == "Kafka"
        assert data["count"] == 100

    def test_creates_parent_directories(self, tmp_path):
        """Test that parent directories are created."""
        model = ProjectMeta(
            name="Kafka",
            proposal_type="KIP",
            count=100,
            summary_url="kafka/kips.json",
        )
        file_path = tmp_path / "nested" / "dirs" / "test.json"

        write_json_file(model, file_path)

        assert file_path.exists()
        assert file_path.parent.exists()

    def test_json_is_indented(self, tmp_path):
        """Test that JSON is formatted with indentation."""
        model = ProjectMeta(
            name="Kafka",
            proposal_type="KIP",
            count=100,
            summary_url="kafka/kips.json",
        )
        file_path = tmp_path / "test.json"

        write_json_file(model, file_path)

        content = file_path.read_text()
        # Indented JSON should have newlines and spaces
        assert "\n" in content
        assert "  " in content


class TestWriteProposalDetails:
    """Tests for write_proposal_details function."""

    def test_creates_individual_json_files(self, tmp_path):
        """Test that individual JSON files are created for each proposal."""
        proposals = [
            KipDetail(
                id=1,
                title="Test KIP 1",
                state="accepted",
                created_by="Alice",
                created_on="2025-01-01",
                last_modified_on="2025-01-15T10:00:00Z",
                last_modified_by="Bob",
                discussion_thread=None,
                vote_thread=None,
                jira=None,
                web_url="https://example.com/kip-1",
                activity_status=None,
                votes=VoteSummary(plus_one=[], zero=[], minus_one=[]),
            ),
            KipDetail(
                id=2,
                title="Test KIP 2",
                state="under discussion",
                created_by="Charlie",
                created_on="2025-01-10",
                last_modified_on="2025-01-20T14:30:00Z",
                last_modified_by="Diana",
                discussion_thread="https://example.com/thread",
                vote_thread=None,
                jira="KAFKA-12345",
                web_url="https://example.com/kip-2",
                activity_status="green",
                votes=VoteSummary(plus_one=[], zero=[], minus_one=[]),
            ),
        ]

        write_proposal_details(proposals, tmp_path)

        file1 = tmp_path / "1.json"
        file2 = tmp_path / "2.json"

        assert file1.exists()
        assert file2.exists()

        with open(file1) as f:
            data1 = json.load(f)
        assert data1["id"] == 1
        assert data1["title"] == "Test KIP 1"

        with open(file2) as f:
            data2 = json.load(f)
        assert data2["id"] == 2
        assert data2["title"] == "Test KIP 2"


class TestWriteProjectSummary:
    """Tests for write_project_summary function."""

    def test_writes_summary_with_correct_structure(self, tmp_path):
        """Test that project summary is written with correct structure."""
        summary = ProjectSummary(
            project="Kafka",
            proposal_type="KIP",
            last_updated="2025-01-20T10:00:00Z",
            count=2,
            proposals=[
                ProposalSummary(
                    id=1,
                    title="Test KIP",
                    state="accepted",
                    created_by="Alice",
                    created_on="2025-01-01",
                    vote_count=VoteCount(plus_one=5, zero=0, minus_one=0),
                    activity_status=None,
                    detail_url="kafka/details/1.json",
                    web_url="https://example.com/kip-1",
                )
            ],
        )
        file_path = tmp_path / "summary.json"

        write_project_summary(summary, file_path)

        assert file_path.exists()
        with open(file_path) as f:
            data = json.load(f)
        assert data["project"] == "Kafka"
        assert data["count"] == 2
        assert len(data["proposals"]) == 1


class TestWriteSchemas:
    """Tests for write_schemas function."""

    def test_creates_schema_files(self, tmp_path):
        """Test that schema files are created."""
        write_schemas(tmp_path)

        schema_dir = tmp_path / "schemas"
        assert schema_dir.exists()

        expected_files = [
            "ApiIndex.json",
            "ProjectSummary.json",
            "KipDetail.json",
            "FlipDetail.json",
        ]

        for filename in expected_files:
            schema_file = schema_dir / filename
            assert schema_file.exists(), f"Missing schema file: {filename}"

    def test_schemas_are_valid_json(self, tmp_path):
        """Test that generated schemas are valid JSON."""
        write_schemas(tmp_path)

        schema_dir = tmp_path / "schemas"
        for schema_file in schema_dir.glob("*.json"):
            with open(schema_file) as f:
                data = json.load(f)
            assert isinstance(data, dict)
            # JSON schemas should have a $schema or properties field
            assert "$schema" in data or "properties" in data

    def test_is_idempotent(self, tmp_path):
        """Test that writing schemas multiple times produces same result."""
        write_schemas(tmp_path)
        schema_dir = tmp_path / "schemas"

        # Capture initial content
        initial_contents = {}
        for schema_file in schema_dir.glob("*.json"):
            initial_contents[schema_file.name] = schema_file.read_text()

        # Write again
        write_schemas(tmp_path)

        # Verify content is identical
        for schema_file in schema_dir.glob("*.json"):
            assert schema_file.read_text() == initial_contents[schema_file.name]


class TestGenerateApiIndex:
    """Tests for generate_api_index function."""

    def test_both_projects_present(self, tmp_path):
        """Test generating index when both projects are present."""
        # Create kafka project data
        kafka_dir = tmp_path / "kafka"
        kafka_dir.mkdir()
        kafka_summary = ProjectSummary(
            project="Kafka",
            proposal_type="KIP",
            last_updated="2025-01-20T10:00:00Z",
            count=50,
            proposals=[],
        )
        write_json_file(kafka_summary, kafka_dir / "kips.json")

        # Create flink project data
        flink_dir = tmp_path / "flink"
        flink_dir.mkdir()
        flink_summary = ProjectSummary(
            project="Flink",
            proposal_type="FLIP",
            last_updated="2025-01-25T14:30:00Z",
            count=30,
            proposals=[],
        )
        write_json_file(flink_summary, flink_dir / "flips.json")

        # Generate index
        generate_api_index(tmp_path)

        # Verify index.json exists
        index_file = tmp_path / "index.json"
        assert index_file.exists()

        with open(index_file) as f:
            data = json.load(f)

        assert data["version"] == 1
        # Should use the latest last_updated (flink's)
        assert data["last_updated"] == "2025-01-25T14:30:00Z"
        assert "kafka" in data["projects"]
        assert "flink" in data["projects"]

        kafka_meta = data["projects"]["kafka"]
        assert kafka_meta["name"] == "Kafka"
        assert kafka_meta["proposal_type"] == "KIP"
        assert kafka_meta["count"] == 50
        assert kafka_meta["summary_url"] == "kafka/kips.json"

        flink_meta = data["projects"]["flink"]
        assert flink_meta["name"] == "Flink"
        assert flink_meta["proposal_type"] == "FLIP"
        assert flink_meta["count"] == 30
        assert flink_meta["summary_url"] == "flink/flips.json"

    def test_only_one_project(self, tmp_path):
        """Test generating index when only one project is present."""
        # Create only kafka project
        kafka_dir = tmp_path / "kafka"
        kafka_dir.mkdir()
        kafka_summary = ProjectSummary(
            project="Kafka",
            proposal_type="KIP",
            last_updated="2025-01-20T10:00:00Z",
            count=50,
            proposals=[],
        )
        write_json_file(kafka_summary, kafka_dir / "kips.json")

        # Generate index
        generate_api_index(tmp_path)

        index_file = tmp_path / "index.json"
        assert index_file.exists()

        with open(index_file) as f:
            data = json.load(f)

        assert "kafka" in data["projects"]
        assert "flink" not in data["projects"]
        assert data["last_updated"] == "2025-01-20T10:00:00Z"

    def test_zero_projects_produces_valid_empty_index(self, tmp_path):
        """Test that zero projects produces a valid empty index."""
        # Generate index with no project data
        generate_api_index(tmp_path)

        index_file = tmp_path / "index.json"
        assert index_file.exists()

        with open(index_file) as f:
            data = json.load(f)

        assert data["version"] == 1
        assert data["projects"] == {}
        # Should have a valid timestamp even with no projects
        assert "last_updated" in data
        # Verify it's a valid ISO timestamp
        dt.datetime.fromisoformat(data["last_updated"].replace("Z", "+00:00"))

    def test_writes_schemas(self, tmp_path):
        """Test that generate_api_index calls write_schemas."""
        generate_api_index(tmp_path)

        # Verify schemas were written
        schema_dir = tmp_path / "schemas"
        assert schema_dir.exists()
        assert (schema_dir / "ApiIndex.json").exists()
