"""Pluggable social media destinations.

To add a destination: create ``ipper/social/posters/<name>.py`` with a class
decorated ``@register_poster`` exposing ``name``, ``from_env()`` (raise
``PosterNotConfigured`` when credentials are missing) and
``post(event) -> PostResult`` (build its own message via
``messages.build_message``, which takes an optional char limit); import the
module here; add its env vars to CI. No other file changes.
"""

from ipper.social.posters import (  # noqa: F401 — registers posters
    bluesky,
    console,
    mastodon,
)
from ipper.social.posters.base import (
    POSTER_REGISTRY,
    Poster,
    PosterNotConfigured,
    PostResult,
    get_poster,
    register_poster,
)
