from enum import StrEnum

from jira import JIRA, JIRAError

APACHE_JIRA_URL = "https://issues.apache.org/jira"


class JiraStatus(StrEnum):

    OPEN: str = "open"
    IN_PROGRESS: str = "in progress"
    RESOLVED: str = "resolved"
    CLOSED: str = "closed"
    UNKNOWN: str = "unknown"

    @classmethod
    def getStatus(cls, status: str):

        clean_status = status.strip().lower()

        if clean_status not in cls:
            return cls.UNKNOWN

        for option in cls:
            if option == clean_status:
                return option


def get_apache_jira_status(issue_id: str) -> JiraStatus:

    apache_jira = JIRA(APACHE_JIRA_URL)

    try:
        issue = apache_jira.issue(issue_id, fields="status")
    except JIRAError:
        return JiraStatus.UNKNOWN

    return JiraStatus.getStatus(issue.fields.status.name)
