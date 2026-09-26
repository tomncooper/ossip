"""Shared adapter for GitHub-backed proposal projects (SIP/SHIP/KDP)."""

import json
from pathlib import Path

from ipper.common.github_config import GITHUB_PROJECT_CONFIGS, GithubProjectConfig
from ipper.common.github_output import detail_page_filename
from ipper.social.config import SOCIAL_PROJECTS, base_url
from ipper.social.models import ProposalSnapshot


def load_snapshots(
    project: str, cache_dir: Path = Path("cache")
) -> list[ProposalSnapshot]:
    """Load proposal snapshots for a GitHub-backed project.

    Reads the "proposals" section of the cache (already filtered to
    proposal-classified PRs). Keyed by PR number so the baseline key is
    stable across renumbering on merge (SIP-PR-245 -> SIP-46).
    """
    config: GithubProjectConfig = GITHUB_PROJECT_CONFIGS[project]
    cache_file = cache_dir / config.cache_filename
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    snapshots = []
    for record in data["proposals"].values():
        pr_number = int(record["pr_number"])
        snapshots.append(
            ProposalSnapshot(
                key=f"{project}:pr-{pr_number}",
                project=project,
                reference=reference_for(config, record),
                title=str(record["title"]).strip(),
                state=record["state"],
                detail_url=(
                    f"{base_url()}/{SOCIAL_PROJECTS[project].detail_dir}/"
                    f"{detail_page_filename(config, record)}"
                ),
            )
        )
    return snapshots


def reference_for(config: GithubProjectConfig, record: dict) -> str:
    """Display reference: SIP-46 for numbered proposals, SIP-PR-245 otherwise."""
    if record.get("id") is not None:
        return f"{config.prefix}-{int(record['id'])}"
    return f"{config.prefix}-PR-{int(record['pr_number'])}"
