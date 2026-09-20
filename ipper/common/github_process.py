"""Data processing for GitHub-based proposal tracking.

Implements tarball parsing (merged proposals), PR classification
(proposal / amendment / plumbing), proposal record building and
incremental cache updates for projects that manage proposals in GitHub
repositories (Strimzi SIPs, StreamsHub SHIPs, Kroxylicious KDPs).

See docs/plans/github-proposal-tracking.md for the design.
"""

import datetime as dt
import io
import json
import logging
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pandas import Timestamp

from ipper.common.constants import IPState
from ipper.common.github import GithubClient
from ipper.common.github_config import GithubProjectConfig
from ipper.common.utils import calculate_activity_status, calculate_age

logger = logging.getLogger(__name__)

CACHE_DIR = "cache"

# Bot accounts filtered from review activity. GitHub App bots use a
# '[bot]' login suffix (e.g. 'dependabot[bot]'); KNOWN_BOTS covers
# accounts that don't follow the convention. Extend as new bots appear.
KNOWN_BOTS = frozenset(
    {
        "github-actions",
        "coderabbitai",
        "copilot-pull-request-copilot",
        "copilot-sweeper",
        "k8s-ci-robot",
        "renovate",
        "renovate-preview",
        "dependabot-preview",
    }
)

# PR file statuses that count as modifying an existing file
MODIFY_STATUSES = frozenset({"modified", "changed", "renamed"})

SLUG_SPLITTER: re.Pattern = re.compile(r"^\d{3}-")


@dataclass
class MergedProposal:
    """A merged proposal file on the repository's main branch."""

    number: int
    title: str
    path: str
    blob_url: str


def is_proposal_file(config: GithubProjectConfig, path: str) -> bool:
    """True when the path is a proposal file (right directory, right
    pattern, not an excluded file)."""

    if config.proposal_dir_prefix:
        prefix = config.proposal_dir_prefix
        if not path.startswith(prefix):
            return False
        relative = path[len(prefix) :]
    else:
        relative = path

    if "/" in relative:
        return False

    if not config.proposal_pattern.fullmatch(relative):
        return False

    return relative not in config.excluded_files


def extract_number(config: GithubProjectConfig, filename: str) -> int | None:
    """Extract the proposal number from a proposal filename."""

    match = config.proposal_pattern.fullmatch(filename.rsplit("/", 1)[-1])
    if match is None:
        return None
    return int(match.group(1))


def extract_title(number: int, content: str) -> str:
    """Extract the proposal title from the first '# ' heading.

    Strips a leading 'NNN - ' style prefix (the Kroxylicious convention is
    '# 124 - Title')."""

    for line in content.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            heading_match = re.match(r"^(\d+)\s*[-\u2013\u2014:.]*\s*", title)
            if heading_match and int(heading_match.group(1)) == number:
                stripped = title[heading_match.span()[1] :].strip()
                if stripped:
                    return stripped
            return title
    return ""


def parse_tarball(
    tar_bytes: bytes, config: GithubProjectConfig
) -> dict[str, MergedProposal]:
    """Parse the merged proposal files out of a repository tarball.

    Returns a dict keyed by the file path relative to the repository root.
    """

    merged: dict[str, MergedProposal] = {}

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue

            # GitHub tarballs prefix every member with "<repo>-<sha>/"
            _, separator, relative_path = member.name.partition("/")
            if not separator:
                continue

            if not is_proposal_file(config, relative_path):
                continue

            number = extract_number(config, relative_path)
            if number is None:
                continue

            file_handler = tar.extractfile(member)
            content = (
                file_handler.read().decode("utf-8", errors="replace")
                if file_handler
                else ""
            )

            merged[relative_path] = MergedProposal(
                number=number,
                title=extract_title(number, content),
                path=relative_path,
                blob_url=(
                    f"https://github.com/{config.owner}/{config.repo}/"
                    f"blob/main/{relative_path}"
                ),
            )

    logger.info(
        "Parsed %d merged %s proposal files from tarball", len(merged), config.prefix
    )
    return merged


