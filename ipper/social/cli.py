"""CLI for social announcements (v2: consumer of the proposal event log).

Detection lives in :mod:`ipper.events`; this module consumes
``cache/events/events.jsonl``. The state file
(``cache/social/announced_states.json``, v2) holds per-destination cursors
(acked-through seq) plus a pending queue of ``EventRecord``s awaiting
acknowledgement — the retry mechanism when one destination is down.
"""

import json
import logging
import os
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pydantic

from ipper.events import store as events_store
from ipper.events.consumer import max_seq
from ipper.events.models import EventRecord
from ipper.social import posters  # noqa: F401 — registers built-in posters
from ipper.social.config import SOCIAL_PROJECTS
from ipper.social.consumer import announcement_type, to_proposal_event
from ipper.social.messages import build_message
from ipper.social.models import (
    DestinationStatus,
    EventPolicy,
    PendingEvent,
    SocialState,
)
from ipper.social.posters.base import PosterNotConfigured, get_poster

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = "cache/social/announced_states.json"

STATE_VERSION = 2


def setup_social_parser(top_level_subparsers) -> None:
    """Register the `social` CLI tree."""
    parser = top_level_subparsers.add_parser(
        "social", help="Social media announcements"
    )
    sub = parser.add_subparsers(dest="social_command", required=True)

    announce = sub.add_parser("announce", help="Detect changes and post announcements")
    announce.add_argument(
        "--post-to",
        default="mastodon,bluesky",
        help="Comma-separated poster names (default mastodon,bluesky)",
    )
    announce.add_argument(
        "--projects",
        default="all",
        help="Comma-separated project keys or 'all'",
    )
    announce.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be posted; no credentials; never writes state",
    )
    announce.add_argument(
        "--demo",
        action="store_true",
        help="Print sample messages for each event type; ignores state",
    )
    announce.add_argument("--max-posts", type=int, default=5)
    announce.add_argument("--max-attempts", type=int, default=5)
    announce.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    announce.add_argument(
        "--reseed",
        action="store_true",
        help="Re-seed cursors to the event-log head; clear pending; post nothing",
    )
    announce.set_defaults(func=run_announce_cmd)


def _resolve_projects(value: str) -> list[str]:
    """Parse the --projects argument into project keys."""
    if value.strip().lower() == "all":
        return list(SOCIAL_PROJECTS)
    keys = [k.strip() for k in value.split(",") if k.strip()]
    unknown = [k for k in keys if k not in SOCIAL_PROJECTS]
    if unknown:
        raise SystemExit(
            f"Unknown projects: {unknown}; valid: {sorted(SOCIAL_PROJECTS)}"
        )
    return keys


def _now() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _path(value: str) -> Path:
    """State file path from a CLI string."""
    return Path(value)


def load_state(path: Path) -> SocialState | None:
    """Load the v2 state file; None if absent, unparseable or wrong version.

    Old v1 files are simply superseded (re-seeded); their baselines are
    meaningless once the event log exists. Never a hard error.
    """
    if not path.exists():
        return None
    try:
        state = SocialState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, pydantic.ValidationError) as ex:
        logger.warning("State file unreadable (%s); reseeding", ex)
        return None
    if state.version != STATE_VERSION:
        logger.info(
            "State file version %s superseded by v%d; reseeding",
            state.version,
            STATE_VERSION,
        )
        return None
    return state


def save_state(state: SocialState, path: Path) -> None:
    """Atomically write the state file (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def seed_state(head: int, destinations: list[str], now: str) -> SocialState:
    """Cursors at the log head; posts nothing."""
    return SocialState(
        version=STATE_VERSION,
        last_run=now,
        cursors=dict.fromkeys(destinations, head),
        pending=[],
    )


def _frontier(state: SocialState, destinations: list[str], head: int) -> int:
    """Least-advanced cursor; a destination missing from cursors starts at head."""
    return min((state.cursors.get(d, head) for d in destinations), default=head)


def _merge_candidates(
    state: SocialState,
    candidates: list[EventRecord],
    destinations: list[str],
) -> None:
    """Add candidates to pending; a candidate for an already-pending proposal
    REPLACES the pending one (fresh acks); a candidate already pending by
    stable_id is skipped (its ack/attempts state is preserved).
    """
    by_key = {p.event.key: p for p in state.pending}
    by_sid = {p.event.stable_id: p for p in state.pending}
    for event in sorted(candidates, key=lambda e: e.seq):
        if event.stable_id in by_sid:
            continue  # already pending — keep existing ack state
        # replacement drops the superseded pending event (and its sid)
        superseded = by_key.get(event.key)
        if superseded is not None:
            by_sid.pop(superseded.event.stable_id, None)
        pending = PendingEvent(
            event=event,
            destinations={name: DestinationStatus() for name in destinations},
        )
        by_key[event.key] = pending
        by_sid[event.stable_id] = pending
    state.pending = list(by_sid.values())


def _eligible(state: SocialState) -> list[PendingEvent]:
    """Pending events ordered retry-first, then ascending seq."""
    eligible = list(state.pending)
    eligible.sort(
        key=lambda p: (
            0 if any(s.attempts > 0 for s in p.destinations.values()) else 1,
            p.event.seq,
        )
    )
    return eligible


def _recompute_cursors(state: SocialState, destinations: list[str], head: int) -> None:
    """cursor[d] = min(unacked-by-d pending seq) - 1, else head.

    Called BEFORE pruning so pruned events do not hold cursors back.
    """
    for name in destinations:
        unacked = [
            p.event.seq
            for p in state.pending
            if name in p.destinations and not p.destinations[name].acked
        ]
        state.cursors[name] = (min(unacked) - 1) if unacked else head


def _prune(
    state: SocialState, policy: EventPolicy, destinations: list[str]
) -> SocialState:
    """Remove events that are fully acked or have exhausted retries."""
    kept: list[PendingEvent] = []
    for pending in state.pending:
        statuses = [pending.destinations.get(name) for name in destinations]
        statuses = [s for s in statuses if s is not None]
        if not statuses:
            kept.append(pending)  # nothing posted yet (overflow) — keep
            continue
        if all(s.acked for s in statuses):
            logger.info("Event %s fully announced", pending.event.key)
            continue
        failed = [s for s in statuses if not s.acked]
        if failed and all(s.attempts >= policy.max_attempts for s in failed):
            logger.error(
                "Dropping event %s after %s attempts per destination",
                pending.event.key,
                policy.max_attempts,
            )
            continue
        kept.append(pending)
    state.pending = kept
    return state


def _sync_destinations(pending: PendingEvent, destinations: list[str]) -> None:
    """Align a pending event's ack map with the currently configured destinations."""
    for name in destinations:
        pending.destinations.setdefault(name, DestinationStatus())
    for name in list(pending.destinations):
        if name not in destinations:
            del pending.destinations[name]


