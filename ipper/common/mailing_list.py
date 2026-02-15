"""Generic mailing list processing functionality for Apache mailing lists.

This module provides reusable functions for downloading, parsing, and processing
mbox archives from Apache mailing lists. It's used by both Kafka and Flink modules
to track improvement proposal mentions and votes.
"""

import datetime as dt
import json
import os
import re
from email.message import Message
from mailbox import mbox
from pathlib import Path
from typing import cast

import requests
from pandas import DataFrame, concat, read_csv, to_datetime
from rapidfuzz import fuzz

from ipper.common.keys import CommitterIndex, parse_email_from_header
from ipper.common.utils import generate_month_list

APACHE_MAILING_LIST_BASE_URL: str = "https://lists.apache.org/api/mbox.lua"
MAIL_DATE_FORMAT = "%a, %d %b %Y %H:%M:%S %z"
MAIL_DATE_FORMAT_ZONE = "%a, %d %b %Y %H:%M:%S %z (%Z)"
PARENTS_PATTERN = re.compile(r"\(([^)]+)\)")
VOTE_PATTERN = re.compile(r"([\+\-]1|0)", re.IGNORECASE)


def get_monthly_mbox_file(
    mailing_list: str,
    domain: str,
    year: int,
    month: int,
    overwrite: bool = False,
    output_directory: str | None = None,
    timeout: int = 30,
) -> Path:
    """Downloads the specified mbox archive file from the specified mailing list.

    Args:
        mailing_list: Name of the mailing list (e.g., 'dev', 'user')
        domain: Apache domain (e.g., 'kafka.apache.org', 'flink.apache.org')
        year: Year of the archive
        month: Month of the archive
        overwrite: Whether to overwrite existing files
        output_directory: Directory to save the file to
        timeout: Request timeout in seconds

    Returns:
        Path to the downloaded mbox file
    """

    filename = f"{mailing_list}_{domain.replace('.', '_')}-{year}-{month}.mbox"

    filepath: Path
    if not output_directory:
        filepath = Path(filename)
    else:
        filepath = Path(output_directory, filename)

    if filepath.exists():
        if not overwrite:
            print(
                f"Mbox file {filepath} already exists. "
                + "Skipping download (set overwrite to True to re-download)."
            )
            return filepath

        print(f"Overwritting existing mbox file: {filepath}")

    options: dict[str, str] = {
        "list": mailing_list,
        "domain": domain,
        "d": f"{year}-{month}",
    }

    with requests.get(
        APACHE_MAILING_LIST_BASE_URL, params=options, stream=True, timeout=timeout
    ) as response:
        response.raise_for_status()
        with open(filepath, "wb") as mbox_file:
            for chunk in response.iter_content(chunk_size=8192):
                mbox_file.write(chunk)

    return filepath


def get_multiple_mbox(
    mailing_list: str,
    domain: str,
    metadata_file: str,
    days_back: int | None = None,
    output_directory: str | None = None,
    overwrite: bool = False,
    use_metadata: bool = False,
) -> list[Path]:
    """Gets all monthly mbox archives from the specified mailing list.

    Args:
        mailing_list: Name of the mailing list
        domain: Apache domain
        metadata_file: Name of the metadata JSON file
        days_back: Number of days back to download (if not using metadata)
        output_directory: Directory to save archives
        overwrite: Whether to overwrite existing files
        use_metadata: Whether to use metadata for incremental updates

    Returns:
        List of paths to downloaded mbox files
    """

    if not output_directory:
        output_directory = mailing_list

    output_dir: Path = Path(output_directory)

    if not output_dir.exists():
        os.mkdir(output_dir)

    metadata_path: Path = output_dir.parent.joinpath(metadata_file)

    month_list: list[tuple[int, int]]
    if use_metadata:
        month_list = get_months_to_download(metadata_path, days_back)
    else:
        if days_back is None:
            days_back = 365
        now: dt.datetime = dt.datetime.now(dt.UTC)
        then: dt.datetime = now - dt.timedelta(days=days_back)
        print(
            f"Downloading mail archives for mailing list {mailing_list} between {then.isoformat()} and {now.isoformat()}"
        )
        month_list = generate_month_list(now, then)

    filepaths: list[Path] = []
    latest_year = 0
    latest_month = 0

    for year, month in month_list:
        print(f"Downloading {mailing_list} archive for {month}/{year}")
        filepath = get_monthly_mbox_file(
            mailing_list,
            domain,
            year,
            month,
            output_directory=output_directory,
            overwrite=overwrite,
        )
        filepaths.append(filepath)

        # Track the most recent month
        if year > latest_year or (year == latest_year and month > latest_month):
            latest_year = year
            latest_month = month

    # Update metadata if using metadata mode
    if use_metadata and latest_year > 0:
        save_metadata(metadata_path, latest_year, latest_month)

    return filepaths


