"""Tests for ipper.events.detection: the pure snapshot/seen diff."""

from ipper.events.detection import detect_events
from ipper.events.models import EventType, ReviewEntry, SeenSnapshot

NOW = "2026-10-01T09:30:00+00:00"


def wiki_snapshot(
    key: str = "kafka:kip-1",
    project: str = "kafka",
    reference: str = "KIP-1",
    state: str = "under discussion",
    **kwargs,
) -> SeenSnapshot:
    defaults = {
        "key": key,
        "project": project,
        "reference": reference,
        "title": "T",
        "state": state,
        "detail_url": f"https://ossip.dev/{reference}.html",
        "created_on": "2026-01-01T00:00:00.000Z",
        "last_modified_on": "2026-02-01T00:00:00.000Z",
    }
    defaults.update(kwargs)
    return SeenSnapshot(**defaults)


def github_snapshot(
    key: str = "strimzi:pr-245",
    project: str = "strimzi",
    reference: str = "SIP-PR-245",
    state: str = "under discussion",
    **kwargs,
) -> SeenSnapshot:
    defaults = {
        "key": key,
        "project": project,
        "reference": reference,
        "title": "T",
        "state": state,
        "detail_url": f"https://ossip.dev/{reference}.html",
        "created_on": "2026-01-01T00:00:00Z",  # full-ISO created_at preferred
        "pr_number": 245,
        "proposal_id": None,
        "reviews": {"accepted": [], "commented": [], "changes_requested": []},
    }
    defaults.update(kwargs)
    return SeenSnapshot(**defaults)


def review(name: str, ts: str) -> ReviewEntry:
    return ReviewEntry(name=name, timestamp=ts)


class TestGone:
    def test_missing_key_emits_disappeared(self):
        old = wiki_snapshot()
        candidates, new_seen = detect_events("kafka", [], {"kafka:kip-1": old}, NOW)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.event_type == EventType.DISAPPEARED
        assert c.state_before == "under discussion"
        assert c.state_after is None
        assert c.effective_at is None
        # seen empty afterwards
        assert new_seen == {}

    def test_no_baseline_no_disappeared(self):
        candidates, _ = detect_events("kafka", [], {}, NOW)
        assert candidates == []


class TestNew:
    def test_wiki_new_uses_created_on(self):
        snap = wiki_snapshot()
        candidates, new_seen = detect_events("kafka", [snap], {}, NOW)
        c = candidates[0]
        assert c.event_type == EventType.NEW
        assert c.state_before is None
        assert c.state_after == "under discussion"
        assert c.effective_at == "2026-01-01T00:00:00.000Z"
        assert c.effective_at_source == "created_on"
        assert new_seen == {snap.key: snap}

    def test_github_new_prefers_created_at(self):
        snap = github_snapshot()
        candidates, _ = detect_events("strimzi", [snap], {}, NOW)
        c = candidates[0]
        assert c.effective_at == "2026-01-01T00:00:00Z"
        assert c.effective_at_source == "created_at"

    def test_github_new_falls_back_to_date_only_created_on(self):
        snap = github_snapshot(created_on="2026-01-01")
        candidates, _ = detect_events("strimzi", [snap], {}, NOW)
        c = candidates[0]
        assert c.effective_at == "2026-01-01"
        assert c.effective_at_source == "created_on"

    def test_github_day_one_reviews_emit_first_approval_and_changes(self):
        snap = github_snapshot(
            reviews={
                "accepted": [review("alice", "2026-01-05T10:00:00Z")],
                "commented": [],
                "changes_requested": [review("bob", "2026-01-06T11:00:00Z")],
            }
        )
        candidates, _ = detect_events("strimzi", [snap], {}, NOW)
        types = {c.event_type for c in candidates}
        assert types == {
            EventType.NEW,
            EventType.FIRST_APPROVAL,
            EventType.CHANGES_REQUESTED,
        }
        first = next(c for c in candidates if c.event_type == EventType.FIRST_APPROVAL)
        assert first.effective_at == "2026-01-05T10:00:00Z"
        assert first.effective_at_source == "review_timestamp"

    def test_wiki_day_one_vote_thread_emits_vote_started(self):
        snap = wiki_snapshot(vote_thread="https://lists.apache.org/x")
        candidates, _ = detect_events("kafka", [snap], {}, NOW)
        types = [c.event_type for c in candidates]
        assert types == [EventType.NEW, EventType.VOTE_STARTED]
        vote = candidates[1]
        assert vote.effective_at == "2026-02-01T00:00:00.000Z"
        assert vote.effective_at_source == "last_modified_on"


