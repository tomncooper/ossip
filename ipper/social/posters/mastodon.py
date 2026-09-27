"""Mastodon poster (fediverse / ActivityPub)."""

import logging
import os

from ipper.social.messages import build_message
from ipper.social.models import ProposalEvent
from ipper.social.posters.base import PosterNotConfigured, PostResult, register_poster

logger = logging.getLogger(__name__)


@register_poster
class MastodonPoster:
    """Posts statuses via Mastodon.py.

    Credentials: MASTODON_ACCESS_TOKEN (required) and MASTODON_BASE_URL
    (optional, defaults to the project instance). The token is a user
    access token created via the instance's
    Settings -> Development -> New application.
    """

    name = "mastodon"
    DEFAULT_BASE_URL = "https://social.netech.dev"

    def __init__(self, client, char_limit: int = 500) -> None:
        self._client = client
        self._limit = char_limit

    @classmethod
    def from_env(cls) -> "MastodonPoster":
        """Build from MASTODON_* environment variables."""
        from mastodon import Mastodon  # import here so dry runs need no SDK

        token = os.environ.get("MASTODON_ACCESS_TOKEN")
        if not token:
            raise PosterNotConfigured("MASTODON_ACCESS_TOKEN is not set")
        base_url = os.environ.get("MASTODON_BASE_URL", cls.DEFAULT_BASE_URL)
        client = Mastodon(api_base_url=base_url, access_token=token)
        limit = cls._instance_char_limit(client)
        return cls(client, limit)

    @staticmethod
    def _instance_char_limit(client) -> int:
        """Query the instance's toot char limit; fall back to 500."""
        try:
            return int(client.instance()["configuration"]["statuses"]["max_characters"])
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("Could not query instance char limit; using 500")
            return 500

    def post(self, event: ProposalEvent) -> PostResult:
        """Publish one status; returns ok=False on any API failure."""
        text = build_message(event, limit=self._limit)
        try:
            status = self._client.status_post(text, visibility="public")
            return PostResult(ok=True, post_id=str(status["id"]))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Mastodon post failed: %s", exc)
            return PostResult(ok=False, error=str(exc))
