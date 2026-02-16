import logging
from argparse import ArgumentParser, Namespace

from ipper.flink.main import setup_flink_parser
from ipper.kafka.main import setup_kafka_parser

CACHE_DIR = "cache"


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level.

    Args:
        verbosity: -1 for quiet (WARNING+), 0 for default (INFO+), 1 for verbose (DEBUG+)
    """
    if verbosity >= 1:
        level = logging.DEBUG
        fmt = "%(levelname)s [%(name)s]: %(message)s"
    elif verbosity <= -1:
        level = logging.WARNING
        fmt = "%(levelname)s: %(message)s"
    else:
        level = logging.INFO
        fmt = "%(levelname)s: %(message)s"

    logging.basicConfig(level=level, format=fmt)


def setup_top_level_parser() -> ArgumentParser:

    top_level_parser = ArgumentParser(
        "ipper",
        description="Ipper - The Improvement Proposal Enrichment program",
    )
    top_level_parser.set_defaults(func=lambda _: print(top_level_parser.format_help()))

    verbosity_group = top_level_parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose/debug output",
    )
    verbosity_group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress informational output, show only warnings and errors",
    )

    top_level_subparsers = top_level_parser.add_subparsers()

    setup_kafka_parser(top_level_subparsers)
    setup_flink_parser(top_level_subparsers)

    return top_level_parser


if __name__ == "__main__":
    PARSER = setup_top_level_parser()
    ARGS: Namespace = PARSER.parse_args()

    verbosity = 0
    if getattr(ARGS, "verbose", False):
        verbosity = 1
    elif getattr(ARGS, "quiet", False):
        verbosity = -1
    configure_logging(verbosity)

    ARGS.func(ARGS)
