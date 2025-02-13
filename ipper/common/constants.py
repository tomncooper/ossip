from enum import StrEnum

UNKNOWN_STR: str = "unknown"
NOT_SET_STR: str = "not set"

DEFAULT_TEMPLATES_DIR = "templates"
DATE_FORMAT = "%Y/%m/%d %H:%M:%S %Z"


class IPState(StrEnum):
    """Enum representing the status of an improvement proposal."""

    COMPLETED = "completed"
    IN_PROGRESS = "in progress"
    ACCEPTED = "accepted"
    UNDER_DISCUSSION = "under discussion"
    NOT_ACCEPTED = "not accepted"
    UNKNOWN = UNKNOWN_STR
