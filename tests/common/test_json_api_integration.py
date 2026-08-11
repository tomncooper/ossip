"""Integration tests for JSON API generation pipeline."""

import datetime as dt
import json

from ipper.common.api_output import generate_api_index
from ipper.common.models import (
    ApiIndex,
    FlipDetail,
    KipDetail,
    ProjectSummary,
)
from ipper.flink.output import generate_flink_json_api
from ipper.kafka.output import (
    KIPStatus,
    generate_kafka_json_api,
    render_standalone_status_page,
)


def _make_kip_wiki_info_entry(kip_id=100, state="under discussion"):
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
        "state": state,
        "jira": "https://issues.apache.org/jira/browse/KAFKA-12345",
        "discussion_thread": "https://lists.apache.org/thread/abc123",
        "vote_thread": "not set",
    }


def _make_kip_status_entry(kip_id=100, state="under discussion", status=None):
    """Factory for creating test KIP status entries."""
    return {
        "id": kip_id,
        "text": "Test Proposal",
        "url": f"https://wiki.apache.org/confluence/display/KAFKA/KIP-{kip_id}",
        "created_by": "Alice",
        "state": state,
        "age": "1 year",
        "status": status,
        "last_mention_age": "2 weeks" if status else None,
        "emoji": None if status else "✅",
        "+1": [{"name": "Charlie", "timestamp": "Feb 10, 2025 09:00 UTC"}],
        "0": [],
        "-1": [{"name": "Eve", "timestamp": "Feb 09, 2025 11:00 UTC"}],
    }


def _make_enriched_flip(flip_id=42, state="in progress"):
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
        "state": state,
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


class TestKafkaIntegration:
    """End-to-end integration tests for Kafka JSON API generation."""

    def test_multi_kip_pipeline_with_different_states(self, tmp_path):
        """Test full pipeline with multiple KIPs in different states.

        Verifies:
        - kips.json validates as ProjectSummary
        - Individual kips/{id}.json files validate as KipDetail
        - Sentinel values are None in output
        - activity_status is correct for each state
        """
        api_dir = tmp_path / "api"

        # Create test data: 3 KIPs in different states
        # KIP-100: under discussion with green status
        wiki_100 = _make_kip_wiki_info_entry(kip_id=100, state="under discussion")
        status_100 = _make_kip_status_entry(
            kip_id=100, state="under discussion", status=KIPStatus.GREEN
        )

        # KIP-200: accepted (no activity status)
        wiki_200 = _make_kip_wiki_info_entry(kip_id=200, state="accepted")
        wiki_200["vote_thread"] = "unknown"  # Test sentinel
        status_200 = _make_kip_status_entry(kip_id=200, state="accepted", status=None)

        # KIP-300: under discussion with yellow status
        wiki_300 = _make_kip_wiki_info_entry(kip_id=300, state="under discussion")
        wiki_300["jira"] = "not set"  # Test sentinel
        status_300 = _make_kip_status_entry(
            kip_id=300, state="under discussion", status=KIPStatus.YELLOW
        )

        kip_wiki_info = {100: wiki_100, 200: wiki_200, 300: wiki_300}
        kip_status = [status_100, status_200, status_300]

        # Generate JSON API
        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        # Verify kips.json validates as ProjectSummary
        with open(api_dir / "kips.json") as f:
            summary_data = json.load(f)

        summary = ProjectSummary(**summary_data)
        assert summary.project == "kafka"
        assert summary.proposal_type == "KIP"
        assert summary.count == 3
        assert len(summary.proposals) == 3

        # Verify individual detail files validate as KipDetail
        for kip_id in [100, 200, 300]:
            detail_path = api_dir / "kips" / f"{kip_id}.json"
            assert detail_path.exists()

            with open(detail_path) as f:
                detail_data = json.load(f)

            detail = KipDetail(**detail_data)
            assert detail.id == kip_id

        # Verify sentinel values are None
        with open(api_dir / "kips" / "200.json") as f:
            kip_200_data = json.load(f)
        assert kip_200_data["vote_thread"] is None

        with open(api_dir / "kips" / "300.json") as f:
            kip_300_data = json.load(f)
        assert kip_300_data["jira"] is None

        # Verify activity_status is correct
        with open(api_dir / "kips" / "100.json") as f:
            kip_100_data = json.load(f)
        assert kip_100_data["activity_status"] == "green"

        with open(api_dir / "kips" / "200.json") as f:
            kip_200_data = json.load(f)
        assert (
            kip_200_data["activity_status"] is None
        )  # Accepted KIPs have no activity status

        with open(api_dir / "kips" / "300.json") as f:
            kip_300_data = json.load(f)
        assert kip_300_data["activity_status"] == "yellow"

    def test_sentinel_values_never_appear_in_output(self, tmp_path):
        """Verify that 'not set' and 'unknown' are never in JSON output."""
        api_dir = tmp_path / "api"

        # Create KIP with all sentinel values
        wiki_entry = _make_kip_wiki_info_entry(kip_id=100)
        wiki_entry["jira"] = "not set"
        wiki_entry["discussion_thread"] = "unknown"
        wiki_entry["vote_thread"] = "not set"

        status_entry = _make_kip_status_entry(kip_id=100)

        kip_wiki_info = {100: wiki_entry}
        kip_status = [status_entry]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        # Read the generated JSON
        with open(api_dir / "kips" / "100.json") as f:
            kip_data = json.load(f)

        # Verify no sentinel strings in the output
        json_str = json.dumps(kip_data)
        assert "not set" not in json_str
        assert "unknown" not in json_str

        # Verify they are None instead
        assert kip_data["jira"] is None
        assert kip_data["discussion_thread"] is None
        assert kip_data["vote_thread"] is None

    def test_activity_status_colored_for_discussion_none_for_others(self, tmp_path):
        """Verify activity_status logic: colored for discussion, None for others."""
        api_dir = tmp_path / "api"

        # Create KIPs in different states
        wiki_discussion = _make_kip_wiki_info_entry(
            kip_id=100, state="under discussion"
        )
        status_discussion = _make_kip_status_entry(
            kip_id=100, state="under discussion", status=KIPStatus.BLUE
        )

        wiki_accepted = _make_kip_wiki_info_entry(kip_id=200, state="accepted")
        status_accepted = _make_kip_status_entry(
            kip_id=200, state="accepted", status=None
        )

        kip_wiki_info = {100: wiki_discussion, 200: wiki_accepted}
        kip_status = [status_discussion, status_accepted]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        # Check discussion KIP has colored status
        with open(api_dir / "kips" / "100.json") as f:
            discussion_data = json.load(f)
        assert discussion_data["activity_status"] == "blue"

        # Check accepted KIP has no activity status
        with open(api_dir / "kips" / "200.json") as f:
            accepted_data = json.load(f)
        assert accepted_data["activity_status"] is None


