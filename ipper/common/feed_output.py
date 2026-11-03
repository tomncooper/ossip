"""Atom feeds of newly-created proposals, built from the JSON API summaries."""

import datetime as dt
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ipper.common.feed_names import (
    COMBINED_FEED,
    COMBINED_FEED_TITLE,
    feed_file,
    feed_title,
)
from ipper.common.github_config import GITHUB_PROJECT_CONFIGS
from ipper.common.github_output import detail_page_filename
from ipper.social.adapters.github import reference_for
from ipper.social.config import SOCIAL_PROJECTS, base_url
from ipper.social.messages import strip_reference_prefix

ATOM_NS = "http://www.w3.org/2005/Atom"
MAX_ENTRIES = 50
# Atom wants a square <icon> and a <logo> at least twice as wide as tall
ICON_PATH = "assets/images/ossy.png"
LOGO_PATH = "assets/images/ossy-banner.png"
logger = logging.getLogger(__name__)

# Entry and feed ids are tag URIs so they never depend on the deployment base URL
TAG_PREFIX = "tag:ossip.dev,2026:"

# Characters that are illegal in XML 1.0 (control characters, lone surrogates and
# U+FFFE/U+FFFF) and would make the feed unparseable
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _text(parent: ET.Element, name: str, text: str) -> ET.Element:
    element = ET.SubElement(parent, name)
    element.text = _INVALID_XML_CHARS.sub("", text)
    return element


def _timestamp(created_on: str) -> str:
    """Atom timestamp for a YYYY-MM-DD (or ISO datetime) created_on value."""
    date = created_on[:10] if created_on else "1970-01-01"
    return f"{date}T00:00:00Z"


def _entry_for(key: str, proposal: dict[str, Any]) -> dict[str, Any]:
    """Normalise one summary record into a feed entry dict."""
    project = SOCIAL_PROJECTS[key]
    if key in GITHUB_PROJECT_CONFIGS:
        config = GITHUB_PROJECT_CONFIGS[key]
        reference = reference_for(config, proposal)
        page = detail_page_filename(config, proposal)
        # SIP/SHIP proposals are renumbered when they merge but keep their PR
        # number, so the PR number is the only stable identity
        stable_id = f"pr-{proposal['pr_number']}"
    else:
        reference = f"{project.prefix}-{proposal['id']}"
        page = f"{reference}.html"
        stable_id = reference
    return {
        "project": key,
        "project_name": project.name,
        "reference": reference,
        "title": strip_reference_prefix(proposal["title"], reference),
        "authors": proposal.get("authors", []),
        "created_on": proposal.get("created_on", ""),
        "url": f"{base_url()}/{project.detail_dir}/{page}",
        "id": f"{TAG_PREFIX}{key}/{stable_id}",
        # Numeric tie-break for proposals created on the same day
        "sort_key": (
            proposal.get("created_on", ""),
            proposal.get("id") or 0,
            proposal.get("pr_number") or 0,
        ),
    }


def load_entries(api_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Read every available project summary into feed entry dicts.

    Projects whose summary file is missing or unreadable are absent from the
    result (unreadable ones are logged); projects with a summary but no
    proposals map to an empty list.
    """
    projects: dict[str, list[dict[str, Any]]] = {}
    for key, project in SOCIAL_PROJECTS.items():
        summary_path = api_dir / key / f"{project.detail_dir}.json"
        if not summary_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            projects[key] = [_entry_for(key, p) for p in summary["proposals"]]
        except (OSError, ValueError, KeyError, TypeError):
            # One bad summary must not cost the other projects their feeds
            logger.exception(
                "Skipping %s feed: unreadable summary %s", key, summary_path
            )
    return projects


def build_feed(
    entries: list[dict[str, Any]],
    title: str,
    feed_name: str,
    site_url: str,
    max_entries: int = MAX_ENTRIES,
    include_project: bool = False,
) -> bytes:
    """Render entries (newest first, capped) as an Atom document.

    The feed's <updated> is the newest entry's timestamp rather than the
    build time, so unchanged content produces byte-identical output (an empty
    feed has no entry to take it from and falls back to the build time).

    Args:
        entries: Entry dicts from load_entries
        title: Feed title
        feed_name: Feed filename relative to the site root (e.g. "kafka.xml")
        site_url: The page the feed describes (the feed's "website" link)
        max_entries: Maximum number of entries to keep
        include_project: Prefix entry titles with the project name
    """
    newest = sorted(entries, key=lambda e: e["sort_key"], reverse=True)[:max_entries]

    feed = ET.Element("feed", xmlns=ATOM_NS)
    _text(feed, "title", title)
    _text(feed, "id", f"{TAG_PREFIX}feed/{feed_name}")
    _text(
        feed,
        "updated",
        (
            _timestamp(newest[0]["created_on"])
            if newest
            else dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        ),
    )
    ET.SubElement(feed, "link", href=f"{base_url()}/{feed_name}", rel="self")
    ET.SubElement(feed, "link", href=site_url, rel="alternate")
    _text(feed, "icon", f"{base_url()}/{ICON_PATH}")
    _text(feed, "logo", f"{base_url()}/{LOGO_PATH}")
    author = ET.SubElement(feed, "author")
    _text(author, "name", "OSSIP")

    for entry in newest:
        item = ET.SubElement(feed, "entry")
        heading = f"{entry['reference']}: {entry['title']}"
        if include_project:
            heading = f"{entry['project_name']} {heading}"
        _text(item, "title", heading)
        _text(item, "id", entry["id"])
        _text(item, "updated", _timestamp(entry["created_on"]))
        _text(item, "published", _timestamp(entry["created_on"]))
        ET.SubElement(item, "link", href=entry["url"], rel="alternate")
        for name in entry["authors"]:
            entry_author = ET.SubElement(item, "author")
            _text(entry_author, "name", name)
        # No proposal state here: <updated> never changes, so readers would
        # keep showing whatever state the proposal had when first seen
        summary = "New proposal"
        if entry["authors"]:
            summary += f" by {', '.join(entry['authors'])}"
        _text(item, "summary", summary)

    ET.indent(feed)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


def write_feeds(api_dir: Path, site_dir: Path) -> None:
    """Write feed.xml (all projects) and one <project>.xml per project.

    Args:
        api_dir: JSON API base directory (e.g. site_files/api/v1)
        site_dir: Site root the feeds are written into
    """
    projects = load_entries(api_dir)
    site_dir.mkdir(parents=True, exist_ok=True)

    all_entries = [entry for entries in projects.values() for entry in entries]
    (site_dir / COMBINED_FEED).write_bytes(
        build_feed(
            all_entries,
            COMBINED_FEED_TITLE,
            COMBINED_FEED,
            f"{base_url()}/",
            include_project=True,
        )
    )
    for key, entries in projects.items():
        name = feed_file(key)
        (site_dir / name).write_bytes(
            build_feed(entries, feed_title(key), name, f"{base_url()}/{key}.html")
        )
