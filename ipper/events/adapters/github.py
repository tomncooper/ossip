"""Shared adapter for GitHub-backed proposal projects (SIP/SHIP/KDP)."""

import json
from pathlib import Path

from ipper.common.github_config import GITHUB_PROJECT_CONFIGS, GithubProjectConfig
from ipper.common.github_output import detail_page_filename
from ipper.common.projects import SOCIAL_PROJECTS, base_url
from ipper.events.models import ReviewEntry, SeenSnapshot


def load_snapshots(project: str, cache_file: Path | None = None) -> list[SeenSnapshot]:
    """Load proposal snapshots for a GitHub-backed project.

    Reads the "proposals" section of the cache (already filtered to
    proposal-classified PRs). Keyed by PR number so the baseline key is
    stable across renumbering on merge (SIP-PR-245 -> SIP-46).
    """
    config: GithubProjectConfig = GITHUB_PROJECT_CONFIGS[project]
    if cache_file is None:
        cache_file = Path("cache") / config.cache_filename
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    snapshots = []
    for record in data["proposals"].values():
        pr_number = int(record["pr_number"])
        proposal_id = record.get("id")
        snapshots.append(
            SeenSnapshot(
                key=f"{project}:pr-{pr_number}",
                project=project,
                reference=reference_for(config, record),
                title=str(record["title"]).strip(),
                state=record["state"],
                detail_url=(
                    f"{base_url()}/{SOCIAL_PROJECTS[project].detail_dir}/"
                    f"{detail_page_filename(config, record)}"
                ),
                created_on=record.get("created_at") or record.get("created_on") or None,
                merged_on=record.get("merged_on") or None,
                closed_on=record.get("closed_on") or None,
                last_activity=record.get("last_activity") or None,
                proposal_id=int(proposal_id) if proposal_id is not None else None,
                pr_number=pr_number,
                reviews=_reviews(record.get("reviews")),
            )
        )
    return snapshots


def reference_for(config: GithubProjectConfig, record: dict) -> str:
    """Display reference: SIP-46 for numbered proposals, SIP-PR-245 otherwise."""
    if record.get("id") is not None:
        return f"{config.prefix}-{int(record['id'])}"
    return f"{config.prefix}-PR-{int(record['pr_number'])}"


def _reviews(raw: dict | None) -> dict[str, list[ReviewEntry]] | None:
    """Copy the cache's review columns verbatim into ReviewEntry lists."""
    if not raw:
        return None
    return {
        column: [
            ReviewEntry(name=entry["name"], timestamp=entry["timestamp"])
            for entry in entries
        ]
        for column, entries in raw.items()
    }