class TestFlinkIntegration:
    """End-to-end integration tests for Flink JSON API generation."""

    def test_multi_flip_pipeline_with_flink_specific_fields(self, tmp_path):
        """Test full pipeline with multiple FLIPs.

        Verifies:
        - flips.json validates as ProjectSummary
        - Individual flips/{id}.json files validate as FlipDetail
        - Flink-specific fields are populated
        - activity_status is always None
        """
        api_dir = tmp_path / "api"

        # Create test data: 3 FLIPs
        flip_42 = _make_enriched_flip(flip_id=42, state="in progress")
        flip_100 = _make_enriched_flip(flip_id=100, state="under discussion")
        flip_200 = _make_enriched_flip(flip_id=200, state="accepted")
        flip_200["release_version"] = "1.19"
        flip_200["release_component"] = "Runtime"

        enriched_wiki_cache = {"42": flip_42, "100": flip_100, "200": flip_200}

        # Generate JSON API
        generate_flink_json_api(enriched_wiki_cache, api_dir)

        # Verify flips.json validates as ProjectSummary
        with open(api_dir / "flips.json") as f:
            summary_data = json.load(f)

        summary = ProjectSummary(**summary_data)
        assert summary.project == "flink"
        assert summary.proposal_type == "FLIP"
        assert summary.count == 3
        assert len(summary.proposals) == 3

        # Verify individual detail files validate as FlipDetail
        for flip_id in [42, 100, 200]:
            detail_path = api_dir / "flips" / f"{flip_id}.json"
            assert detail_path.exists()

            with open(detail_path) as f:
                detail_data = json.load(f)

            detail = FlipDetail(**detail_data)
            assert detail.id == flip_id

    def test_flink_specific_fields_populated(self, tmp_path):
        """Verify Flink-specific fields are correctly populated."""
        api_dir = tmp_path / "api"

        flip_data = _make_enriched_flip(flip_id=42)
        flip_data["release_version"] = "1.18"
        flip_data["release_component"] = "Runtime"
        flip_data["jira_id"] = "FLINK-12345"
        flip_data["jira_link"] = "https://issues.apache.org/jira/browse/FLINK-12345"

        enriched_wiki_cache = {"42": flip_data}

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        with open(api_dir / "flips" / "42.json") as f:
            detail_data = json.load(f)

        assert detail_data["release_version"] == "1.18"
        assert detail_data["release_component"] == "Runtime"
        assert detail_data["jira_id"] == "FLINK-12345"
        assert (
            detail_data["jira_link"]
            == "https://issues.apache.org/jira/browse/FLINK-12345"
        )

    def test_activity_status_always_none(self, tmp_path):
        """Verify activity_status is always None for FLIPs, regardless of state."""
        api_dir = tmp_path / "api"

        # Create FLIPs in different states
        flip_discussion = _make_enriched_flip(flip_id=100, state="under discussion")
        flip_accepted = _make_enriched_flip(flip_id=200, state="accepted")
        flip_progress = _make_enriched_flip(flip_id=300, state="in progress")

        enriched_wiki_cache = {
            "100": flip_discussion,
            "200": flip_accepted,
            "300": flip_progress,
        }

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        # Check all have None activity_status
        for flip_id in [100, 200, 300]:
            with open(api_dir / "flips" / f"{flip_id}.json") as f:
                flip_data = json.load(f)
            assert flip_data["activity_status"] is None


