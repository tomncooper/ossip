import datetime as dt

from pathlib import Path

from jinja2 import Template, Environment, FileSystemLoader

from ipper.common.constants import DEFAULT_TEMPLATES_DIR, DATE_FORMAT

FLINK_MAIN_PAGE_TEMPLATE = "flink-index.html.jinja"
FLIP_RAW_INFO_PAGE_TEMPLATE = "flip-raw-info.html.jinja"


def get_template(template_dir: str, template_filename) -> Template:
    
    template_path = Path(template_dir).joinpath(Path(template_filename))
    if not template_path.exists():
        raise AttributeError(f"Template {template_path} not found")

    template: Template = Environment(loader=FileSystemLoader(template_dir)).get_template(
        template_filename
    )

    return template


def render_flink_main_page(
    wiki_cache: dict,
    output_filepath: str,
    template_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = FLINK_MAIN_PAGE_TEMPLATE,
) -> None:

    output_path = Path(output_filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template = get_template(template_dir, template_filename)

    # Put the FLIPS in reverse order
    flip_data = [
        wiki_cache[str(flip_id)] for flip_id in sorted(
            [int(key) for key in wiki_cache.keys()], reverse=True
        )
    ]

    output: str = template.render(
        flip_data=flip_data,
        date=dt.datetime.now(dt.timezone.utc).strftime(DATE_FORMAT),
    )

    with open(output_path, "w", encoding="utf8") as out_file:
        out_file.write(output)


def render_raw_info_pages(
    wiki_cache: dict,
    output_directory: str,
    template_dir: str = DEFAULT_TEMPLATES_DIR,
    template_filename: str = FLINK_MAIN_PAGE_TEMPLATE,
) -> None:

    template = get_template(template_dir, template_filename)

    output_dir_path = Path(output_directory)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    for flip_id, flip in wiki_cache.items():
        filename = f"FLIP-{flip_id}.html"
        output_filepath = output_dir_path.joinpath(Path(filename))

        output: str = template.render(
            flip_data=flip,
            date=dt.datetime.now(dt.timezone.utc).strftime(DATE_FORMAT),
        )

        with open(output_filepath, "w", encoding="utf8") as out_file:
            out_file.write(output)
