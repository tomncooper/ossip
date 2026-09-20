"""Shared CLI command factory for GitHub-based proposal tracking.

Each supported project (strimzi, streamshub, kroxylicious) registers the
same set of subcommands - init, update, refresh, output - parameterised by
its GithubProjectConfig. All logic lives here; the per-project modules are
thin wrappers.
"""

import logging
import sys
from argparse import Namespace
from pathlib import Path

from ipper.common.github import (
    GithubClient,
    GithubClientError,
    GithubTokenRequiredError,
)
from ipper.common.github_config import GithubProjectConfig
from ipper.common.github_output import (
    generate_github_json_api,
    render_detail_pages,
    render_index_page,
)
from ipper.common.github_process import (
    cache_path_for,
    init_cache,
    load_cache,
    migrate_cache,
    save_cache,
    update_cache,
)

logger = logging.getLogger(__name__)


def _build_client(config: GithubProjectConfig, require_token: bool) -> GithubClient:
    try:
        return GithubClient(config.owner, config.repo, require_token=require_token)
    except GithubTokenRequiredError as ex:
        logger.error("%s", ex)
        sys.exit(1)


def run_init_cmd(config: GithubProjectConfig, args: Namespace) -> None:
    """Full first fetch from GitHub (requires GITHUB_TOKEN)."""

    logger.info("Initializing %s proposal cache (full fetch)", config.key)
    client = _build_client(config, require_token=True)
    try:
        cache = init_cache(config, client)
    except GithubClientError as ex:
        logger.error("%s init failed: %s", config.key, ex)
        sys.exit(1)
    output_path = cache_path_for(config)
    save_cache(cache, output_path)
    logger.info(
        "Cached %d proposals and %d indexed PRs to %s",
        len(cache["proposals"]),
        len(cache["pr_index"]),
        output_path,
    )


def run_refresh_cmd(config: GithubProjectConfig, args: Namespace) -> None:
    """Full reprocess from GitHub (requires GITHUB_TOKEN)."""

    logger.info("Refreshing %s proposal cache (full reprocess)", config.key)
    client = _build_client(config, require_token=True)
    try:
        cache = init_cache(config, client)
    except GithubClientError as ex:
        logger.error("%s refresh failed: %s", config.key, ex)
        sys.exit(1)
    output_path = cache_path_for(config)
    save_cache(cache, output_path)
    logger.info(
        "Cached %d proposals and %d indexed PRs to %s",
        len(cache["proposals"]),
        len(cache["pr_index"]),
        output_path,
    )


def run_update_cmd(config: GithubProjectConfig, args: Namespace) -> None:
    """Incremental update (~5-15 requests; works unauthenticated)."""

    cache_path = cache_path_for(config)
    if not cache_path.exists():
        logger.error(
            "Cache file %s does not exist. Run '%s init' first.",
            cache_path,
            config.key,
        )
        sys.exit(1)

    logger.info("Updating %s proposal cache (incremental)", config.key)
    cache = load_cache(cache_path)
    client = _build_client(config, require_token=False)
    cache = migrate_cache(config, cache, client)
    try:
        cache = update_cache(config, cache, client)
    except GithubClientError as ex:
        logger.error("%s update failed: %s", config.key, ex)
        sys.exit(1)
    save_cache(cache, cache_path)
    logger.info(
        "Cached %d proposals and %d indexed PRs to %s",
        len(cache["proposals"]),
        len(cache["pr_index"]),
        cache_path,
    )


def run_output_cmd(config: GithubProjectConfig, args: Namespace) -> None:
    """Render the index page, detail pages and (optional) JSON API."""

    cache_file = Path(args.cache_file)
    if not cache_file.exists():
        logger.error("Cache file %s does not exist", cache_file)
        sys.exit(1)

    cache = load_cache(cache_file)
    migrate_cache(config, cache)

    render_index_page(
        config, cache, args.index_html, detail_dir=Path(args.detail_dir).name
    )
    render_detail_pages(config, cache, args.detail_dir)

    if args.api_dir:
        generate_github_json_api(config, cache, Path(args.api_dir))


def setup_github_project_parser(top_level_subparsers, config: GithubProjectConfig):
    """Register the {init,update,refresh,output} subcommands for a project."""

    parser = top_level_subparsers.add_parser(
        config.key,
        help=f"Track {config.name} improvement proposals ({config.prefix}s) "
        f"from GitHub {config.owner}/{config.repo}",
    )
    parser.set_defaults(func=lambda _: print(parser.format_help()))

    main_subparser = parser.add_subparsers(
        title=f"{config.key} subcommands",
        dest=f"{config.key}_subcommand",
    )

    init_parser = main_subparser.add_parser(
        "init",
        help="Full first fetch from GitHub (requires GITHUB_TOKEN)",
    )
    init_parser.set_defaults(func=lambda args: run_init_cmd(config, args))

    update_parser = main_subparser.add_parser(
        "update",
        help="Incremental update of the cached proposal data",
    )
    update_parser.set_defaults(func=lambda args: run_update_cmd(config, args))

    refresh_parser = main_subparser.add_parser(
        "refresh",
        help="Full reprocess from GitHub (requires GITHUB_TOKEN)",
    )
    refresh_parser.set_defaults(func=lambda args: run_refresh_cmd(config, args))

    output_parser = main_subparser.add_parser(
        "output",
        help="Render the proposal index page, detail pages and JSON API",
    )
    output_parser.add_argument(
        "cache_file",
        help=f"The path to the cache json file (e.g. cache/{config.cache_filename})",
    )
    output_parser.add_argument(
        "index_html",
        help=f"The path to the output {config.key}.html file",
    )
    output_parser.add_argument(
        "detail_dir",
        help=f"The path to the directory for storing individual {config.prefix} pages",
    )
    output_parser.add_argument(
        "--api-dir",
        default=None,
        help="Optional: Directory for JSON API output "
        f"(e.g., site_files/api/v1/{config.key})",
    )
    output_parser.set_defaults(func=lambda args: run_output_cmd(config, args))

    return parser
