"""Apache KEYS file parsing and committer matching functionality.

This module provides functionality to download, parse, and cache Apache KEYS files
which contain PGP keys of project committers. It enables automatic detection of
binding votes from committers even when they don't explicitly mark their vote as
"(binding)".
"""

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from email.utils import parseaddr
from pathlib import Path

import requests
from rapidfuzz import fuzz


@dataclass
class CommitterInfo:
    """Information about a project committer extracted from KEYS file.

    Each committer has a unique name and one or more email addresses.
    Multiple PGP keys for the same person are consolidated into a single entry.
    """

    name: str
    emails: list[str]  # All email addresses for this committer
    raw_uid: str  # First UID line encountered, for debugging

    def __post_init__(self):
        """Normalize emails to lowercase for case-insensitive matching."""
        self.emails = [email.lower().strip() for email in self.emails]


@dataclass
class CommitterIndex:
    """Index of committers for a project with matching capabilities."""

    committers: list[CommitterInfo]
    last_updated: dt.datetime
    source_url: str
    _email_to_committer: dict[str, CommitterInfo] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self):
        """Build email lookup dictionary for O(1) exact matching."""
        self._email_to_committer = {}
        for committer in self.committers:
            for email in committer.emails:
                self._email_to_committer[email.lower().strip()] = committer

    def match_email_exact(self, email: str) -> CommitterInfo | None:
        """Match email address exactly (case-insensitive).

        Args:
            email: Email address to match

        Returns:
            CommitterInfo if exact match found, None otherwise
        """
        if not email:
            return None
        normalized_email = email.lower().strip()
        return self._email_to_committer.get(normalized_email)

    def match_name_fuzzy(
        self, name: str, threshold: float = 70.0
    ) -> tuple[CommitterInfo | None, float]:
        """Match name using fuzzy string matching.

        Args:
            name: Name to match
            threshold: Minimum similarity score (0-100) to consider a match

        Returns:
            Tuple of (CommitterInfo or None, confidence_score)
        """
        if not name:
            return None, 0.0

        normalized_name = name.lower().strip()
        best_match: CommitterInfo | None = None
        best_score = 0.0

        for committer in self.committers:
            # Try token sort ratio (handles word order variations)
            score = fuzz.token_sort_ratio(
                normalized_name, committer.name.lower().strip()
            )

            if score > best_score:
                best_score = score
                best_match = committer

        if best_score >= threshold:
            return best_match, best_score
        return None, best_score

    def is_committer(
        self, name: str, email: str, name_threshold: float = 70.0
    ) -> tuple[bool, float, str]:
        """Check if a person is a committer using email and/or name matching.

        Tries exact email match first (highest confidence), then falls back to
        fuzzy name matching if no email match found.

        Args:
            name: Person's name
            email: Person's email address
            name_threshold: Minimum similarity score for name matching

        Returns:
            Tuple of (is_match, confidence_score, match_method)
            - is_match: True if committer identified
            - confidence_score: 100 for email match, 0-100 for name match
            - match_method: "email" or "name" or "none"
        """
        # Try exact email match first (highest confidence)
        email_match = self.match_email_exact(email)
        if email_match:
            return True, 100.0, "email"

        # Fall back to fuzzy name matching
        name_match, score = self.match_name_fuzzy(name, name_threshold)
        if name_match:
            return True, score, "name"

        return False, 0.0, "none"


def parse_email_from_header(from_header: str) -> tuple[str, str]:
    """Parse name and email from email 'From' header.

    Handles common formats:
    - "John Doe" <john@example.com>
    - john@example.com (John Doe)
    - john@example.com

    Args:
        from_header: Raw 'From' header value

    Returns:
        Tuple of (name, email)
    """
    name, email = parseaddr(from_header)
    return name.strip(), email.strip()


