"""Producer hook shared by every project's ``update`` command.

Each project appends to the event log at the end of its update. The logic is
identical across all five, so it lives here once instead of being copied into
``kafka/main.py``, ``flink/main.py`` and ``common/github_cli.py``.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def update_event_log(project: str, cache_path: Path) -> None:
    """Append proposal events to the event log (never fails the update).

    An events crash before ``save_seen`` costs nothing (replay-dedup protects
    the next run), but a version mismatch means we cannot safely detect at all,
    so ``EventsVersionError`` propagates.
    """
    # Imported at call time so tests can monkeypatch ``ipper.events.update_from_cache``.
    from ipper.events import EventsVersionError, update_from_cache

    try:
        appended = update_from_cache(project, cache_path)
        logger.info("Event log: %d new event(s)", len(appended))
    except EventsVersionError:
        raise  # version problems must fail loudly, never guess
    except Exception:
        logger.exception("Event log update failed; events will be re-detected next run")
