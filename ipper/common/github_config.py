"""Per-project configuration for GitHub-based proposal tracking.

Each supported project manages its improvement proposals in a GitHub
repository. Differences between projects are purely configuration:

- Strimzi (SIP): files at the repo root, sequential numbering
- StreamsHub (SHIP): files at the repo root, sequential numbering
- Kroxylicious (KDP): files under ``proposals/``, numbered after the PR
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GithubProjectConfig:
    """Configuration describing one GitHub-hosted proposal process.

    Attributes:
        key: CLI/API key (e.g. "strimzi")
        name: Display name (e.g. "Strimzi")
        owner: GitHub repository owner
        repo: GitHub repository name
        prefix: Proposal prefix (e.g. "SIP")
        proposal_dir: Directory containing proposal files ("" for repo root)
        numbering: "sequential" (number assigned on merge) or "pr_number"
            (file number == originating PR number)
        proposal_pattern: Pattern a proposal filename must fullmatch; group 1
            captures the proposal number
        excluded_files: Filenames matching the pattern but not being proposals
        cache_filename: Committed cache file (under cache/)
        index_title: Optional override for the index page title; defaults to
            "<name> Improvement Proposals (<prefix>s)"
    """

    key: str
    name: str
    owner: str
    repo: str
    prefix: str
    proposal_dir: str
    numbering: str
    proposal_pattern: re.Pattern[str]
    excluded_files: frozenset[str]
    cache_filename: str
    index_title: str | None = None

    @property
    def display_title(self) -> str:
        """Title shown on the index page (heading and <title> tag)."""
        if self.index_title:
            return self.index_title
        return f"{self.name} Improvement Proposals ({self.prefix}s)"

    @property
    def proposal_dir_prefix(self) -> str:
        """Path prefix (with trailing slash) proposal files must live under."""
        if not self.proposal_dir:
            return ""
        return self.proposal_dir.rstrip("/") + "/"

    @property
    def detail_dirname(self) -> str:
        """Directory name for detail pages / JSON API files (e.g. "sips")."""
        return self.prefix.lower() + "s"


PROPOSAL_PATTERN = re.compile(r"^(\d{3})-.+\.md$", re.IGNORECASE)
EXCLUDED_FILES = frozenset({"000-template.md", "README.md"})

STRIMZI_CONFIG = GithubProjectConfig(
    key="strimzi",
    name="Strimzi",
    owner="strimzi",
    repo="proposals",
    prefix="SIP",
    proposal_dir="",
    numbering="sequential",
    proposal_pattern=PROPOSAL_PATTERN,
    excluded_files=EXCLUDED_FILES,
    cache_filename="sip_proposals_cache.json",
)

STREAMSHUB_CONFIG = GithubProjectConfig(
    key="streamshub",
    name="StreamsHub",
    owner="streamshub",
    repo="proposals",
    prefix="SHIP",
    proposal_dir="",
    numbering="sequential",
    proposal_pattern=PROPOSAL_PATTERN,
    excluded_files=EXCLUDED_FILES,
    cache_filename="ship_proposals_cache.json",
)

KROXYLICIOUS_CONFIG = GithubProjectConfig(
    key="kroxylicious",
    name="Kroxylicious",
    owner="kroxylicious",
    repo="design",
    prefix="KDP",
    proposal_dir="proposals",
    numbering="pr_number",
    proposal_pattern=PROPOSAL_PATTERN,
    excluded_files=EXCLUDED_FILES,
    cache_filename="kdp_proposals_cache.json",
    index_title="Kroxylicious Design Proposals (KDPs)",
)

GITHUB_PROJECT_CONFIGS: dict[str, GithubProjectConfig] = {
    config.key: config
    for config in (STRIMZI_CONFIG, STREAMSHUB_CONFIG, KROXYLICIOUS_CONFIG)
}