def save_metadata(metadata_path: Path, year: int, month: int) -> None:
    """Save metadata about the last processed mbox file.

    Args:
        metadata_path: Path to the metadata JSON file
        year: Year of the last processed archive
        month: Month of the last processed archive
    """

    metadata = {
        "last_updated": dt.datetime.now(dt.UTC).isoformat(),
        "latest_mbox_year": year,
        "latest_mbox_month": month,
    }

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Updated metadata: {metadata}")


def load_metadata(metadata_path: Path) -> dict[str, str | int] | None:
    """Load metadata about the last processed mbox file.

    Args:
        metadata_path: Path to the metadata JSON file

    Returns:
        Dictionary containing metadata or None if file doesn't exist
    """

    if not metadata_path.exists():
        return None

    with open(metadata_path) as f:
        metadata = json.load(f)

    return metadata


def get_months_to_download(
    metadata_path: Path, days_back: int | None = None
) -> list[tuple[int, int]]:
    """Determine which months need to be downloaded based on metadata.

    Args:
        metadata_path: Path to the metadata JSON file
        days_back: Number of days back to download (overrides metadata)

    Returns:
        List of (year, month) tuples to download
    """

    now: dt.datetime = dt.datetime.now(dt.UTC)

    metadata = load_metadata(metadata_path)

    if metadata and days_back is None:
        # Incremental update: download from last update to now
        last_year = metadata["latest_mbox_year"]
        last_month = metadata["latest_mbox_month"]

        # Ensure year and month are integers for datetime constructor
        if not isinstance(last_year, int) or not isinstance(last_month, int):
            raise ValueError(
                f"Invalid metadata: year and month must be integers, got {type(last_year)} and {type(last_month)}"
            )

        # Start from the last processed month (re-download it to catch any late emails)
        then = dt.datetime(last_year, last_month, 1, tzinfo=dt.UTC)
        print(f"Incremental update from {then.isoformat()} to {now.isoformat()}")
    else:
        # Full download: use days_back
        if days_back is None:
            days_back = 365
        then = now - dt.timedelta(days=days_back)
        print(f"Full download for last {days_back} days")

    return generate_month_list(now, then)


def parse_message_timestamp(date_str: str) -> dt.datetime | None:
    """Parses the message timestamp string and converts to a python datetime object.

    Args:
        date_str: Date string from email header

    Returns:
        Parsed datetime object or None if parsing fails
    """

    timestamp: dt.datetime | None = None

    try:
        timestamp = dt.datetime.strptime(date_str, MAIL_DATE_FORMAT)
    except ValueError:
        pass
    else:
        return timestamp

    try:
        timestamp = dt.datetime.strptime(date_str, MAIL_DATE_FORMAT_ZONE)
    except ValueError:
        pass
    else:
        return timestamp

    # If neither the main format or one with TZ string work, try stripping
    # the TZ String as one last hail Mary.
    try:
        timestamp = dt.datetime.strptime(date_str.split(" (")[0], MAIL_DATE_FORMAT)
    except ValueError:
        print(f"Could not parse timestamp: {date_str}")

    return timestamp


