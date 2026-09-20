"""StreamsHub improvement proposal (SHIP) CLI entry point."""

from ipper.common.github_cli import setup_github_project_parser
from ipper.common.github_config import STREAMSHUB_CONFIG


def setup_streamshub_parser(top_level_subparsers) -> None:
    """Add the streamshub subcommands to the supplied top level subparser"""

    setup_github_project_parser(top_level_subparsers, STREAMSHUB_CONFIG)
