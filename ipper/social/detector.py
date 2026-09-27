"""Change detection and the announced-state cache.

Detection model
---------------
* ``baselines`` records the last-seen state of every proposal. It is
  advanced at *detection* time so a transition can never be detected twice.
* ``pending`` holds events not yet acknowledged by every destination; it is
  the retry mechanism. Per-destination acks prevent duplicate posts when
  one destination succeeds and another fails.
"""

import json
import logging
import os
from pathlib import Path

from ipper.social.messages import ACCEPTED_STATES, REJECTED_STATE
from ipper.social.models import (
    BaselineRecord,
    DestinationStatus,
    EventPolicy,
    EventType,
    PendingEvent,
    ProposalEvent,
    ProposalSnapshot,
    SocialState,
)

logger = logging.getLogger(__name__)


def load_state(path: Path) -> SocialState | None:
    """Load the state file; None if absent. Reseed on unknown versions."""
    if not path.exists():
        return None
    state = SocialState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if state.version != 1:
        logger.warning("State file version %s unsupported; reseeding", state.version)
        return None
    return state


def save_state(state: SocialState, path: Path) -> None:
    """Atomically write the state file (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def seed_state(snapshots: list[ProposalSnapshot], now: str) -> SocialState:
    """Build a fresh baseline from current snapshots; posts nothing."""
    return SocialState(
        version=1,
        last_run=now,
        baselines={s.key: _baseline(s) for s in snapshots},
        pending=[],
    )


def _baseline(snapshot: ProposalSnapshot) -> BaselineRecord:
    """Baseline record from a snapshot."""
    return BaselineRecord(state=snapshot.state)


def classify_transition(old: str | None, new: str) -> EventType | None:
    """Map a state transition to an event type (None = no event).

    Rules: absent -> NEW; -> accepted/completed -> ACCEPTED (but a flip
    between the two "accepted" words is silent); -> not accepted -> REJECTED;
    everything else (reopens, unknown, in-progress wiggles) is silent — the
    baseline still updates.
    """
    if old is None:
        return EventType.NEW
    if old == new:
        return None
    if new in ACCEPTED_STATES:
        return None if old in ACCEPTED_STATES else EventType.ACCEPTED
    if new == REJECTED_STATE:
        return EventType.REJECTED
    return None


def detect(
    snapshots: list[ProposalSnapshot],
    state: SocialState,
    policy: EventPolicy,
    loaded_projects: set[str],
    destinations: list[str],
    now: str,
) -> SocialState:
    """Update baselines and the pending queue with newly detected events.

    Args:
        snapshots: current snapshots (all successfully loaded projects).
        loaded_projects: keys of projects whose caches loaded OK. Baseline
            entries of other projects are left untouched (their data is
            unavailable, not deleted).
        destinations: configured destination names for fresh ack records.
        now: ISO 8601 timestamp of this run.
    """
    current = {s.key: s for s in snapshots}

    # Drop baselines for proposals that genuinely disappeared from caches
    # that loaded successfully (deleted pages/PRs).
    for key in list(state.baselines):
        project = key.split(":", 1)[0]
        if project in loaded_projects and key not in current:
            logger.info("Proposal %s vanished from cache; removing baseline", key)
            del state.baselines[key]

    # Detect transitions and advance baselines.
    new_events: dict[str, ProposalEvent] = {}
    for key, snap in current.items():
        old = state.baselines.get(key)
        old_state = old.state if old is not None else None
        event_type = classify_transition(old_state, snap.state)
        if event_type is not None and event_type in policy.enabled_event_types:
            new_events[key] = ProposalEvent(
                event_type=event_type, snapshot=snap, observed_at=now
            )
        state.baselines[key] = _baseline(snap)

    # Merge with the existing pending queue. A new event for the same
    # proposal REPLACES the pending one (coalescing: one post per proposal
    # describing the latest state). Replaced events start with fresh acks.
    # Pending events whose proposal vanished are dropped (their links 404).
    pending_by_key = {
        p.event.snapshot.key: p
        for p in state.pending
        if p.event.snapshot.key in current
    }
    for key, event in new_events.items():
        pending_by_key[key] = PendingEvent(
            event=event,
            destinations={name: DestinationStatus() for name in destinations},
        )
    state.pending = list(pending_by_key.values())
    state.last_run = now
    return state


def sync_destinations(pending: PendingEvent, destinations: list[str]) -> None:
    """Align a pending event's ack map with the currently configured destinations."""
    for name in destinations:
        pending.destinations.setdefault(name, DestinationStatus())
    for name in list(pending.destinations):
        if name not in destinations:
            del pending.destinations[name]


def select_to_post(
    state: SocialState, policy: EventPolicy, destinations: list[str]
) -> list[PendingEvent]:
    """Pick up to max_posts pending events to announce this run.

    Retries (attempts > 0) go first, then new events by observed_at, so a
    backlog drains oldest-first. Overflow stays pending for the next run.
    """
    eligible = [
        p for p in state.pending if p.event.event_type in policy.enabled_event_types
    ]
    for pending in eligible:
        sync_destinations(pending, destinations)
    eligible.sort(
        key=lambda p: (
            0 if any(s.attempts > 0 for s in p.destinations.values()) else 1,
            p.event.observed_at,
        )
    )
    return eligible[: policy.max_posts]


def prune(
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
            logger.info("Event %s fully announced", pending.event.snapshot.key)
            continue
        failed = [s for s in statuses if not s.acked]
        if failed and all(s.attempts >= policy.max_attempts for s in failed):
            logger.error(
                "Dropping event %s after %s attempts per destination",
                pending.event.snapshot.key,
                policy.max_attempts,
            )
            continue
        kept.append(pending)
    state.pending = kept
    return state
