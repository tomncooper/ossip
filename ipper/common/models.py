"""Pydantic models for OSSIP JSON API."""

from pydantic import BaseModel


class VoterInfo(BaseModel):
    """Information about a single voter.

    Attributes:
        name: Voter's name
        timestamp: ISO 8601 timestamp when the vote was cast (YYYY-MM-DDTHH:MM:SSZ)
    """

    name: str
    timestamp: str


class VoteSummary(BaseModel):
    """Summary of votes for a proposal.

    Attributes:
        plus_one: List of voters who voted +1
        zero: List of voters who voted 0
        minus_one: List of voters who voted -1
    """

    plus_one: list[VoterInfo]
    zero: list[VoterInfo]
    minus_one: list[VoterInfo]


class VoteCount(BaseModel):
    """Integer vote counts for a proposal.

    Used in summary lists where full voter details aren't needed.

    Attributes:
        plus_one: Number of +1 votes
        zero: Number of 0 votes
        minus_one: Number of -1 votes
    """

    plus_one: int
    zero: int
    minus_one: int


class ProposalSummary(BaseModel):
    """Compact proposal information for summary lists.

    Attributes:
        id: Proposal ID number
        title: Proposal title
        state: Current state (e.g., "accepted", "under discussion")
        created_by: Author's name
        created_on: Creation date (YYYY-MM-DD)
        vote_count: Integer vote counts
        activity_status: Activity level indicator ("blue", "green", "yellow", "red",
            "black") or None for non-discussion states or projects without activity
            tracking
        detail_url: URL to the full detail JSON file
        web_url: URL to the canonical wiki page
    """

    id: int
    title: str
    state: str
    created_by: str
    created_on: str
    vote_count: VoteCount
    activity_status: str | None
    detail_url: str
    web_url: str


class ProposalDetail(BaseModel):
    """Full proposal information with vote details.

    Attributes:
        id: Proposal ID number
        title: Proposal title
        state: Current state (e.g., "accepted", "under discussion")
        created_by: Author's name
        created_on: Creation date (YYYY-MM-DD)
        last_modified_on: Last modification timestamp (YYYY-MM-DDTHH:MM:SSZ)
        last_modified_by: Name of last modifier
        discussion_thread: URL to discussion thread or None
        vote_thread: URL to vote thread or None
        jira: JIRA ticket reference or None
        web_url: URL to the canonical wiki page
        activity_status: Activity level indicator or None
        votes: Full vote details with voter names and timestamps
    """

    id: int
    title: str
    state: str
    created_by: str
    created_on: str
    last_modified_on: str
    last_modified_by: str
    discussion_thread: str | None
    vote_thread: str | None
    jira: str | None
    web_url: str
    activity_status: str | None
    votes: VoteSummary


class KipDetail(ProposalDetail):
    """Kafka Improvement Proposal (KIP) detail.

    Currently has no additional fields beyond ProposalDetail, but is kept
    as a separate class for extensibility and clear type distinction.
    """

    pass


class FlipDetail(ProposalDetail):
    """Flink Improvement Proposal (FLIP) detail.

    Extends ProposalDetail with Flink-specific fields.

    Attributes:
        release_version: Target Flink release version or None
        release_component: Target Flink component or None
        jira_id: Associated JIRA ticket ID (e.g., "FLINK-12345") or None
        jira_link: URL to JIRA ticket or None
    """

    release_version: str | None
    release_component: str | None
    jira_id: str | None
    jira_link: str | None


class ProjectMeta(BaseModel):
    """Metadata about a project in the API index.

    Attributes:
        name: Project display name (e.g., "Kafka", "Flink")
        proposal_type: Type of proposals (e.g., "KIP", "FLIP")
        count: Number of proposals in the project
        summary_url: URL to the project's summary JSON file
    """

    name: str
    proposal_type: str
    count: int
    summary_url: str


class ProjectSummary(BaseModel):
    """Summary of all proposals for a project.

    Attributes:
        project: Project name
        proposal_type: Type of proposals
        last_updated: Timestamp when this data was last updated (YYYY-MM-DDTHH:MM:SSZ)
        count: Number of proposals
        proposals: List of proposal summaries
    """

    project: str
    proposal_type: str
    last_updated: str
    count: int
    proposals: list[ProposalSummary]


class ApiIndex(BaseModel):
    """Top-level API index.

    Entry point for the JSON API, listing all available projects.

    Attributes:
        version: API version number
        last_updated: Timestamp when the index was last updated (YYYY-MM-DDTHH:MM:SSZ)
        projects: Dictionary mapping project keys (e.g., "kafka", "flink") to metadata
    """

    version: int
    last_updated: str
    projects: dict[str, ProjectMeta]
