"""Public events JSON API emitter (Phase 1 of the timeline feature).

Writes ``api_dir/events.json`` — the proposal event log enriched with
precomputed display fields (``event_time``/``headline``/``summary``) and
current proposal resolution (``current_reference``/``current_detail_url``
via ``last_seen.json``), newest-first. Consumed by the timeline page
(``timeline.html`` + ``assets/timeline.js``) and AI agents.
"""

import datetime as dt
import logging
from pathlib import Path

from ipper.events import store
from ipper.events.consumer import newest_first
from ipper.events.models import ApiEvent, EventRecord, EventsDocument
from ipper.events.presentation import event_time, headline, summary_text
from ipper.events.store import load_events, load_seen

logger = logging.getLogger(__name__)


def enrich_event(event: EventRecord, current: dict[str, tuple[str, str]]) -> ApiEvent:
    """Attach display fields + current reference/URL to one event.

    ``current`` maps proposal key → ``(reference, detail_url)`` resolved
    from ``last_seen.json`` (see :func:`_seen_index`).
    """
    snapshot = current.get(event.key)
    current_reference, current_detail_url = snapshot if snapshot else (None, None)
    return ApiEvent(
        **event.model_dump(),
        event_time=event_time(event),
        headline=headline(event, include_project=True),
        summary=summary_text(event),
        current_reference=current_reference,
        current_detail_url=current_detail_url,
    )


def _seen_index(seen_file: Path | None = None) -> dict[str, tuple[str, str]]:
    """Map proposal key → (reference, detail_url) from last_seen.json.

    ``last_seen.json`` is loaded once and indexed by key; a missing file
    yields an empty map (no current resolution).
    """
    seen = load_seen(seen_file or store.SEEN_FILE)
    index: dict[str, tuple[str, str]] = {}
    for snapshots in seen.projects.values():
        for key, snapshot in snapshots.items():
            index[key] = (snapshot.reference, snapshot.detail_url)
    return index


def generate_events_api(
    api_dir: str | Path,
    events_file: Path | None = None,
    seen_file: Path | None = None,
) -> Path:
    """Write ``api_dir/events.json`` (newest-first, enriched).

    Resilient: a missing or empty log still produces a valid document with
    ``count: 0``. Returns the path written.
    """
    events = load_events(events_file or store.EVENTS_FILE)
    ordered = newest_first(events)
    current = _seen_index(seen_file)

    api_events = [enrich_event(event, current) for event in ordered]
    document = EventsDocument(
        version=1,
        generated_at=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        count=len(api_events),
        latest_seq=max((event.seq for event in ordered), default=0),
        events=api_events,
    )

    path = Path(api_dir) / "events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Compact JSON: unlike the per-project API files this document is
    # machine-consumed only (timeline fetch + agents), and indent=2 would
    # roughly double the size (~3.4 MB -> ~1.9 MB today).
    path.write_text(document.model_dump_json() + "\n", encoding="utf-8")
    logger.info("Wrote %d events to %s", len(api_events), path)
    return path
