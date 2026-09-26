"""Console poster — prints messages; used for dry runs and local testing."""

from ipper.social.messages import build_message
from ipper.social.models import ProposalEvent
from ipper.social.posters.base import PostResult, register_poster


@register_poster
class ConsolePoster:
    """Echoes the rendered message to stdout. No credentials required."""

    name = "console"

    @classmethod
    def from_env(cls) -> "ConsolePoster":
        """No credentials required."""
        return cls()

    def post(self, event: ProposalEvent) -> PostResult:
        """Echo the rendered message to stdout."""
        print(f"[console] {build_message(event)}")
        return PostResult(ok=True, post_id="console")
