"""Pure event detection: snapshots + previous baselines -> candidates.

No I/O. ``detect_events`` compares the current snapshots against the
``last_seen`` baselines and emits one candidate per detectable change;
consumers decide what they care about. The returned ``new_seen`` is the
complete baseline to store for the project (ALL current snapshots).
"""

import logging

from ipper.events.models import (
    EventCandidate,
    EventType,
    ReviewEntry,
    SeenSnapshot,
)

logger = logging.getLogger(__name__)

ACCEPTED_STATES = frozenset({"accepted", "completed"})
REJECTED_STATE = "not accepted"


def _earliest(entries: list[ReviewEntry]) -> str | None:
    """Earliest timestamp among review entries (None if empty)."""
    stamps = [e.timestamp for e in entries if e.timestamp]
    return min(stamps) if stamps else None


def _wiki_effective(
    snapshot: SeenSnapshot,
    field: str,
    source: str,
) -> tuple[str | None, str | None]:
    """Wiki effective-at: ``last_modified_on`` is an upper bound, never a promise."""
    value = getattr(snapshot, field, None)
    return (value, source) if value else (None, None)


def _new_effective(snapshot: SeenSnapshot) -> tuple[str | None, str | None]:
    """effective_at for a NEW event, per the mapping table."""
    if snapshot.project in ("kafka", "flink"):
        return _wiki_effective(snapshot, "created_on", "created_on")
    # GitHub: prefer the full-ISO created_at (stored in created_on by the adapter)
    if snapshot.created_on:
        if "T" in snapshot.created_on:
            return snapshot.created_on, "created_at"
        return snapshot.created_on, "created_on"
    return None, None


def _state_changed_effective(
    snapshot: SeenSnapshot, state_after: str
) -> tuple[str | None, str | None]:
    """effective_at for a STATE_CHANGED event, per the mapping table."""
    if snapshot.project in ("kafka", "flink"):
        return _wiki_effective(snapshot, "last_modified_on", "last_modified_on")
    if state_after in ACCEPTED_STATES:
        return (snapshot.merged_on, "merged_on") if snapshot.merged_on else (None, None)
    if state_after == REJECTED_STATE:
        if snapshot.closed_on:
            return snapshot.closed_on, "closed_on"
        if snapshot.last_activity:
            return snapshot.last_activity, "last_activity"
        return None, None
    # reopens / other wiggles
    if snapshot.last_activity:
        return snapshot.last_activity, "last_activity"
    return None, "observed_at"


def _candidate(
    project: str,
    snapshot: SeenSnapshot,
    event_type: EventType,
    now: str,
    *,
    state_before: str | None = None,
    state_after: str | None = None,
    effective_at: str | None = None,
    effective_at_source: str | None = None,
    reference_before: str | None = None,
) -> EventCandidate:
    """Build a candidate from a snapshot with the common fields filled in."""
    return EventCandidate(
        project=project,
        key=snapshot.key,
        event_type=event_type.value,
        reference=snapshot.reference,
        title=snapshot.title,
        state_before=state_before,
        state_after=state_after,
        observed_at=now,
        effective_at=effective_at,
        effective_at_source=effective_at_source,
        detail_url=snapshot.detail_url,
        reference_before=reference_before,
    )


