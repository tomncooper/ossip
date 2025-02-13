import json
import sys

from argparse import Namespace
from pathlib import Path

from ipper.flink.wiki import (
    get_flip_main_page_info,
    get_flip_information
)
from ipper.flink.output import render_flink_main_page, FLINK_MAIN_PAGE_TEMPLATE
from ipper.common.constants import DEFAULT_TEMPLATES_DIR

FLIP_CACHE_FILENAME = "flip_wiki_cache.json"


def setup_flink_parser(top_level_subparsers) -> None:

    flink_parser = top_level_subparsers.add_parser("flink")
    flink_parser.set_defaults(func=lambda _: print(flink_parser.format_help()))

    main_subparser = flink_parser.add_subparsers(
        title="flink subcommands",
        dest="flink_subcommand",
    )
    setup_wiki_command(main_subparser)
    setup_output_command(main_subparser)


def process_wiki(args: Namespace) -> None:

    cache_path: Path = Path(args.cache)
    cache_path.mkdir(parents=True, exist_ok=True)
    flip_cache_path: Path = cache_path.joinpath(FLIP_CACHE_FILENAME)

    if flip_cache_path.exists() and not args.overwrite:
        print(f"Cache file {flip_cache_path} already exists. Add --overwrite to redownload")
        sys.exit(1)

    main_page = get_flip_main_page_info()
    flip_data = get_flip_information(main_page, chunk=args.chunk)

    with open(flip_cache_path, "w", encoding="utf8") as flip_cache_file:
        json.dump(flip_data, flip_cache_file)


def process_output(args: Namespace) -> None:

    wiki_cache_path = Path(args.wiki_cache_file)
    if not wiki_cache_path.exists():
        raise AttributeError(f"Wiki Cache file {wiki_cache_path} does not exist")

    with open(wiki_cache_path, "r", encoding="utf8") as wiki_cache_file:
        wiki_cache_data = json.load(wiki_cache_file)

    render_flink_main_page(
        wiki_cache_data,
        args.output_file,
        args.template_dir,
        args.template_filename,
    )


def setup_wiki_command(main_subparser):
    """Setup the top level wiki command line option."""

    wiki_parser = main_subparser.add_parser(
        "wiki", help="Command for performing wiki related tasks"
    )
    wiki_parser.set_defaults(func=wiki_parser.print_help)
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


def setup_output_command(main_subparser):
    """Setup the top level output command line option."""

    output_parser = main_subparser.add_parser(
        "output", help="Command for performing output related tasks"
    )
    output_parser.set_defaults(func=output_parser.print_help)

    output_parser.add_argument(
        "wiki_cache_file", help="The path to the wiki data json file"
    )

    output_parser.add_argument(
        "output_file", help="The path to the output html file"
    )

    output_parser.add_argument(
        "--template_dir", required=False, default=DEFAULT_TEMPLATES_DIR,
        help="Path to the directory holding the jinja templates",
    )

    output_parser.add_argument(
        "--template_filename", required=False, default=FLINK_MAIN_PAGE_TEMPLATE,
        help="Name of the flink main page template inside the template directory",
    )

    output_parser.set_defaults(func=process_output)
