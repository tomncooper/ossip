import datetime as dt
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template
from pandas import DataFrame

from ipper.common.constants import DATE_FORMAT, DEFAULT_TEMPLATES_DIR, NOT_SET_STR
from ipper.common.mailing_list import create_vote_dict as _create_vote_dict
from ipper.common.models import (
    FlipDetail,
    ProposalSummary,
    ProjectSummary,
    VoteCount,
    VoterInfo,
    VoteSummary,
)
from ipper.common.api_output import (
    confluence_date_to_iso_date,
    confluence_date_to_iso_datetime,
    vote_timestamp_to_iso,
    sentinel_to_none,
    write_proposal_details,
    write_project_summary,
)

logger = logging.getLogger(__name__)

FLINK_MAIN_PAGE_TEMPLATE = "flink-index.html.jinja"
FLIP_RAW_INFO_PAGE_TEMPLATE = "flip-more-info.html.jinja"


def get_template(template_dir: str, template_filename) -> Template:

    template_path = Path(template_dir).joinpath(Path(template_filename))
    if not template_path.exists():
        raise AttributeError(f"Template {template_path} not found")

    template: Template = Environment(
        loader=FileSystemLoader(template_dir)
    ).get_template(template_filename)

    return template


def create_vote_dict(
    flip_mentions: DataFrame,
) -> dict[int, dict[str, list[dict[str, str]]]]:
    """Creates a dictionary mapping from FLIP ID to vote info by type."""
    return _create_vote_dict(flip_mentions, "flip")


def enrich_flip_wiki_info_with_votes(
    flip_wiki_info: dict,
    flip_mentions: DataFrame,
) -> dict:
    """Enriches FLIP wiki information with vote data from mailing list mentions.

    Args:
        flip_wiki_info: Dictionary of FLIP wiki data (keyed by FLIP ID as string)
        flip_mentions: DataFrame containing FLIP mentions

    Returns:
        Enriched dictionary with vote information added
    """

    vote_dict: dict[int, dict[str, list[dict[str, str]]]] = create_vote_dict(
        flip_mentions
    )

    enriched_info: dict = {}
    for flip_id_str, flip_data in flip_wiki_info.items():
        flip_id = int(flip_id_str)
        enriched_flip: dict[str, int | str | list[str] | list[dict[str, str]]] = dict(
            flip_data
        )

        if flip_id in vote_dict:
            for vote in ["+1", "0", "-1"]:
                enriched_flip[vote] = vote_dict[flip_id][vote]
        else:
            for vote in ["+1", "0", "-1"]:
                enriched_flip[vote] = []

        enriched_info[flip_id_str] = enriched_flip

    return enriched_info


