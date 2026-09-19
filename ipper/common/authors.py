"""Parsing and deduplication of improvement proposal authors.

Proposals (KIPs/FLIPs) can be authored by several people. The wiki page
creator is not always (the only) author, so we parse explicit author
declarations from the page body and merge them with the page creator.
"""

import logging
import re

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Matches "Author", "Authors", "Co-Author", "Co Author", "Co-authors", etc.
# \b after "author(s)" prevents false positives on prose like
# "Authorization note: ..." which starts with the letters "author".
AUTHOR_LABEL_PATTERN: re.Pattern = re.compile(
    r"^\s*(?:co[\s-]+)?authors?\b\s*[:：]?\s*", re.IGNORECASE
)

# Matches only "Co-Author(s)" / "Co Author(s)" labels. Checked before
# AUTHOR_LABEL_PATTERN (which also matches co-author lines) so callers can
# distinguish the two.
CO_AUTHOR_LABEL_PATTERN: re.Pattern = re.compile(
    r"^\s*co[\s-]+authors?\b\s*[:：]?\s*", re.IGNORECASE
)

# Text that ends an author list when the paragraph contains other fields
# (e.g. KIP-1320: "Authors: Eric Chang<br/>Discussion thread: ...")
STOP_PHRASES: list[str] = ["discussion thread", "vote thread", "jira", "email"]

# Delimiters between names in a list. "and" only counts as a delimiter when
# surrounded by whitespace, so names containing "and" as a substring (e.g.
# "Anderson") are safe.
NAME_DELIMITER_PATTERN: re.Pattern = re.compile(r"\s*(?:,|;|\band\b)\s*")

# Email addresses, with optional surrounding angle brackets and whitespace
# (e.g. "Vince Rose vrose@confluent.io Farid Zakaria fzakaria@confluent.io"
# on KIP-1115, or the common "Jane Doe <jane@example.com>" convention).
# Replaced with a delimiter before splitting so that "Name email Name email"
# runs (which have no other delimiter) split into individual names.
EMAIL_PATTERN: re.Pattern = re.compile(
    r"\s*[(\[]*[<]?[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}[>)\]]*\s*"
)

# Zero-width characters Confluence sometimes emits inside styled spans
ZERO_WIDTH_CHARS: str = "\u200b\u200c\u200d\ufeff"

# Trailing punctuation to trim from parsed names
TRAILING_PUNCTUATION: str = ",;.("

FUZZY_DEDUPE_THRESHOLD: float = 85.0


def _strip_label(text: str) -> str:
    """Removes a leading author label ("Authors:", "Co-Author:", etc.) if present."""
    return AUTHOR_LABEL_PATTERN.sub("", text, count=1)


def _cut_at_stop_phrase(text: str) -> str:
    """Cuts the text at the first (case-insensitive) stop phrase, if any.

    Stop phrases only appear after the name list when the paragraph is
    shared with other fields, so searching from the left is safe.
    """
    lower_text: str = text.lower()
    cut_index: int = len(text)
    for phrase in STOP_PHRASES:
        index: int = lower_text.find(phrase)
        if index != -1 and index < cut_index:
            cut_index = index
    return text[:cut_index]


def _clean_name(name: str) -> str:
    """Cleans a single parsed name: removes zero-width characters, trims
    whitespace and strips trailing punctuation."""
    name = name.translate(str.maketrans("", "", ZERO_WIDTH_CHARS))
    return name.strip().rstrip(TRAILING_PUNCTUATION).strip()


def parse_authors_from_text(text: str) -> list[str]:
    """Parse individual author names from the text following an author label.

    Handles comma / semicolon / " and " separated lists, trims whitespace,
    removes empty entries, and cuts the list at known stop phrases
    ("discussion thread", "vote thread", "jira") so that paragraphs which
    share fields with the author line (KIP-1320 style) parse correctly.

    If the text does not start with an author label (e.g. FLIP summary
    table cells, which hold bare name lists), the whole text is treated
    as the author list.
    """
    remainder: str = _cut_at_stop_phrase(_strip_label(text))

    # Email addresses act as delimiters between "Name email" pairs (KIP-1115
    # style) and are dropped; a bare email is not a usable display name.
    remainder = EMAIL_PATTERN.sub(", ", remainder)

    names: list[str] = [
        cleaned
        for cleaned in (
            _clean_name(part) for part in NAME_DELIMITER_PATTERN.split(remainder)
        )
        if cleaned
    ]

    return names


def is_author_line(text: str) -> bool:
    """True if the paragraph/cell text starts with an author label
    ("Authors:", "Co-Author:", "Author:", etc.)."""
    return AUTHOR_LABEL_PATTERN.match(text) is not None


def is_co_author_line(text: str) -> bool:
    """True if the text starts with a co-author label
    ("Co-Author:", "Co Author:", "Co-Authors:", etc.)."""
    return CO_AUTHOR_LABEL_PATTERN.match(text) is not None


def dedupe_authors(
    names: list[str], threshold: float = FUZZY_DEDUPE_THRESHOLD
) -> list[str]:
    """Deduplicate author names, preserving first-occurrence order.

    1. Normalise (strip + casefold) and drop exact duplicates.
    2. Fuzzy-dedupe each remaining name against already-kept names using
       rapidfuzz.fuzz.token_sort_ratio; names scoring >= threshold are
       considered duplicates and dropped. Every fuzzy merge is logged
       (kept name, dropped name, score) for auditability.
    """
    kept: list[str] = []
    seen: set[str] = set()

    for name in names:
        cleaned: str = name.strip()
        if not cleaned:
            continue

        normalised: str = cleaned.casefold()
        if normalised in seen:
            continue

        duplicate_of: str | None = None
        for kept_name in kept:
            score: float = fuzz.token_sort_ratio(normalised, kept_name.casefold())
            if score >= threshold:
                logger.info(
                    "Dropping duplicate author '%s' (matches '%s', score %.1f)",
                    cleaned,
                    kept_name,
                    score,
                )
                duplicate_of = kept_name
                break

        if duplicate_of is not None:
            continue

        seen.add(normalised)
        kept.append(cleaned)

    return kept
