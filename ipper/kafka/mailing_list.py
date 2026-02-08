import os
import re
from enum import Enum
from pathlib import Path

from pandas import DataFrame, concat

from ipper.common.mailing_list import (
    get_monthly_mbox_file as generic_get_monthly_mbox_file,
)
from ipper.common.mailing_list import (
    get_multiple_mbox as generic_get_multiple_mbox,
)
from ipper.common.mailing_list import (
    load_mbox_cache_file,
)
from ipper.common.mailing_list import (
    process_mbox_archive as generic_process_mbox_archive,
)

KIP_PATTERN: re.Pattern = re.compile(r"KIP-(?P<kip>\d+)", re.IGNORECASE)
DOMAIN: str = "kafka.apache.org"
KIP_MENTION_COLUMNS = [
    "kip",
    "mention_type",
    "message_id",
    "mbox_year",
    "mbox_month",
    "timestamp",
    "from",
    "vote",
]
METADATA_FILE = "kip_mentions_metadata.json"


class KIPMentionType(Enum):
    """Enum class representing the possible types of KIP mention"""

    SUBJECT = "subject"
    VOTE = "vote"
    DISCUSS = "discuss"
    BODY = "body"


def kmt_from_str(mention_type: str) -> KIPMentionType:
    """Finds the KIPMentionType enum value which matches the supplied string.
    Raises a ValueError if the supplied string doesn't match a mention type."""

    for option in KIPMentionType:
        if mention_type == option.value:
            return option

    raise ValueError(f"{mention_type} is not a valid KIPMentionType")


def get_monthly_mbox_file(
    mailing_list: str,
    year: int,
    month: int,
    overwrite: bool = False,
    output_directory: str | None = None,
    timeout: int = 30,
) -> Path:
    """Downloads the specified mbox archive file from the specified mailing list"""

    return generic_get_monthly_mbox_file(
        mailing_list,
        DOMAIN,
        year,
        month,
        overwrite,
        output_directory,
        timeout,
    )


def get_multiple_mbox(
    mailing_list: str,
    days_back: int | None = None,
    output_directory: str | None = None,
    overwrite: bool = False,
    use_metadata: bool = False,
) -> list[Path]:
    """Gets all monthly mbox archives from the specified mailing list.

    If use_metadata is True and metadata exists, downloads only new months since last update.
    Otherwise downloads based on days_back parameter.
    """

    return generic_get_multiple_mbox(
        mailing_list,
        DOMAIN,
        METADATA_FILE,
        days_back,
        output_directory,
        overwrite,
        use_metadata,
    )


def process_mbox_archive(filepath: Path) -> DataFrame:
    """Process the supplied mbox archive, harvest the KIP data and
    create a DataFrame containing each mention"""

    return generic_process_mbox_archive(
        filepath,
        KIP_PATTERN,
        "kip",
        KIP_MENTION_COLUMNS,
        vote_keyword="VOTE",
        discuss_keyword="DISCUSS",
    )


def update_kip_mentions_cache(
    new_mbox_files: list[Path], output_file: Path, mbox_directory: Path
) -> DataFrame:
    """Update the kip mentions cache by processing new mbox files and appending to existing cache.

    Args:
        new_mbox_files: List of newly downloaded mbox files to process
        output_file: Path to the kip_mentions.csv file
        mbox_directory: Directory containing mbox files

    Returns:
        The updated DataFrame with all mentions
    """

    # Load existing kip_mentions.csv if it exists
    if output_file.exists():
        print(f"Loading existing KIP mentions from {output_file}")
        existing_mentions: DataFrame = load_mbox_cache_file(output_file)
    else:
        print("No existing KIP mentions file found, starting fresh")
        existing_mentions = DataFrame(columns=KIP_MENTION_COLUMNS)

    # Process new mbox files directly (no intermediate cache)
    print(f"Processing {len(new_mbox_files)} new mbox file(s)")
    new_mentions: DataFrame = DataFrame(columns=KIP_MENTION_COLUMNS)

    for mbox_file in new_mbox_files:
        print(f"Processing {mbox_file.name}")
        try:
            file_data = process_mbox_archive(mbox_file)
            new_mentions = concat((new_mentions, file_data), ignore_index=True)
        except Exception as ex:
            print(f"ERROR processing file {mbox_file.name}: {ex}")

    # Combine and deduplicate
    combined: DataFrame = concat((existing_mentions, new_mentions), ignore_index=True)
    combined = combined.drop_duplicates()

    # Save updated cache
    combined.to_csv(output_file, index=False)
    print(
        f"Saved updated KIP mentions to {output_file} ({len(combined)} total mentions)"
    )

    return combined


def get_most_recent_mentions(kip_mentions: DataFrame) -> DataFrame:
    """Gets the most recent mentions, for each metion type, for each kip from
    the supplied mentions dataframe"""

    output = []

    for _, kip_mention_data in kip_mentions.groupby(["kip", "mention_type"]):
        output.append(
            kip_mention_data[
                kip_mention_data["timestamp"] == kip_mention_data["timestamp"].max()
            ]
        )

    return concat(output, ignore_index=True)


def get_most_recent_mention_by_type(kip_mentions: DataFrame) -> DataFrame:
    """Gets a dataframe indexed by KIP number with the most recent mention of each mention type."""

    most_recent_kip_mentions: DataFrame = get_most_recent_mentions(kip_mentions)

    most_recent: DataFrame = most_recent_kip_mentions.pivot_table(
        index="kip", columns="mention_type", values="timestamp"
    )
    most_recent["overall"] = most_recent.max(axis=1, skipna=True, numeric_only=False)

    return most_recent
