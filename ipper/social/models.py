"""Pydantic models for the social announcement pipeline."""

from enum import StrEnum

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Announcement event types.

    v1 emits only NEW, ACCEPTED and REJECTED. The remaining types are
    modelled so they can be enabled via config later (see EventPolicy).
    """

    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    # Reserved for future use — disabled by default:
    VOTE_STARTED = "vote_started"
    FIRST_APPROVAL = "first_approval"
    CHANGES_REQUESTED = "changes_requested"


class ProposalSnapshot(BaseModel):
    """Normalised view of one proposal from a project cache."""

    key: str  # baseline key, e.g. "kafka:kip-123" or "strimzi:pr-245"
    project: str  # SOCIAL_PROJECTS key
    reference: str  # human-facing id, e.g. "KIP-123", "SIP-PR-245"
    title: str  # display title with the reference prefix stripped
    state: str  # IPState value string from the cache
    detail_url: str


class ProposalEvent(BaseModel):
    """A single detectable change to one proposal."""

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

    event: ProposalEvent
    destinations: dict[str, DestinationStatus] = Field(default_factory=dict)


class BaselineRecord(BaseModel):
    """Last-announced state of one proposal."""

    state: str


class SocialState(BaseModel):
    """Root of announced_states.json."""

    version: int = 1
    last_run: str | None = None
    baselines: dict[str, BaselineRecord] = Field(default_factory=dict)
    pending: list[PendingEvent] = Field(default_factory=list)


class EventPolicy(BaseModel):
    """What to announce and how much.

    Attributes:
        enabled_event_types: types that generate posts.
        max_posts: per-run cap; overflow stays pending for the next run.
        max_attempts: per-destination retry limit before dropping an event.
    """

    enabled_event_types: set[EventType] = Field(
        default_factory=lambda: {EventType.NEW, EventType.ACCEPTED, EventType.REJECTED}
    )
    max_posts: int = 5
    max_attempts: int = 5
