"""Flink cache adapter: FLIP wiki cache -> SeenSnapshots."""

import json
from pathlib import Path

from ipper.common.projects import base_url
from ipper.events.models import SeenSnapshot
from ipper.social.messages import strip_reference_prefix

DEFAULT_CACHE = Path("cache/flip_wiki_cache.json")


def load_snapshots(cache_file: Path = DEFAULT_CACHE) -> list[SeenSnapshot]:
    """Load FLIP snapshots from the wiki cache."""
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    detail_dir = "flips"
    snapshots = []
    for entry in data.values():
        flip_id = int(entry["id"])
        reference = f"FLIP-{flip_id}"
        snapshots.append(
            SeenSnapshot(
                key=f"flink:{reference.lower()}",
                project="flink",
                reference=reference,
                title=strip_reference_prefix(entry["title"], reference),
                state=entry["state"],
                detail_url=f"{base_url()}/{detail_dir}/{reference}.html",
                created_on=entry.get("created_on"),
                last_modified_on=entry.get("last_modified_on"),
                vote_thread=_vote_thread(entry.get("vote_thread")),
            )
        )
    return snapshots


def _vote_thread(value: str | None) -> str | None:
    """Normalise the wiki sentinel ('not set') to None."""
    if not value or value == "not set":
        return None
    return value
