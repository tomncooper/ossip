"""Tests for the social announcement models."""

from ipper.social.models import SocialState


def test_social_state_roundtrip() -> None:
    """Serialising and re-validating a SocialState is lossless."""
    state = SocialState()
    state.last_run = "2026-10-05T09:30:00+00:00"
    restored = SocialState.model_validate_json(state.model_dump_json())
    assert restored == state
