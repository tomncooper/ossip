"""Tests for message formatting."""

from ipper.common.constants import IPState
from ipper.social.messages import (
    STATE_EMOJI,
    build_message,
    display_state,
    emoji_for,
    strip_reference_prefix,
)
from ipper.social.models import EventType


def make_event(event_type: EventType, state: str, title: str, url: str):
    """Build a ProposalEvent without needing the conftest factories."""
    from ipper.social.models import ProposalEvent, ProposalSnapshot

    snapshot = ProposalSnapshot(
        key="kafka:kip-123",
        project="kafka",
        reference="KIP-123",
        title=title,
        state=state,
        detail_url=url,
    )
    return ProposalEvent(
        event_type=event_type,
        snapshot=snapshot,
        observed_at="2026-10-05T09:30:00+00:00",
    )


def test_accepted_message_format(make_snapshot) -> None:
    """An ACCEPTED event renders the exact agreed template."""
    from ipper.social.models import ProposalEvent

    event = ProposalEvent(
        event_type=EventType.ACCEPTED,
        snapshot=make_snapshot(state="accepted"),
        observed_at="2026-10-05T09:30:00+00:00",
    )
    expected = (
        "Kafka KIP-123 ✅ accepted — “Exactly-once semantics” "
        "https://ossip.dev/kips/KIP-123.html #Kafka #KIP"
    )
    assert build_message(event) == expected


def test_new_message_includes_state_phrase(make_snapshot) -> None:
    """NEW events show the display state in parentheses."""
    from ipper.social.models import ProposalEvent

    event = ProposalEvent(
        event_type=EventType.NEW,
        snapshot=make_snapshot(state="under discussion"),
        observed_at="2026-10-05T09:30:00+00:00",
    )
    message = build_message(event)
    assert "new proposal (under discussion)" in message
    assert "💬" in message


def test_rejected_message_says_not_accepted(make_snapshot) -> None:
    """REJECTED events use the 'not accepted' phrase."""
    from ipper.social.models import ProposalEvent

    event = ProposalEvent(
        event_type=EventType.REJECTED,
        snapshot=make_snapshot(state="not accepted"),
        observed_at="2026-10-05T09:30:00+00:00",
    )
    assert "❌ not accepted" in build_message(event)


def test_emoji_map_covers_all_ip_states() -> None:
    """Every IPState value has an emoji entry (guards against new states)."""
    for state in IPState:
        assert state.value in STATE_EMOJI


def test_completed_uses_accepted_word_and_check_emoji() -> None:
    """FLIP-style 'completed' displays as accepted with a check mark."""
    assert emoji_for("completed") == "✅"
    assert display_state("completed") == "accepted"


def test_strip_reference_prefix_kip_and_flip() -> None:
    """KIP/FLIP title prefixes are stripped; bare titles pass through."""
    assert strip_reference_prefix("KIP-1 - Foo", "KIP-1") == "Foo"
    assert strip_reference_prefix("FLIP-1: Foo", "FLIP-1") == "Foo"
    assert strip_reference_prefix("Foo", "KIP-1") == "Foo"


def _accepted_event(make_snapshot, title: str):
    """ACCEPTED event built from the conftest snapshot factory."""
    from ipper.social.models import ProposalEvent

    return ProposalEvent(
        event_type=EventType.ACCEPTED,
        snapshot=make_snapshot(title=title),
        observed_at="2026-10-05T09:30:00+00:00",
    )


def test_fit_message_drops_tags_first(make_snapshot) -> None:
    """Over-limit messages lose hashtags before anything else."""
    event = _accepted_event(make_snapshot, "Title")
    full = build_message(event)
    limit = len(full) - 1  # one char too long
    fitted = build_message(event, limit=limit)
    assert len(fitted) <= limit
    assert "#Kafka" not in fitted
    assert "Title”" in fitted
    assert fitted.endswith("https://ossip.dev/kips/KIP-123.html")


def test_fit_message_truncates_title(make_snapshot) -> None:
    """Very long titles are truncated with an ellipsis; URL survives."""
    event = _accepted_event(make_snapshot, "T" * 200)
    fitted = build_message(event, limit=150)
    assert len(fitted) <= 150
    assert "https://ossip.dev/kips/KIP-123.html" in fitted
    assert fitted.endswith("https://ossip.dev/kips/KIP-123.html")
    assert "…" in fitted


def test_fit_message_falls_back_to_no_title(make_snapshot) -> None:
    """An absurdly small limit still keeps project + reference + URL."""
    event = _accepted_event(make_snapshot, "T" * 200)
    fitted = build_message(event, limit=90)
    assert "Kafka KIP-123" in fitted
    assert "https://ossip.dev/kips/KIP-123.html" in fitted
    assert len(fitted) <= 90
