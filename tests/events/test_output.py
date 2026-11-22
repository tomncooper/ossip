"""Tests for the public events JSON API emitter (ipper.events.output)."""

import json
import re
from pathlib import Path

import pytest

import ipper.events.store as store
from ipper.events.models import (
    ApiEvent,
    EventRecord,
    EventsDocument,
    SeenSnapshot,
    SeenState,
)
from ipper.events.output import enrich_event, generate_events_api
from ipper.events.presentation import headline, summary_text
from ipper.events.store import save_seen

NOW = "2026-10-01T09:30:00+00:00"

GENERATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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
        "effective_at": f"2026-09-{(seq % 28) + 1:02d}T00:00:00+00:00",
        "detail_url": f"https://ossip.dev/kips/KIP-{seq}.html",
        "state_after": "under discussion",
    }
    defaults.update(kwargs)
    return EventRecord(**defaults)


def write_log(path: Path, events: list[EventRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event.model_dump()) + "\n")


@pytest.fixture
def events() -> list[EventRecord]:
    return [
        record(1),
        record(2, effective_at=None),
        record(3, backfilled=True),
        record(
            4,
            event_type="state_changed",
            state_before="under discussion",
            state_after="accepted",
            effective_at=None,
        ),
        record(
            5,
            event_type="renumbered",
            reference="SIP-46",
            reference_before="SIP-PR-245",
            project="strimzi",
            key="strimzi:pr-245",
            effective_at=None,
        ),
    ]


@pytest.fixture
def log_file(tmp_path: Path, events: list[EventRecord]) -> Path:
    path = tmp_path / "events.jsonl"
    write_log(path, events)
    return path


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the store module's default paths at empty tmp locations."""
    monkeypatch.setattr(store, "EVENTS_FILE", tmp_path / "none" / "events.jsonl")
    monkeypatch.setattr(store, "SEEN_FILE", tmp_path / "none" / "last_seen.json")


@pytest.fixture
def seen_file(tmp_path: Path) -> Path:
    state = SeenState()
    state.projects["strimzi"] = {
        "strimzi:pr-245": SeenSnapshot(
            key="strimzi:pr-245",
            project="strimzi",
            reference="SIP-46",
            title="Renumbered proposal",
            state="accepted",
            detail_url="https://ossip.dev/sips/SIP-46.html",
        )
    }
    path = tmp_path / "last_seen.json"
    save_seen(state, path)
    return path


class TestEnrichEvent:
    def test_display_fields(self, events):
        api_event = enrich_event(events[0], {})
        assert api_event.event_time == events[0].effective_at
        assert api_event.headline == headline(events[0], include_project=True)
        assert api_event.summary == summary_text(events[0])

    def test_event_time_prefers_effective_at(self, events):
        assert enrich_event(events[0], {}).event_time == "2026-09-02T00:00:00+00:00"

    def test_event_time_falls_back_to_observed_at(self, events):
        assert enrich_event(events[1], {}).event_time == NOW

    def test_current_fields_resolved(
        self, tmp_path: Path, log_file: Path, seen_file: Path
    ):
        generate_events_api(tmp_path / "out", events_file=log_file, seen_file=seen_file)
        document = EventsDocument.model_validate(
            json.loads((tmp_path / "out" / "events.json").read_text())
        )
        renumbered = {event.seq: event for event in document.events}[5]
        assert renumbered.current_reference == "SIP-46"
        assert renumbered.current_detail_url == "https://ossip.dev/sips/SIP-46.html"

    def test_current_fields_none_when_untracked(
        self, tmp_path: Path, log_file: Path, seen_file: Path
    ):
        generate_events_api(tmp_path / "out", events_file=log_file, seen_file=seen_file)
        document = EventsDocument.model_validate(
            json.loads((tmp_path / "out" / "events.json").read_text())
        )
        untracked = {event.seq: event for event in document.events}[1]
        assert untracked.current_reference is None
        assert untracked.current_detail_url is None

    def test_verbatim_fields_preserved(self, events):
        api_event = enrich_event(events[4], {})
        dumped = api_event.model_dump()
        original = events[4].model_dump()
        for field, value in original.items():
            assert dumped[field] == value

    def test_is_an_api_event(self, events):
        assert isinstance(enrich_event(events[0], {}), ApiEvent)


class TestGenerateEventsApi:
    def test_writes_document(self, tmp_path: Path, log_file: Path):
        path = generate_events_api(tmp_path / "out", events_file=log_file)
        assert path == tmp_path / "out" / "events.json"
        assert path.exists()
        document = EventsDocument.model_validate(json.loads(path.read_text()))
        assert document.version == 1
        assert document.count == 5
        assert document.latest_seq == 5
        assert GENERATED_AT_RE.match(document.generated_at)

    def test_newest_first_ordering(self, tmp_path: Path, log_file: Path):
        generate_events_api(tmp_path / "out", events_file=log_file)
        document = EventsDocument.model_validate(
            json.loads((tmp_path / "out" / "events.json").read_text())
        )
        times = [event.event_time for event in document.events]
        assert times == sorted(times, reverse=True)

    def test_ties_broken_by_seq_descending(self, tmp_path: Path):
        # Same event_time, different seqs: higher seq first
        log = [record(7, effective_at=None), record(3, effective_at=None)]
        log_file = tmp_path / "log.jsonl"
        write_log(log_file, log)
        generate_events_api(tmp_path / "out", events_file=log_file)
        document = EventsDocument.model_validate(
            json.loads((tmp_path / "out" / "events.json").read_text())
        )
        assert [event.seq for event in document.events] == [7, 3]

    def test_enrichment_in_document(self, tmp_path: Path, log_file: Path):
        generate_events_api(tmp_path / "out", events_file=log_file)
        document = EventsDocument.model_validate(
            json.loads((tmp_path / "out" / "events.json").read_text())
        )
        first = document.events[0]
        assert first.headline == headline(first, include_project=True)
        assert first.summary == summary_text(first)

    def test_missing_log_writes_empty_document(self, tmp_path: Path, isolated_store):
        path = generate_events_api(tmp_path / "out")
        document = EventsDocument.model_validate(json.loads(path.read_text()))
        assert document.count == 0
        assert document.latest_seq == 0
        assert document.events == []

    def test_empty_log_writes_empty_document(self, tmp_path: Path):
        empty = tmp_path / "empty.jsonl"
        write_log(empty, [])
        generate_events_api(tmp_path / "out", events_file=empty)
        document = EventsDocument.model_validate(
            json.loads((tmp_path / "out" / "events.json").read_text())
        )
        assert document.count == 0

    def test_round_trip(self, tmp_path: Path, log_file: Path):
        generate_events_api(tmp_path / "out", events_file=log_file)
        raw = json.loads((tmp_path / "out" / "events.json").read_text())
        for entry in raw["events"]:
            assert ApiEvent.model_validate(entry)

    def test_creates_nested_directories(self, tmp_path: Path, log_file: Path):
        path = generate_events_api(tmp_path / "a" / "b" / "c", events_file=log_file)
        assert path.exists()


class TestSchemas:
    def test_api_event_schema_exports(self, tmp_path: Path):
        from ipper.common.api_output import write_schemas

        write_schemas(tmp_path)
        assert (tmp_path / "schemas" / "ApiEvent.schema.json").exists()
        assert (tmp_path / "schemas" / "EventsDocument.schema.json").exists()