class TestStateChange:
    def test_wiki_state_changed_uses_last_modified_on(self):
        old = wiki_snapshot(state="under discussion")
        new = wiki_snapshot(state="accepted")
        candidates, _ = detect_events("kafka", [new], {new.key: old}, NOW)
        c = candidates[0]
        assert c.event_type == EventType.STATE_CHANGED
        assert c.state_before == "under discussion"
        assert c.state_after == "accepted"
        assert c.effective_at == "2026-02-01T00:00:00.000Z"
        assert c.effective_at_source == "last_modified_on"

    def test_github_accepted_uses_merged_on(self):
        old = github_snapshot(state="under discussion")
        new = github_snapshot(state="accepted", merged_on="2026-03-01T10:00:00Z")
        candidates, _ = detect_events("strimzi", [new], {new.key: old}, NOW)
        c = candidates[0]
        assert c.effective_at == "2026-03-01T10:00:00Z"
        assert c.effective_at_source == "merged_on"

    def test_github_rejected_prefers_closed_on_then_last_activity(self):
        old = github_snapshot(state="under discussion")
        new = github_snapshot(
            state="not accepted",
            closed_on="2026-03-02T10:00:00Z",
            last_activity="2026-03-02T09:00:00Z",
        )
        candidates, _ = detect_events("strimzi", [new], {new.key: old}, NOW)
        assert candidates[0].effective_at == "2026-03-02T10:00:00Z"
        assert candidates[0].effective_at_source == "closed_on"

        older = github_snapshot(
            state="not accepted", last_activity="2026-03-02T09:00:00Z"
        )
        candidates, _ = detect_events("strimzi", [older], {older.key: old}, NOW)
        assert candidates[0].effective_at == "2026-03-02T09:00:00Z"
        assert candidates[0].effective_at_source == "last_activity"

    def test_github_other_wiggle_uses_last_activity(self):
        old = github_snapshot(state="accepted")
        new = github_snapshot(
            state="under discussion", last_activity="2026-03-05T10:00:00Z"
        )
        candidates, _ = detect_events("strimzi", [new], {new.key: old}, NOW)
        c = candidates[0]
        assert c.state_before == "accepted"
        assert c.state_after == "under discussion"
        assert c.effective_at == "2026-03-05T10:00:00Z"
        assert c.effective_at_source == "last_activity"

    def test_no_change_no_event(self):
        snap = wiki_snapshot()
        candidates, new_seen = detect_events("kafka", [snap], {snap.key: snap}, NOW)
        assert candidates == []
        assert new_seen == {snap.key: snap}


class TestRenumbered:
    def test_renumber_and_accept_emit_both(self):
        old = github_snapshot()
        new = github_snapshot(
            reference="SIP-46",
            proposal_id=46,
            state="accepted",
            merged_on="2026-03-01T10:00:00Z",
        )
        candidates, _ = detect_events("strimzi", [new], {old.key: old}, NOW)
        types = [c.event_type for c in candidates]
        assert types == [EventType.STATE_CHANGED, EventType.RENUMBERED]
        renum = candidates[1]
        assert renum.reference == "SIP-46"
        assert renum.reference_before == "SIP-PR-245"
        assert renum.effective_at == "2026-03-01T10:00:00Z"
        assert renum.effective_at_source == "merged_on"

    def test_renumber_falls_back_to_observed_at(self):
        old = github_snapshot()
        new = github_snapshot(reference="SIP-46", proposal_id=46, state="accepted")
        candidates, _ = detect_events("strimzi", [new], {old.key: old}, NOW)
        renum = next(c for c in candidates if c.event_type == EventType.RENUMBERED)
        assert renum.effective_at == NOW
        assert renum.effective_at_source == "observed_at"

    def test_wiki_reference_change_is_silent(self):
        # wiki keys are id-based, so a reference change cannot happen; but a
        # non-GitHub proposal_id transition must never emit renumbered
        old = wiki_snapshot()
        new = wiki_snapshot(title="Renamed")
        candidates, _ = detect_events("kafka", [new], {old.key: old}, NOW)
        assert candidates == []


