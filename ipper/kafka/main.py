from argparse import ArgumentParser, Namespace
from pathlib import Path

from pandas import DataFrame, concat

from ipper.common.keys import get_committer_index
from ipper.kafka.mailing_list import (
    KEYS_CACHE_PATH,
    KEYS_URL,
    KIP_MENTION_COLUMNS,
    get_multiple_mbox,
    load_mbox_cache_file,
    process_mbox_archive,
    update_kip_mentions_cache,
)
from ipper.kafka.output import (
    enrich_kip_wiki_info_with_votes,
    render_kip_info_pages,
    render_standalone_status_page,
)
from ipper.kafka.wiki import get_kip_information, get_kip_main_page_info


def setup_kafka_parser(top_level_subparsers) -> None:
    """Add the kafka subcommands to the supplied top level subparser"""

    kafka_parser = top_level_subparsers.add_parser("kafka")
    kafka_parser.set_defaults(func=lambda _: print(kafka_parser.format_help()))

    main_subparser = kafka_parser.add_subparsers(
        title="kafka subcommands",
        dest="kafka_subcommand",
    )
    setup_init_command(main_subparser)
    setup_update_command(main_subparser)
    setup_refresh_command(main_subparser)
    setup_keys_command(main_subparser)
    setup_wiki_command(main_subparser)
    setup_output_command(main_subparser)


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
        help="The number of KIP pages to fetch at once.",
    )

    init_parser.set_defaults(func=run_init_cmd)


def setup_update_command(main_subparser) -> None:
    """Setup the 'update' command parser"""

    update_parser = main_subparser.add_parser(
        "update",
        help="Command for updating the cached data from the KIP Wiki and Mail Archives",
    )

    update_parser.set_defaults(func=run_update_cmd)


def setup_refresh_command(main_subparser) -> None:
    """Setup the 'refresh' command parser"""

    refresh_parser = main_subparser.add_parser(
        "refresh",
        help="Command for regenerating outputs from existing cache files without downloading",
    )

    refresh_parser.set_defaults(func=run_refresh_cmd)


def setup_keys_command(main_subparser) -> None:
    """Setup the 'keys' command parser"""

    keys_parser = main_subparser.add_parser(
        "keys", help="Commands for managing committer KEYS file cache"
    )
    keys_subparser = keys_parser.add_subparsers(dest="keys_subcommand")

    keys_refresh_parser = keys_subparser.add_parser(
        "refresh", help="Force refresh of committer KEYS file from Apache downloads"
    )
    keys_refresh_parser.set_defaults(func=run_keys_refresh_cmd)

    keys_info_parser = keys_subparser.add_parser(
        "info", help="Display information about cached committer KEYS"
    )
    keys_info_parser.set_defaults(func=run_keys_info_cmd)


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
        help="The number of KIP pages to fetch at once.",
    )

    wiki_download_subparser.add_argument(
        "-ow",
        "--overwrite",
        required=False,
        action="store_true",
        help="Redownload all KIP wiki information.",
    )

    wiki_download_subparser.add_argument(
        "-u",
        "--update",
        required=False,
        action="store_true",
        help=(
            "Update KIP wiki information. "
            + "This will add any newly added KIPs to the existing cache."
        ),
    )

    wiki_download_subparser.set_defaults(func=setup_wiki_download)


def setup_output_command(main_subparser):
    """Setup the top level output command line option."""

    output_parser = main_subparser.add_parser(
        "output", help="Command for performing output related commands"
    )
    output_parser.set_defaults(func=output_parser.print_help)

    output_subparser = output_parser.add_subparsers(dest="output_subcommand")

    standalone_subparser = output_subparser.add_parser(
        "standalone",
        help="Command for rendering a standalone html file of the kp table.",
    )

    standalone_subparser.add_argument(
        "kip_mentions_file", help="The path to the processed kip mentions csv."
    )

    standalone_subparser.add_argument(
        "output_file", help="The path to the output html file"
    )

    standalone_subparser.add_argument(
        "kip_info_dir",
        nargs="?",
        default=None,
        help="Optional: The path to the directory for storing individual KIP info pages",
    )

    standalone_subparser.set_defaults(func=run_output_standalone_cmd)


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


def setup_wiki_download(args: Namespace) -> None:
    """Run the KIP wiki information download"""

    kip_main_info = get_kip_main_page_info()
    get_kip_information(
        kip_main_info,
        chunk=args.chunk,
        update=args.update,
        overwrite_cache=args.overwrite,
    )


