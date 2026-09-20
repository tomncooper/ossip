"""Strimzi improvement proposal (SIP) CLI entry point."""

from ipper.common.github_cli import setup_github_project_parser
from ipper.common.github_config import STRIMZI_CONFIG


def setup_strimzi_parser(top_level_subparsers) -> None:
    """Add the strimzi subcommands to the supplied top level subparser"""

    setup_github_project_parser(top_level_subparsers, STRIMZI_CONFIG)
