"""Flink mailing list processing functionality.

This module provides Flink-specific functions for downloading, parsing, and processing
mbox archives from Apache Flink mailing lists to track FLIP mentions and votes.
"""

import os
import re
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
from ipper.common.mailing_list import (
    process_mbox_files as generic_process_mbox_files,
)

FLIP_PATTERN: re.Pattern = re.compile(r"FLIP-(?P<flip>\d+)", re.IGNORECASE)
DOMAIN: str = "flink.apache.org"
FLIP_MENTION_COLUMNS = [
    "flip",
    "mention_type",
    "message_id",
    "mbox_year",
    "mbox_month",
    "timestamp",
    "from",
    "vote",
]
CACHE_DIR = "flink_processed_mailbox_cache"
METADATA_FILE = "flip_mentions_metadata.json"


def get_monthly_mbox_file(
    mailing_list: str,
    year: int,
    month: int,
    overwrite: bool = False,
    output_directory: str | None = None,
    timeout: int = 30,
) -> Path:
    """Downloads the specified mbox archive file from the specified Flink mailing list.

    Args:
        mailing_list: Name of the mailing list (e.g., 'dev', 'user')
        year: Year of the archive
        month: Month of the archive
        overwrite: Whether to overwrite existing files
        output_directory: Directory to save the file to
        timeout: Request timeout in seconds

    Returns:
        Path to the downloaded mbox file
    """

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
    """Gets all monthly mbox archives from the specified Flink mailing list.

    If use_metadata is True and metadata exists, downloads only new months since last update.
    Otherwise downloads based on days_back parameter.

    Args:
        mailing_list: Name of the mailing list
        days_back: Number of days back to download (if not using metadata)
        output_directory: Directory to save archives
        overwrite: Whether to overwrite existing files
        use_metadata: Whether to use metadata for incremental updates

    Returns:
        List of paths to downloaded mbox files
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
    """Process the supplied mbox archive, harvest the FLIP data and
    create a DataFrame containing each mention.

    Args:
        filepath: Path to the mbox file

    Returns:
        DataFrame containing each FLIP mention with metadata
    """

    return generic_process_mbox_archive(
        filepath,
        FLIP_PATTERN,
        "flip",
        FLIP_MENTION_COLUMNS,
        vote_keyword="VOTE",
        discuss_keyword="DISCUSS",
    )


def process_mbox_files(
    mbox_files: list[Path], cache_dir: Path, overwrite_cache: bool = False
) -> DataFrame:
    """Process a list of mbox files and cache the results under the provided cache directory.

    Args:
        mbox_files: List of mbox file paths to process
        cache_dir: Directory to store cache files
        overwrite_cache: Whether to reprocess and overwrite existing cache files

    Returns:
        Combined DataFrame of all FLIP mentions
    """

    return generic_process_mbox_files(
        mbox_files,
        cache_dir,
        FLIP_PATTERN,
        "flip",
        FLIP_MENTION_COLUMNS,
        overwrite_cache,
    )


def process_all_mbox_in_directory(
    dir_path: Path, overwrite_cache: bool = False
) -> DataFrame:
    """Process all the mbox files in the given directory and harvest all FLIP mentions.

    Args:
        dir_path: Directory containing mbox files
        overwrite_cache: Whether to reprocess existing cache files

    Returns:
        Combined DataFrame of all FLIP mentions
    """

    if not dir_path.is_dir():
        raise ValueError(f"The supplied path ({dir_path}) is not a directory.")

    cache_dir: Path = dir_path.joinpath(CACHE_DIR)

    if not cache_dir.exists():
        os.mkdir(cache_dir)

    mbox_files: list[Path] = []

    for element in dir_path.iterdir():
        if element.is_file():
            if "mbox" in element.name:
                mbox_files.append(element)
            else:
                print(f"Skipping non-mbox file: {element.name}")

    output: DataFrame = process_mbox_files(mbox_files, cache_dir, overwrite_cache)

    return output


def update_flip_mentions_cache(
    new_mbox_files: list[Path], output_file: Path, mbox_directory: Path
) -> DataFrame:
    """Update the flip mentions cache by processing new mbox files and appending to existing cache.

    Args:
        new_mbox_files: List of newly downloaded mbox files to process
        output_file: Path to the flip_mentions.csv file
        mbox_directory: Directory containing mbox files

    Returns:
        The updated DataFrame with all mentions
    """

    # Load existing flip_mentions.csv if it exists
    if output_file.exists():
        print(f"Loading existing FLIP mentions from {output_file}")
        existing_mentions: DataFrame = load_mbox_cache_file(output_file)
    else:
        print("No existing FLIP mentions file found, starting fresh")
        existing_mentions = DataFrame(columns=FLIP_MENTION_COLUMNS)

    # Process new mbox files directly (no intermediate cache)
    print(f"Processing {len(new_mbox_files)} new mbox file(s)")
    new_mentions: DataFrame = DataFrame(columns=FLIP_MENTION_COLUMNS)

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
        f"Saved updated FLIP mentions to {output_file} ({len(combined)} total mentions)"
    )

    return combined


def get_most_recent_mentions(flip_mentions: DataFrame) -> DataFrame:
    """Gets the most recent mentions, for each mention type, for each flip from
    the supplied mentions dataframe.

    Args:
        flip_mentions: DataFrame containing FLIP mentions

    Returns:
        DataFrame with only the most recent mention of each type for each FLIP
    """

    output = []

    for _, flip_mention_data in flip_mentions.groupby(["flip", "mention_type"]):
        output.append(
            flip_mention_data[
                flip_mention_data["timestamp"] == flip_mention_data["timestamp"].max()
            ]
        )

    return concat(output, ignore_index=True)


def get_most_recent_mention_by_type(flip_mentions: DataFrame) -> DataFrame:
    """Gets a dataframe indexed by FLIP number with the most recent mention of each mention type.

    Args:
        flip_mentions: DataFrame containing FLIP mentions

    Returns:
        Pivot table with FLIP numbers as index and mention types as columns
    """

    most_recent_flip_mentions: DataFrame = get_most_recent_mentions(flip_mentions)

    most_recent: DataFrame = most_recent_flip_mentions.pivot_table(
        index="flip", columns="mention_type", values="timestamp"
    )
    most_recent["overall"] = most_recent.max(axis=1, skipna=True, numeric_only=False)

    return most_recent
