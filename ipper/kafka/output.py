import datetime as dt
import logging
import re
from enum import Enum
from pathlib import Path
from typing import cast

from jinja2 import Environment, FileSystemLoader, Template
from pandas import DataFrame, Series, Timedelta, Timestamp, to_datetime

from ipper.common.constants import DATE_FORMAT, DEFAULT_TEMPLATES_DIR, IPState, NOT_SET_STR, UNKNOWN_STR
from ipper.common.mailing_list import create_vote_dict as _create_vote_dict
from ipper.common.models import (
    KipDetail,
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
from ipper.common.utils import calculate_age
from ipper.common.wiki import APACHE_CONFLUENCE_DATE_FORMAT
from ipper.kafka.mailing_list import get_most_recent_mention_by_type
from ipper.kafka.wiki import (
    get_kip_information,
    get_kip_main_page_info,
)

logger = logging.getLogger(__name__)

KIP_SPLITTER: re.Pattern = re.compile(r"KIP-\d+\W?[:-]?\W?", re.IGNORECASE)

KAFKA_MAIN_PAGE_TEMPLATE = "kafka-index.html.jinja"
KIP_RAW_INFO_PAGE_TEMPLATE = "kip-more-info.html.jinja"


class KIPStatus(Enum):
    """Enum representing the possible values of a KIP's status"""

    BLUE = ("blue", Timedelta(weeks=0))
    GREEN = ("green", Timedelta(weeks=4))
    YELLOW = ("yellow", Timedelta(weeks=12))
    RED = ("red", Timedelta(days=365))
    BLACK = ("black", Timedelta.max)

    def __init__(self, text: str, duration: Timedelta) -> None:
        super().__init__()
        self.text = text
        self.duration = duration


def calculate_status(last_mention: Timestamp) -> KIPStatus:
    """Calculates the appropriate KIPStatus instance based on the time
    difference between now and the last mention."""

    now: Timestamp = to_datetime(dt.datetime.now(dt.UTC), utc=True)
    diff: Timedelta = now - last_mention

    if diff <= KIPStatus.GREEN.duration:
        return KIPStatus.GREEN

    if diff <= KIPStatus.YELLOW.duration:
        return KIPStatus.YELLOW

    if diff <= KIPStatus.RED.duration:
        return KIPStatus.RED

    return KIPStatus.BLACK


def get_state_emoji(state: str) -> str:
    """Returns an emoji representing the KIP state.

    Args:
        state: The IPState value as a string

    Returns:
        Emoji string representing the state
    """
    if state == IPState.ACCEPTED:
        return "✅"
    if state == IPState.NOT_ACCEPTED:
        return "❌"
    if state in [IPState.COMPLETED, IPState.IN_PROGRESS]:
        return "✅"
    # For unknown or other states
    return "🚫"


def clean_description(description: str):
    """Cleans the kips description of the KIP-XXX string"""

    kip_match: re.Match | None = re.match(KIP_SPLITTER, description)
    if kip_match:
        return description[kip_match.span()[1] :].strip()

    return description


def create_vote_dict(
    kip_mentions: DataFrame,
) -> dict[int, dict[str, list[dict[str, str]]]]:
    """Creates a dictionary mapping from KIP ID to vote info by type."""
    return _create_vote_dict(kip_mentions, "kip")


def create_status_dict(
    kip_mentions: DataFrame, kip_wiki_info: dict[int, dict[str, int | str]]
) -> list[dict[str, int | str | None | KIPStatus | list[dict[str, str]]]]:
    """Calculate a status for each KIP. For KIPs under discussion, calculate status
    based on how recently it was mentioned in email subject. For other KIPs, use emoji."""

    recent_mentions: DataFrame = get_most_recent_mention_by_type(kip_mentions)

    subject_mentions: Series = recent_mentions["subject"].dropna()

    vote_dict: dict[int, dict[str, list[dict[str, str]]]] = create_vote_dict(
        kip_mentions
    )

    output: list[dict[str, int | str | None | KIPStatus | list[dict[str, str]]]] = []
    for kip_id in sorted(kip_wiki_info.keys(), reverse=True):
        kip_data: dict[str, int | str] = kip_wiki_info[kip_id]
        status_entry: dict[
            str, int | str | None | KIPStatus | list[dict[str, str]]
        ] = {}
        status_entry["id"] = kip_id
        status_entry["text"] = clean_description(cast(str, kip_data["title"]))
        status_entry["url"] = kip_data["web_url"]
        status_entry["created_by"] = kip_data["created_by"]
        status_entry["state"] = kip_data["state"]
        status_entry["age"] = calculate_age(
            cast(str, kip_data["created_on"]), APACHE_CONFLUENCE_DATE_FORMAT
        )

        # Only calculate colored status for KIPs under discussion
        if kip_data["state"] == IPState.UNDER_DISCUSSION:
            if kip_id in subject_mentions:
                status_entry["status"] = calculate_status(subject_mentions[kip_id])
                # Store the last mention date for tooltip display
                last_mention_ts = subject_mentions[kip_id]
                status_entry["last_mention_age"] = calculate_age(
                    last_mention_ts.strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S"
                )
            else:
                created_diff: dt.timedelta = dt.datetime.now(
                    dt.UTC
                ) - dt.datetime.strptime(
                    cast(str, kip_data["created_on"]), APACHE_CONFLUENCE_DATE_FORMAT
                ).replace(tzinfo=dt.UTC)
                if created_diff <= dt.timedelta(days=28):
                    status_entry["status"] = KIPStatus.BLUE
                else:
                    status_entry["status"] = KIPStatus.BLACK
                # No last mention for KIPs that were never discussed
                status_entry["last_mention_age"] = None
            status_entry["emoji"] = None
        else:
            # For non-discussion KIPs, use emoji instead of colored status
            status_entry["status"] = None
            status_entry["last_mention_age"] = None
            status_entry["emoji"] = get_state_emoji(cast(str, kip_data["state"]))

        for vote in ["+1", "0", "-1"]:
            if kip_id in vote_dict:
                status_entry[vote] = vote_dict[kip_id][vote]
            else:
                status_entry[vote] = []

        output.append(status_entry)

    return output


def render_standalone_status_page(
    kip_mentions: DataFrame,
    output_filename: str,
    templates_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = KAFKA_MAIN_PAGE_TEMPLATE,
) -> None:
    """Renders the KIPs table with status entries based on state and recent activity."""

    output_path: Path = Path(output_filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    kip_main_info = get_kip_main_page_info()
    kip_wiki_info = get_kip_information(kip_main_info)

    kip_status: list[dict[str, int | str | None | KIPStatus | list[dict[str, str]]]] = (
        create_status_dict(kip_mentions, kip_wiki_info)
    )

    template: Template = Environment(
        loader=FileSystemLoader(templates_dir)
    ).get_template(template_filename)

    output: str = template.render(
        kip_status=kip_status,
        kip_status_enum=KIPStatus,
        date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
    )

    with open(output_path, "w", encoding="utf8") as out_file:
        out_file.write(output)


def enrich_kip_wiki_info_with_votes(
    kip_wiki_info: dict[int, dict[str, int | str]],
    kip_mentions: DataFrame,
) -> dict[int, dict[str, int | str | list[dict[str, str]]]]:
    """Enriches KIP wiki information with vote data from mailing list mentions."""

    vote_dict: dict[int, dict[str, list[dict[str, str]]]] = create_vote_dict(
        kip_mentions
    )

    enriched_info: dict[int, dict[str, int | str | list[dict[str, str]]]] = {}
    for kip_id, kip_data in kip_wiki_info.items():
        enriched_kip: dict[str, int | str | list[dict[str, str]]] = dict(kip_data)

        if kip_id in vote_dict:
            for vote in ["+1", "0", "-1"]:
                enriched_kip[vote] = vote_dict[kip_id][vote]
        else:
            for vote in ["+1", "0", "-1"]:
                enriched_kip[vote] = []

        enriched_info[kip_id] = enriched_kip

    return enriched_info


def render_kip_info_pages(
    kip_wiki_info: dict[int, dict[str, int | str | list[dict[str, str]]]],
    output_directory: str,
    template_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = KIP_RAW_INFO_PAGE_TEMPLATE,
) -> None:
    """Renders individual more info pages for each KIP."""

    template: Template = Environment(
        loader=FileSystemLoader(template_dir)
    ).get_template(template_filename)

    output_dir_path = Path(output_directory)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    for kip_id, kip in kip_wiki_info.items():
        filename = f"KIP-{kip_id}.html"
        output_filepath = output_dir_path.joinpath(Path(filename))

        output: str = template.render(
            kip_data=kip,
            date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
        )

        with open(output_filepath, "w", encoding="utf8") as out_file:
            out_file.write(output)


def kip_to_detail(wiki_entry: dict, status_entry: dict) -> KipDetail:
    """Convert KIP wiki and status entries to KipDetail model.

    Args:
        wiki_entry: Wiki information dict containing full KIP metadata
        status_entry: Status dict containing activity status and votes

    Returns:
        KipDetail model instance
    """
    # Convert vote lists
    plus_one_votes = [
        VoterInfo(name=v["name"], timestamp=vote_timestamp_to_iso(v["timestamp"]))
        for v in status_entry["+1"]
    ]
    zero_votes = [
        VoterInfo(name=v["name"], timestamp=vote_timestamp_to_iso(v["timestamp"]))
        for v in status_entry["0"]
    ]
    minus_one_votes = [
        VoterInfo(name=v["name"], timestamp=vote_timestamp_to_iso(v["timestamp"]))
        for v in status_entry["-1"]
    ]

    votes = VoteSummary(
        plus_one=plus_one_votes,
        zero=zero_votes,
        minus_one=minus_one_votes,
    )

    # Determine activity_status
    status = status_entry.get("status")
    activity_status = status.text if status is not None else None

    return KipDetail(
        id=status_entry["id"],
        title=wiki_entry["title"],
        state=wiki_entry["state"],
        created_by=wiki_entry["created_by"],
        created_on=confluence_date_to_iso_date(wiki_entry["created_on"]),
        last_modified_on=confluence_date_to_iso_datetime(wiki_entry["last_modified_on"]),
        last_modified_by=wiki_entry["last_modified_by"],
        discussion_thread=sentinel_to_none(wiki_entry["discussion_thread"]),
        vote_thread=sentinel_to_none(wiki_entry["vote_thread"]),
        jira=sentinel_to_none(wiki_entry["jira"]),
        web_url=wiki_entry["web_url"],
        activity_status=activity_status,
        votes=votes,
    )


def kip_to_summary(status_entry: dict, wiki_entry: dict) -> ProposalSummary:
    """Convert KIP status and wiki entries to ProposalSummary model.

    Args:
        status_entry: Status dict containing activity status and votes
        wiki_entry: Wiki information dict containing full KIP metadata

    Returns:
        ProposalSummary model instance
    """
    # Count votes
    vote_count = VoteCount(
        plus_one=len(status_entry["+1"]),
        zero=len(status_entry["0"]),
        minus_one=len(status_entry["-1"]),
    )

    # Determine activity_status
    status = status_entry.get("status")
    activity_status = status.text if status is not None else None

    return ProposalSummary(
        id=status_entry["id"],
        title=wiki_entry["title"],
        state=status_entry["state"],
        created_by=status_entry["created_by"],
        created_on=confluence_date_to_iso_date(wiki_entry["created_on"]),
        vote_count=vote_count,
        activity_status=activity_status,
        detail_url=f"kips/{status_entry['id']}.json",
        web_url=status_entry["url"],
    )


def generate_kafka_json_api(kip_status: list, kip_wiki_info: dict, api_dir: Path) -> None:
    """Generate JSON API files for Kafka KIPs.

    Creates:
    - kips.json: Summary file with all KIPs
    - kips/{id}.json: Individual detail files for each KIP

    Args:
        kip_status: List of status dicts from create_status_dict
        kip_wiki_info: Dict mapping KIP IDs to wiki info dicts
        api_dir: Base directory for API output
    """
    details = []
    summaries = []

    # Process each status entry
    for status_entry in kip_status:
        kip_id = status_entry["id"]

        # Skip KIPs not in wiki_info
        if kip_id not in kip_wiki_info:
            logger.warning(f"Skipping KIP-{kip_id}: not found in wiki info")
            continue

        wiki_entry = kip_wiki_info[kip_id]

        # Build detail and summary
        detail = kip_to_detail(wiki_entry, status_entry)
        summary = kip_to_summary(status_entry, wiki_entry)

        details.append(detail)
        summaries.append(summary)

    # Write individual detail files
    write_proposal_details(details, api_dir / "kips")

    # Build and write project summary
    project_summary = ProjectSummary(
        project="kafka",
        proposal_type="KIP",
        last_updated=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        count=len(summaries),
        proposals=summaries,
    )

    write_project_summary(project_summary, api_dir / "kips.json")
