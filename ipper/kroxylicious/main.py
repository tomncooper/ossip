"""Kroxylicious design proposal (KDP) CLI entry point."""

from ipper.common.github_cli import setup_github_project_parser
from ipper.common.github_config import KROXYLICIOUS_CONFIG


def setup_kroxylicious_parser(top_level_subparsers) -> None:
    """Add the kroxylicious subcommands to the supplied top level subparser"""

    setup_github_project_parser(top_level_subparsers, KROXYLICIOUS_CONFIG)
