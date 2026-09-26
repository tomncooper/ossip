"""Per-project configuration for the social announcement pipeline."""

import os
from dataclasses import dataclass

from ipper.common.github_config import GITHUB_PROJECT_CONFIGS


@dataclass(frozen=True)
class SocialProjectConfig:
    """Static metadata needed to format announcements for one project.

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


SOCIAL_PROJECTS: dict[str, SocialProjectConfig] = {
    "kafka": SocialProjectConfig("kafka", "Kafka", "KIP", "kips"),
    "flink": SocialProjectConfig("flink", "Flink", "FLIP", "flips"),
}

# GitHub-backed projects reuse the canonical project config so names,
# prefixes and detail dirs can never diverge from the site generator.
for _cfg in GITHUB_PROJECT_CONFIGS.values():
    SOCIAL_PROJECTS[_cfg.key] = SocialProjectConfig(
        _cfg.key, _cfg.name, _cfg.prefix, _cfg.detail_dirname
    )


def base_url() -> str:
    """Site base URL (override with OSSIP_BASE_URL for local testing)."""
    return os.environ.get("OSSIP_BASE_URL", "https://ossip.dev").rstrip("/")
