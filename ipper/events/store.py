"""Event log storage: locking, load/append, detection baselines, version guard.

The log (``cache/events/events.jsonl``) is append-only; detection baselines
(``cache/events/last_seen.json``) are mutable and rewritten atomically. All
mutation happens under an exclusive ``fcntl.flock`` because the five project
updates run in parallel in ``local_build.sh``.
"""

import fcntl
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ipper.events.adapters import ADAPTERS
from ipper.events.detection import detect_events
from ipper.events.models import (
    LAST_SEEN_VERSION,
    EventCandidate,
    EventRecord,
    SeenState,
)
from ipper.events.presentation import stable_id

logger = logging.getLogger(__name__)

EVENTS_DIR = Path("cache/events")
EVENTS_FILE = EVENTS_DIR / "events.jsonl"
SEEN_FILE = EVENTS_DIR / "last_seen.json"
LOCK_FILE = EVENTS_DIR / ".lock"


class EventsVersionError(RuntimeError):
    """Raised when a data file's schema version is unsupported.

    Never silently reseeded: reseeding detection baselines would re-emit
    thousands of duplicate events into a permanent, append-only log.
    """


def _now() -> str:
    """Current UTC time as an ISO 8601 string (same format as social)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def _log_lock() -> Iterator[None]:
    """Exclusive cross-process lock guarding both log and baseline files."""
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _identity(
    project: str,
    key: str,
    event_type: str,
    effective_at: str | None,
    observed_at: str,
    state_before: str | None,
    state_after: str | None,
    reference_before: str | None,
) -> tuple:
    """Identity tuple used for replay dedup."""
    effective_date = (effective_at or observed_at)[:10]
    return (
        project,
        key,
        event_type,
        effective_date,
        state_before,
        state_after,
        reference_before,
    )


def load_events(events_file: Path | None = None) -> list[EventRecord]:
    """Load the event log, skipping corrupt lines and torn final writes.

    One bad line never fails the pipeline; a file that ends mid-line (torn
    write from a crashed process) is silently dropped to the last complete
    line. Unknown event types and extra fields load fine (models use
    ``extra="allow"`` and ``event_type`` is a plain str).
    """
    events_file = events_file or EVENTS_FILE
    if not events_file.exists():
        return []
    data = events_file.read_bytes()
    lines = data.split(b"\n")
    torn = lines[-1] != b""
    if torn:  # crashed mid-write: drop the incomplete final line
        logger.debug(
            "%s ends mid-line; dropping incomplete trailing record", events_file
        )
    events: list[EventRecord] = []
    for lineno, raw in enumerate(lines[:-1] if torn else lines, start=1):
        if not raw.strip():
            continue
        try:
            events.append(EventRecord.model_validate(json.loads(raw)))
        except Exception as ex:
            logger.warning(
                "Skipping unparseable event at %s:%d: %s", events_file, lineno, ex
            )
    return events


def load_seen(seen_file: Path | None = None) -> SeenState:
    """Load the detection baselines; version mismatch is a hard error.

    Never falls back to reseeding — a reseed would re-emit the entire
    history as duplicate events into the append-only log.
    """
    seen_file = seen_file or SEEN_FILE
    if not seen_file.exists():
        return SeenState()
    state = SeenState.model_validate(json.loads(seen_file.read_text(encoding="utf-8")))
    if state.version != LAST_SEEN_VERSION:
        raise EventsVersionError(
            f"last_seen.json is version {state.version}, this build supports "
            f"{LAST_SEEN_VERSION}. Update your checkout or run the event-log "
            "migration for this version."
        )
    return state


def save_seen(state: SeenState, seen_file: Path | None = None) -> None:
    """Atomically write the baselines (temp file + rename)."""
    seen_file = seen_file or SEEN_FILE
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = seen_file.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, seen_file)


def append_events(
    events: list[EventRecord],
    candidates: list[EventCandidate],
    events_file: Path | None = None,
) -> list[EventRecord]:
    """Append candidates to the log; returns the records actually appended.

    Must be called under the lock. Replay-dedup drops candidates whose
    identity tuple already exists in the log (crash-safety: if the process
    dies after appending but before ``save_seen``, the next run re-detects
    the same transition and the replay is dropped here).
    """
    if not candidates:
        return []

    existing_ids = {event.stable_id for event in events}
    existing_identities = {
        _identity(
            event.project,
            event.key,
            event.event_type,
            event.effective_at,
            event.observed_at,
            event.state_before,
            event.state_after,
            event.reference_before,
        )
        for event in events
    }
    next_seq = max((event.seq for event in events), default=0) + 1

    records: list[EventRecord] = []
    for candidate in candidates:
        identity = _identity(
            candidate.project,
            candidate.key,
            candidate.event_type,
            candidate.effective_at,
            candidate.observed_at,
            candidate.state_before,
            candidate.state_after,
            candidate.reference_before,
        )
        if identity in existing_identities:
            logger.debug("Replay-dedup dropped %s", identity)
            continue
        existing_identities.add(identity)
        date = (candidate.effective_at or candidate.observed_at)[:10]
        sid = stable_id(candidate, date, existing_ids)
        existing_ids.add(sid)
        record = EventRecord(
            seq=next_seq,
            stable_id=sid,
            **candidate.model_dump(),
        )
        next_seq += 1
        records.append(record)

    if not records:
        return []
    events_file = events_file or EVENTS_FILE
    events_file.parent.mkdir(parents=True, exist_ok=True)
    with open(events_file, "a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.model_dump()) + "\n")
    return records


def update_from_cache(
    project: str,
    cache_path: Path,
    now: str | None = None,
) -> list[EventRecord]:
    """Producer entrypoint: diff a project cache against the baselines.

    The only public mutator that takes the lock. A missing cache means the
    project is skipped (never "everything disappeared").
    """
    if not cache_path.exists():
        logger.warning(
            "Cache for %s unavailable (%s); skipping project", project, cache_path
        )
        return []
    now = now or _now()
    with _log_lock():
        events = load_events(EVENTS_FILE)
        seen_state = load_seen(SEEN_FILE)
        seen = seen_state.projects.get(project, {})

        snapshots = ADAPTERS[project](cache_path)
        candidates, new_seen = detect_events(project, snapshots, seen, now)
        appended = append_events(events, candidates, EVENTS_FILE)

        seen_state.projects[project] = new_seen
        seen_state.last_run = now
        save_seen(seen_state, SEEN_FILE)
    return appended