class TestReviewEdges:
    def test_accepted_empty_to_nonempty(self):
        old = github_snapshot()
        new = github_snapshot(
            reviews={
                "accepted": [
                    review("alice", "2026-02-05T10:00:00Z"),
                    review("bob", "2026-02-04T09:00:00Z"),
                ]
            }
        )
        candidates, _ = detect_events("strimzi", [new], {old.key: old}, NOW)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.event_type == EventType.FIRST_APPROVAL
        # earliest timestamp among the newly present entries
        assert c.effective_at == "2026-02-04T09:00:00Z"

    def test_changes_requested_empty_to_nonempty(self):
        old = github_snapshot()
        new = github_snapshot(
            reviews={
                "accepted": [],
                "commented": [],
                "changes_requested": [review("bob", "2026-02-06T09:00:00Z")],
            }
        )
        candidates, _ = detect_events("strimzi", [new], {old.key: old}, NOW)
        assert candidates[0].event_type == EventType.CHANGES_REQUESTED

    def test_addition_to_nonempty_is_silent(self):
        old = github_snapshot(
            reviews={"accepted": [review("alice", "2026-02-01T00:00:00Z")]}
        )
        new = github_snapshot(
            reviews={
                "accepted": [
                    review("alice", "2026-02-01T00:00:00Z"),
                    review("bob", "2026-02-05T00:00:00Z"),
                ]
            }
        )
        candidates, new_seen = detect_events("strimzi", [new], {old.key: old}, NOW)
        assert candidates == []
        assert new_seen == {new.key: new}  # baseline still updates

    def test_dismissal_is_silent(self):
        old = github_snapshot(
            reviews={"accepted": [review("alice", "2026-02-01T00:00:00Z")]}
        )
        new = github_snapshot(reviews={"accepted": []})
        candidates, new_seen = detect_events("strimzi", [new], {old.key: old}, NOW)
        assert candidates == []
        assert new_seen == {new.key: new}


class TestVoteStarted:
    def test_vote_thread_set_later(self):
        old = wiki_snapshot(vote_thread=None)
        new = wiki_snapshot(vote_thread="https://lists.apache.org/x")
        candidates, _ = detect_events("kafka", [new], {old.key: old}, NOW)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.event_type == EventType.VOTE_STARTED
        assert c.effective_at == "2026-02-01T00:00:00.000Z"
        assert c.effective_at_source == "last_modified_on"

    def test_vote_thread_already_set_is_silent(self):
        snap = wiki_snapshot(vote_thread="https://x")
        candidates, _ = detect_events("kafka", [snap], {snap.key: snap}, NOW)
        assert candidates == []


class TestSuccessiveRuns:
    def test_wiggle_produces_one_event_per_run(self):
        base = wiki_snapshot(state="under discussion")
        accepted = wiki_snapshot(state="accepted")
        rejected = wiki_snapshot(state="not accepted")

        seen: dict[str, SeenSnapshot] = {base.key: base}
        all_types = []
        for snap in (accepted, rejected):
            candidates, seen = detect_events("kafka", [snap], seen, NOW)
            all_types.extend(c.event_type for c in candidates)
        assert all_types == [EventType.STATE_CHANGED, EventType.STATE_CHANGED]

    def test_detection_is_pure_no_file_access(self, monkeypatch):
        def explode(*args, **kwargs):  # pragma: no cover
            raise AssertionError("detection must not touch the filesystem")

        monkeypatch.setattr("builtins.open", explode)
        snap = wiki_snapshot()
        candidates, _ = detect_events("kafka", [snap], {}, NOW)
        assert len(candidates) == 1


def test_observed_at_stamped_on_all_candidates():
    snaps = [
        wiki_snapshot(),
        wiki_snapshot(key="kafka:kip-2", reference="KIP-2"),
    ]
    candidates, _ = detect_events("kafka", snaps, {}, NOW)
    assert all(c.observed_at == NOW for c in candidates)
    assert all(c.project == "kafka" for c in candidates)
