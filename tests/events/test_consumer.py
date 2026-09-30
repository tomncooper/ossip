"""Tests for ipper.events.consumer and presentation display helpers."""

import json
from pathlib import Path

import pytest

from ipper.events import consumer, presentation
from ipper.events.consumer import (
    events_after_seq,
    filter_events,
    latest_snapshot,
    max_seq,
    newest_first,
)
from ipper.events.models import EventRecord, SeenSnapshot, SeenState
from ipper.events.presentation import headline, summary_text
from ipper.events.store import save_seen

NOW = "2026-10-01T09:30:00+00:00"


def record(seq: int, **kwargs) -> EventRecord:
    defaults = {
        "seq": seq,
        "stable_id": f"kafka:kip-{seq}/new@2026-10-01",
        "project": "kafka",
        "key": f"kafka:kip-{seq}",
        "event_type": "new",
        "reference": f"KIP-{seq}",
        "title": f"T{seq}",
        "observed_at": NOW,
        "effective_at": f"2026-09-{seq:02d}T00:00:00+00:00",
        "detail_url": f"https://ossip.dev/kips/KIP-{seq}.html",
        "state_after": "under discussion",
    }
    defaults.update(kwargs)
    return EventRecord(**defaults)


@pytest.fixture
def events() -> list[EventRecord]:
    return [
        record(1),
        record(
            2,
            project="flink",
            key="flink:flip-1",
            reference="FLIP-1",
            stable_id="flink:flip-1/new@2026-10-01",
        ),
        record(
            3,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        ),
        record(4, backfilled=True, effective_at="2026-09-01T00:00:00+00:00"),
        record(
            5,
            event_type="renumbered",
            reference="SIP-46",
            reference_before="SIP-PR-245",
        ),
    ]


class TestMaxSeq:
    def test_empty(self):
        assert max_seq([]) == 0

    def test_head(self, events):
        assert max_seq(events) == 5


class TestFilterEvents:
    def test_by_project(self, events):
        assert [e.seq for e in filter_events(events, project="kafka")] == [1, 3, 4, 5]

    def test_by_types(self, events):
        assert [e.seq for e in filter_events(events, types={"new"})] == [1, 2, 4]

    def test_unknown_types_pass_through_without_filter(self, events):
        # unknown event types survive filtering when types not specified
        extra = record(
            6, event_type="future_kind", stable_id="kafka:kip-6/future_kind@2026-10-01"
        )
        assert [e.seq for e in filter_events(events + [extra])] == [1, 2, 3, 4, 5, 6]
        assert filter_events(events + [extra], types={"new"})[0].seq == 1

    def test_since_until_bounds_on_event_time(self, events):
        assert [e.seq for e in filter_events(events, since="2026-09-03")] == [3, 5]
        assert [e.seq for e in filter_events(events, until="2026-09-02")] == [1, 2, 4]
        assert [
            e.seq for e in filter_events(events, since="2026-09-02", until="2026-09-03")
        ] == [2, 3]

    def test_include_backfilled_flag(self, events):
        assert [e.seq for e in filter_events(events, include_backfilled=False)] == [
            1,
            2,
            3,
            5,
        ]


class TestNewestFirst:
    def test_sorts_by_event_time_desc(self, events):
        assert [e.seq for e in newest_first(events)] == [5, 3, 2, 4, 1]

    def test_limit(self, events):
        assert [e.seq for e in newest_first(events, limit=2)] == [5, 3]

    def test_stable_on_equal_times(self):
        same_time = [
            record(1, effective_at="2026-09-01T00:00:00+00:00"),
            record(2, effective_at="2026-09-01T00:00:00+00:00"),
        ]
        assert [e.seq for e in newest_first(same_time)] == [2, 1]


class TestEventsAfterSeq:
    def test_strictly_after(self, events):
        assert [e.seq for e in events_after_seq(events, 3)] == [4, 5]


class TestLatestSnapshot:
    @pytest.fixture
    def seen_file(self, tmp_path: Path):
        seen = SeenState()
        seen.projects["strimzi"] = {
            "strimzi:pr-245": SeenSnapshot(
                key="strimzi:pr-245",
                project="strimzi",
                reference="SIP-46",
                title="T",
                state="accepted",
                detail_url="https://ossip.dev/sips/SIP-46.html",
            )
        }
        seen.projects["kafka"] = {}
        path = tmp_path / "last_seen.json"
        save_seen(seen, path)
        return path

    def test_resolves_current_reference(self, seen_file):
        snap = latest_snapshot("strimzi:pr-245", seen_file)
        assert snap is not None
        assert snap.reference == "SIP-46"

    def test_unknown_key_none(self, seen_file):
        assert latest_snapshot("kafka:kip-999", seen_file) is None


class TestReadEventsAlias:
    def test_alias(self, tmp_path, monkeypatch):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text(
            json.dumps(record(1).model_dump()) + "\n", encoding="utf-8"
        )
        assert [e.seq for e in consumer.load_events(events_file)] == [1]


class TestPresentation:
    def test_headline_state_changed(self):
        event = record(
            3,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        assert headline(event) == "KIP-3 accepted — T3"

    def test_headline_completed_shown_as_accepted(self):
        event = record(3, event_type="state_changed", state_after="completed")
        assert headline(event) == "KIP-3 accepted — T3"

    def test_headline_with_project(self):
        assert headline(record(1), include_project=True) == "Kafka KIP-1 new — T1"

    def test_headline_renumbered(self):
        event = record(5, event_type="renumbered", reference="SIP-46")
        assert headline(event) == "SIP-46 renumbered — T5"

    def test_summary_texts(self):
        new = record(1)
        assert summary_text(new) == "New proposal, currently under discussion."
        changed = record(
            3,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
        )
        assert "from under discussion to accepted" in summary_text(changed)
        renum = record(
            5,
            event_type="renumbered",
            reference="SIP-46",
            reference_before="SIP-PR-245",
        )
        assert "SIP-PR-245" in summary_text(renum)
        gone = record(
            9, event_type="disappeared", stable_id="kafka:kip-9/disappeared@2026-10-01"
        )
        assert summary_text(gone) == "Removed from the upstream tracker."
        unknown = record(
            10,
            event_type="future_kind",
            stable_id="kafka:kip-10/future_kind@2026-10-01",
        )
        assert "future_kind" in summary_text(unknown)

    def test_event_time_prefers_effective(self):
        assert presentation.event_time(record(1)) == "2026-09-01T00:00:00+00:00"
        no_eff = record(2, effective_at=None)
        assert presentation.event_time(no_eff) == NOW


def test_package_exports_consumer_api():
    """The package __init__ exposes the full consumer API (lazily)."""
    import ipper.events

    for name in (
        "load_events",
        "read_events",
        "filter_events",
        "newest_first",
        "max_seq",
        "events_after_seq",
        "latest_snapshot",
        "headline",
        "summary_text",
        "update_from_cache",
        "EventRecord",
        "EventType",
    ):
        assert hasattr(ipper.events, name), name


def test_docstring_feed_example(tmp_path, monkeypatch):
    """The documented feed integration example actually runs."""
    import ipper.events

    events_file = tmp_path / "events.jsonl"
    lines = "\n".join(json.dumps(e.model_dump()) for e in (record(1), record(3)))
    events_file.write_text(lines + "\n", encoding="utf-8")
    events = ipper.events.newest_first(
        ipper.events.filter_events(
            ipper.events.load_events(events_file), types={"new", "state_changed"}
        ),
        limit=50,
    )
    assert len(events) == 2
