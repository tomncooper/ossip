"""Tests for change detection and the state file."""

import json
import logging

from ipper.social.detector import (
    classify_transition,
    detect,
    load_state,
    prune,
    save_state,
    seed_state,
    select_to_post,
    sync_destinations,
)
from ipper.social.models import (
    EventPolicy,
    EventType,
)

NOW = "2026-10-05T09:30:00+00:00"


def policy(**kwargs) -> EventPolicy:
    """Default v1 policy with optional overrides."""
    return EventPolicy(**kwargs)


def run_detect(state, snapshots, loaded=None, destinations=("mastodon", "bluesky")):
    """detect() with sensible defaults for tests."""
    return detect(
        snapshots,
        state,
        policy(),
        loaded if loaded is not None else {"kafka", "flink", "strimzi"},
        list(destinations),
        NOW,
    )


def test_first_run_via_seed_posts_nothing(make_snapshot) -> None:
    """Seeding produces a full baseline and empty pending."""
    snaps = [make_snapshot(), make_snapshot(key="kafka:kip-2", reference="KIP-2")]
    state = seed_state(snaps, NOW)
    assert len(state.baselines) == 2
    assert state.pending == []


def test_new_proposal_emits_new(make_snapshot) -> None:
    """An unseen proposal emits NEW."""
    state = seed_state([], NOW)
    state = run_detect(state, [make_snapshot()])
    assert len(state.pending) == 1
    assert state.pending[0].event.event_type is EventType.NEW


def test_under_discussion_to_accepted_emits_accepted(make_snapshot) -> None:
    """under discussion -> accepted is an ACCEPTED event."""
    state = seed_state([make_snapshot()], NOW)
    state.baselines["kafka:kip-123"].state = "under discussion"
    state = run_detect(state, [make_snapshot(state="accepted")])
    assert state.pending[0].event.event_type is EventType.ACCEPTED


def test_under_discussion_to_completed_emits_accepted(make_snapshot) -> None:
    """under discussion -> completed (FLIP) is an ACCEPTED event."""
    state = seed_state([make_snapshot()], NOW)
    state.baselines["kafka:kip-123"].state = "under discussion"
    state = run_detect(state, [make_snapshot(state="completed")])
    assert state.pending[0].event.event_type is EventType.ACCEPTED


def test_to_not_accepted_emits_rejected(make_snapshot) -> None:
    """Any state -> not accepted is a REJECTED event."""
    state = seed_state([make_snapshot()], NOW)
    state.baselines["kafka:kip-123"].state = "under discussion"
    state = run_detect(state, [make_snapshot(state="not accepted")])
    assert state.pending[0].event.event_type is EventType.REJECTED


def test_accepted_to_completed_is_silent(make_snapshot) -> None:
    """accepted -> completed (both 'accepted' words) emits nothing."""
    state = seed_state([make_snapshot(state="accepted")], NOW)
    state = run_detect(state, [make_snapshot(state="completed")])
    assert state.pending == []


def test_reopen_is_silent(make_snapshot) -> None:
    """accepted -> under discussion emits nothing; baseline still updates."""
    state = seed_state([make_snapshot(state="accepted")], NOW)
    state = run_detect(state, [make_snapshot(state="under discussion")])
    assert state.pending == []
    assert state.baselines["kafka:kip-123"].state == "under discussion"


def test_same_state_no_event(make_snapshot) -> None:
    """Unchanged state emits nothing."""
    state = seed_state([make_snapshot()], NOW)
    state = run_detect(state, [make_snapshot()])
    assert state.pending == []


def test_baseline_advances_even_when_event_filtered_out(make_snapshot) -> None:
    """A disabled event type still advances the baseline (no stale diff)."""
    state = seed_state([make_snapshot()], NOW)
    state.baselines["kafka:kip-123"].state = "under discussion"
    restricted = policy(enabled_event_types={EventType.NEW})
    detect(
        [make_snapshot(state="accepted")],
        state,
        restricted,
        {"kafka"},
        ["mastodon"],
        NOW,
    )
    assert state.pending == []
    assert state.baselines["kafka:kip-123"].state == "accepted"


def test_missing_project_cache_retains_baselines(make_snapshot) -> None:
    """Baselines of projects not in loaded_projects survive a failed load."""
    state = seed_state(
        [make_snapshot(), make_snapshot(key="flink:flip-1", project="flink")], NOW
    )
    # Only kafka loaded this run; flink's cache file was missing.
    state = run_detect(state, [make_snapshot()], loaded={"kafka"})
    assert "flink:flip-1" in state.baselines


def test_vanished_proposal_removed_from_baselines(make_snapshot) -> None:
    """A proposal gone from a loaded project's cache loses its baseline."""
    state = seed_state([make_snapshot()], NOW)
    state = run_detect(state, [], loaded={"kafka"})
    assert "kafka:kip-123" not in state.baselines


