"""Direct unit tests for the social consumer mapping (event log -> announcements).

The ``announce`` CLI integration tests exercise this transitively; these pin the
decision table (which events become posts, and which are silent) on its own.
"""

import pytest

from ipper.events.models import EventRecord
from ipper.social.consumer import announcement_type, to_proposal_event
from ipper.social.models import EventType

NOW = "2026-10-01T09:30:00+00:00"


def record(event_type: str, **kwargs) -> EventRecord:
    defaults = {
        "seq": 1,
        "stable_id": f"kafka:kip-1/{event_type}@2026-10-01",
        "project": "kafka",
        "key": "kafka:kip-1",
        "event_type": event_type,
        "reference": "KIP-1",
        "title": "Exactly-once semantics",
        "observed_at": NOW,
        "detail_url": "https://ossip.dev/kips/KIP-1.html",
    }
    defaults.update(kwargs)
    return EventRecord(**defaults)


class TestAnnouncementType:
    def test_new_maps_to_new(self):
        assert announcement_type(record("new", state_after="under discussion")) is (
            EventType.NEW
        )

    @pytest.mark.parametrize("state_after", ["accepted", "completed"])
    def test_state_changed_into_accepted_maps_to_accepted(self, state_after):
        event = record(
            "state_changed", state_before="under discussion", state_after=state_after
        )
        assert announcement_type(event) is EventType.ACCEPTED

    @pytest.mark.parametrize(
        ("state_before", "state_after"),
        [("accepted", "completed"), ("completed", "accepted")],
    )
    def test_accepted_completed_flip_is_silent(self, state_before, state_after):
        event = record(
            "state_changed", state_before=state_before, state_after=state_after
        )
        assert announcement_type(event) is None

    def test_state_changed_into_not_accepted_maps_to_rejected(self):
        event = record(
            "state_changed", state_before="under discussion", state_after="not accepted"
        )
        assert announcement_type(event) is EventType.REJECTED

    def test_reopen_is_silent(self):
        event = record(
            "state_changed", state_before="not accepted", state_after="under discussion"
        )
        assert announcement_type(event) is None

    @pytest.mark.parametrize(
        "event_type",
        [
            "renumbered",
            "first_approval",
            "changes_requested",
            "vote_started",
            "disappeared",
        ],
    )
    def test_non_announceable_types_are_silent(self, event_type):
        event = record(event_type, state_after="under discussion")
        assert announcement_type(event) is None


class TestToProposalEvent:
    def test_copies_snapshot_fields(self):
        event = record(
            "state_changed", state_before="under discussion", state_after="accepted"
        )
        proposal_event = to_proposal_event(event)
        assert proposal_event.event_type is EventType.ACCEPTED
        assert proposal_event.observed_at == NOW
        snap = proposal_event.snapshot
        assert snap.key == "kafka:kip-1"
        assert snap.project == "kafka"
        assert snap.reference == "KIP-1"
        assert snap.title == "Exactly-once semantics"
        assert snap.detail_url == "https://ossip.dev/kips/KIP-1.html"
        assert snap.state == "accepted"  # state_after preferred

    def test_state_falls_back_to_state_before(self):
        # A NEW event has no state_before; use a crafted record whose state_after
        # is None to prove the fallback chain (state_after or state_before or "").
        event = record("new", state_before="under discussion", state_after=None)
        assert to_proposal_event(event).snapshot.state == "under discussion"

    def test_non_announceable_event_trips_guard(self):
        with pytest.raises(AssertionError):
            to_proposal_event(record("disappeared", state_before="accepted"))
