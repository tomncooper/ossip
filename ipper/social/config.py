"""Per-project configuration for the social announcement pipeline.

The definitions live in :mod:`ipper.common.projects` so the event-log
pipeline (and any future consumer) can share them; this module re-exports
them for backward compatibility.
"""

from ipper.common.projects import (  # noqa: F401
    SOCIAL_PROJECTS,
    ProjectConfig,
    SocialProjectConfig,
    base_url,
)

__all__ = ["SOCIAL_PROJECTS", "ProjectConfig", "SocialProjectConfig", "base_url"]
