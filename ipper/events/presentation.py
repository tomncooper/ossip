"""Presentation helpers: stable ids, event timing and display wording.

``stable_id`` is computed once at append time and stored on the record;
consumers must never recompute it. It is safe to embed in ``tag:`` URIs.

``headline``/``summary_text`` are shared with the social pipeline so site
and posts never diverge in wording.
"""

from ipper.events.models import EventCandidate, EventRecord

# Canonical display word per state (mirrors social/messages.STATE_DISPLAY).
_STATE_DISPLAY = {
    "completed": "accepted",  # FLIPs say "completed"
}

_EVENT_PHRASES = {
    "new": "new",
    "renumbered": "renumbered",
    "disappeared": "removed",
    "first_approval": "first approval",
    "changes_requested": "changes requested",
    "vote_started": "vote started",
}


def display_state(state: str) -> str:
    """Canonical display word for a proposal state string."""
    return _STATE_DISPLAY.get(state, state)


def stable_id(candidate: EventCandidate, date: str, existing_ids: set[str]) -> str:
    """Build a stable id for a candidate; first free numeric suffix on collision.

    Base format: ``{key}/{event_type}@{YYYY-MM-DD}``. Collisions (same
    proposal, same event type, same day, different content) get ``-2``,
    ``-3``, ... appended.
    """
    base = f"{candidate.key}/{candidate.event_type}@{date}"
    if base not in existing_ids:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing_ids:
        suffix += 1
    return f"{base}-{suffix}"


def event_time(event: EventRecord) -> str:
    """The event's best-known change time: effective_at, else observed_at."""
    return event.effective_at or event.observed_at


def headline(event: EventRecord, include_project: bool = False) -> str:
    """One-line headline, e.g. "SIP-46 accepted — <title>".

    With ``include_project`` the project name prefixes the reference:
    "Kafka KIP-123 new — <title>".
    """
    from ipper.common.projects import SOCIAL_PROJECTS

    if event.event_type == "state_changed":
        phrase = display_state(event.state_after or "unknown")
    else:
        phrase = _EVENT_PHRASES.get(event.event_type, event.event_type)
    prefix = f"{SOCIAL_PROJECTS[event.project].name} " if include_project else ""
    return f"{prefix}{event.reference} {phrase} — {event.title}"


def summary_text(event: EventRecord) -> str:
    """One-sentence, state-focused description of the event."""
    if event.event_type == "new":
        return (
            f"New proposal, currently {display_state(event.state_after or 'unknown')}."
        )
    if event.event_type == "state_changed":
        before = display_state(event.state_before) if event.state_before else "unknown"
        after = display_state(event.state_after) if event.state_after else "unknown"
        return f"State changed from {before} to {after}."
    if event.event_type == "renumbered":
        return (
            f"Renumbered from {event.reference_before or '?'} to "
            f"{event.reference} on merge."
        )
    if event.event_type == "disappeared":
        return "Removed from the upstream tracker."
    if event.event_type == "first_approval":
        return "Received its first approval."
    if event.event_type == "changes_requested":
        return "Changes were requested."
    if event.event_type == "vote_started":
        return "A vote has started."
    return f"Event of type {event.event_type}."  # future types