def normalize_reviews(reviews: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Normalize raw GitHub review payloads to {name, state, timestamp}."""

    normalized: list[dict[str, str]] = []
    for review in reviews:
        user = review.get("user") or {}
        if not user:
            continue
        normalized.append(
            {
                "name": user.get("login", ""),
                "state": review.get("state", ""),
                "timestamp": review.get("submitted_at") or "",
            }
        )
    return normalized


def extract_comments(comments: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Normalize raw GitHub issue-comment payloads to {name, timestamp}."""

    normalized: list[dict[str, str]] = []
    for comment in comments:
        user = comment.get("user") or {}
        if not user:
            continue
        normalized.append(
            {
                "name": user.get("login", ""),
                "timestamp": comment.get("created_at") or "",
            }
        )
    return normalized


def is_bot_login(login: str) -> bool:
    """True when a GitHub login belongs to a bot account."""

    return login.endswith("[bot]") or login in KNOWN_BOTS


def derive_review_activity(
    reviews: list[dict[str, Any]], comments: list[dict[str, Any]], author: str = ""
) -> dict[str, list[dict[str, str]]]:
    """Derive unique-user review activity from raw GitHub payloads.

    See derive_review_activity_from_snapshots for the column semantics.
    """

    return derive_review_activity_from_snapshots(
        normalize_reviews(reviews), extract_comments(comments), author
    )


def derive_pull_state(pull: dict[str, Any]) -> str:
    """Derive 'open' | 'merged' | 'closed' from a pull request payload."""

    if pull.get("merged_at"):
        return "merged"
    if pull.get("state") == "open":
        return "open"
    return "closed"


def last_activity_of(
    pull: dict[str, Any], reviews: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> str | None:
    """Latest activity timestamp of an open proposal PR: max of the PR
    updated_at, review submitted_at and comment created_at."""

    candidates = [pull.get("updated_at") or ""]
    candidates.extend(
        review.get("submitted_at") or "" for review in reviews if review.get("user")
    )
    candidates.extend(
        comment.get("created_at") or "" for comment in comments if comment.get("user")
    )
    return max(candidates) or None


def activity_status_name(last_activity: str | None) -> str | None:
    """Map the last activity timestamp to the shared colour thresholds."""

    if not last_activity:
        return None
    return calculate_activity_status(Timestamp(last_activity)).text


def activity_age(last_activity: str | None) -> str | None:
    """Human-readable age of the last activity, for tooltips."""

    if not last_activity:
        return None
    return calculate_age(last_activity[:19], "%Y-%m-%dT%H:%M:%S")


def classify_pull(
    config: GithubProjectConfig,
    files: list[dict[str, Any]],
    merged_paths: set[str],
) -> dict[str, Any]:
    """Classify a pull request from its file list.

    - proposal: adds >= 1 file matching the proposal pattern (added files
      only, so the Kroxylicious '000-' placeholder and same-PR rename both
      count)
    - amendment: no added proposal files, but modifies/renames a file that
      is a currently-merged proposal file
    - plumbing: neither

    Returns {"classification", "proposal_files", "amendment_files"}.
    """

    proposal_files = [
        file_entry["filename"]
        for file_entry in files
        if file_entry.get("status") == "added"
        and is_proposal_file(config, file_entry["filename"])
    ]
    if proposal_files:
        return {
            "classification": "proposal",
            "proposal_files": proposal_files,
            "amendment_files": [],
        }

    amendment_files = [
        file_entry["filename"]
        for file_entry in files
        if file_entry.get("status") in MODIFY_STATUSES
        and file_entry["filename"] in merged_paths
    ]
    if amendment_files:
        return {
            "classification": "amendment",
            "proposal_files": [],
            "amendment_files": amendment_files,
        }

    return {"classification": "plumbing", "proposal_files": [], "amendment_files": []}


def _base_record(config: GithubProjectConfig, pull: dict[str, Any]) -> dict[str, Any]:
    """Common fields shared by every proposal record."""

    author = (pull.get("user") or {}).get("login", "")
    return {
        "pr_number": pull["number"],
        "pr_url": pull.get("html_url", ""),
        "title": pull.get("title", ""),
        "created_by": author,
        "authors": [author] if author else [],
        "created_on": (pull.get("created_at") or "")[:10],
        "state": "",
        "web_url": "",
        "reviews": {"accepted": [], "commented": [], "changes_requested": []},
        "last_activity": None,
        "activity_status": None,
        "last_activity_age": None,
        "amendments": [],
        "frozen": False,
    }


def build_open_record(
    config: GithubProjectConfig,
    pull: dict[str, Any],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a proposal record for an open (under discussion) proposal PR."""

    record = _base_record(config, pull)
    author = (pull.get("user") or {}).get("login", "")
    record["state"] = IPState.UNDER_DISCUSSION
    record["id"] = pull["number"] if config.numbering == "pr_number" else None
    record["web_url"] = pull.get("html_url", "")
    record["reviews"] = derive_review_activity(reviews, comments, author)
    record["last_activity"] = last_activity_of(pull, reviews, comments)
    record["activity_status"] = activity_status_name(record["last_activity"])
    record["last_activity_age"] = activity_age(record["last_activity"])
    return record


def build_rejected_record(
    config: GithubProjectConfig,
    pull: dict[str, Any],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a proposal record for a closed-unmerged (rejected) proposal PR.

    Review activity is frozen at close time.
    """

    record = _base_record(config, pull)
    author = (pull.get("user") or {}).get("login", "")
    record["state"] = IPState.NOT_ACCEPTED
    record["id"] = pull["number"] if config.numbering == "pr_number" else None
    record["web_url"] = pull.get("html_url", "")
    record["reviews"] = derive_review_activity(reviews, comments, author)
    record["last_activity"] = pull.get("closed_at") or pull.get("updated_at")
    record["activity_status"] = None
    record["frozen"] = True
    return record


def sync_open_record(
    record: dict[str, Any],
    pull: dict[str, Any],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> None:
    """Refresh an open proposal record's reviews/activity in place."""

    record["state"] = IPState.UNDER_DISCUSSION
    record["title"] = pull.get("title", record.get("title", ""))
    record["reviews"] = derive_review_activity(
        reviews, comments, (pull.get("user") or {}).get("login", "")
    )
    record["last_activity"] = last_activity_of(pull, reviews, comments)
    record["activity_status"] = activity_status_name(record["last_activity"])
    record["last_activity_age"] = activity_age(record["last_activity"])


def _new_index_entry(
    pull: dict[str, Any],
    files: list[dict[str, Any]],
    classification: dict[str, Any],
    state: str,
) -> dict[str, Any]:
    return {
        "state": state,
        "classification": classification["classification"],
        "proposal_key": "",
        "files": files,
        "updated_at": pull.get("updated_at") or "",
        "head_sha": (pull.get("head") or {}).get("sha", ""),
        "frozen": False,
        "reviews_snapshot": [],
        "comments_snapshot": [],
    }


def _fetch_reviews_and_comments(
    client: GithubClient, pr_number: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviews = list(client.get_pull_reviews(pr_number))
    comments = list(client.get_issue_comments(pr_number))
    return reviews, comments


def _store_snapshots(
    entry: dict[str, Any], reviews: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> None:
    entry["reviews_snapshot"] = normalize_reviews(reviews)
    entry["comments_snapshot"] = extract_comments(comments)
    # Marks that snapshots were fetched at least once, so snapshot-less
    # entries can be told apart from zero-activity ones (used by the
    # KDP backfill in migrate_cache).
    entry["snapshots_fetched"] = True


def _promote_merged_record(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    merged_file: MergedProposal,
    pr_number: int,
    pulls_seen: dict[str, dict[str, Any]],
    client: GithubClient,
) -> None:
    """Create or move the proposal record for a merged proposal file."""

    key = str(merged_file.number)
    entry = cache["pr_index"].get(str(pr_number))
    if entry is None:
        logger.warning(
            "%s-%d: no PR index entry for merged PR #%d, skipping",
            config.prefix,
            merged_file.number,
            pr_number,
        )
        return

    # Already reconciled on a previous run: unchanged PRs cost nothing.
    if entry.get("proposal_key") == key and cache["proposals"].get(key, {}).get(
        "frozen"
    ):
        return

    pull = pulls_seen.get(str(pr_number))
    if pull is None:
        pull = client.get_pull(pr_number)
        pulls_seen[str(pr_number)] = pull

    previous_key = entry.get("proposal_key") or ""
    record = dict(
        cache["proposals"].get(previous_key)
        or cache["proposals"].get(key)
        or _base_record(config, pull)
    )

    author = (pull.get("user") or {}).get("login", "")
    reviews = derive_review_activity_from_snapshots(
        entry.get("reviews_snapshot", []),
        entry.get("comments_snapshot", []),
        author,
    )
    merged_on = pull.get("merged_at") or pull.get("updated_at") or ""
    record.update(
        {
            "key": key,
            "id": merged_file.number,
            "pr_number": pr_number,
            "title": merged_file.title or pull.get("title", ""),
            "state": IPState.ACCEPTED,
            "created_by": author,
            "authors": [author] if author else [],
            "created_on": (pull.get("created_at") or "")[:10],
            "merged_on": merged_on,
            "last_modified_on": merged_on,
            "web_url": merged_file.blob_url,
            "pr_url": pull.get("html_url", ""),
            "file_path": merged_file.path,
            "reviews": reviews,
            "last_activity": None,
            "activity_status": None,
            "last_activity_age": None,
            "frozen": True,
        }
    )

    if previous_key and previous_key != key and previous_key in cache["proposals"]:
        del cache["proposals"][previous_key]
    cache["proposals"][key] = record
    entry["proposal_key"] = key
    entry["classification"] = "proposal"
    entry["frozen"] = True


def derive_review_activity_from_snapshots(
    reviews_snapshot: list[dict[str, str]],
    comments_snapshot: list[dict[str, str]],
    author: str = "",
) -> dict[str, list[dict[str, str]]]:
    """Derive unique-user review activity from stored PR snapshots.

    Columns (each a list of unique users with their latest qualifying
    timestamp):
    - accepted: users with at least one APPROVED review. Terminal: an
      approver never appears in the other columns.
    - changes_requested: users with at least one CHANGES_REQUESTED
      review and no approval.
    - commented: everyone else who participated via issue comments or
      COMMENTED reviews.

    PENDING and DISMISSED reviews are ignored (a dismissed approval no
    longer counts). Bots and the PR author are excluded.
    """

    latest: dict[str, dict[str, str | None]] = {}

    def note(name: str, column: str, timestamp: str) -> None:
        entry = latest.setdefault(
            name, {"accepted": None, "changes_requested": None, "commented": None}
        )
        current = entry[column]
        if current is None or timestamp > current:
            entry[column] = timestamp

    for review in reviews_snapshot:
        name = review.get("name", "")
        if not name or name == author or is_bot_login(name):
            continue
        state = review.get("state", "")
        if state == "APPROVED":
            note(name, "accepted", review.get("timestamp", ""))
        elif state == "CHANGES_REQUESTED":
            note(name, "changes_requested", review.get("timestamp", ""))
        elif state == "COMMENTED":
            note(name, "commented", review.get("timestamp", ""))

    for comment in comments_snapshot:
        name = comment.get("name", "")
        if not name or name == author or is_bot_login(name):
            continue
        note(name, "commented", comment.get("timestamp", ""))

    activity: dict[str, list[dict[str, str]]] = {
        "accepted": [],
        "commented": [],
        "changes_requested": [],
    }
    for name, stamps in latest.items():
        if stamps["accepted"] is not None:
            activity["accepted"].append({"name": name, "timestamp": stamps["accepted"]})
        elif stamps["changes_requested"] is not None:
            activity["changes_requested"].append(
                {"name": name, "timestamp": stamps["changes_requested"]}
            )
        elif stamps["commented"] is not None:
            activity["commented"].append(
                {"name": name, "timestamp": stamps["commented"]}
            )

    for users in activity.values():
        users.sort(key=lambda user: (user["timestamp"], user["name"]), reverse=True)
    return activity


def _find_origin_pr(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    merged_files: dict[str, MergedProposal],
    path: str,
    file_to_pr: dict[str, int],
) -> int | None:
    """Map a merged proposal file back to its originating PR.

    Strategies, in order:
    1. exact filename match among files added by merged PRs
    2. slug match (same basename minus the NNN- prefix), for files that
       were renumbered when merged (e.g. a 000- placeholder)
    3. Kroxylicious: proposal number == originating PR number
    """

    exact = file_to_pr.get(path)
    if exact is not None:
        return exact

    slug = SLUG_SPLITTER.sub("", path.rsplit("/", 1)[-1])
    for pr_number in sorted(int(k) for k in cache["pr_index"]):
        entry = cache["pr_index"][str(pr_number)]
        if entry["state"] != "merged" or entry["classification"] != "proposal":
            continue
        for file_entry in entry["files"]:
            if (
                file_entry.get("status") == "added"
                and is_proposal_file(config, file_entry["filename"])
                and SLUG_SPLITTER.sub("", file_entry["filename"].rsplit("/", 1)[-1])
                == slug
            ):
                return pr_number

    if config.numbering == "pr_number":
        return merged_files[path].number

    return None


def _reconcile_merged_proposals(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    merged_files: dict[str, MergedProposal],
    pulls_seen: dict[str, dict[str, Any]],
    client: GithubClient,
) -> None:
    """Reconcile the tarball's merged proposal files with the PR index.

    Ground truth for merged proposals is the tarball; each merged file is
    mapped back to its originating PR, and non-merged records are moved to
    their numbered key with a frozen approval-history vote record.
    """

    # Map added proposal filenames -> originating PR (lowest PR number wins,
    # so an amendment PR re-adding a renamed file cannot steal the mapping).
    file_to_pr: dict[str, int] = {}
    for pr_str, entry in cache["pr_index"].items():
        if entry["state"] != "merged" or entry["classification"] != "proposal":
            continue
        for file_entry in entry["files"]:
            if file_entry.get("status") == "added" and is_proposal_file(
                config, file_entry["filename"]
            ):
                file_to_pr.setdefault(file_entry["filename"], int(pr_str))

    for path, merged_file in merged_files.items():
        origin_pr = _find_origin_pr(config, cache, merged_files, path, file_to_pr)
        if origin_pr is None:
            logger.warning(
                "%s: merged proposal file %s could not be mapped to a PR",
                config.prefix,
                path,
            )
            continue
        _promote_merged_record(
            config, cache, merged_file, origin_pr, pulls_seen, client
        )


def _attach_amendments(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    merged_files: dict[str, MergedProposal],
    pulls_seen: dict[str, dict[str, Any]],
) -> None:
    """Attach closed/merged amendment PRs to their proposal records."""

    for pr_str, entry in cache["pr_index"].items():
        if entry.get("classification") != "amendment":
            continue
        if entry["state"] not in ("merged", "closed"):
            continue

        pull = pulls_seen.get(pr_str)
        if pull is None:
            continue

        date = (
            pull.get("merged_at")
            or pull.get("closed_at")
            or pull.get("updated_at")
            or ""
        )
        stamp = date

        for file_entry in entry["files"]:
            if (
                file_entry.get("status") in MODIFY_STATUSES
                and file_entry["filename"] in merged_files
            ):
                merged_file = merged_files[file_entry["filename"]]
                record = cache["proposals"].get(str(merged_file.number))
                if record is None:
                    continue
                amendments = record.setdefault("amendments", [])
                if not any(a["pr_number"] == int(pr_str) for a in amendments):
                    amendments.append(
                        {
                            "pr_number": int(pr_str),
                            "url": pull.get("html_url", ""),
                            "date": date[:10],
                        }
                    )
                if stamp > (record.get("last_modified_on") or ""):
                    record["last_modified_on"] = stamp


def _process_new_pull(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    pull: dict[str, Any],
    merged_files: dict[str, MergedProposal],
    client: GithubClient,
) -> None:
    """Process a pull request not present in the PR index yet."""

    pr_str = str(pull["number"])
    state = derive_pull_state(pull)
    merged_paths = set(merged_files)
    merged_numbers = {merged.number for merged in merged_files.values()}

    if config.numbering == "pr_number" and state == "merged":
        # Kroxylicious shortcut: a merged KDP PR needs no files call - it
        # is a proposal iff proposals/<PR#>-*.md exists on main (the
        # proposal number equals the PR number). Snapshots are captured
        # now so the frozen approval history is available to
        # reconciliation.
        files: list[dict[str, Any]] = []
        is_proposal_pr = pull["number"] in merged_numbers
        classification: dict[str, Any] = {
            "classification": "proposal" if is_proposal_pr else "plumbing",
            "proposal_files": [],
            "amendment_files": [],
        }
        entry = _new_index_entry(pull, files, classification, state)
        cache["pr_index"][pr_str] = entry
        if is_proposal_pr:
            reviews, comments = _fetch_reviews_and_comments(client, pull["number"])
            _store_snapshots(entry, reviews, comments)
            entry["frozen"] = True
        return

    files = list(client.get_pull_files(pull["number"]))
    classification = classify_pull(config, files, merged_paths)

    entry = _new_index_entry(pull, files, classification, state)
    cache["pr_index"][pr_str] = entry

    is_proposal_pr = classification["classification"] == "proposal"

    if state in ("open", "closed") and is_proposal_pr:
        reviews, comments = _fetch_reviews_and_comments(client, pull["number"])
        _store_snapshots(entry, reviews, comments)
        key = f"pr-{pr_str}"
        if state == "open":
            cache["proposals"][key] = build_open_record(config, pull, reviews, comments)
        else:
            cache["proposals"][key] = build_rejected_record(
                config, pull, reviews, comments
            )
        entry["proposal_key"] = key
        if state == "closed":
            entry["frozen"] = True
    elif state == "merged" and is_proposal_pr:
        # Sequential repos: capture the frozen approval history now; the
        # numbered record is created by reconciliation.
        reviews, comments = _fetch_reviews_and_comments(client, pull["number"])
        _store_snapshots(entry, reviews, comments)
        entry["frozen"] = True


def _process_changed_pull(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    pull: dict[str, Any],
    merged_files: dict[str, MergedProposal],
    client: GithubClient,
) -> None:
    """Apply the incremental gating rules to one changed pull request."""

    pr_str = str(pull["number"])
    state = derive_pull_state(pull)
    entry = cache["pr_index"].get(pr_str)

    if entry is None:
        _process_new_pull(config, cache, pull, merged_files, client)
        return

    merged_paths = set(merged_files)

    previous_state = entry["state"]
    head_sha = (pull.get("head") or {}).get("sha", "")
    head_changed = entry.get("head_sha") != head_sha
    state_changed = previous_state != state

    if (
        not state_changed
        and not head_changed
        and pull["updated_at"] <= entry["updated_at"]
    ):
        return  # unchanged; nothing to do

    if previous_state == "open" and state in ("closed", "merged"):
        # Transition to close/merge: capture the final review/comment
        # snapshot and freeze the vote record.
        reviews, comments = _fetch_reviews_and_comments(client, pull["number"])
        _store_snapshots(entry, reviews, comments)
        entry["frozen"] = True
        record = cache["proposals"].get(entry.get("proposal_key") or "")
        if record is not None:
            record["frozen"] = True
            record["activity_status"] = None
            record["last_activity_age"] = None
            record["reviews"] = derive_review_activity(
                reviews, comments, (pull.get("user") or {}).get("login", "")
            )
            if state == "closed":
                record["state"] = IPState.NOT_ACCEPTED
                record["last_activity"] = pull.get("closed_at") or pull["updated_at"]

    elif state == "open" and previous_state == "closed":
        # Reopened: unfreeze and resume activity/vote tracking.
        reviews, comments = _fetch_reviews_and_comments(client, pull["number"])
        _store_snapshots(entry, reviews, comments)
        entry["frozen"] = False
        if head_changed:
            files = list(client.get_pull_files(pull["number"]))
            classification = classify_pull(config, files, merged_paths)
            entry["files"] = files
            entry["classification"] = classification["classification"]
        record = cache["proposals"].get(entry.get("proposal_key") or "")
        if record is not None:
            record["frozen"] = False
            sync_open_record(record, pull, reviews, comments)

    elif state == "open":
        # Still open but bumped: refresh reviews/activity. A head.sha change
        # also triggers a files re-fetch and reclassification.
        reviews, comments = _fetch_reviews_and_comments(client, pull["number"])
        _store_snapshots(entry, reviews, comments)
        if head_changed:
            files = list(client.get_pull_files(pull["number"]))
            classification = classify_pull(config, files, merged_paths)
            entry["files"] = files
            entry["classification"] = classification["classification"]
        record = cache["proposals"].get(entry.get("proposal_key") or "")
        if record is not None:
            sync_open_record(record, pull, reviews, comments)
        elif classification_of(entry) == "proposal":
            # e.g. a plumbing PR became a proposal PR after a push
            key = f"pr-{pr_str}"
            cache["proposals"][key] = build_open_record(config, pull, reviews, comments)
            entry["proposal_key"] = key

    # else: closed/merged with only an updated_at bump - metadata only,
    # covered by the entry field updates below.

    entry["state"] = state
    entry["updated_at"] = pull["updated_at"]
    entry["head_sha"] = head_sha


def classification_of(entry: dict[str, Any]) -> str:
    return entry.get("classification", "plumbing")


def update_cache(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    client: GithubClient,
) -> dict[str, Any]:
    """Incrementally update the cache for one GitHub project.

    1. Re-download the tarball and reconcile merged proposals.
    2. Walk the PR list (sorted by updated desc) until every remaining
       entry is at or below the watermark with unchanged state.
    3. Gate per-PR work by what changed.
    """

    logger.info("Downloading %s/%s tarball", config.owner, config.repo)
    merged_files = parse_tarball(client.download_tarball(), config)

    watermark = cache.get("watermark") or ""
    changed: list[dict[str, Any]] = []
    pulls_seen: dict[str, dict[str, Any]] = {}

    for pull in client.list_pulls(state="all"):
        pr_str = str(pull["number"])
        state = derive_pull_state(pull)
        entry = cache["pr_index"].get(pr_str)
        if (
            entry is not None
            and pull["updated_at"] <= watermark
            and entry["state"] == state
            and entry.get("head_sha") == (pull.get("head") or {}).get("sha", "")
        ):
            # Everything after this point is at/below the watermark and
            # unchanged: stop walking.
            break
        changed.append(pull)
        pulls_seen[pr_str] = pull
        if pull["updated_at"] > watermark:
            watermark = pull["updated_at"]

    logger.info(
        "%s: %d changed pull request(s) since last update", config.key, len(changed)
    )

    for pull in changed:
        _process_changed_pull(config, cache, pull, merged_files, client)

    cache["watermark"] = watermark
    _reconcile_merged_proposals(config, cache, merged_files, pulls_seen, client)
    _attach_amendments(config, cache, merged_files, pulls_seen)

    cache["last_updated"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return cache


def init_cache(config: GithubProjectConfig, client: GithubClient) -> dict[str, Any]:
    """Build a cache from scratch (init / refresh).

    Full fetch: tarball + all PRs + files for every PR + reviews/comments
    for proposal PRs. Requires GITHUB_TOKEN.
    """

    logger.info("Downloading %s/%s tarball", config.owner, config.repo)
    merged_files = parse_tarball(client.download_tarball(), config)

    cache: dict[str, Any] = {
        "last_updated": None,
        "proposals": {},
        "pr_index": {},
        "watermark": "",
    }

    pulls_seen: dict[str, dict[str, Any]] = {}
    pull_count = 0
    for pull in client.list_pulls(state="all"):
        pull_count += 1
        pulls_seen[str(pull["number"])] = pull
        _process_new_pull(config, cache, pull, merged_files, client)
        if pull_count % 50 == 0:
            logger.info("Processed %d pull requests...", pull_count)
    logger.info("Fetched and classified %d pull requests", pull_count)

    cache["watermark"] = max(
        (entry["updated_at"] for entry in cache["pr_index"].values()), default=""
    )
    _reconcile_merged_proposals(config, cache, merged_files, pulls_seen, client)
    _attach_amendments(config, cache, merged_files, pulls_seen)

    cache["last_updated"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return cache


def _backfill_merged_snapshots(
    config: GithubProjectConfig, cache: dict[str, Any], client: GithubClient | None
) -> None:
    """One-time backfill of review/comment snapshots for merged KDP PRs.

    Older versions never fetched reviews/comments for merged Kroxylicious
    PRs (the classification shortcut), so their approval history is
    missing. Snapshots are fetched once per PR (~2 API calls each) and
    frozen. Skipped when no client is provided.
    """

    if config.numbering != "pr_number":
        return

    pending = [
        (pr_str, entry)
        for pr_str, entry in cache.get("pr_index", {}).items()
        if entry.get("state") == "merged"
        and entry.get("classification") == "proposal"
        and not entry.get("snapshots_fetched")
        and not entry.get("reviews_snapshot")
        and not entry.get("comments_snapshot")
    ]
    if not pending:
        return

    if client is None:
        logger.warning(
            "%s: %d merged proposal PR(s) have no review snapshot "
            "(pre-backfill cache); run '%s update' to backfill them",
            config.key,
            len(pending),
            config.key,
        )
        return

    for pr_str, entry in pending:
        logger.info(
            "%s: backfilling reviews/comments for merged PR #%s", config.key, pr_str
        )
        reviews, comments = _fetch_reviews_and_comments(client, int(pr_str))
        _store_snapshots(entry, reviews, comments)
        entry["frozen"] = True


def migrate_cache(
    config: GithubProjectConfig,
    cache: dict[str, Any],
    client: GithubClient | None = None,
) -> dict[str, Any]:
    """Migrate a cache to the review-activity record format.

    1. Backfill snapshots for merged KDP proposal PRs (needs a client;
       skipped with a warning otherwise).
    2. Re-derive every proposal record's review activity from its PR
       index snapshots and drop the legacy 'votes' key. Idempotent.
    """

    _backfill_merged_snapshots(config, cache, client)

    for record in cache.get("proposals", {}).values():
        entry = cache.get("pr_index", {}).get(str(record.get("pr_number")), {})
        record["reviews"] = derive_review_activity_from_snapshots(
            entry.get("reviews_snapshot", []),
            entry.get("comments_snapshot", []),
            record.get("created_by", ""),
        )
        record.pop("votes", None)
    return cache


def cache_path_for(config: GithubProjectConfig) -> Path:
    """Path of the committed cache file for a project."""

    return Path(CACHE_DIR) / config.cache_filename


def load_cache(path: Path) -> dict[str, Any]:
    """Load a cache file from disk."""

    with open(path, encoding="utf8") as cache_file:
        return json.load(cache_file)


def save_cache(cache: dict[str, Any], path: Path) -> None:
    """Write a cache file atomically (write temp file, rename)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf8") as cache_file:
        json.dump(cache, cache_file, indent=2)
    temp_path.replace(path)
