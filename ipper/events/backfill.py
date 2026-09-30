"""One-time historical synthesis of the event log from current caches.

Backfill creates the log's initial content: every proposal currently in the
caches gets a ``new`` event (``backfilled: true``), plus derived
``state_changed``/``renumbered`` events where the current state implies one.
Review-history events (first_approval/changes_requested/vote_started) are
NOT backfilled — review timing is only partially reconstructible; those
accrue from detection day one. After backfill, ``last_seen`` is seeded so
subsequent updates only log genuinely new changes.
"""

import logging
from pathlib import Path

import ipper.events.store as store
from ipper.common.github_config import GITHUB_PROJECT_CONFIGS
from ipper.common.projects import SOCIAL_PROJECTS
from ipper.events.adapters import ADAPTERS
from ipper.events.detection import (
    _new_effective,
    _state_changed_effective,
)
from ipper.events.models import (
    EventCandidate,
    EventRecord,
    EventType,
    SeenSnapshot,
)

logger = logging.getLogger(__name__)

WIKI_CACHE_FILENAMES = {
    "kafka": "kip_wiki_cache.json",
    "flink": "flip_wiki_cache.json",
}

ACCEPTED_STATES = frozenset({"accepted", "completed"})
REJECTED_STATE = "not accepted"


def _cache_file(project: str, cache_dir: Path) -> Path:
    """Cache file path for one project under cache_dir."""
    if project in WIKI_CACHE_FILENAMES:
        return cache_dir / WIKI_CACHE_FILENAMES[project]
    return cache_dir / GITHUB_PROJECT_CONFIGS[project].cache_filename


def _candidates_for_snapshot(
    snapshot: SeenSnapshot, now: str, renumber_applicable: bool = True
) -> list[EventCandidate]:
    """Historical candidates implied by one proposal's current state.

    Every proposal gets NEW; accepted/not-accepted GitHub proposals and
    numbered GitHub proposals get derived STATE_CHANGED/RENUMBERED events;
    wiki accepted/completed and not-accepted proposals get STATE_CHANGED.
    ``renumber_applicable`` is False for pr_number-numbering projects (e.g.
    KDP) whose proposals are numbered from birth — renumbering only makes
    sense for sequential numbering, where it happens on merge.
    """
    is_wiki = snapshot.project in ("kafka", "flink")
    out: list[EventCandidate] = []

    eff, eff_src = _new_effective(snapshot)
    out.append(
        EventCandidate(
            project=snapshot.project,
            key=snapshot.key,
            event_type=EventType.NEW.value,
            reference=snapshot.reference,
            title=snapshot.title,
            state_before=None,
            state_after=snapshot.state,
            observed_at=now,
            effective_at=eff,
            effective_at_source=eff_src,
            detail_url=snapshot.detail_url,
            backfilled=True,
        )
    )

    if snapshot.state in ACCEPTED_STATES or snapshot.state == REJECTED_STATE:
        if is_wiki:
            eff, eff_src = _state_changed_effective(snapshot, snapshot.state)
            out.append(
                EventCandidate(
                    project=snapshot.project,
                    key=snapshot.key,
                    event_type=EventType.STATE_CHANGED.value,
                    reference=snapshot.reference,
                    title=snapshot.title,
                    state_before=None,  # genuinely unknown for wiki history
                    state_after=snapshot.state,
                    observed_at=now,
                    effective_at=eff,
                    effective_at_source=eff_src,
                    detail_url=snapshot.detail_url,
                    backfilled=True,
                )
            )
        else:
            # GitHub: accepted (merged) and not accepted both imply a
            # state change; a numbered proposal additionally implies
            # renumbering at merge time.
            if snapshot.state in ACCEPTED_STATES:
                eff = snapshot.merged_on or now
                eff_src = "merged_on" if snapshot.merged_on else "observed_at"
                out.append(
                    EventCandidate(
                        project=snapshot.project,
                        key=snapshot.key,
                        event_type=EventType.STATE_CHANGED.value,
                        reference=snapshot.reference,
                        title=snapshot.title,
                        state_before=None,  # genuinely unknown
                        state_after="accepted",
                        observed_at=now,
                        effective_at=eff,
                        effective_at_source=eff_src,
                        detail_url=snapshot.detail_url,
                        backfilled=True,
                    )
                )
            if snapshot.proposal_id is not None and renumber_applicable:
                eff = snapshot.merged_on or now
                eff_src = "merged_on" if snapshot.merged_on else "observed_at"
                out.append(
                    EventCandidate(
                        project=snapshot.project,
                        key=snapshot.key,
                        event_type=EventType.RENUMBERED.value,
                        reference=snapshot.reference,
                        title=snapshot.title,
                        state_before=None,
                        state_after=snapshot.state,
                        observed_at=now,
                        effective_at=eff,
                        effective_at_source=eff_src,
                        detail_url=snapshot.detail_url,
                        reference_before=(
                            f"{snapshot.reference.split('-')[0]}-PR-{snapshot.pr_number}"
                        ),
                        backfilled=True,
                    )
                )
            if snapshot.state == REJECTED_STATE:
                eff, eff_src = _state_changed_effective(snapshot, snapshot.state)
                if eff is None:
                    eff, eff_src = now, "observed_at"
                out.append(
                    EventCandidate(
                        project=snapshot.project,
                        key=snapshot.key,
                        event_type=EventType.STATE_CHANGED.value,
                        reference=snapshot.reference,
                        title=snapshot.title,
                        state_before=None,
                        state_after="not accepted",
                        observed_at=now,
                        effective_at=eff,
                        effective_at_source=eff_src,
                        detail_url=snapshot.detail_url,
                        backfilled=True,
                    )
                )

    # Under-discussion/unknown/in-progress states get only their NEW event.
    return out