class TestApiIndexIntegration:
    """Integration tests for API index generation across projects."""

    def test_full_pipeline_kafka_and_flink_with_index(self, tmp_path):
        """Test generating Kafka + Flink APIs and then index.

        Verifies:
        - index.json has correct project count
        - last_updated is correct
        - schemas directory exists with 4 schema files
        """
        api_dir = tmp_path / "api"

        # Generate Kafka JSON API
        wiki_100 = _make_kip_wiki_info_entry(kip_id=100)
        wiki_200 = _make_kip_wiki_info_entry(kip_id=200)
        status_100 = _make_kip_status_entry(kip_id=100)
        status_200 = _make_kip_status_entry(kip_id=200)
        kip_wiki_info = {100: wiki_100, 200: wiki_200}
        kip_status = [status_100, status_200]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir / "kafka")

        # Generate Flink JSON API
        flip_42 = _make_enriched_flip(flip_id=42)
        flip_100 = _make_enriched_flip(flip_id=100)
        flip_200 = _make_enriched_flip(flip_id=200)
        enriched_wiki_cache = {"42": flip_42, "100": flip_100, "200": flip_200}

        generate_flink_json_api(enriched_wiki_cache, api_dir / "flink")

        # Generate API index
        generate_api_index(api_dir)

        # Verify index.json exists and validates
        index_path = api_dir / "index.json"
        assert index_path.exists()

        with open(index_path) as f:
            index_data = json.load(f)

        index = ApiIndex(**index_data)
        assert index.version == 1
        assert len(index.projects) == 2
        assert "kafka" in index.projects
        assert "flink" in index.projects

        # Verify project metadata
        assert index.projects["kafka"].name == "Kafka"
        assert index.projects["kafka"].proposal_type == "KIP"
        assert index.projects["kafka"].count == 2
        assert index.projects["kafka"].summary_url == "kafka/kips.json"

        assert index.projects["flink"].name == "Flink"
        assert index.projects["flink"].proposal_type == "FLIP"
        assert index.projects["flink"].count == 3
        assert index.projects["flink"].summary_url == "flink/flips.json"

        # Verify last_updated is present and valid
        assert index.last_updated
        # Should be in ISO format
        dt.datetime.fromisoformat(index.last_updated.replace("Z", "+00:00"))

        # Verify schemas directory exists with 4 schema files
        schemas_dir = api_dir / "schemas"
        assert schemas_dir.exists()
        assert schemas_dir.is_dir()

        schema_files = list(schemas_dir.glob("*.json"))
        assert len(schema_files) == 4

        expected_schemas = {
            "ApiIndex.schema.json",
            "ProjectSummary.schema.json",
            "KipDetail.schema.json",
            "FlipDetail.schema.json",
        }
        actual_schemas = {f.name for f in schema_files}
        assert actual_schemas == expected_schemas

    def test_index_with_only_kafka(self, tmp_path):
        """Test index generation when only Kafka data exists."""
        api_dir = tmp_path / "api"

        # Generate only Kafka JSON API
        wiki_100 = _make_kip_wiki_info_entry(kip_id=100)
        status_100 = _make_kip_status_entry(kip_id=100)
        kip_wiki_info = {100: wiki_100}
        kip_status = [status_100]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir / "kafka")

        # Generate API index
        generate_api_index(api_dir)

        # Verify index has only Kafka
        with open(api_dir / "index.json") as f:
            index_data = json.load(f)

        index = ApiIndex(**index_data)
        assert len(index.projects) == 1
        assert "kafka" in index.projects
        assert "flink" not in index.projects

    def test_empty_index_when_no_projects(self, tmp_path):
        """Test index generation when no project data exists."""
        api_dir = tmp_path / "api"
        api_dir.mkdir(parents=True, exist_ok=True)

        # Generate API index with no projects
        generate_api_index(api_dir)

        # Verify index exists but has no projects
        with open(api_dir / "index.json") as f:
            index_data = json.load(f)

        index = ApiIndex(**index_data)
        assert index.version == 1
        assert len(index.projects) == 0
        assert index.last_updated  # Should still have a timestamp

        # Schemas should still be generated
        schemas_dir = api_dir / "schemas"
        assert schemas_dir.exists()
        assert len(list(schemas_dir.glob("*.json"))) == 4


