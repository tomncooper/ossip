"""Tests for the poster plugins."""

import pytest

from ipper.social import posters  # noqa: F401 — registers built-in posters
from ipper.social.messages import build_message
from ipper.social.posters.base import (
    POSTER_REGISTRY,
    PosterNotConfigured,
    get_poster,
)


class FakeMastodon:
    """Mimics the Mastodon.py client surface used by MastodonPoster."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def status_post(self, text, visibility=None, **kwargs):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append({"text": text, "visibility": visibility})
        return {"id": 42}


class FakeBluesky:
    """Mimics the atproto Client surface used by BlueskyPoster."""

    def __init__(self, fail: bool = False) -> None:
        self.posts: list = []
        self.fail = fail

    def send_post(self, text_builder):
        if self.fail:
            raise RuntimeError("boom")
        self.posts.append(text_builder)
        from atproto.models import AppBskyFeedPost  # lazy import

        return AppBskyFeedPost.View(uri="at://did:plc:test/app.bsky.feed.post/1")


class FakeBlueskyNoModel(FakeBluesky):
    """Fallback response type if the models module layout differs."""

    class _Response:  # pylint: disable=too-few-public-methods
        def __init__(self) -> None:
            self.uri = "at://did:plc:test/app.bsky.feed.post/1"

    def send_post(self, text_builder):
        if self.fail:
            raise RuntimeError("boom")
        self.posts.append(text_builder)
        return self._Response()


def test_mastodon_post_success(make_event) -> None:
    """A successful post returns ok=True with the status id."""
    from ipper.social.posters.mastodon import MastodonPoster

    client = FakeMastodon()
    poster = MastodonPoster(client, char_limit=500)
    result = poster.post(make_event())
    assert result.ok is True
    assert result.post_id == "42"
    assert len(client.calls) == 1
    assert client.calls[0]["visibility"] == "public"
    assert "KIP-123" in client.calls[0]["text"]


def test_mastodon_post_failure_returns_not_ok(make_event) -> None:
    """API failures become ok=False results, never exceptions."""
    from ipper.social.posters.mastodon import MastodonPoster

    poster = MastodonPoster(FakeMastodon(fail=True), char_limit=500)
    result = poster.post(make_event())
    assert result.ok is False
    assert result.error == "boom"
    assert result.post_id is None


def test_mastodon_instance_char_limit_fallback() -> None:
    """A broken instance() response falls back to 500 chars."""
    from ipper.social.posters.mastodon import MastodonPoster

    class BrokenInstance:
        def instance(self):
            raise RuntimeError("down")

    assert MastodonPoster._instance_char_limit(BrokenInstance()) == 500


def test_bluesky_post_success_injects_link_facet(make_event) -> None:
    """The detail URL is posted via TextBuilder.link (clickable facet)."""
    from ipper.social.posters.bluesky import BlueskyPoster

    client = FakeBlueskyNoModel()
    poster = BlueskyPoster(client)
    result = poster.post(make_event())
    assert result.ok is True
    assert result.post_id.startswith("at://")
    builder = client.posts[0]
    rendered = builder.build_text()
    assert "https://ossip.dev/kips/KIP-123.html" in rendered
    # The message went through TextBuilder.link, so facets were generated.
    assert builder.build_facets() is not None


def test_bluesky_post_failure_returns_not_ok(make_event) -> None:
    """API failures become ok=False results, never exceptions."""
    from ipper.social.posters.bluesky import BlueskyPoster

    poster = BlueskyPoster(FakeBlueskyNoModel(fail=True))
    result = poster.post(make_event())
    assert result.ok is False
    assert result.error == "boom"


def test_poster_not_configured_when_env_missing(monkeypatch) -> None:
    """Missing credentials raise PosterNotConfigured (loudly)."""
    from ipper.social.posters.bluesky import BlueskyPoster
    from ipper.social.posters.mastodon import MastodonPoster

    monkeypatch.delenv("MASTODON_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BLUESKY_IDENTIFIER", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    with pytest.raises(PosterNotConfigured):
        MastodonPoster.from_env()
    with pytest.raises(PosterNotConfigured):
        BlueskyPoster.from_env()


def test_console_poster_prints(make_event, capsys) -> None:
    """The console poster echoes the message to stdout."""
    from ipper.social.posters.console import ConsolePoster

    result = ConsolePoster().post(make_event())
    captured = capsys.readouterr()
    assert result.ok is True
    assert build_message(make_event()) in captured.out


def test_registry_contains_builtins() -> None:
    """All three built-in posters register themselves on import."""
    assert {"console", "mastodon", "bluesky"} <= set(POSTER_REGISTRY)


def test_get_poster_unknown_name_raises() -> None:
    """Unknown poster names raise ValueError."""
    with pytest.raises(ValueError, match="Unknown poster"):
        get_poster(" carrier-pigeon")
