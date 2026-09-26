"""CLI for social announcements."""

import logging
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from ipper.social import posters  # noqa: F401 — registers built-in posters
from ipper.social.adapters import LOADERS
from ipper.social.config import SOCIAL_PROJECTS
from ipper.social.detector import (
    detect,
    load_state,
    prune,
    save_state,
    seed_state,
    select_to_post,
)
from ipper.social.messages import build_message
from ipper.social.models import (
    DestinationStatus,
    EventPolicy,
    EventType,
    ProposalEvent,
    ProposalSnapshot,
)
from ipper.social.posters.base import PosterNotConfigured, get_poster

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = "cache/social/announced_states.json"


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
        help="Rebuild the baseline from current snapshots; clear pending; post nothing",
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


def _demo(projects: list[str]) -> None:
    """Print sample NEW/ACCEPTED/REJECTED messages built from real snapshots."""
    by_state: dict[str, ProposalSnapshot] = {}
    for project in projects:
        try:
            for snap in LOADERS[project]():
                by_state.setdefault(snap.state, snap)
        except FileNotFoundError:
            continue
    if not by_state:
        print("No proposal caches found — run the data pipelines first.")
        return

    samples: list[ProposalEvent] = []
    for state_name, event_type in (
        ("under discussion", EventType.NEW),
        ("accepted", EventType.ACCEPTED),
        ("not accepted", EventType.REJECTED),
    ):
        snap = by_state.get(state_name)
        if snap is not None:
            samples.append(
                ProposalEvent(
                    event_type=event_type,
                    snapshot=snap,
                    observed_at=_now(),
                )
            )
    for event in samples:
        print(build_message(event))


def run_announce_cmd(args: Namespace) -> None:
    """Top-level announce command implementation."""
    destinations = [d.strip() for d in args.post_to.split(",") if d.strip()]
    projects = _resolve_projects(args.projects)
    policy = EventPolicy(
        enabled_event_types={EventType.NEW, EventType.ACCEPTED, EventType.REJECTED},
        max_posts=args.max_posts,
        max_attempts=args.max_attempts,
    )
    state_path = _path(args.state_file)

    if args.demo:
        _demo(projects)
        return

    # Load snapshots; a missing cache skips the project (never treated as mass deletion).
    snapshots: list[ProposalSnapshot] = []
    loaded: set[str] = set()
    for project in projects:
        try:
            snapshots.extend(LOADERS[project]())
            loaded.add(project)
        except FileNotFoundError as exc:
            logger.warning(
                "Cache for %s unavailable (%s); skipping project", project, exc
            )

    now = _now()
    state = load_state(state_path)

    if args.reseed:
        if args.dry_run:
            print(
                f"Would re-seed baseline with {len(snapshots)} proposals; "
                f"pending queue would be cleared."
            )
            return
        save_state(seed_state(snapshots, now), state_path)
        print(
            f"Re-seeded baseline with {len(snapshots)} proposals; pending queue cleared."
        )
        return

    if state is None:  # first run: seed
        if args.dry_run:
            print(
                f"Would seed baseline with {len(snapshots)} proposals (no announcements)."
            )
            return
        save_state(seed_state(snapshots, now), state_path)
        print(
            f"Seeded baseline with {len(snapshots)} proposals; no announcements this run."
        )
        return

    state = detect(snapshots, state, policy, loaded, destinations, now)

    chosen = select_to_post(state, policy, destinations)

    if args.dry_run:
        held = max(len(state.pending) - len(chosen), 0)
        print(
            f"Dry run: {len(chosen)} announcement(s) would be posted (+{held} held for later)."
        )
        for pending in chosen:
            print(build_message(pending.event))
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
            result = poster.post(pending.event)
            status.attempts += 1
            status.acked = result.ok
            status.post_id = result.post_id
            status.last_error = result.error
            if not result.ok:
                logger.error(
                    "Posting to %s failed for %s: %s",
                    poster.name,
                    pending.event.snapshot.key,
                    result.error,
                )

    state = prune(state, policy, destinations)
    save_state(state, state_path)
    posted = sum(1 for p in chosen for s in p.destinations.values() if s.acked)
    print(
        f"Announcements: {len(chosen)} event(s), {posted} successful post(s); "
        f"{len(state.pending)} pending."
    )
