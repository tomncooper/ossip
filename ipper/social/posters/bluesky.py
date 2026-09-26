"""Bluesky poster (AT Protocol)."""

import logging
import os

from ipper.social.messages import build_message
from ipper.social.models import ProposalEvent
from ipper.social.posters.base import PosterNotConfigured, PostResult, register_poster

logger = logging.getLogger(__name__)


@register_poster
class BlueskyPoster:
    """Posts via the atproto SDK.

    Credentials: BLUESKY_IDENTIFIER (e.g. "ossip.bsky.social") and
    BLUESKY_APP_PASSWORD — an app-specific password from
    bsky.app -> Settings -> App Passwords (NOT the account password).
    """

    name = "bluesky"
    CHAR_LIMIT = 300

    def __init__(self, client) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "BlueskyPoster":
        """Build from BLUESKY_* environment variables."""
        from atproto import Client  # import here so dry runs need no SDK

        identifier = os.environ.get("BLUESKY_IDENTIFIER")
        password = os.environ.get("BLUESKY_APP_PASSWORD")
        if not identifier or not password:
            raise PosterNotConfigured("BLUESKY_IDENTIFIER/BLUESKY_APP_PASSWORD not set")
        client = Client()
        client.login(identifier, password)
        return cls(client)

    def post(self, event: ProposalEvent) -> PostResult:
        """Publish with a link facet so the ossip.dev URL is clickable."""
        text = build_message(event, limit=self.CHAR_LIMIT)
        try:
            from atproto import client_utils

            builder = client_utils.TextBuilder()
            url = event.snapshot.detail_url
            if url and url in text:
                head, _, tail = text.partition(url)
                builder.text(head)
                builder.link(url, url)
                builder.text(tail)
            else:
                builder.text(text)
            response = self._client.send_post(builder)
            return PostResult(ok=True, post_id=str(response.uri))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Bluesky post failed: %s", exc)
            return PostResult(ok=False, error=str(exc))