def extract_message_payload(msg: Message) -> list[str]:
    """Extract email message string from the supplied message instance.

    Args:
        msg: Email message object

    Returns:
        List of valid payload strings (deduplicated)
    """

    valid_payloads: list[str] = []

    for message in msg.walk():
        temp_payload: list[Message | str] | Message | str = message.get_payload()
        if isinstance(temp_payload, list):
            if isinstance(temp_payload[0], Message):
                payload: str = cast(str, temp_payload[0].get_payload())
            elif isinstance(temp_payload[0], str):
                payload = cast(str, message.get_payload())
        elif isinstance(temp_payload, str):
            payload = cast(str, message.get_payload())
        else:
            err_msg: str = f"Expected payload to be list or str no {type(temp_payload)}"
            print(err_msg)
            raise ValueError(err_msg)

        if (
            ("<html>" in payload)
            or ("</html>" in payload)
            or ("<div>" in payload)
            or ("</div>" in payload)
        ):
            # Sometimes the message will contain an additional html copy of the
            # main message
            continue

        if (" " not in payload) or ("PGP SIGNATURE" in payload):
            # If the message doesn't contain a single space the it is probably
            # a public key and def is it has PGP SIGNATURE in it.
            continue

        valid_payloads.append(payload)

    # Sometimes there are multiple copies of the exact same message in a payload so
    # we use a set to remove those.
    valid_payloads_set: set[str] = set(valid_payloads)

    if len(valid_payloads_set) > 1:
        print(
            f"Warning: more than 1 message ({len(valid_payloads)}) in the message payload"
        )

    return list(valid_payloads_set)


def _extract_parenthetical_text(line: str) -> list[str]:
    """Extract all text within parentheses from a line.

    Args:
        line: Text line to search

    Returns:
        List of strings found within parentheses (without the parentheses)
    """
    matches = PARENTS_PATTERN.findall(line)
    return [match.strip() for match in matches]


def _fuzzy_match_binding(text: str, threshold: float = 85.0) -> bool:
    """Check if text fuzzy matches 'binding'.

    Uses rapidfuzz to handle typos like 'binging', 'bindng', 'bindign', etc.

    Args:
        text: Text to check (typically from parentheses)
        threshold: Minimum similarity score (0-100) to consider a match

    Returns:
        True if text matches 'binding' with similarity >= threshold
    """
    if not text:
        return False

    normalized_text = text.lower().strip()
    score = fuzz.ratio(normalized_text, "binding")
    return score >= threshold


def _fuzzy_match_non_binding(text: str, threshold: float = 80.0) -> bool:
    """Check if text fuzzy matches 'non-binding'.

    Uses rapidfuzz to handle variations like 'non binding', 'nonbinding',
    'non-binging', etc. Requires text to start with 'non' to avoid matching
    plain 'binding' (which has 77.8% similarity to 'non-binding').

    Args:
        text: Text to check (typically from parentheses)
        threshold: Minimum similarity score (0-100) to consider a match

    Returns:
        True if text starts with 'non' and matches 'non-binding' with similarity >= threshold
    """
    if not text:
        return False

    normalized_text = text.lower().strip()

    # Must start with 'non' to avoid matching plain 'binding'
    if not normalized_text.startswith("non"):
        return False

    score = fuzz.ratio(normalized_text, "non-binding")
    return score >= threshold


