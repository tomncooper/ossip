"""Tests for ipper.events.models: schema contract and backward compatibility."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ipper.events.models import (
    SCHEMA_VERSION,
    EventCandidate,
    EventRecord,
    ReviewEntry,
    SeenSnapshot,
    SeenState,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_golden_fixture_loads_every_event_type():
    """The committed golden fixture (one record per event type) round-trips."""
    lines = (FIXTURES / "golden_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 7
    seen_types = set()
    for line in lines:
        record = EventRecord.model_validate(json.loads(line))
        assert record.schema_version == SCHEMA_VERSION
        seen_types.add(record.event_type)
    assert seen_types == {
        "new",
        "state_changed",
        "renumbered",
        "disappeared",
        "first_approval",
        "changes_requested",
        "vote_started",
    }


def test_golden_fixture_round_trips_through_dump_validate():
    for line in (
        (FIXTURES / "golden_events.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        original = json.loads(line)
        record = EventRecord.model_validate(original)
        assert record.model_dump() == original


def test_unknown_event_type_loads():
    """Future event types parse (event_type is a plain str)."""
    record = EventRecord.model_validate(
        {
            "seq": 8,
            "stable_id": "kafka:kip-1/future_kind@2026-10-01",
            "project": "kafka",
            "key": "kafka:kip-1",
            "event_type": "future_kind",
            "reference": "KIP-1",
            "title": "T",
            "observed_at": "2026-10-01T09:30:00+00:00",
            "detail_url": "https://ossip.dev/kips/KIP-1.html",
        }
    )
    assert record.event_type == "future_kind"


def test_unknown_extra_fields_load():
    record = EventRecord.model_validate(
        {
            "seq": 8,
            "stable_id": "kafka:kip-1/new@2026-10-01",
            "project": "kafka",
            "key": "kafka:kip-1",
            "event_type": "new",
            "reference": "KIP-1",
            "title": "T",
            "observed_at": "2026-10-01T09:30:00+00:00",
            "detail_url": "https://ossip.dev/kips/KIP-1.html",
            "some_future_field": {"nested": True},
        }
    )
    assert record.model_dump()["some_future_field"] == {"nested": True}


def test_future_schema_version_still_parses():
    """schema_version 99 is current-version-parseable (per-record additive)."""
    record = EventRecord.model_validate(
        {
            "schema_version": 99,
            "seq": 8,
            "stable_id": "kafka:kip-1/new@2026-10-01",
            "project": "kafka",
            "key": "kafka:kip-1",
            "event_type": "new",
            "reference": "KIP-1",
            "title": "T",
            "observed_at": "2026-10-01T09:30:00+00:00",
            "detail_url": "https://ossip.dev/kips/KIP-1.html",
        }
    )
    assert record.schema_version == 99


def test_event_record_requires_stable_id_and_seq():
    with pytest.raises(ValidationError):
        EventRecord.model_validate(
            {
                "project": "kafka",
                "key": "kafka:kip-1",
                "event_type": "new",
                "reference": "KIP-1",
                "title": "T",
                "observed_at": "2026-10-01T09:30:00+00:00",
                "detail_url": "https://x",
            }
        )


def test_event_candidate_omits_assigned_fields():
    candidate = EventCandidate(
        project="kafka",
        key="kafka:kip-1",
        event_type="new",
        reference="KIP-1",
        title="T",
        observed_at="2026-10-01T09:30:00+00:00",
        detail_url="https://x",
    )
    dumped = candidate.model_dump()
    assert "seq" not in dumped
    assert "stable_id" not in dumped
    assert "schema_version" not in dumped


def test_seen_snapshot_defaults_and_reviews():
    snap = SeenSnapshot(
        key="strimzi:pr-245",
        project="strimzi",
        reference="SIP-PR-245",
        title="T",
        state="under discussion",
        detail_url="https://x",
        reviews={
            "accepted": [{"name": "alice", "timestamp": "2026-09-20T10:00:00Z"}],
            "commented": [],
            "changes_requested": [],
        },
    )
    assert snap.reviews is not None
    entry = snap.reviews["accepted"][0]
    assert isinstance(entry, ReviewEntry)
    assert entry.name == "alice"


def test_seen_state_defaults():
    state = SeenState()
    assert state.version == 1
    assert state.projects == {}
    assert state.last_run is None
