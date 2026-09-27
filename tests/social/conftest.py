"""Shared fixtures for the social announcement tests."""

import json
from pathlib import Path

import pytest

from ipper.social.models import ProposalEvent, ProposalSnapshot


@pytest.fixture
def sample_kip_cache() -> dict:
    """KIP wiki cache shape (§2.1 of the implementation plan)."""
    return {
        "1": {
            "kip_id": 1,
            "title": "KIP-1 - Remove support of request.required.acks",
            "web_url": "https://example.com/kip-1",
            "state": "accepted",
        },
        "2": {
            "kip_id": 2,
            "title": "KIP-2 - Another proposal",
            "web_url": "https://example.com/kip-2",
            "state": "under discussion",
        },
        "3": {
            "kip_id": 3,
            "title": "KIP-3 - Rejected one",
            "web_url": "https://example.com/kip-3",
            "state": "not accepted",
        },
    }


@pytest.fixture
def sample_flip_cache() -> dict:
    """FLIP wiki cache shape. Note 'completed' == accepted for FLIPs."""
    return {
        "1": {
            "id": 1,
            "title": "FLIP-1: Fine Grained Recovery",
            "web_url": "https://example.com/flip-1",
            "state": "completed",
        },
        "2": {
            "id": 2,
            "title": "FLIP-2: Ongoing work",
            "web_url": "https://example.com/flip-2",
            "state": "in progress",
        },
    }


@pytest.fixture
def sample_sip_cache() -> dict:
    """GitHub proposals cache shape (SIP; SHIP/KDP identical)."""
    return {
        "last_updated": "2026-10-05T09:30:00+00:00",
        "proposals": {
            "pr-3": {
                "pr_number": 3,
                "title": "Improving configurability of Kafka listeners",
                "state": "accepted",
                "id": 5,
            },
            "pr-245": {
                "pr_number": 245,
                "title": "Add proposal for Kafka Exporter",
                "state": "under discussion",
                "id": None,
            },
        },
        "pr_index": {},
        "watermark": "2026-10-05T09:30:00+00:00",
    }


@pytest.fixture
def write_cache(tmp_path: Path):
    """Write a JSON cache file into tmp_path and return its path."""

    def _write(name: str, data: dict) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def make_snapshot() -> callable:
    """Factory for ProposalSnapshot objects."""

    def _make(
        key: str = "kafka:kip-123",
        project: str = "kafka",
        reference: str = "KIP-123",
        title: str = "Exactly-once semantics",
        state: str = "under discussion",
        detail_url: str = "https://ossip.dev/kips/KIP-123.html",
    ) -> ProposalSnapshot:
        return ProposalSnapshot(
            key=key,
            project=project,
            reference=reference,
            title=title,
            state=state,
            detail_url=detail_url,
        )

    return _make


@pytest.fixture
def make_event(make_snapshot) -> callable:
    """Factory for ProposalEvent objects."""

    def _make(
        event_type="new",
        observed_at: str = "2026-10-05T09:30:00+00:00",
        **snapshot_kwargs,
    ) -> ProposalEvent:
        return ProposalEvent(
            event_type=event_type,
            snapshot=make_snapshot(**snapshot_kwargs),
            observed_at=observed_at,
        )

    return _make