class TestSchemaValidation:
    """Tests for validating generated JSON against Pydantic models."""

    def test_generated_kafka_json_validates_against_models(self, tmp_path):
        """Generate Kafka JSON, read back, and validate with Pydantic."""
        api_dir = tmp_path / "api"

        wiki_entry = _make_kip_wiki_info_entry(kip_id=100)
        status_entry = _make_kip_status_entry(kip_id=100)
        kip_wiki_info = {100: wiki_entry}
        kip_status = [status_entry]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)

        # Read and validate summary file
        with open(api_dir / "kips.json") as f:
            summary_data = json.load(f)

        summary = ProjectSummary(**summary_data)
        assert summary.count == 1

        # Read and validate detail file
        with open(api_dir / "kips" / "100.json") as f:
            detail_data = json.load(f)

        detail = KipDetail(**detail_data)
        assert detail.id == 100

    def test_generated_flink_json_validates_against_models(self, tmp_path):
        """Generate Flink JSON, read back, and validate with Pydantic."""
        api_dir = tmp_path / "api"

        flip_data = _make_enriched_flip(flip_id=42)
        enriched_wiki_cache = {"42": flip_data}

        generate_flink_json_api(enriched_wiki_cache, api_dir)

        # Read and validate summary file
        with open(api_dir / "flips.json") as f:
            summary_data = json.load(f)

        summary = ProjectSummary(**summary_data)
        assert summary.count == 1

        # Read and validate detail file
        with open(api_dir / "flips" / "42.json") as f:
            detail_data = json.load(f)

        detail = FlipDetail(**detail_data)
        assert detail.id == 42

    def test_generated_index_validates_against_model(self, tmp_path):
        """Generate index, read back, and validate with Pydantic."""
        api_dir = tmp_path / "api"

        # Generate Kafka data
        wiki_100 = _make_kip_wiki_info_entry(kip_id=100)
        status_100 = _make_kip_status_entry(kip_id=100)
        kip_wiki_info = {100: wiki_100}
        kip_status = [status_100]

        generate_kafka_json_api(kip_status, kip_wiki_info, api_dir / "kafka")

        # Generate index
        generate_api_index(api_dir)

        # Read and validate index
        with open(api_dir / "index.json") as f:
            index_data = json.load(f)

        index = ApiIndex(**index_data)
        assert index.version == 1
        assert len(index.projects) == 1


class TestHtmlUnchanged:
    """Verify HTML rendering still works with refactored signature."""

    def test_render_standalone_status_page_with_precomputed_status(self, tmp_path):
        """Verify render_standalone_status_page works with pre-computed kip_status."""
        output_file = tmp_path / "index.html"

        # Create pre-computed kip_status (same structure as create_status_dict output)
        kip_status = [
            {
                "id": 100,
                "text": "Test Proposal",
                "url": "https://wiki.apache.org/confluence/display/KAFKA/KIP-100",
                "created_by": "Alice",
                "state": "under discussion",
                "age": "1 year",
                "status": KIPStatus.GREEN,
                "last_mention_age": "2 weeks",
                "emoji": None,
                "+1": [{"name": "Charlie", "timestamp": "Feb 10, 2025 09:00 UTC"}],
                "0": [],
                "-1": [{"name": "Eve", "timestamp": "Feb 09, 2025 11:00 UTC"}],
            },
            {
                "id": 200,
                "text": "Another Proposal",
                "url": "https://wiki.apache.org/confluence/display/KAFKA/KIP-200",
                "created_by": "Bob",
                "state": "accepted",
                "age": "6 months",
                "status": None,
                "last_mention_age": None,
                "emoji": "✅",
                "+1": [],
                "0": [],
                "-1": [],
            },
        ]

        # Call render_standalone_status_page with pre-computed status
        render_standalone_status_page(kip_status, str(output_file))

        # Verify HTML file was created
        assert output_file.exists()

        # Verify basic HTML structure
        html_content = output_file.read_text()
        assert "KIP-100" in html_content or "100" in html_content
        assert "KIP-200" in html_content or "200" in html_content
