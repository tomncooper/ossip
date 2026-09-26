"""Kafka cache adapter."""

import json
from pathlib import Path

from ipper.social.config import SOCIAL_PROJECTS, base_url
from ipper.social.messages import strip_reference_prefix
from ipper.social.models import ProposalSnapshot

DEFAULT_CACHE = Path("cache/kip_wiki_cache.json")


def load_snapshots(cache_file: Path = DEFAULT_CACHE) -> list[ProposalSnapshot]:
    """Load KIP snapshots from the wiki cache."""
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    cfg = SOCIAL_PROJECTS["kafka"]
    snapshots = []
    for entry in data.values():
        kip_id = int(entry["kip_id"])
        reference = f"KIP-{kip_id}"
        snapshots.append(
            ProposalSnapshot(
                key=f"kafka:{reference.lower()}",
                project="kafka",
                reference=reference,
                title=strip_reference_prefix(entry["title"], reference),
                state=entry["state"],
                detail_url=f"{base_url()}/{cfg.detail_dir}/{reference}.html",
            )
        )
    return snapshots
