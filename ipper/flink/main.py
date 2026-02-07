import json
import sys
from argparse import Namespace
from pathlib import Path

from pandas import DataFrame

from ipper.common.constants import DEFAULT_TEMPLATES_DIR
from ipper.flink.mailing_list import (
    get_multiple_mbox,
    load_mbox_cache_file,
    process_all_mbox_in_directory,
    update_flip_mentions_cache,
)
from ipper.flink.output import (
    FLINK_MAIN_PAGE_TEMPLATE,
    FLIP_RAW_INFO_PAGE_TEMPLATE,
    render_flink_main_page,
    render_raw_info_pages,
)
from ipper.flink.wiki import (
    get_flip_information,
    get_flip_main_page_info,
)

FLIP_CACHE_FILENAME = "flip_wiki_cache.json"


def setup_flink_parser(top_level_subparsers) -> None:

    flink_parser = top_level_subparsers.add_parser("flink")
    flink_parser.set_defaults(func=lambda _: print(flink_parser.format_help()))

    main_subparser = flink_parser.add_subparsers(
        title="flink subcommands",
        dest="flink_subcommand",
    )
    setup_init_command(main_subparser)
    setup_update_command(main_subparser)
    setup_refresh_command(main_subparser)
    setup_mail_command(main_subparser)
    setup_wiki_command(main_subparser)
    setup_output_command(main_subparser)


def process_wiki(args: Namespace) -> None:

    cache_path: Path = Path(args.cache)
    cache_path.mkdir(parents=True, exist_ok=True)
    flip_cache_path: Path = cache_path.joinpath(FLIP_CACHE_FILENAME)

    # Handle update vs overwrite vs error
    if args.update and args.overwrite:
        args.update = False

    existing_flips = {}
    if flip_cache_path.exists() and not args.overwrite:
        if not args.update:
            print(
                f"Cache file {flip_cache_path} already exists. Add --overwrite to redownload or --update for incremental update"
            )
            sys.exit(1)

        print(f"Loading existing FLIP cache from {flip_cache_path}")
        with open(flip_cache_path, encoding="utf8") as flip_cache_file:
            existing_flips = {int(k): v for k, v in json.load(flip_cache_file).items()}

    main_page = get_flip_main_page_info()
    flip_data = get_flip_information(
        main_page,
        chunk=args.chunk,
        existing_cache=existing_flips,
        refresh_days=args.refresh_days,
    )

    with open(flip_cache_path, "w", encoding="utf8") as flip_cache_file:
        json.dump(flip_data, flip_cache_file)


def process_output(args: Namespace) -> None:

    wiki_cache_path = Path(args.wiki_cache_file)
    if not wiki_cache_path.exists():
        raise AttributeError(f"Wiki Cache file {wiki_cache_path} does not exist")

    with open(wiki_cache_path, encoding="utf8") as wiki_cache_file:
        wiki_cache_data = json.load(wiki_cache_file)

    # Load mailing list mentions if available
    flip_mentions = None
    mentions_file = Path("cache/flink_mailbox_files/flip_mentions.csv")
    if mentions_file.exists():
        print(f"Loading FLIP mentions from {mentions_file}")
        flip_mentions = load_mbox_cache_file(mentions_file)
    else:
        print("No FLIP mentions file found, rendering without vote data")

    render_flink_main_page(
        wiki_cache_data,
        args.main_page_file,
        args.template_dir,
        args.main_page_template_filename,
        flip_mentions,
    )

    render_raw_info_pages(
        wiki_cache_data,
        args.raw_flip_dir,
        args.template_dir,
        args.raw_flip_template_filename,
        flip_mentions,
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
        help="Folder path where processed information will be cached",
    )

    wiki_download_subparser.add_argument(
        "-ow",
        "--overwrite",
        required=False,
        action="store_true",
        help="Redownload all FLIP wiki information.",
    )

    wiki_download_subparser.add_argument(
        "-u",
        "--update",
        required=False,
        action="store_true",
        help="Update FLIP wiki information. Adds new FLIPs and refreshes recently created ones.",
    )

    wiki_download_subparser.add_argument(
        "--refresh-days",
        required=False,
        type=int,
        default=30,
        help="Days since FLIP creation within which to refresh metadata (default: 30)",
    )

    wiki_download_subparser.set_defaults(func=process_wiki)


def setup_init_command(main_subparser):
    """Setup the initialization command"""

    init_parser = main_subparser.add_parser(
        "init", help="Command for initializing all data caches"
    )

    init_parser.add_argument(
        "-d",
        "--days",
        required=False,
        type=int,
        default=365,
        help="The number of days back in time over which to download mail archives. "
        + "Archives are by month so a full month of data will be downloaded "
        + "even if only 1 day is covered by the requested range.",
    )

    init_parser.add_argument(
        "-od",
        "--output_dir",
        required=False,
        help="Directory to save mailing list archives too.",
    )

    init_parser.add_argument(
        "-c",
        "--chunk",
        required=False,
        type=int,
        default=100,
        help="The number of FLIP pages to fetch at once.",
    )

    init_parser.set_defaults(func=run_init_cmd)


def setup_update_command(main_subparser) -> None:
    """Setup the 'update' command parser"""

    update_parser = main_subparser.add_parser(
        "update",
        help="Command for updating the cached data from the FLIP Wiki and Mail Archives",
    )

    update_parser.set_defaults(func=run_update_cmd)


