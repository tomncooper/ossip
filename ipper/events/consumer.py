"""Consumer API: read, filter, sort and resolve proposal events.

The feed-facing surface for the event log — consumers (RSS feeds, webhooks,
JSON API) use these helpers instead of touching caches or internal state.
``latest_snapshot`` resolves a proposal's CURRENT reference/detail_url from
``last_seen.json``, fixing the stale-link problem for renumbered proposals.
"""

import logging
from collections.abc import Iterable
from itertools import islice
from pathlib import Path

from ipper.events.models import SeenSnapshot
from ipper.events.presentation import event_time
from ipper.events.store import SEEN_FILE, load_events, load_seen  # noqa: F401

logger = logging.getLogger(__name__)


def max_seq(events: Iterable) -> int:
    """Highest seq in the log (0 if empty)."""
    return max((e.seq for e in events), default=0)


def filter_events(
    events: Iterable,
    project: str | None = None,
    types: Iterable[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    include_backfilled: bool = True,
) -> list:
    """Filter events by project, type, date bounds (on event_time) and backfill flag.

    ``since``/``until`` are inclusive date bounds (``YYYY-MM-DD``) compared
    against the first 10 chars of ``event_time``. Unknown event types pass
    through harmlessly (they simply don't match ``types`` if given).
    """
    type_set = set(types) if types is not None else None
    out = []
    for event in events:
        if project is not None and event.project != project:
            continue
        if type_set is not None and event.event_type not in type_set:
            continue
        if not include_backfilled and event.backfilled:
            continue
        stamp = event_time(event)
        if since is not None and stamp[:10] < since:
            continue
        if until is not None and stamp[:10] > until:
            continue
        out.append(event)
    return out


def newest_first(events: list, limit: int | None = None) -> list:
    """Sort events by (event_time, seq) descending; stable; optional limit."""
    ordered = sorted(events, key=lambda e: (event_time(e), e.seq), reverse=True)
    if limit is not None:
        return list(islice(ordered, limit))
    return ordered


def events_after_seq(events: list, seq: int) -> list:
    """Events strictly after a seq (ascending), for cursor-style consumers."""
    return [e for e in events if e.seq > seq]


def latest_snapshot(key: str, seen_file: Path | None = None) -> SeenSnapshot | None:
    """The proposal's CURRENT snapshot from last_seen.json (None if unknown)."""
    seen = load_seen(seen_file or SEEN_FILE)
    for project_snapshots in seen.projects.values():
        snapshot = project_snapshots.get(key)
        if snapshot is not None:
            return snapshot
    return None
