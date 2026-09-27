"""Message formatting for social announcements."""

import re

from ipper.common.constants import IPState
from ipper.social.config import SOCIAL_PROJECTS
from ipper.social.models import EventType, ProposalEvent

STATE_EMOJI: dict[str, str] = {
    IPState.ACCEPTED.value: "✅",
    IPState.COMPLETED.value: "✅",
    IPState.IN_PROGRESS.value: "🛠️",
    IPState.UNDER_DISCUSSION.value: "💬",
    IPState.NOT_ACCEPTED.value: "❌",
    IPState.UNKNOWN.value: "❓",
}
DEFAULT_EMOJI = "❓"

# Normalise project-specific vocabulary to a common display word.
STATE_DISPLAY: dict[str, str] = {
    IPState.COMPLETED.value: "accepted",  # FLIPs say "completed"
}

ACCEPTED_STATES = frozenset({IPState.ACCEPTED.value, IPState.COMPLETED.value})
REJECTED_STATE = IPState.NOT_ACCEPTED.value


def emoji_for(state: str) -> str:
    """Emoji for a proposal state string."""
    return STATE_EMOJI.get(state, DEFAULT_EMOJI)


def display_state(state: str) -> str:
    """Canonical display word for a proposal state string."""
    return STATE_DISPLAY.get(state, state)


def strip_reference_prefix(title: str, reference: str) -> str:
    """Strip a leading “KIP-1 - ” / “FLIP-1: ” style prefix from a title."""
    cleaned = re.sub(rf"^{re.escape(reference)}\s*[-–:]*\s*", "", title, count=1)
    return cleaned.strip() or title


def status_phrase(event: ProposalEvent) -> str:
    """Human phrase describing the event, e.g. “accepted”."""
    snap = event.snapshot
    if event.event_type is EventType.NEW:
        return f"new proposal ({display_state(snap.state)})"
    if event.event_type is EventType.ACCEPTED:
        return "accepted"
    return "not accepted"


def build_message(event: ProposalEvent, limit: int | None = None) -> str:
    """Render the announcement message, fitting an optional char limit.

    Long messages are shrunk by (1) dropping hashtags, then (2) truncating
    the title with an ellipsis. The URL is never dropped or truncated.
    `limit` counts Python characters (conservative for both APIs: Mastodon
    counts links as 23 chars regardless of length, Bluesky counts graphemes).
    """
    cfg = SOCIAL_PROJECTS[event.snapshot.project]
    snap = event.snapshot
    emoji = emoji_for(snap.state)
    phrase = status_phrase(event)
    tags = f"#{cfg.name} #{cfg.prefix}"

    def assemble(title: str | None, tags_to_add: str) -> str:
        title_part = f"“{title}” " if title else ""
        tag_part = f" {tags_to_add}" if tags_to_add else ""
        return (
            f"{cfg.name} {snap.reference} {emoji} {phrase} — "
            f"{title_part}{snap.detail_url}{tag_part}"
        )

    message = assemble(snap.title, tags)
    if limit is None or len(message) <= limit:
        return message
    message = assemble(snap.title, "")
    if len(message) <= limit:
        return message
    if len(snap.title) > len(message) - limit + 1:
        keep = len(snap.title) - (len(message) - limit) - 1
        return assemble(snap.title[:keep].rstrip() + "…", "")
    return assemble(None, "")