def run_init_cmd(args: Namespace) -> None:
    print("Initializing all data caches")
    print("Downloading KIP Wiki Information")
    args.update = False
    args.overwrite = True
    setup_wiki_download(args)
    print("Downloading Developer Mailing List Archives")
    args.mailing_list = "dev"
    args.output_dir = "cache/mailbox_files"
    args.use_metadata = True  # Enable metadata tracking even for init
    mbox_files: list[Path] = setup_mail_download(args)

    # Process all mbox files directly (no intermediate cache)
    print("Processing mbox files")
    all_mentions: DataFrame = DataFrame(columns=KIP_MENTION_COLUMNS)

    for mbox_file in mbox_files:
        print(f"Processing {mbox_file.name}")
        try:
            file_data = process_mbox_archive(mbox_file)
            all_mentions = concat((all_mentions, file_data), ignore_index=True)
        except Exception as ex:
            print(f"ERROR processing file {mbox_file.name}: {ex}")

    # Deduplicate and save
    all_mentions = all_mentions.drop_duplicates()
    output_file = Path("cache/mailbox_files/kip_mentions.csv")
    all_mentions.to_csv(output_file, index=False)
    print(f"Saved {len(all_mentions)} KIP mentions to {output_file}")


def run_update_cmd(args: Namespace) -> None:
    print("Updating all data caches (incremental mode)")
    print("Updating KIP Wiki Information")
    args.update = True
    args.overwrite = False
    args.chunk = 100  # Default chunk size for wiki download
    setup_wiki_download(args)

    print("Updating Developer Mailing List Archives")
    # Use metadata to download only new months
    args.mailing_list = "dev"
    args.output_dir = "cache/mailbox_files"
    args.overwrite = True
    args.use_metadata = True
    args.days = None  # Let metadata determine what to download

    updated_files: list[Path] = setup_mail_download(args)

    # Update kip_mentions.csv by appending new data
    output_file = Path("cache/mailbox_files/kip_mentions.csv")
    mbox_directory = Path("cache/mailbox_files")
    update_kip_mentions_cache(updated_files, output_file, mbox_directory)


def run_refresh_cmd(args: Namespace) -> None:
    print("Refreshing by reprocessing all mbox files")
    mbox_directory = Path("cache/mailbox_files")
    mbox_files: list[Path] = sorted(mbox_directory.glob("*.mbox"))

    print(f"Found {len(mbox_files)} mbox files to process")
    all_mentions: DataFrame = DataFrame(columns=KIP_MENTION_COLUMNS)

    for mbox_file in mbox_files:
        print(f"Processing {mbox_file.name}")
        try:
            file_data = process_mbox_archive(mbox_file)
            all_mentions = concat((all_mentions, file_data), ignore_index=True)
        except Exception as ex:
            print(f"ERROR processing file {mbox_file.name}: {ex}")

    # Deduplicate before saving (important!)
    all_mentions = all_mentions.drop_duplicates()

    output_file = mbox_directory / "kip_mentions.csv"
    all_mentions.to_csv(output_file, index=False)
    print(f"Saved {len(all_mentions)} KIP mentions to {output_file}")


def run_output_standalone_cmd(args: Namespace) -> None:
    cache_file = Path(args.kip_mentions_file)
    kip_mentions: DataFrame = load_mbox_cache_file(cache_file)
    render_standalone_status_page(kip_mentions, args.output_file)

    # Generate individual KIP info pages if directory is specified
    if args.kip_info_dir:
        kip_main_info = get_kip_main_page_info()
        kip_wiki_info = get_kip_information(kip_main_info)

        # Enrich with vote data
        enriched_kip_info = enrich_kip_wiki_info_with_votes(kip_wiki_info, kip_mentions)

        # Render individual pages
        render_kip_info_pages(enriched_kip_info, args.kip_info_dir)


def run_keys_refresh_cmd(args: Namespace) -> None:
    """Force refresh of the Kafka committer KEYS file."""
    print(f"Force refreshing Kafka committer KEYS from {KEYS_URL}")
    index = get_committer_index(KEYS_URL, KEYS_CACHE_PATH, force_refresh=True)
    print(f"Successfully loaded {len(index.committers)} committers")
    print(f"Cache saved to: {KEYS_CACHE_PATH}")


def run_keys_info_cmd(args: Namespace) -> None:
    """Display information about cached committer KEYS."""
    from ipper.common.keys import load_committer_index

    print(f"Loading Kafka committer KEYS from cache: {KEYS_CACHE_PATH}")
    index = load_committer_index(KEYS_CACHE_PATH)

    if not index:
        print("No cached KEYS file found. Run 'kafka keys refresh' to download.")
        return

    print(f"\nSource: {index.source_url}")
    print(f"Last updated: {index.last_updated.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Number of committers: {len(index.committers)}")
    print("\nSample committers:")
    for committer in index.committers[:5]:
        print(f"  - {committer.name} ({', '.join(committer.emails[:2])})")
    if len(index.committers) > 5:
        print(f"  ... and {len(index.committers) - 5} more")


if __name__ == "__main__":
    PARSER: ArgumentParser = ArgumentParser(
        "Kafka Improvement Proposal Enrichment Program"
    )
    setup_kafka_parser(PARSER)
    ARGS: Namespace = PARSER.parse_args()
    ARGS.func(ARGS)