def download_keys_file(url: str, timeout: int = 30) -> str:
    """Download KEYS file from Apache downloads.

    Args:
        url: URL to KEYS file (e.g., https://downloads.apache.org/kafka/KEYS)
        timeout: Request timeout in seconds

    Returns:
        Raw KEYS file content as string

    Raises:
        requests.RequestException: If download fails
    """
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_keys_file(keys_content: str) -> list[CommitterInfo]:
    """Parse Apache KEYS file to extract committer information.

    The KEYS file format has blocks like:

    Old format:
        pub   4096R/99369B56 2011-10-06
        uid   Neha Narkhede (Key for signing code) <nehanarkhede@apache.org>
        sub   4096R/A71D126A 2011-10-06

    New format:
        pub   rsa4096 2023-05-03 [SC]
              42EFF58EC9BDFD20FA7DF8B16CCECEFAC04AC304
        uid   [ultimate] Luke Chen (CODE SIGNING KEY) <showuon@apache.org>
        sub   rsa4096 2023-05-03 [E]

    Committers with multiple keys are consolidated into a single entry with
    all their email addresses.

    Args:
        keys_content: Raw KEYS file content

    Returns:
        List of CommitterInfo objects (one per unique committer name)
    """
    # Dictionary to aggregate committers by name: {name: {emails: set, raw_uid: str}}
    committer_data: dict[str, dict[str, any]] = {}

    # Pattern to match uid lines with name and email
    # Format: uid   [optional trust] Name (optional comment) <email@domain.com>
    uid_pattern = re.compile(r"^uid\s+(.+?)\s*<([^>]+)>", re.MULTILINE)

    # Split into key blocks (each starting with "pub")
    blocks = re.split(r"(?=^pub\s)", keys_content, flags=re.MULTILINE)

    for block in blocks:
        if not block.strip():
            continue

        # Extract all uid lines for this key (may have multiple)
        uid_matches = uid_pattern.findall(block)
        if not uid_matches:
            continue

        # Use the first uid as primary
        primary_name_raw, primary_email = uid_matches[0]

        # Clean up name:
        # 1. Remove [ultimate], [full], etc. trust indicators in square brackets
        # 2. Remove (comments) in parentheses
        # 3. Strip whitespace
        name = re.sub(r"\[[^\]]*\]", "", primary_name_raw)  # Remove [...]
        name = re.sub(r"\([^)]*\)", "", name)  # Remove (...)
        name = name.strip()

        if not name:
            continue

        # Collect all emails for this key
        emails = {email.strip() for _, email in uid_matches}

        # Aggregate by name - if we've seen this name before, merge emails
        if name in committer_data:
            # Merge emails (union)
            committer_data[name]["emails"].update(emails)
            # Keep the first raw_uid we encountered
        else:
            # First time seeing this committer - store their data
            raw_uid_clean = re.sub(r"\[[^\]]*\]", "", primary_name_raw).strip()
            raw_uid = f"{raw_uid_clean} <{primary_email.strip()}>"

            committer_data[name] = {
                "emails": emails,
                "raw_uid": raw_uid,
            }

    # Convert aggregated data to CommitterInfo objects
    committers = [
        CommitterInfo(
            name=name,
            emails=sorted(data["emails"]),  # Sort for consistent output
            raw_uid=data["raw_uid"],
        )
        for name, data in sorted(committer_data.items())  # Sort by name
    ]

    return committers


def load_committer_index(cache_path: Path) -> CommitterIndex | None:
    """Load cached committer index from disk.

    Args:
        cache_path: Path to JSON cache file

    Returns:
        CommitterIndex if cache exists and is valid, None otherwise
    """
    if not cache_path.exists():
        return None

    try:
        with open(cache_path) as f:
            data = json.load(f)

        committers = [
            CommitterInfo(
                name=c["name"],
                emails=c["emails"],
                raw_uid=c["raw_uid"],
            )
            for c in data["committers"]
        ]

        return CommitterIndex(
            committers=committers,
            last_updated=dt.datetime.fromisoformat(data["last_updated"]),
            source_url=data["source_url"],
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Error loading cache from {cache_path}: {e}")
        return None


def save_committer_index(index: CommitterIndex, cache_path: Path) -> None:
    """Save committer index to disk cache.

    Args:
        index: CommitterIndex to save
        cache_path: Path to JSON cache file
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "last_updated": index.last_updated.isoformat(),
        "source_url": index.source_url,
        "committers": [
            {
                "name": c.name,
                "emails": c.emails,
                "raw_uid": c.raw_uid,
            }
            for c in index.committers
        ],
    }

    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)


def get_committer_index(
    keys_url: str,
    cache_path: Path,
    force_refresh: bool = False,
    max_age_days: int = 7,
) -> CommitterIndex:
    """Get committer index, using cache if fresh or downloading if stale.

    Args:
        keys_url: URL to KEYS file
        cache_path: Path to cache file
        force_refresh: Force download even if cache is fresh
        max_age_days: Maximum cache age in days before refresh

    Returns:
        CommitterIndex with up-to-date committer information

    Raises:
        requests.RequestException: If download fails and no cache available
    """
    # Check if cache exists and is fresh
    if not force_refresh and cache_path.exists():
        index = load_committer_index(cache_path)
        if index:
            age = dt.datetime.now(dt.UTC) - index.last_updated.replace(tzinfo=dt.UTC)
            if age.days < max_age_days:
                print(
                    f"Using cached committer data from {cache_path} "
                    f"(age: {age.days} days)"
                )
                return index
            print(f"Cache is stale (age: {age.days} days), refreshing...")

    # Download and parse KEYS file
    print(f"Downloading KEYS file from {keys_url}")
    keys_content = download_keys_file(keys_url)

    print("Parsing KEYS file...")
    committers = parse_keys_file(keys_content)

    print(f"Found {len(committers)} committers")

    # Create index and save to cache
    index = CommitterIndex(
        committers=committers,
        last_updated=dt.datetime.now(dt.UTC),
        source_url=keys_url,
    )

    save_committer_index(index, cache_path)
    print(f"Saved committer index to {cache_path}")

    return index
