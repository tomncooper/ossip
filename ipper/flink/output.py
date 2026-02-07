import datetime as dt
from pathlib import Path
from typing import cast

from jinja2 import Environment, FileSystemLoader, Template
from pandas import DataFrame

from ipper.common.constants import DATE_FORMAT, DEFAULT_TEMPLATES_DIR

FLINK_MAIN_PAGE_TEMPLATE = "flink-index.html.jinja"
FLIP_RAW_INFO_PAGE_TEMPLATE = "flip-more-info.html.jinja"


def get_template(template_dir: str, template_filename) -> Template:

    template_path = Path(template_dir).joinpath(Path(template_filename))
    if not template_path.exists():
        raise AttributeError(f"Template {template_path} not found")

    template: Template = Environment(
        loader=FileSystemLoader(template_dir)
    ).get_template(template_filename)

    return template


def create_vote_dict(
    flip_mentions: DataFrame,
) -> dict[int, dict[str, list[dict[str, str]]]]:
    """Creates a dictionary mapping from FLIP ID to a dict mapping
    from vote type to list of voter info (name and timestamp).

    Args:
        flip_mentions: DataFrame containing FLIP mentions from mailing lists

    Returns:
        Dictionary mapping FLIP ID to vote info by type
    """

    vote_dict: dict[int, dict[str, list[dict[str, str]]]] = {}
    flip_votes: DataFrame
    for flip_id, flip_votes in flip_mentions[~flip_mentions["vote"].isna()][
        ["flip", "from", "vote", "timestamp"]
    ].groupby("flip"):
        flip_dict = {}
        for vote in ["+1", "0", "-1"]:
            vote_rows = flip_votes[flip_votes["vote"] == vote]

            # Keep only the most recent vote per voter
            voter_map: dict[str, dict[str, str]] = {}
            for _, row in vote_rows.iterrows():
                voter_name = row["from"].replace('"', "")
                timestamp = row["timestamp"]

                if (
                    voter_name not in voter_map
                    or timestamp > voter_map[voter_name]["raw_timestamp"]
                ):
                    voter_map[voter_name] = {
                        "name": voter_name,
                        "timestamp": timestamp.strftime("%b %d, %Y %H:%M UTC"),
                        "raw_timestamp": timestamp,
                    }

            # Sort by timestamp descending (newest first) and remove raw_timestamp
            sorted_voters = sorted(
                voter_map.values(), key=lambda x: x["raw_timestamp"], reverse=True
            )
            flip_dict[f"{vote}"] = [
                {"name": v["name"], "timestamp": v["timestamp"]} for v in sorted_voters
            ]

        vote_dict[cast(int, flip_id)] = flip_dict

    return vote_dict


def enrich_flip_wiki_info_with_votes(
    flip_wiki_info: dict,
    flip_mentions: DataFrame,
) -> dict:
    """Enriches FLIP wiki information with vote data from mailing list mentions.

    Args:
        flip_wiki_info: Dictionary of FLIP wiki data (keyed by FLIP ID as string)
        flip_mentions: DataFrame containing FLIP mentions

    Returns:
        Enriched dictionary with vote information added
    """

    vote_dict: dict[int, dict[str, list[dict[str, str]]]] = create_vote_dict(
        flip_mentions
    )

    enriched_info: dict = {}
    for flip_id_str, flip_data in flip_wiki_info.items():
        flip_id = int(flip_id_str)
        enriched_flip: dict[str, int | str | list[str] | list[dict[str, str]]] = dict(
            flip_data
        )

        if flip_id in vote_dict:
            for vote in ["+1", "0", "-1"]:
                enriched_flip[vote] = vote_dict[flip_id][vote]
        else:
            for vote in ["+1", "0", "-1"]:
                enriched_flip[vote] = []

        enriched_info[flip_id_str] = enriched_flip

    return enriched_info


def render_flink_main_page(
    wiki_cache: dict,
    output_filepath: str,
    template_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = FLINK_MAIN_PAGE_TEMPLATE,
    flip_mentions: DataFrame | None = None,
) -> None:
    """Render the main Flink index page with FLIP data.

    Args:
        wiki_cache: Dictionary of FLIP wiki data
        output_filepath: Path to save the output HTML file
        template_dir: Directory containing Jinja2 templates
        template_filename: Name of the template file
        flip_mentions: Optional DataFrame with mailing list mentions for vote data
    """

    output_path = Path(output_filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Enrich with vote data if available
    if flip_mentions is not None:
        wiki_cache = enrich_flip_wiki_info_with_votes(wiki_cache, flip_mentions)

    template = get_template(template_dir, template_filename)

    # Put the FLIPS in reverse order
    flip_data = [
        wiki_cache[str(flip_id)]
        for flip_id in sorted([int(key) for key in wiki_cache], reverse=True)
    ]

    output: str = template.render(
        flip_data=flip_data,
        date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
    )

    with open(output_path, "w", encoding="utf8") as out_file:
        out_file.write(output)


def render_raw_info_pages(
    wiki_cache: dict,
    output_directory: str,
    template_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = FLIP_RAW_INFO_PAGE_TEMPLATE,
    flip_mentions: DataFrame | None = None,
) -> None:
    """Render individual FLIP information pages.

    Args:
        wiki_cache: Dictionary of FLIP wiki data
        output_directory: Directory to save the output HTML files
        template_dir: Directory containing Jinja2 templates
        template_filename: Name of the template file
        flip_mentions: Optional DataFrame with mailing list mentions for vote data
    """

    # Enrich with vote data if available
    if flip_mentions is not None:
        wiki_cache = enrich_flip_wiki_info_with_votes(wiki_cache, flip_mentions)

    template = get_template(template_dir, template_filename)

    output_dir_path = Path(output_directory)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    for flip_id, flip in wiki_cache.items():
        filename = f"FLIP-{flip_id}.html"
        output_filepath = output_dir_path.joinpath(Path(filename))

        output: str = template.render(
            flip_data=flip,
            date=dt.datetime.now(dt.UTC).strftime(DATE_FORMAT),
        )

        with open(output_filepath, "w", encoding="utf8") as out_file:
            out_file.write(output)
