import json

from argparse import Namespace
from pathlib import Path

from ipper.flink.wiki import (
    get_flip_main_page_info,
    get_flip_information
)

FLIP_CACHE_FILENAME = "flip_wiki_cache.json"


def setup_flink_parser(top_level_subparsers) -> None:

    flink_parser = top_level_subparsers.add_parser("flink")
    flink_parser.set_defaults(func=lambda _: print(flink_parser.format_help()))

    main_subparser = flink_parser.add_subparsers(
        title="flink subcommands",
        dest="flink_subcommand",
    )
    setup_wiki_command(main_subparser)


def process_wiki(args: Namespace):

    main_page = get_flip_main_page_info()
    flip_data = get_flip_information(main_page, chunk=args.chunk)

    cache_path: Path = Path(args.cache)
    cache_path.mkdir(parents=True, exist_ok=args.overwrite)
    flip_cache_path: Path = cache_path.joinpath(FLIP_CACHE_FILENAME)

    with open(flip_cache_path, "w", encoding="utf8") as flip_cache_file:
        json.dump(flip_data, flip_cache_file)


def setup_wiki_command(main_subparser):
    """Setup the top level wiki command line option."""

    wiki_parser = main_subparser.add_parser(
        "wiki", help="Command for performing wiki related commands"
    )
    wiki_subparser = wiki_parser.add_subparsers(dest="wiki_subcommand")

    wiki_download_subparser = wiki_subparser.add_parser(
        "download", help="Command for downloading and caching KIP wiki information."
    )

    wiki_download_subparser.add_argument(
        "-c",
        "--chunk",
        required=False,
        type=int,
        default=100,
        help="The number of FLIP pages to fetch at once.",
    )

    wiki_download_subparser.add_argument(
        "--cache",
        required=False,
        default="cache",
        help="Folder path where processed information will be cached"
    )

    wiki_download_subparser.add_argument(
        "-ow",
        "--overwrite",
        required=False,
        action="store_true",
        help="Redownload all FLIP wiki information.",
    )

    wiki_download_subparser.set_defaults(func=process_wiki)