def parse_for_vote(
    payload: str,
    voter_from_header: str,
    committer_index: CommitterIndex | None = None,
) -> str | None:
    """Parses the supplied payload string line by line for voting patterns.

    Ignores lines starting with ">" (reply quotes) and checks if the line contains
    a +1, 0 or -1 voting pattern. Votes are counted as binding if:
    1. Explicitly marked with "(binding)" or fuzzy variations, OR
    2. The voter is identified as a committer via the committer index

    Uses fuzzy matching to handle:
    - Spacing issues: "+1(binding)" vs "+1 (binding)"
    - Typos: "+1(binging)", "+1(bindng)"
    - Format variations for non-binding: "(non binding)", "(nonbinding)"

    Priority: Explicit "(binding)" votes take precedence over committer-based votes.
    This prevents false matches from phrases like "0 concerns" being counted as votes
    when the actual vote appears later in the message.

    Args:
        payload: Email message body text
        voter_from_header: Email 'From' header to identify voter
        committer_index: Optional index of project committers for automatic binding detection

    Returns:
        Vote string ("+1", "0", "-1") or None if no binding vote found
    """

    # First pass: Look for explicit binding/non-binding votes
    for line in payload.split("\n"):
        # Skip quoted lines
        if ">" in line[:10]:
            continue

        # Check if line contains a vote
        vote_match = VOTE_PATTERN.search(line)
        if not vote_match:
            continue

        vote = vote_match.group(1)

        # Extract any parenthetical text from the line
        parenthetical_texts = _extract_parenthetical_text(line)

        # Check for non-binding first (highest priority - prevents counting as binding)
        for text in parenthetical_texts:
            if _fuzzy_match_non_binding(text):
                # Explicitly non-binding, don't count it
                return None

        # Check for binding marker (explicit or fuzzy match)
        for text in parenthetical_texts:
            if _fuzzy_match_binding(text):
                return _normalize_vote(vote)

    # Second pass: If no explicit binding marker found, check if voter is a committer
    # This allows committer votes to be binding, but with lower priority than explicit markers
    # Prefer +1/-1 over 0 to avoid matching incidental zeros in text
    if committer_index:
        voter_name, voter_email = parse_email_from_header(voter_from_header)
        is_match, confidence, method = committer_index.is_committer(
            voter_name, voter_email
        )

        if is_match:
            # Look for +1 or -1 votes first (skip 0 to avoid false matches like "0 concerns")
            for line in payload.split("\n"):
                # Skip quoted lines
                if ">" in line[:10]:
                    continue

                # Check if line contains a +1 or -1 vote
                vote_match = VOTE_PATTERN.search(line)
                if not vote_match:
                    continue

                vote = vote_match.group(1)
                # Skip standalone 0 - only accept +1 or -1 from committers without explicit binding
                if vote == "0":
                    continue

                print(
                    f"  Detected binding vote from committer: {voter_name} "
                    f"<{voter_email}> (matched by {method}, confidence: {confidence:.1f}%)"
                )
                return _normalize_vote(vote)

            # If no +1/-1 found, check for 0 votes (less common but valid)
            for line in payload.split("\n"):
                if ">" in line[:10]:
                    continue

                vote_match = VOTE_PATTERN.search(line)
                if not vote_match:
                    continue

                vote = vote_match.group(1)
                if vote == "0":
                    print(
                        f"  Detected binding vote from committer: {voter_name} "
                        f"<{voter_email}> (matched by {method}, confidence: {confidence:.1f}%)"
                    )
                    return _normalize_vote(vote)

    return None


def _normalize_vote(vote: str) -> str:
    """Normalize vote string to standard format.

    Args:
        vote: Raw vote string ("+1", "1", "-1", "0")

    Returns:
        Normalized vote string ("+1", "-1", or "0")
    """
    if vote in ["+1", "1"]:
        return "+1"
    elif vote in ["-1"]:
        return "-1"
    elif vote in ["0"]:
        return "0"
    return vote


