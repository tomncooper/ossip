"""Rendering and JSON API output for GitHub-based proposal tracking."""

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ipper.common.api_output import (
    write_project_summary,
    write_proposal_details,
)
from ipper.common.constants import DATE_FORMAT, DEFAULT_TEMPLATES_DIR, IPState
from ipper.common.github_config import GithubProjectConfig
from ipper.common.github_models import Amendment, GithubProposalDetail
from ipper.common.models import (
    GithubProposalSummary,
    ProjectSummary,
    ReviewCount,
    ReviewerInfo,
    ReviewSummary,
)

logger = logging.getLogger(__name__)

GITHUB_INDEX_TEMPLATE = "github-index.html.jinja"
GITHUB_MORE_INFO_TEMPLATE = "github-more-info.html.jinja"

STATE_EMOJI = {
    IPState.ACCEPTED: "✅",
    IPState.NOT_ACCEPTED: "❌",
}


def _get_template(template_dir: str, template_filename: str):
    return Environment(
        loader=FileSystemLoader(template_dir), autoescape=True
    ).get_template(template_filename)


def detail_page_filename(config: GithubProjectConfig, record: dict[str, Any]) -> str:
    """Detail page filename for a proposal record.

    Numbered proposals use '{PREFIX}-{number}.html'; unnumbered ones (SIP/
    SHIP proposals before merge) use '{PREFIX}-PR-{pr_number}.html'.
    """

    number = record.get("id")
    if number is not None:
        return f"{config.prefix}-{number}.html"
    return f"{config.prefix}-PR-{record['pr_number']}.html"


def detail_json_filename(config: GithubProjectConfig, record: dict[str, Any]) -> str:
    """Detail JSON filename for a proposal record."""

    number = record.get("id")
    if number is not None:
        return f"{number}"
    return f"PR-{record['pr_number']}"


def display_id(config: GithubProjectConfig, record: dict[str, Any]) -> str:
    """Table display id: the number, or 'PR #N' for unnumbered proposals."""

    number = record.get("id")
    if number is not None:
        return str(number)
    return f"PR #{record['pr_number']}"


def _sorted_proposals(cache: dict[str, Any]) -> list[dict[str, Any]]:
    """Proposal records sorted by created_on (descending)."""

    return sorted(
        cache.get("proposals", {}).values(),
        key=lambda record: record.get("created_on") or "",
        reverse=True,
    )


EMPTY_REVIEW_ACTIVITY: dict[str, list[dict[str, str]]] = {
    "accepted": [],
    "commented": [],
    "changes_requested": [],
}


