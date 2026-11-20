"""Per-project configuration shared across pipelines (social, events, feeds)."""

import os
from dataclasses import dataclass

from ipper.common.github_config import GITHUB_PROJECT_CONFIGS


@dataclass(frozen=True)
class ProjectConfig:
    """Static metadata needed to identify one project's proposals.

    Attributes:
        key: CLI/API key ("kafka", "strimzi", ...)
        name: Display name used in messages ("Kafka", "Strimzi", ...)
        prefix: Proposal acronym ("KIP", "SIP", ...)
        detail_dir: Directory of detail pages on ossip.dev ("kips", "sips", ...)
    """

    key: str
    name: str
    prefix: str
    detail_dir: str


# Historical name kept as an alias so existing social-pipeline imports stay valid.
SocialProjectConfig = ProjectConfig


SOCIAL_PROJECTS: dict[str, ProjectConfig] = {
    "kafka": ProjectConfig("kafka", "Kafka", "KIP", "kips"),
    "flink": ProjectConfig("flink", "Flink", "FLIP", "flips"),
}

# GitHub-backed projects reuse the canonical project config so names,
# prefixes and detail dirs can never diverge from the site generator.
for _cfg in GITHUB_PROJECT_CONFIGS.values():
    SOCIAL_PROJECTS[_cfg.key] = ProjectConfig(
        _cfg.key, _cfg.name, _cfg.prefix, _cfg.detail_dirname
    )


def base_url() -> str:
    """Site base URL (override with OSSIP_BASE_URL for local testing)."""
    return os.environ.get("OSSIP_BASE_URL", "https://ossip.dev").rstrip("/")


def renumbers_on_merge(project: str) -> bool:
    """Whether a project's proposals are renumbered when a PR merges.

    True for wiki projects and sequential-numbering GitHub projects (the file
    lands on main and gets its number). False for pr_number projects (e.g.
    Kroxylicious/KDP), which are numbered from the PR itself. Shared by live
    detection and backfill so the event log never disagrees with itself.
    """
    cfg = GITHUB_PROJECT_CONFIGS.get(project)
    return cfg is None or cfg.numbering == "sequential"
