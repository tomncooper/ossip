"""Kafka cache adapter: KIP wiki cache -> SeenSnapshots."""

import json
from pathlib import Path

from ipper.common.projects import base_url
from ipper.events.models import SeenSnapshot
from ipper.social.messages import strip_reference_prefix

DEFAULT_CACHE = Path("cache/kip_wiki_cache.json")


def load_snapshots(cache_file: Path = DEFAULT_CACHE) -> list[SeenSnapshot]:
    """Load KIP snapshots from the wiki cache."""
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    detail_dir = "kips"
    snapshots = []
    for entry in data.values():
        kip_id = int(entry["kip_id"])
        reference = f"KIP-{kip_id}"
        snapshots.append(
            SeenSnapshot(
                key=f"kafka:{reference.lower()}",
                project="kafka",
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
