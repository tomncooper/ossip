"""Adapters convert project caches into normalised ProposalSnapshots."""

from collections.abc import Callable

from ipper.social.adapters import flink, github, kafka
from ipper.social.models import ProposalSnapshot

LOADERS: dict[str, Callable[[], list[ProposalSnapshot]]] = {
    "kafka": kafka.load_snapshots,
    "flink": flink.load_snapshots,
    "strimzi": lambda: github.load_snapshots("strimzi"),
    "streamshub": lambda: github.load_snapshots("streamshub"),
    "kroxylicious": lambda: github.load_snapshots("kroxylicious"),
}