def process_mbox_archive(
    filepath: Path,
    pattern: re.Pattern,
    id_column_name: str,
    mention_columns: list[str],
    vote_keyword: str = "VOTE",
    discuss_keyword: str = "DISCUSS",
    committer_index: CommitterIndex | None = None,
) -> DataFrame:
    """Process the supplied mbox archive, harvest improvement proposal mentions.

    Args:
        filepath: Path to the mbox file
        pattern: Regex pattern to match improvement proposals (e.g., KIP-XXX)
        id_column_name: Name of the ID column (e.g., 'kip', 'flip')
        mention_columns: List of column names for the output DataFrame
        vote_keyword: Keyword in subject line indicating a vote thread
        discuss_keyword: Keyword in subject line indicating a discussion thread
        committer_index: Optional index of committers for automatic binding vote detection

    Returns:
        DataFrame containing each mention with metadata
    """

    mail_box: mbox = mbox(filepath)

    year_month: list[str] = filepath.name.split(".")[0].split("-")
    mbox_year: int = int(year_month[-2])
    mbox_month: int = int(year_month[-1])

    data: list[list[str | int | dt.datetime | None]] = []

    for key, msg in mail_box.items():
        subject_match: re.Match | None = re.search(pattern, msg["subject"])

        timestamp: dt.datetime | None = parse_message_timestamp(msg["Date"])
        if not timestamp:
            print(f"Could not parse timestamp for message {key}")
            continue

        is_vote: bool = False

        if subject_match:
            # Extract the ID from the first capturing group
            subject_id: int = int(subject_match.group(1))
            data.append(
                [
                    subject_id,
                    "subject",
                    key,
                    mbox_year,
                    mbox_month,
                    timestamp,
                    str(msg["from"]),
                    None,
                ]
            )

            if vote_keyword in msg["subject"]:
                is_vote = True

            elif discuss_keyword in msg["subject"]:
                data.append(
                    [
                        subject_id,
                        "discuss",
                        key,
                        mbox_year,
                        mbox_month,
                        timestamp,
                        str(msg["from"]),
                        None,
                    ]
                )

        try:
            valid_payloads: list[str] = extract_message_payload(msg)
        except ValueError:
            print(f"Error processing payload for message {key} in file {filepath}")
            continue

        if not valid_payloads:
            continue

        for payload in valid_payloads:
            if is_vote:
                vote_str: str | None = parse_for_vote(
                    payload, str(msg["from"]), committer_index
                )
                data.append(
                    [
                        subject_id,
                        "vote",
                        key,
                        mbox_year,
                        mbox_month,
                        timestamp,
                        str(msg["from"]),
                        vote_str,
                    ]
                )

            try:
                body_matches: list[str] = re.findall(pattern, payload)
            except TypeError:
                print(f"Unable to parse payload of type {type(payload)}")
                continue

            if body_matches:
                for body_id_str in body_matches:
                    body_id: int = int(body_id_str)
                    data.append(
                        [
                            body_id,
                            "body",
                            key,
                            mbox_year,
                            mbox_month,
                            timestamp,
                            str(msg["from"]),
                            None,
                        ]
                    )

    output = DataFrame(data, columns=mention_columns)
    output["timestamp"] = to_datetime(output["timestamp"], utc=True)

    return output.drop_duplicates()


def vote_converter(vote: str | None) -> str | None:
    """Converter function for the vote column of the mbox cache dataframe.

    Args:
        vote: Vote value as string or None

    Returns:
        Normalized vote string or None
    """

    if vote != "":
        vote_num: float = float(cast(str, vote))
        if vote_num >= 1.0:
            return "+1"

        if vote_num <= -1.0:
            return "-1"

        return "0"

    return None


def load_mbox_cache_file(cache_file: Path) -> DataFrame:
    """Loads the pre-processed mbox cache file and applies the relevant type converters.

    Args:
        cache_file: Path to the CSV cache file

    Returns:
        DataFrame with parsed data
    """

    file_data: DataFrame = read_csv(
        cache_file, converters={"vote": vote_converter}, parse_dates=["timestamp"]
    )

    return file_data


def process_all_mbox_in_directory(
    directory: Path,
    process_func,
    mention_columns: list[str],
    overwrite_cache: bool = False,
) -> DataFrame:
    """Process all mbox files in a directory and return combined DataFrame.

    Args:
        directory: Directory containing mbox files
        process_func: Function to process individual mbox files
        mention_columns: List of column names for the resulting DataFrame
        overwrite_cache: Whether to reprocess files (currently ignored)

    Returns:
        DataFrame containing all mentions from all mbox files
    """

    mbox_files: list[Path] = sorted(directory.glob("*.mbox"))

    print(f"Found {len(mbox_files)} mbox files to process")
    all_mentions: DataFrame = DataFrame(columns=mention_columns)

    for mbox_file in mbox_files:
        print(f"Processing {mbox_file.name}")
        try:
            file_data = process_func(mbox_file)
            all_mentions = concat((all_mentions, file_data), ignore_index=True)
        except Exception as ex:
            print(f"ERROR processing file {mbox_file.name}: {ex}")

    # Deduplicate before returning
    all_mentions = all_mentions.drop_duplicates()

    return all_mentions
