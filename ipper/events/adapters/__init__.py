"""Adapters convert project caches into normalised SeenSnapshots.

``ADAPTERS`` maps a project key to a loader taking the cache path (the
GitHub loader dispatches per ``GITHUB_PROJECT_CONFIGS``).
"""

from collections.abc import Callable
from pathlib import Path

from ipper.events.adapters import flink, github, kafka
from ipper.events.models import SeenSnapshot

ADAPTERS: dict[str, Callable[[Path], list[SeenSnapshot]]] = {
    "kafka": kafka.load_snapshots,
    "flink": flink.load_snapshots,
    "strimzi": lambda cache_dir: github.load_snapshots("strimzi", cache_dir),
    "streamshub": lambda cache_dir: github.load_snapshots("streamshub", cache_dir),
    "kroxylicious": lambda cache_dir: github.load_snapshots("kroxylicious", cache_dir),
}
