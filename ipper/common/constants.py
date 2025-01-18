from enum import StrEnum

UNKNOWN_STR: str = "unknown"
NOT_SET_STR: str = "not set"


class IPState(StrEnum):
    """Enum representing the status of an improvement proposal."""

    COMPLETED: str = "completed"
    IN_PROGRESS: str = "in progress"
    ACCEPTED: str = "accepted"
    UNDER_DISCUSSION: str = "under discussion"
    NOT_ACCEPTED: str = "not accepted"
    UNKNOWN: str = UNKNOWN_STR