def test_coalesce_replaces_pending_new_with_accepted(make_snapshot) -> None:
    """A new event replaces the pending one with fresh per-destination acks."""
    state = seed_state([make_snapshot()], NOW)
    state = run_detect(state, [make_snapshot(state="accepted")])
    # Simulate a partial success: mastodon acked, bluesky attempted+failed.
    state.pending[0].destinations["mastodon"].acked = True
    state.pending[0].destinations["bluesky"].attempts = 1
    state.pending[0].destinations["bluesky"].last_error = "500"
    # The proposal transitions again before bluesky recovered.
    state = run_detect(state, [make_snapshot(state="not accepted")])
    assert len(state.pending) == 1
    pending = state.pending[0]
    assert pending.event.event_type is EventType.REJECTED
    # Fresh acks: mastodon must be re-posted (it announced the older state).
    assert pending.destinations["mastodon"].acked is False
    assert pending.destinations["mastodon"].attempts == 0


def test_select_respects_max_posts(make_snapshot) -> None:
    """select_to_post returns at most max_posts; state.pending keeps the rest."""
    snaps = [
        make_snapshot(key=f"kafka:kip-{i}", reference=f"KIP-{i}") for i in range(3)
    ]
    state = seed_state([], NOW)
    state = run_detect(state, snaps)
    chosen = select_to_post(state, policy(max_posts=2), ["mastodon"])
    assert len(chosen) == 2
    assert len(state.pending) == 3


def test_select_prefers_retries(make_snapshot) -> None:
    """Events with attempts > 0 are selected before brand-new events."""
    snaps = [
        make_snapshot(key=f"kafka:kip-{i}", reference=f"KIP-{i}") for i in range(3)
    ]
    state = seed_state([], NOW)
    state = run_detect(state, snaps)
    state.pending[2].destinations["mastodon"].attempts = 1
    chosen = select_to_post(state, policy(max_posts=2), ["mastodon"])
    assert chosen[0].event.snapshot.key == "kafka:kip-2"


def test_prune_removes_fully_acked(make_snapshot) -> None:
    """Fully-acked events leave the pending queue."""
    state = seed_state([make_snapshot()], NOW)
    state = run_detect(state, [make_snapshot(state="accepted")])
    for status in state.pending[0].destinations.values():
        status.acked = True
    state = prune(state, policy(), ["mastodon", "bluesky"])
    assert state.pending == []


def test_prune_drops_exhausted_events_with_error_log(make_snapshot, caplog) -> None:
    """Events past max_attempts are dropped with an error-level log."""
    state = seed_state([make_snapshot()], NOW)
    state = run_detect(state, [make_snapshot(state="accepted")])
    for status in state.pending[0].destinations.values():
        status.attempts = 5
    with caplog.at_level(logging.ERROR):
        state = prune(state, policy(max_attempts=5), ["mastodon", "bluesky"])
    assert state.pending == []
    assert "Dropping event" in caplog.text


def test_prune_keeps_partially_failed(make_snapshot) -> None:
    """A failed destination under max_attempts stays pending for retry."""
    state = seed_state([make_snapshot()], NOW)
    state = run_detect(state, [make_snapshot(state="accepted")])
    state.pending[0].destinations["mastodon"].acked = True
    state.pending[0].destinations["bluesky"].attempts = 1
    state.pending[0].destinations["bluesky"].last_error = "502"
    state = prune(state, policy(), ["mastodon", "bluesky"])
    assert len(state.pending) == 1


def test_sync_destinations_adds_and_removes(make_snapshot) -> None:
    """Ack maps follow the configured destinations across runs."""
    state = seed_state([make_snapshot()], NOW)
    state = run_detect(
        state, [make_snapshot(state="accepted")], destinations=("mastodon",)
    )
    pending = state.pending[0]
    sync_destinations(pending, ["mastodon", "bluesky"])
    assert set(pending.destinations) == {"mastodon", "bluesky"}
    sync_destinations(pending, ["bluesky"])
    assert set(pending.destinations) == {"bluesky"}


def test_save_and_load_state_roundtrip(tmp_path, make_snapshot) -> None:
    """save_state/load_state is lossless."""
    path = tmp_path / "state.json"
    state = seed_state([make_snapshot()], NOW)
    save_state(state, path)
    assert load_state(path) == state


def test_load_state_missing_file_returns_none(tmp_path) -> None:
    """A missing state file means 'first run'."""
    assert load_state(tmp_path / "absent.json") is None


def test_load_state_reseeds_on_bad_version(tmp_path, caplog) -> None:
    """An unsupported version logs a warning and returns None (reseed)."""
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 99, "baselines": {}}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert load_state(path) is None
    assert "unsupported" in caplog.text


def test_classify_transition_table() -> None:
    """Direct checks on the transition table."""
    assert classify_transition(None, "under discussion") is EventType.NEW
    assert classify_transition("under discussion", "accepted") is EventType.ACCEPTED
    assert classify_transition("under discussion", "completed") is EventType.ACCEPTED
    assert classify_transition("under discussion", "not accepted") is EventType.REJECTED
    assert classify_transition("accepted", "completed") is None
    assert classify_transition("accepted", "under discussion") is None
    assert classify_transition("under discussion", "unknown") is None
    assert classify_transition("accepted", "accepted") is None