def render_flink_main_page(
    wiki_cache: dict,
    output_filepath: str,
    template_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = FLINK_MAIN_PAGE_TEMPLATE,
) -> None:
    """Render the main Flink index page with FLIP data.

    Args:
        wiki_cache: Dictionary of FLIP wiki data (already enriched with vote data)
        output_filepath: Path to save the output HTML file
        template_dir: Directory containing Jinja2 templates
        template_filename: Name of the template file
    """

    output_path = Path(output_filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template = get_template(template_dir, template_filename)

    # Put the FLIPS in reverse order
    flip_data = [
        wiki_cache[str(flip_id)]
        for flip_id in sorted([int(key) for key in wiki_cache], reverse=True)
    ]

    output: str = template.render(
        flip_data=flip_data,
        date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
    )

    with open(output_path, "w", encoding="utf8") as out_file:
        out_file.write(output)


def render_raw_info_pages(
    wiki_cache: dict,
    output_directory: str,
    template_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = FLIP_RAW_INFO_PAGE_TEMPLATE,
) -> None:
    """Render individual FLIP information pages.

    Args:
        wiki_cache: Dictionary of FLIP wiki data (already enriched with vote data)
        output_directory: Directory to save the output HTML files
        template_dir: Directory containing Jinja2 templates
        template_filename: Name of the template file
    """

    template = get_template(template_dir, template_filename)

    output_dir_path = Path(output_directory)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    for flip_id, flip in wiki_cache.items():
        filename = f"FLIP-{flip_id}.html"
        output_filepath = output_dir_path.joinpath(Path(filename))

        output: str = template.render(
            flip_data=flip,
            date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
        )

        with open(output_filepath, "w", encoding="utf8") as out_file:
            out_file.write(output)


def flip_to_detail(flip_data: dict) -> FlipDetail:
    """Convert enriched FLIP data to FlipDetail model.

    Args:
        flip_data: Enriched FLIP dict (already contains votes from enrich_flip_wiki_info_with_votes)

    Returns:
        FlipDetail model instance
    """
    # Convert vote lists
    plus_one_votes = [
        VoterInfo(name=v["name"], timestamp=vote_timestamp_to_iso(v["timestamp"]))
        for v in flip_data["+1"]
    ]
    zero_votes = [
        VoterInfo(name=v["name"], timestamp=vote_timestamp_to_iso(v["timestamp"]))
        for v in flip_data["0"]
    ]
    minus_one_votes = [
        VoterInfo(name=v["name"], timestamp=vote_timestamp_to_iso(v["timestamp"]))
        for v in flip_data["-1"]
    ]

    votes = VoteSummary(
        plus_one=plus_one_votes,
        zero=zero_votes,
        minus_one=minus_one_votes,
    )

    return FlipDetail(
        id=int(flip_data["id"]),
        title=flip_data["title"],
        state=flip_data["state"],
        created_by=flip_data["created_by"],
        created_on=confluence_date_to_iso_date(flip_data["created_on"]),
        last_modified_on=confluence_date_to_iso_datetime(flip_data["last_modified_on"]),
        last_modified_by=flip_data["last_modified_by"],
        discussion_thread=sentinel_to_none(flip_data.get("discussion_thread", NOT_SET_STR)),
        vote_thread=sentinel_to_none(flip_data.get("vote_thread", NOT_SET_STR)),
        jira=sentinel_to_none(flip_data.get("jira_link", NOT_SET_STR)),
        web_url=flip_data["web_url"],
        activity_status=None,
        votes=votes,
        release_version=sentinel_to_none(flip_data.get("release_version", NOT_SET_STR)),
        release_component=sentinel_to_none(flip_data.get("release_component", NOT_SET_STR)),
        jira_id=sentinel_to_none(flip_data.get("jira_id", NOT_SET_STR)),
        jira_link=sentinel_to_none(flip_data.get("jira_link", NOT_SET_STR)),
    )


def flip_to_summary(flip_data: dict) -> ProposalSummary:
    """Convert enriched FLIP data to ProposalSummary model.

    Args:
        flip_data: Enriched FLIP dict (already contains votes from enrich_flip_wiki_info_with_votes)

    Returns:
        ProposalSummary model instance
    """
    # Count votes
    vote_count = VoteCount(
        plus_one=len(flip_data["+1"]),
        zero=len(flip_data["0"]),
        minus_one=len(flip_data["-1"]),
    )

    flip_id = int(flip_data["id"])

    return ProposalSummary(
        id=flip_id,
        title=flip_data["title"],
        state=flip_data["state"],
        created_by=flip_data["created_by"],
        created_on=confluence_date_to_iso_date(flip_data["created_on"]),
        vote_count=vote_count,
        activity_status=None,
        detail_url=f"flips/{flip_id}.json",
        web_url=flip_data["web_url"],
    )


def generate_flink_json_api(enriched_wiki_cache: dict, api_dir: Path) -> None:
    """Generate JSON API files for Flink FLIPs.

    Creates:
    - flips.json: Summary file with all FLIPs
    - flips/{id}.json: Individual detail files for each FLIP

    Args:
        enriched_wiki_cache: Dict mapping FLIP ID strings to enriched FLIP dicts
        api_dir: Base directory for API output
    """
    details = []
    summaries = []

    # Sort FLIP IDs numerically in descending order
    # Cache keys are strings, so we need to convert to int for sorting
    sorted_flip_ids = sorted([int(key) for key in enriched_wiki_cache.keys()], reverse=True)

    # Process each FLIP
    for flip_id in sorted_flip_ids:
        flip_id_str = str(flip_id)
        flip_data = enriched_wiki_cache[flip_id_str]

        # Build detail and summary
        detail = flip_to_detail(flip_data)
        summary = flip_to_summary(flip_data)

        details.append(detail)
        summaries.append(summary)

    # Write individual detail files
    write_proposal_details(details, api_dir / "flips")

    # Build and write project summary
    project_summary = ProjectSummary(
        project="flink",
        proposal_type="FLIP",
        last_updated=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        count=len(summaries),
        proposals=summaries,
    )

    write_project_summary(project_summary, api_dir / "flips.json")