def _sort_key(candidate: EventCandidate) -> str:
    return candidate.effective_at or candidate.observed_at


def backfill(
    cache_dir: Path = Path("cache"), now: str | None = None
) -> list[EventRecord]:
    """Synthesize historical events from current caches; seed last_seen.

    Runs entirely under the lock. Refuses to run against a non-empty log.
    """
    now = now or store._now()
    with store._log_lock():
        events = store.load_events(store.EVENTS_FILE)
        if events:
            raise RuntimeError(
                f"events.jsonl already contains {len(events)} records; backfill "
                "runs only once. git history retains the file if you ever need "
                "to redo it."
            )
        seen_state = store.load_seen(store.SEEN_FILE)

        total: list[EventCandidate] = []
        for project in SOCIAL_PROJECTS:
            cache_file = _cache_file(project, cache_dir)
            if not cache_file.exists():
                logger.warning(
                    "Cache for %s unavailable (%s); skipping backfill for this project",
                    project,
                    cache_file,
                )
                continue
            snapshots = ADAPTERS[project](cache_file)
            # Renumbering only applies to sequential-numbering GitHub projects
            # (a pr_number project like Kroxylicious is numbered from birth).
            renumber_applicable = project not in GITHUB_PROJECT_CONFIGS or (
                GITHUB_PROJECT_CONFIGS[project].numbering == "sequential"
            )
            candidates: list[EventCandidate] = []
            for snapshot in snapshots:
                candidates.extend(
                    _candidates_for_snapshot(snapshot, now, renumber_applicable)
                )
            # Chronological within the project (projects stay in config order;
            # never interleaved globally).
            candidates.sort(key=_sort_key)
            total.extend(candidates)
            seen_state.projects[project] = {s.key: s for s in snapshots}
            logger.info("Backfilling %s: %d event(s)", project, len(candidates))

        appended = store.append_events(events, total, store.EVENTS_FILE)
        seen_state.last_run = now
        store.save_seen(seen_state, store.SEEN_FILE)
    return appended