def _review_activity(record: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """A record's review activity, defaulting to empty lists."""

    return record.get("reviews") or EMPTY_REVIEW_ACTIVITY


def _prepare_row(config: GithubProjectConfig, record: dict[str, Any]) -> dict[str, Any]:
    """Prepare a template-friendly dict for one index table row."""

    state = IPState(record.get("state") or "unknown")
    return {
        "display_id": display_id(config, record),
        "title": record.get("title", ""),
        "state": state,
        "authors": record.get("authors", []),
        "created_on": record.get("created_on", ""),
        "reviews": _review_activity(record),
        "web_url": record.get("web_url", ""),
        "emoji": None if state == IPState.UNDER_DISCUSSION else STATE_EMOJI.get(state),
        "activity_status": record.get("activity_status"),
        "last_activity_age": record.get("last_activity_age"),
        "detail_url": f"{config.detail_dirname}/{detail_page_filename(config, record)}",
    }


def render_index_page(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    output_filename: str,
    detail_dir: str | None = None,
    templates_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = GITHUB_INDEX_TEMPLATE,
) -> None:
    """Render the project's proposal index page.

    Rows are ordered by created_on (descending).
    """

    output_path = Path(output_filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template = _get_template(templates_dir, template_filename)

    rows = [_prepare_row(config, record) for record in _sorted_proposals(cache)]

    output: str = template.render(
        project_name=config.name,
        prefix=config.prefix,
        rows=rows,
        detail_dirname=detail_dir if detail_dir is not None else config.detail_dirname,
        date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
    )

    with open(output_path, "w", encoding="utf8") as out_file:
        out_file.write(output)


def _prepare_detail(
    config: GithubProjectConfig, record: dict[str, Any]
) -> dict[str, Any]:
    detail = dict(record)
    detail["reviews"] = _review_activity(record)
    detail["heading"] = (
        f"{config.prefix}-{record['id']}"
        if record.get("id") is not None
        else f"{config.prefix} PR #{record['pr_number']}"
    )
    return detail


def render_detail_pages(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    output_directory: str,
    templates_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = GITHUB_MORE_INFO_TEMPLATE,
) -> None:
    """Render individual more-info pages for each proposal."""

    template = _get_template(templates_dir, template_filename)

    output_dir_path = Path(output_directory)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    for record in cache.get("proposals", {}).values():
        output_filepath = output_dir_path / detail_page_filename(config, record)

        output: str = template.render(
            prefix=config.prefix,
            project_name=config.name,
            detail_page_dir=config.key,
            data=_prepare_detail(config, record),
            date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
        )

        with open(output_filepath, "w", encoding="utf8") as out_file:
            out_file.write(output)


def _record_to_detail(
    config: GithubProjectConfig, record: dict[str, Any]
) -> GithubProposalDetail:
    reviews = _review_activity(record)

    return GithubProposalDetail(
        id=record.get("id"),
        pr_number=record["pr_number"],
        title=record.get("title", ""),
        state=record.get("state", ""),
        created_by=record.get("created_by", ""),
        authors=record.get("authors", []),
        created_on=record.get("created_on", ""),
        last_modified_on=record.get("last_modified_on")
        or record.get("merged_on")
        or record.get("created_on", ""),
        last_modified_by=record.get("created_by", ""),
        discussion_thread=None,
        vote_thread=None,
        jira=None,
        web_url=record.get("web_url", ""),
        activity_status=record.get("activity_status"),
        reviews=ReviewSummary(
            accepted=[
                ReviewerInfo(login=r["name"], timestamp=r["timestamp"])
                for r in reviews["accepted"]
            ],
            commented=[
                ReviewerInfo(login=r["name"], timestamp=r["timestamp"])
                for r in reviews["commented"]
            ],
            changes_requested=[
                ReviewerInfo(login=r["name"], timestamp=r["timestamp"])
                for r in reviews["changes_requested"]
            ],
        ),
        merged_on=record.get("merged_on"),
        pr_url=record.get("pr_url"),
        amendments=[
            Amendment(**amendment) for amendment in record.get("amendments", [])
        ],
    )


def _record_to_summary(
    config: GithubProjectConfig, record: dict[str, Any]
) -> GithubProposalSummary:
    reviews = _review_activity(record)
    return GithubProposalSummary(
        id=record.get("id"),
        pr_number=record["pr_number"],
        title=record.get("title", ""),
        state=record.get("state", ""),
        created_by=record.get("created_by", ""),
        authors=record.get("authors", []),
        created_on=record.get("created_on", ""),
        review_count=ReviewCount(
            accepted=len(reviews["accepted"]),
            commented=len(reviews["commented"]),
            changes_requested=len(reviews["changes_requested"]),
        ),
        activity_status=record.get("activity_status"),
        detail_url=(
            f"{config.detail_dirname}/{detail_json_filename(config, record)}.json"
        ),
        web_url=record.get("web_url", ""),
    )


def generate_github_json_api(
    config: GithubProjectConfig, cache: dict[str, Any], api_dir: Path
) -> None:
    """Generate JSON API files for a GitHub-tracked project.

    Creates:
    - {prefix}s.json: Summary file with all proposals
    - {prefix}s/{detail}.json: Individual detail files

    Args:
        config: The project configuration
        cache: The project's cache data
        api_dir: Base directory for API output
    """

    proposals = _sorted_proposals(cache)

    details = [_record_to_detail(config, record) for record in proposals]
    summaries = [_record_to_summary(config, record) for record in proposals]

    write_proposal_details(details, api_dir / config.detail_dirname)

    project_summary = ProjectSummary(
        project=config.key,
        proposal_type=config.prefix,
        last_updated=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        count=len(summaries),
        proposals=summaries,
    )

    write_project_summary(project_summary, api_dir / f"{config.detail_dirname}.json")
