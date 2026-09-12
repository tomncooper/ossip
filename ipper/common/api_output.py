"""JSON output utilities for OSSIP API."""

import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path

from ipper.common.constants import NOT_SET_STR, UNKNOWN_STR
from ipper.common.models import (
    ApiIndex,
    FlipDetail,
    KipDetail,
    ProjectMeta,
    ProjectSummary,
    ProposalDetail,
)
from ipper.common.wiki import APACHE_CONFLUENCE_DATE_FORMAT

VOTE_TIMESTAMP_FORMAT = "%b %d, %Y %H:%M UTC"


def confluence_date_to_iso_date(date_str: str) -> str:
    """Convert Confluence date format to ISO date (YYYY-MM-DD).

    Args:
        date_str: Date string in Confluence format (YYYY-MM-DDTHH:MM:SS.000Z)

    Returns:
        ISO date string (YYYY-MM-DD)
    """
    parsed = dt.datetime.strptime(date_str, APACHE_CONFLUENCE_DATE_FORMAT)
    return parsed.strftime("%Y-%m-%d")


def confluence_date_to_iso_datetime(date_str: str) -> str:
    """Convert Confluence date format to ISO datetime (YYYY-MM-DDTHH:MM:SSZ).

    Args:
        date_str: Date string in Confluence format (YYYY-MM-DDTHH:MM:SS.000Z)

    Returns:
        ISO datetime string (YYYY-MM-DDTHH:MM:SSZ)
    """
    parsed = dt.datetime.strptime(date_str, APACHE_CONFLUENCE_DATE_FORMAT)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def vote_timestamp_to_iso(timestamp_str: str) -> str:
    """Convert vote timestamp to ISO datetime.

    Args:
        timestamp_str: Timestamp in format "Jan 02, 2025 10:00 UTC"

    Returns:
        ISO datetime string (YYYY-MM-DDTHH:MM:SSZ)
    """
    parsed = dt.datetime.strptime(timestamp_str, VOTE_TIMESTAMP_FORMAT)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def sentinel_to_none(value: str) -> str | None:
    """Convert sentinel values to None.

    Args:
        value: String value to check

    Returns:
        None if value is a sentinel ("not set" or "unknown"), otherwise the original value
    """
    if value in (NOT_SET_STR, UNKNOWN_STR):
        return None
    return value


def write_json_file(
    model: ProjectMeta | ProjectSummary | ApiIndex | ProposalDetail, path: Path
) -> None:
    """Write a Pydantic model to a JSON file.

    Args:
        model: Pydantic model instance to write
        path: Path to write JSON file to
    """
    # Create parent directories if they don't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON with indentation
    json_content = model.model_dump_json(indent=2)
    path.write_text(json_content)


def write_proposal_details(proposals: Sequence[ProposalDetail], dir_path: Path) -> None:
    """Write individual JSON files for each proposal.

    Args:
        proposals: Sequence of proposal detail models
        dir_path: Directory to write proposal JSON files to
    """
    for proposal in proposals:
        file_path = dir_path / f"{proposal.id}.json"
        write_json_file(proposal, file_path)


def write_project_summary(summary: ProjectSummary, path: Path) -> None:
    """Write a project summary to a JSON file.

    Args:
        summary: ProjectSummary model instance
        path: Path to write JSON file to
    """
    write_json_file(summary, path)


def write_schemas(dir_path: Path) -> None:
    """Export JSON schemas for API models.

    Args:
        dir_path: Base directory to write schemas to (will create schemas/ subdirectory)
    """
    schema_dir = dir_path / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)

    # Export schemas for the four main API models
    models_to_export = [
        (ApiIndex, "ApiIndex.schema.json"),
        (ProjectSummary, "ProjectSummary.schema.json"),
        (KipDetail, "KipDetail.schema.json"),
        (FlipDetail, "FlipDetail.schema.json"),
    ]

    for model_class, filename in models_to_export:
        schema = model_class.model_json_schema()
        schema_path = schema_dir / filename
        schema_path.write_text(
            # Use json.dumps for consistent formatting
            json.dumps(schema, indent=2)
        )


def generate_api_index(base_dir: Path) -> None:
    """Generate the API index file by scanning for project summary files.

    Scans for kafka/kips.json and flink/flips.json, reads count and last_updated
    from each found file, builds ApiIndex, writes index.json, and calls write_schemas.

    Resilient: missing projects are skipped, zero projects produces valid empty index.

    Args:
        base_dir: Base directory containing project subdirectories
    """
    projects = {}
    latest_update = None

    # Define project configurations
    project_configs = [
        ("kafka", "kafka/kips.json", "Kafka", "KIP"),
        ("flink", "flink/flips.json", "Flink", "FLIP"),
    ]

    # Scan for each project
    for project_key, summary_path, project_name, proposal_type in project_configs:
        full_path = base_dir / summary_path
        if full_path.exists():
            # Read the summary file to get count and last_updated
            with open(full_path) as f:
                summary_data = json.load(f)

            projects[project_key] = ProjectMeta(
                name=project_name,
                proposal_type=proposal_type,
                count=summary_data["count"],
                summary_url=summary_path,
            )

            # Track the latest update timestamp across all projects
            project_timestamp = summary_data["last_updated"]
            if latest_update is None or project_timestamp > latest_update:
                latest_update = project_timestamp

    # If no projects found, use current timestamp
    if latest_update is None:
        latest_update = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build the API index
    index = ApiIndex(
        version=1,
        last_updated=latest_update,
        projects=projects,
    )

    # Write index.json
    index_path = base_dir / "index.json"
    write_json_file(index, index_path)

    # Write schemas
    write_schemas(base_dir)
