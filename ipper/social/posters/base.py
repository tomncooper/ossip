"""Poster protocol and registry."""

from typing import Any, Protocol, runtime_checkable

from ipper.social.models import ProposalEvent


class PosterNotConfigured(Exception):
    """Raised when a destination's credentials are missing."""


@runtime_checkable
class Poster(Protocol):
    """A social media destination."""

    name: str

    def post(self, event: ProposalEvent) -> "PostResult":
        """Build, fit and publish the message for this destination.

        Each poster renders its own message (destinations have different
        length limits and link handling) via messages.build_message.
        Returns ok=False on any expected failure; unexpected errors are
        caught and also reported via ok=False.
        """
        ...


class PostResult:
    """Outcome of one posting attempt."""

    def __init__(
        self, ok: bool, post_id: str | None = None, error: str | None = None
    ) -> None:
        self.ok = ok
        self.post_id = post_id
        self.error = error


POSTER_REGISTRY: dict[str, Any] = {}


def register_poster(cls: Any) -> Any:
    """Class decorator: register a poster under its `name` attribute."""
    POSTER_REGISTRY[cls.name] = cls
    return cls


def get_poster(name: str) -> Poster:
    """Instantiate a registered poster; raises PosterNotConfigured if creds are missing."""
    if name not in POSTER_REGISTRY:
        raise ValueError(
            f"Unknown poster {name!r}; registered: {sorted(POSTER_REGISTRY)}"
        )
    return POSTER_REGISTRY[name].from_env()