def _demo(projects: list[str]) -> None:
    """Print sample NEW/ACCEPTED/REJECTED messages built from the event log."""
    events = events_store.load_events(events_store.EVENTS_FILE)
    if not events:
        print("Event log is empty — run `events backfill`.")
        return
    latest: dict[str, EventRecord] = {}
    for event in events:
        if event.project not in projects:
            continue
        announcement = announcement_type(event)
        if announcement is not None:
            latest[announcement.value] = event
    samples = [latest.get(key) for key in ("new", "accepted", "rejected")]
    printed = 0
    for event in samples:
        if event is None:
            continue
        print(build_message(to_proposal_event(event)))
        printed += 1
    if not printed:
        print("No announceable events in the log.")


def run_announce_cmd(args: Namespace) -> None:
    """Top-level announce command implementation."""
    destinations = [d.strip() for d in args.post_to.split(",") if d.strip()]
    projects = _resolve_projects(args.projects)
    policy = EventPolicy(max_posts=args.max_posts, max_attempts=args.max_attempts)
    state_path = _path(args.state_file)

    if args.demo:
        _demo(projects)
        return

    events = events_store.load_events(events_store.EVENTS_FILE)
    head = max_seq(events)
    now = _now()
    state = load_state(state_path)

    if args.reseed:
        if args.dry_run:
            print(
                f"Would re-seed cursors to event-log head {head} for "
                f"{destinations}; pending queue would be cleared."
            )
            return
        save_state(seed_state(head, destinations, now), state_path)
        print(f"Re-seeded cursors to head {head}; pending queue cleared.")
        return

    if state is None:  # first run (or v1 file): seed, post nothing
        if args.dry_run:
            print(f"Would seed cursors to event-log head {head} (no announcements).")
            return
        save_state(seed_state(head, destinations, now), state_path)
        print(f"Seeded cursors to head {head}; no announcements this run.")
        return

    # Discover new candidates past the least-advanced cursor.
    frontier = _frontier(state, destinations, head)
    candidates = [
        e
        for e in events
        if e.seq > frontier
        and announcement_type(e) is not None
        and e.project in projects
    ]
    _merge_candidates(state, candidates, destinations)
    for pending in state.pending:
        _sync_destinations(pending, destinations)

    eligible = _eligible(state)
    chosen = eligible[: policy.max_posts]
    # overflow stays pending (not selected); cursors never advance past
    # unacked pending events, so overflow is re-discovered next run

    if args.dry_run:
        print(
            f"Dry run: {len(chosen)} announcement(s) would be posted "
            f"(+{len(eligible) - len(chosen)} held for later)."
        )
        for pending in chosen:
            print(build_message(to_proposal_event(pending.event)))
        return

    posters_list = []
    for name in destinations:
        try:
            posters_list.append(get_poster(name))
        except PosterNotConfigured as exc:
            raise SystemExit(f"Destination {name!r} not configured: {exc}") from exc

    for pending in chosen:
        for poster in posters_list:
            status = pending.destinations.setdefault(poster.name, DestinationStatus())
            if status.acked:
                continue  # re-post only to failed destinations
            result = poster.post(to_proposal_event(pending.event))
            status.attempts += 1
            status.acked = result.ok
            status.post_id = result.post_id
            status.last_error = result.error
            if not result.ok:
                logger.error(
                    "Posting to %s failed for %s: %s",
                    poster.name,
                    pending.event.key,
                    result.error,
                )

    _recompute_cursors(state, destinations, head)
    state = _prune(state, policy, destinations)
    state.last_run = now
    save_state(state, state_path)
    posted = sum(
        1
        for p in chosen
        for name in destinations
        if (s := p.destinations.get(name)) is not None and s.acked
    )
    print(
        f"Announcements: {len(chosen)} event(s), {posted} successful post(s); "
        f"{len(state.pending)} pending."
    )
