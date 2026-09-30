"""Shared fixtures for the social announcement tests."""

import pytest

from ipper.social.models import ProposalEvent, ProposalSnapshot


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
