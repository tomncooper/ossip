"""Data contracts for the proposal event log.

The pydantic models here are the source of truth for the log schema.
``EventRecord`` tolerates unknown extra fields (``extra="allow"``) and keeps
``event_type`` as a plain ``str`` so old checkouts can read a log written by
a newer build; producers always write :class:`EventType` values.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = 1  # per-record version stamped on every event line
LAST_SEEN_VERSION = 1  # document-level version in last_seen.json


class EventType(StrEnum):
    """Event types written to the log (producer vocabulary)."""

    NEW = "new"
    STATE_CHANGED = "state_changed"
    RENUMBERED = "renumbered"
    DISAPPEARED = "disappeared"
    FIRST_APPROVAL = "first_approval"
    CHANGES_REQUESTED = "changes_requested"
    VOTE_STARTED = "vote_started"


class ReviewEntry(BaseModel):
    """One review/comment entry copied verbatim from a GitHub cache."""

    model_config = ConfigDict(extra="allow")

    name: str
    timestamp: str


class EventRecord(BaseModel):
    """One line of the append-only event log."""

    model_config = ConfigDict(extra="allow")  # tolerate unknown future fields

    schema_version: int = SCHEMA_VERSION
    seq: int  # strictly increasing, never reused
    stable_id: str  # computed+stored at append time
    project: str  # "kafka", "strimzi", ...
    key: str  # "kafka:kip-123", "strimzi:pr-245"
    event_type: str  # EventType VALUE; plain str by design
    reference: str  # display ref at event time, "SIP-PR-245"
    title: str  # display title at event time, prefix stripped
    state_before: str | None = None  # None for new/backfilled-unknown
    state_after: str | None = None  # None ONLY for disappeared
    observed_at: str  # ISO 8601 UTC, detection run time
    effective_at: str | None = None  # best-known actual change time
    effective_at_source: str | None = None  # where effective_at came from
    detail_url: str  # proposal page URL at event time
    reference_before: str | None = None  # set for renumbered
    backfilled: bool = False


class EventCandidate(BaseModel):
    """An event before seq/stable_id/schema_version are assigned at append time."""

    model_config = ConfigDict(extra="allow")

    project: str
    key: str
    event_type: str
    reference: str
    title: str
    state_before: str | None = None
    state_after: str | None = None
    observed_at: str
    effective_at: str | None = None
    effective_at_source: str | None = None
    detail_url: str
    reference_before: str | None = None
    backfilled: bool = False


class SeenSnapshot(BaseModel):
    """One proposal as extracted from a project cache.

    Also the unit stored in ``last_seen.json`` (the 'before' side of the
    diff). Unknown extra fields are tolerated so adapters can attach
    additional data without a schema bump.
    """

    model_config = ConfigDict(extra="allow")

    key: str
    project: str
    reference: str
    title: str
    state: str
    detail_url: str
    created_on: str | None = None  # full ISO when the cache has it
    last_modified_on: str | None = None
    merged_on: str | None = None  # GitHub merged records
    closed_on: str | None = None  # GitHub closed records
    last_activity: str | None = None  # GitHub
    proposal_id: int | None = None  # GitHub numbered proposals (SIP-46)
    pr_number: int | None = None  # GitHub
    vote_thread: str | None = None  # wiki projects
    reviews: dict[str, list[ReviewEntry]] | None = None  # GitHub


class SeenState(BaseModel):
    """Root of last_seen.json (detection baselines)."""

    version: int = LAST_SEEN_VERSION
    last_run: str | None = None
    projects: dict[str, dict[str, SeenSnapshot]] = {}  # noqa: RUF012
