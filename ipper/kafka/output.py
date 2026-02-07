import datetime as dt
import re
from enum import Enum
from pathlib import Path
from typing import cast

from jinja2 import Environment, FileSystemLoader, Template
from pandas import DataFrame, Series, Timedelta, Timestamp, to_datetime

from ipper.common.constants import DATE_FORMAT, DEFAULT_TEMPLATES_DIR, IPState
from ipper.common.utils import calculate_age
from ipper.common.wiki import APACHE_CONFLUENCE_DATE_FORMAT
from ipper.kafka.mailing_list import get_most_recent_mention_by_type
from ipper.kafka.wiki import (
    get_kip_information,
    get_kip_main_page_info,
)

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


def clean_description(description: str):
    """Cleans the kips description of the KIP-XXX string"""

    kip_match: re.Match | None = re.match(KIP_SPLITTER, description)
    if kip_match:
        return description[kip_match.span()[1] :].strip()

    return description


def create_vote_dict(
    kip_mentions: DataFrame,
) -> dict[int, dict[str, list[dict[str, str]]]]:
    """Creates a dictionary mapping from KIP ID to a dict mapping
    from vote type to list of voter info (name and timestamp)"""

    vote_dict: dict[int, dict[str, list[dict[str, str]]]] = {}
    kip_votes: DataFrame
    for kip_id, kip_votes in kip_mentions[~kip_mentions["vote"].isna()][
        ["kip", "from", "vote", "timestamp"]
    ].groupby("kip"):
        kip_dict = {}
        for vote in ["+1", "0", "-1"]:
            vote_rows = kip_votes[kip_votes["vote"] == vote]

            # Keep only the most recent vote per voter
            voter_map: dict[str, dict[str, str]] = {}
            for _, row in vote_rows.iterrows():
                voter_name = row["from"].replace('"', "")
                timestamp = row["timestamp"]

                if (
                    voter_name not in voter_map
                    or timestamp > voter_map[voter_name]["raw_timestamp"]
                ):
                    voter_map[voter_name] = {
                        "name": voter_name,
                        "timestamp": timestamp.strftime("%b %d, %Y %H:%M UTC"),
                        "raw_timestamp": timestamp,
                    }

            # Sort by timestamp descending (newest first) and remove raw_timestamp
            sorted_voters = sorted(
                voter_map.values(), key=lambda x: x["raw_timestamp"], reverse=True
            )
            kip_dict[f"{vote}"] = [
                {"name": v["name"], "timestamp": v["timestamp"]} for v in sorted_voters
            ]

        vote_dict[cast(int, kip_id)] = kip_dict

    return vote_dict


def create_status_dict(
    kip_mentions: DataFrame, kip_wiki_info: dict[int, dict[str, int | str]]
) -> list[dict[str, int | str | KIPStatus | list[dict[str, str]]]]:
    """Calculate a status for each KIP based on how recently it was mentioned in an
    email subject"""

    recent_mentions: DataFrame = get_most_recent_mention_by_type(kip_mentions)

    subject_mentions: Series = recent_mentions["subject"].dropna()

    vote_dict: dict[int, dict[str, list[dict[str, str]]]] = create_vote_dict(
        kip_mentions
    )

    output: list[dict[str, int | str | KIPStatus | list[dict[str, str]]]] = []
    for kip_id in sorted(kip_wiki_info.keys(), reverse=True):
        kip_data: dict[str, int | str] = kip_wiki_info[kip_id]
        if kip_data["state"] == IPState.UNDER_DISCUSSION:
            status_entry: dict[str, int | str | KIPStatus | list[dict[str, str]]] = {}
            status_entry["id"] = kip_id
            status_entry["text"] = clean_description(cast(str, kip_data["title"]))
            status_entry["url"] = kip_data["web_url"]
            status_entry["created_by"] = kip_data["created_by"]
            status_entry["age"] = calculate_age(
                cast(str, kip_data["created_on"]), APACHE_CONFLUENCE_DATE_FORMAT
            )

            if kip_id in subject_mentions:
                status_entry["status"] = calculate_status(subject_mentions[kip_id])
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
    """Renders the KIPs under discussion table with a status entry based on
    how recently the KIP was mentioned in an email subject line."""

    output_path: Path = Path(output_filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    kip_main_info = get_kip_main_page_info()
    kip_wiki_info = get_kip_information(kip_main_info)

    kip_status: list[dict[str, int | str | KIPStatus | list[dict[str, str]]]] = (
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
    kip_wiki_info: dict[int, dict[str, int | str | list[str]]],
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
