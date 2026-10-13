"""Feed filenames and titles, shared by the feed writer and the index pages."""

from ipper.social.config import SOCIAL_PROJECTS

COMBINED_FEED = "feed.xml"
COMBINED_FEED_TITLE = "OSSIP - new proposals"


def feed_file(key: str) -> str:
    """Filename of a project's feed (also what its index page links to)."""
    return f"{key}.xml"


def feed_title(key: str) -> str:
    """Title of a project's feed (also used for feed auto-discovery)."""
    project = SOCIAL_PROJECTS[key]
    return f"OSSIP - new {project.name} proposals ({project.prefix})"
