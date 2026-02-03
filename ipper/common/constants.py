from enum import StrEnum, Enum

UNKNOWN_STR: str = "unknown"
NOT_SET_STR: str = "not set"

DEFAULT_TEMPLATES_DIR = "templates"
DATE_FORMAT = "%Y/%m/%d %H:%M:%S %Z"

# Mailing list constants
APACHE_MAILING_LIST_BASE_URL: str = "https://lists.apache.org/api/mbox.lua"
MAIL_DATE_FORMAT = "%a, %d %b %Y %H:%M:%S %z"
MAIL_DATE_FORMAT_ZONE = "%a, %d %b %Y %H:%M:%S %z (%Z)"


class IPState(StrEnum):
    """Enum representing the status of an improvement proposal."""

    COMPLETED = "completed"
    IN_PROGRESS = "in progress"
    ACCEPTED = "accepted"
    UNDER_DISCUSSION = "under discussion"
    NOT_ACCEPTED = "not accepted"
    UNKNOWN = UNKNOWN_STR


class MentionType(Enum):
    """Generic enum representing the possible types of improvement proposal mention."""

    SUBJECT = "subject"
    VOTE = "vote"
    DISCUSS = "discuss"
    BODY = "body"
