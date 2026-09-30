"""Proposal event log: append-only change history for all five projects.

Producers call :func:`update_from_cache` at the end of each project's
``update`` command. Consumers use the read-only helpers in
:mod:`ipper.events.consumer`.

Feed-integration example::

    from ipper.events import load_events, filter_events, newest_first, latest_snapshot

    events = newest_first(
        filter_events(load_events(), types={"new", "state_changed"}), limit=50
    )

The public API is exposed lazily (``__getattr__``) to keep module import
cycles between ``ipper.events`` and ``ipper.social`` impossible; the names
below import exactly as they would eagerly.
"""

from ipper.events.models import (  # models are dependency-free — eager
    SCHEMA_VERSION,
    EventCandidate,
    EventRecord,
    EventType,
    ReviewEntry,
    SeenSnapshot,
    SeenState,
)

__all__ = [
    "EVENTS_DIR",
    "EVENTS_FILE",
    "LOCK_FILE",
    "SEEN_FILE",
    "SCHEMA_VERSION",
    "EventCandidate",
    "EventRecord",
    "EventType",
    "EventsVersionError",
    "ReviewEntry",
    "SeenSnapshot",
    "SeenState",
    "append_events",
    "events_after_seq",
    "filter_events",
    "headline",
    "latest_snapshot",
    "load_events",
    "load_seen",
    "max_seq",
    "newest_first",
    "read_events",
    "save_seen",
    "summary_text",
    "update_from_cache",
]

# Modules whose public names are re-exported lazily.
_LAZY_MODULES = {
    "EVENTS_DIR": "ipper.events.store",
    "EVENTS_FILE": "ipper.events.store",
    "LOCK_FILE": "ipper.events.store",
    "SEEN_FILE": "ipper.events.store",
    "EventsVersionError": "ipper.events.store",
    "append_events": "ipper.events.store",
    "load_events": "ipper.events.store",
    "load_seen": "ipper.events.store",
    "save_seen": "ipper.events.store",
    "update_from_cache": "ipper.events.store",
    "max_seq": "ipper.events.consumer",
    "filter_events": "ipper.events.consumer",
    "newest_first": "ipper.events.consumer",
    "events_after_seq": "ipper.events.consumer",
    "latest_snapshot": "ipper.events.consumer",
    "headline": "ipper.events.presentation",
    "summary_text": "ipper.events.presentation",
}


def __getattr__(name: str):
    module_path = _LAZY_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def read_events(events_file=None):
    """Alias for :func:`load_events` (the name used in the feed discussion)."""
    loader = __getattr__("load_events")
    return loader(events_file) if events_file is not None else loader()
