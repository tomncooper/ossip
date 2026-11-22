"""CLI for the proposal event log: tail / backfill / stats."""

import json
import logging
from argparse import Namespace
from collections import Counter
from pathlib import Path

from ipper.events.backfill import backfill
from ipper.events.models import EventRecord
from ipper.events.presentation import event_time
from ipper.events.store import load_events, load_seen

logger = logging.getLogger(__name__)


def _events_file() -> Path:
    """Log path resolved at call time (module global, monkeypatch-friendly)."""
    from ipper.events import store

    return store.EVENTS_FILE


def _seen_file() -> Path:
    from ipper.events import store

    return store.SEEN_FILE


def setup_events_parser(top_level_subparsers) -> None:
    """Register the `events` CLI tree."""
    parser = top_level_subparsers.add_parser(
        "events", help="Proposal event log (append-only)"
    )
    sub = parser.add_subparsers(dest="events_command", required=True)

    tail = sub.add_parser("tail", help="Print the last N events")
    tail.add_argument("--project", default=None, help="Filter by project key")
    tail.add_argument(
        "--type", default=None, help="Filter by event type (e.g. new, state_changed)"
    )
    tail.add_argument(
        "--limit", type=int, default=20, help="Number of events (default 20)"
    )
    tail.set_defaults(func=run_tail_cmd)

    fill = sub.add_parser("backfill", help="One-time historical synthesis from caches")
    fill.set_defaults(func=run_backfill_cmd)

    stats = sub.add_parser("stats", help="Log statistics")
    stats.set_defaults(func=run_stats_cmd)

    output = sub.add_parser(
        "output", help="Write the public events JSON API (api_dir/events.json)"
    )
    output.add_argument(
        "--api-dir",
        required=True,
        help="Output directory (e.g. site_files/api/v1/events)",
    )
    output.add_argument(
        "--events-file",
        default=None,
        help="Event log path (default: cache/events/events.jsonl)",
    )
    output.add_argument(
        "--seen-file",
        default=None,
        help="last_seen.json path (default: cache/events/last_seen.json)",
    )
    output.set_defaults(func=run_output_cmd)


def _matches(event: EventRecord, project: str | None, event_type: str | None) -> bool:
    if project and event.project != project:
        return False
    return not event_type or event.event_type == event_type


def run_tail_cmd(args: Namespace) -> None:
    """Print the last N events, newest last, human-readable."""
    events = load_events(_events_file())
    selected = [e for e in events if _matches(e, args.project, args.type)]
    tail = selected[-args.limit :] if args.limit > 0 else []
    for event in tail:
        transition = f"{event.state_before or '-'}→{event.state_after or '-'}"
        print(
            f"{event.seq:>6}  {event.stable_id:<50}  {event.observed_at}  "
            f"{event_time(event):<25}  {transition:<35}  {event.title}"
        )
    if not selected:
        print("No matching events. Run `events backfill` to initialise the event log.")


def run_backfill_cmd(args: Namespace) -> None:
    """Run the one-time backfill against cache/."""
    try:
        appended = backfill(Path("cache"))
    except RuntimeError as ex:
        print(f"Backfill refused: {ex}")
        raise SystemExit(1) from ex
    print(f"Backfilled {len(appended)} event(s).")
    by_project = Counter(e.project for e in appended)
    by_type = Counter(e.event_type for e in appended)
    for project, count in by_project.items():
        print(f"  {project}: {count}")
    for event_type, count in sorted(by_type.items()):
        print(f"  {event_type}: {count}")


def run_output_cmd(args: Namespace) -> None:
    """Write the public events JSON document and print a summary."""
    from ipper.events.output import generate_events_api

    path = generate_events_api(
        args.api_dir,
        events_file=Path(args.events_file) if args.events_file else None,
        seen_file=Path(args.seen_file) if args.seen_file else None,
    )
    count = json.loads(path.read_text(encoding="utf-8"))["count"]
    print(f"Wrote {count} events to {path}")


def run_stats_cmd(args: Namespace) -> None:
    """Print totals, head seq, per-project/type counts and last_seen summary."""
    if not _events_file().exists():
        print("Event log not found (cache/events/events.jsonl).")
        print("Run `events backfill` to initialise the event log.")
        return
    events = load_events(_events_file())
    print(f"Total events: {len(events)}")
    print(f"Head seq: {max((e.seq for e in events), default=0)}")
    print("By project:")
    for project, count in sorted(Counter(e.project for e in events).items()):
        print(f"  {project}: {count}")
    print("By event type:")
    for event_type, count in sorted(Counter(e.event_type for e in events).items()):
        print(f"  {event_type}: {count}")
    if _seen_file().exists():
        seen = load_seen(_seen_file())
        print(f"last_seen version: {seen.version}, last_run: {seen.last_run}")
        for project in sorted(seen.projects):
            print(f"  {project}: {len(seen.projects[project])} baselined proposal(s)")
    else:
        print("last_seen: absent")
