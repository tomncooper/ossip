"""Consumer-side mapping: event-log records -> announcement types/models.

``announcement_type`` is the successor of ``detector.classify_transition``:
silent rules moved from "not logged" to "logged but not announced".
"""

from ipper.events.models import EventRecord
from ipper.social.messages import ACCEPTED_STATES, REJECTED_STATE
from ipper.social.models import EventType, ProposalEvent, ProposalSnapshot

AnnouncementType = EventType


def announcement_type(event: EventRecord) -> AnnouncementType | None:
    """Granular event -> announcement type (None = not announced).

    Rules: new -> NEW; state_changed -> ACCEPTED when entering
    accepted/completed from outside those states, REJECTED when entering
    "not accepted"; accepted<->completed flips and all other
    wiggles/reopens -> None. renumbered, first_approval, changes_requested,
    vote_started and disappeared are logged but never announced.
    """
    if event.event_type == "new":
        return EventType.NEW
    if event.event_type == "state_changed":
        if (
            event.state_after in ACCEPTED_STATES
            and event.state_before not in ACCEPTED_STATES
        ):
            return EventType.ACCEPTED
        if event.state_after == REJECTED_STATE:
            return EventType.REJECTED
        return None
    return None


def to_proposal_event(event: EventRecord) -> ProposalEvent:
    """Render-time mapping of an EventRecord to the models build_message uses."""
    announcement = announcement_type(event)
    assert announcement is not None, "only announceable events map to ProposalEvent"
    snapshot = ProposalSnapshot(
        key=event.key,
        project=event.project,
        reference=event.reference,
        title=event.title,
        state=event.state_after or event.state_before or "",
        detail_url=event.detail_url,
    )
    return ProposalEvent(
        event_type=announcement,
        snapshot=snapshot,
        observed_at=event.observed_at,
    )