def setup_refresh_command(main_subparser) -> None:
    """Setup the 'refresh' command parser"""

    refresh_parser = main_subparser.add_parser(
        "refresh",
        help="Command for regenerating outputs from existing cache files without downloading",
    )

    refresh_parser.set_defaults(func=run_refresh_cmd)


def setup_mail_command(main_subparser) -> None:
    """Setup the top level mail command line option."""

    mail_parser = main_subparser.add_parser(
        "mail", help="Command for performing mailing list related commands"
    )
    mail_parser.set_defaults(func=mail_parser.print_help)

    mail_subparser = mail_parser.add_subparsers(dest="mail_subcommand")

    download_subparser = mail_subparser.add_parser(
        "download", help="Command for downloading mailing list archives."
    )

    download_subparser.add_argument(
        "mailing_list",
        choices=["dev", "user", "jira", "commits"],
        help="The mailing list to download archives from.",
    )

    download_subparser.add_argument(
        "-d",
        "--days",
        required=False,
        type=int,
        default=365,
        help="The number of days back in time over which to download archives. "
        + "Archives are by month so a full month of data will be downloaded "
        + "even if only 1 day is covered by the requested range.",
    )

    download_subparser.add_argument(
        "-od",
        "--output_dir",
        required=False,
        help="Directory to save mailing list archives too.",
    )

    download_subparser.add_argument(
        "-ow",
        "--overwrite",
        required=False,
        action="store_true",
        help="Replace existing mail archives.",
    )

    download_subparser.set_defaults(func=setup_mail_download)

    process_subparser = mail_subparser.add_parser(
        "process", help="Command for processing mailing list archives."
    )

    process_subparser.add_argument(
        "directory", help="The directory containing the mbox files to be processed."
    )

    process_subparser.add_argument(
        "-owc",
        "--overwrite_cache",
        required=False,
        action="store_true",
        help="Reprocess the mbox files and overwrite their cache files.",
    )

    process_subparser.set_defaults(func=process_mail_archives)


def setup_mail_download(args: Namespace) -> list[Path]:
    """Run the mail archive download command"""

    out_dir = None if "output_dir" not in args else args.output_dir

    use_metadata = getattr(args, "use_metadata", False)
    days = getattr(args, "days", None)

    files: list[Path] = get_multiple_mbox(
        args.mailing_list,
        days_back=days,
        output_directory=out_dir,
        overwrite=args.overwrite,
        use_metadata=use_metadata,
    )

    return files


def process_mail_archives(args: Namespace) -> None:
    """Run the mail archive processing command"""

    out_dir: Path = Path(args.directory)
    flip_mentions: DataFrame = process_all_mbox_in_directory(
        out_dir, overwrite_cache=args.overwrite_cache
    )
    output_file: Path = out_dir.joinpath("flip_mentions.csv")
    flip_mentions.to_csv(output_file, index=False)
    print(f"Saved FLIP mentions to {output_file}")


def run_init_cmd(args: Namespace) -> None:
    print("Initializing all data caches")
    print("Downloading FLIP Wiki Information")
    args.update = False
    args.overwrite = True
    args.cache = "cache"
    args.refresh_days = 30
    process_wiki(args)
    print("Downloading Developer Mailing List Archives")
    args.mailing_list = "dev"
    args.output_dir = "cache/flink_mailbox_files"
    args.use_metadata = True  # Enable metadata tracking even for init
    setup_mail_download(args)
    args.overwrite_cache = True
    args.directory = "cache/flink_mailbox_files"
    process_mail_archives(args)


def run_update_cmd(args: Namespace) -> None:
    print("Updating all data caches (incremental mode)")
    print("Updating FLIP Wiki Information")
    args.update = True
    args.overwrite = False
    args.cache = "cache"
    args.chunk = 100  # Default chunk size for wiki download
    args.refresh_days = 60  # Refresh FLIPs created in last 60 days
    process_wiki(args)

    print("Updating Developer Mailing List Archives")
    # Use metadata to download only new months
    args.mailing_list = "dev"
    args.output_dir = "cache/flink_mailbox_files"
    args.overwrite = True
    args.use_metadata = True
    args.days = None  # Let metadata determine what to download

    updated_files: list[Path] = setup_mail_download(args)

    # Update flip_mentions.csv by appending new data
    output_file = Path("cache/flink_mailbox_files/flip_mentions.csv")
    mbox_directory = Path("cache/flink_mailbox_files")
    update_flip_mentions_cache(updated_files, output_file, mbox_directory)


def run_refresh_cmd(args: Namespace) -> None:
    print("Refreshing outputs from existing cache files")
    # Regenerate flip_mentions.csv from all existing cache files
    args.directory = "cache/flink_mailbox_files"
    args.overwrite_cache = False
    process_mail_archives(args)


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
        "main_page_file", help="The path to the main Flink index html file"
    )

    output_parser.add_argument(
        "raw_flip_dir",
        help="The path to the directory for storing the raw flip information files",
    )

    output_parser.add_argument(
        "--template_dir",
        required=False,
        default=DEFAULT_TEMPLATES_DIR,
        help="Path to the directory holding the jinja templates",
    )

    output_parser.add_argument(
        "--main_page_template_filename",
        required=False,
        default=FLINK_MAIN_PAGE_TEMPLATE,
        help="Name of the flink main page template, inside the template directory",
    )

    output_parser.add_argument(
        "--raw_flip_template_filename",
        required=False,
        default=FLIP_RAW_INFO_PAGE_TEMPLATE,
        help="Name of the template for the raw flip info pages, inside the template directory",
    )

    output_parser.set_defaults(func=process_output)