def detect_events(
    project: str,
    snapshots: list[SeenSnapshot],
    seen: dict[str, SeenSnapshot],
    now: str,
) -> tuple[list[EventCandidate], dict[str, SeenSnapshot]]:
    """Diff snapshots against baselines; returns (candidates, new_seen).

    ``new_seen`` is the complete baseline to store for this project (ALL
    current snapshots) — silent changes (title-only edits, dismissed
    approvals) still advance it.
    """
    current = {s.key: s for s in snapshots}
    candidates: list[EventCandidate] = []

    # 1. Gone: keys in the prior baseline that vanished from the cache.
    #    Only compares against a non-empty prior baseline; a MISSING cache
    #    is handled in the store and never reaches here.
    if seen:
        for key, old in seen.items():
            if key not in current:
                candidates.append(
                    EventCandidate(
                        project=project,
                        key=key,
                        event_type=EventType.DISAPPEARED.value,
                        reference=old.reference,
                        title=old.title,
                        state_before=old.state,
                        state_after=None,
                        observed_at=now,
                        effective_at=None,
                        effective_at_source=None,
                        detail_url=old.detail_url,
                    )
                )

    for key, snap in current.items():
        old = seen.get(key)

        # 2. New: first sight. Day-one edge cases so early reviews/votes on
        #    already-open proposals are not missed.
        if old is None:
            eff, eff_src = _new_effective(snap)
            candidates.append(
                _candidate(
                    project,
                    snap,
                    EventType.NEW,
                    now,
                    state_after=snap.state,
                    effective_at=eff,
                    effective_at_source=eff_src,
                )
            )
            if snap.project not in ("kafka", "flink"):  # GitHub review edges
                for column, event_type in (
                    ("accepted", EventType.FIRST_APPROVAL),
                    ("changes_requested", EventType.CHANGES_REQUESTED),
                ):
                    entries = (snap.reviews or {}).get(column) or []
                    if entries:
                        candidates.append(
                            _candidate(
                                project,
                                snap,
                                event_type,
                                now,
                                state_after=snap.state,
                                effective_at=_earliest(entries),
                                effective_at_source="review_timestamp",
                            )
                        )
            if snap.project in ("kafka", "flink") and snap.vote_thread:
                candidates.append(
                    _candidate(
                        project,
                        snap,
                        EventType.VOTE_STARTED,
                        now,
                        state_after=snap.state,
                        effective_at=snap.last_modified_on,
                        effective_at_source=(
                            "last_modified_on" if snap.last_modified_on else None
                        ),
                    )
                )
            continue

        # 3. State change.
        if old.state != snap.state:
            eff, eff_src = _state_changed_effective(snap, snap.state)
            candidates.append(
                _candidate(
                    project,
                    snap,
                    EventType.STATE_CHANGED,
                    now,
                    state_before=old.state,
                    state_after=snap.state,
                    effective_at=eff,
                    effective_at_source=eff_src,
                )
            )

        # 4. Renumbered: reference changed AND the proposal gained its number
        #    (merge). Co-occurs with state_changed -> accepted; emit both.
        if (
            snap.reference != old.reference
            and old.proposal_id is None
            and snap.proposal_id is not None
        ):
            eff = snap.merged_on or now
            candidates.append(
                _candidate(
                    project,
                    snap,
                    EventType.RENUMBERED,
                    now,
                    state_after=snap.state,
                    reference_before=old.reference,
                    effective_at=eff,
                    effective_at_source=(
                        "merged_on" if snap.merged_on else "observed_at"
                    ),
                )
            )

        # 5. Review edges (GitHub): empty column -> non-empty. Additions to a
        #    non-empty column and dismissals (n->0) are silent.
        if snap.project not in ("kafka", "flink"):
            old_reviews = old.reviews or {}
            new_reviews = snap.reviews or {}
            for column, event_type in (
                ("accepted", EventType.FIRST_APPROVAL),
                ("changes_requested", EventType.CHANGES_REQUESTED),
            ):
                if not (old_reviews.get(column) or []) and (
                    new_reviews.get(column) or []
                ):
                    entries = new_reviews[column]
                    candidates.append(
                        _candidate(
                            project,
                            snap,
                            event_type,
                            now,
                            state_after=snap.state,
                            effective_at=_earliest(entries),
                            effective_at_source="review_timestamp",
                        )
                    )

        # 6. Vote started (wiki): vote_thread empty/None -> set.
        if (
            snap.project in ("kafka", "flink")
            and not old.vote_thread
            and snap.vote_thread
        ):
            candidates.append(
                _candidate(
                    project,
                    snap,
                    EventType.VOTE_STARTED,
                    now,
                    state_after=snap.state,
                    effective_at=snap.last_modified_on,
                    effective_at_source=(
                        "last_modified_on" if snap.last_modified_on else None
                    ),
                )
            )

        # 7. Everything else (title-only changes, URL changes) is silent.

    return candidates, current
