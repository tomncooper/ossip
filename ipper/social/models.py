"""Pydantic models for the social announcement pipeline (v2 state).

Since the event log exists, social no longer stores detection baselines:
it is a consumer of ``cache/events/events.jsonl``. Its state file holds
per-destination cursors (acked-through seq) plus a pending queue of
``EventRecord``s awaiting acknowledgement.

``ProposalSnapshot``/``ProposalEvent`` are render-time mapping targets used
by ``messages.build_message``; they are no longer stored state.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from ipper.events.models import EventRecord


class EventType(StrEnum):
    """Announcement vocabulary (mapping targets for event-log records)."""

    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ProposalSnapshot(BaseModel):
    """Normalised view of one proposal, built from an EventRecord for rendering."""

    key: str  # event key, e.g. "kafka:kip-123" or "strimzi:pr-245"
    project: str  # SOCIAL_PROJECTS key
    reference: str  # human-facing id, e.g. "KIP-123", "SIP-PR-245"
    title: str  # display title with the reference prefix stripped
    state: str  # proposal state string from the cache
    detail_url: str


class ProposalEvent(BaseModel):
    """A single announcement, built from an EventRecord for rendering."""

    event_type: EventType
    snapshot: ProposalSnapshot
    observed_at: str  # ISO 8601 UTC timestamp


class DestinationStatus(BaseModel):
    """Per-destination acknowledgement state for one pending event."""

    acked: bool = False
    attempts: int = 0
    post_id: str | None = None
    last_error: str | None = None


class PendingEvent(BaseModel):
    """An event awaiting successful posting to all destinations."""

    event: EventRecord
    destinations: dict[str, DestinationStatus] = Field(default_factory=dict)


class SocialState(BaseModel):
    """Root of announced_states.json (v2)."""

    version: int = 2
    last_run: str | None = None
    cursors: dict[str, int] = Field(default_factory=dict)  # dest -> acked_through_seq
    pending: list[PendingEvent] = Field(default_factory=list)


class EventPolicy(BaseModel):
    """What to announce and how much.

    Attributes:
        enabled_event_types: announcement types that generate posts.
        max_posts: per-run cap; overflow stays pending for the next run.
        max_attempts: per-destination retry limit before dropping an event.
    """

    enabled_event_types: set[EventType] = Field(
        default_factory=lambda: {EventType.NEW, EventType.ACCEPTED, EventType.REJECTED}
    )
    max_posts: int = 5
    max_attempts: int = 5
