"""Pydantic models for OSSIP JSON API."""

from collections.abc import Sequence

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


class ReviewerInfo(BaseModel):
    """Information about a single GitHub reviewer.

    Attributes:
        login: Reviewer's GitHub login
        timestamp: ISO 8601 timestamp of their latest qualifying review
            interaction (approval, comment or change request)
    """

    login: str
    timestamp: str


class ReviewSummary(BaseModel):
    """Unique GitHub reviewer counts per interaction type for a proposal.

    Attributes:
        accepted: Users who approved the PR (APPROVED review); approval is
            terminal - approvers never appear in the other lists
        commented: Users who only participated via comments (issue comments
            or COMMENTED reviews); the PR author and bots are excluded
        changes_requested: Users who requested changes (CHANGES_REQUESTED
            review) and did not approve
    """

    accepted: list[ReviewerInfo]
    commented: list[ReviewerInfo]
    changes_requested: list[ReviewerInfo]


class ReviewCount(BaseModel):
    """Integer unique-reviewer counts for a GitHub-tracked proposal.

    Attributes:
        accepted: Number of unique users who approved
        commented: Number of unique users who only commented
        changes_requested: Number of unique users who requested changes
    """

    accepted: int
    commented: int
    changes_requested: int


class ProposalSummaryBase(BaseModel):
    """Compact proposal information shared by all proposal types.

    Attributes:
        id: Proposal ID number
        title: Proposal title
        state: Current state (e.g., "accepted", "under discussion")
        created_by: Name of the wiki page creator
        authors: Merged, deduplicated list of proposal authors (creator + any
            authors/co-authors declared on the wiki page)
        created_on: Creation date (YYYY-MM-DD)
        activity_status: Activity level indicator ("blue", "green", "yellow", "red",
            "black") or None for non-discussion states or projects without activity
            tracking
        detail_url: URL to the full detail JSON file
        web_url: URL to the canonical wiki page
        pr_number: GitHub pull request number for GitHub-tracked proposals, or
            None for wiki-tracked proposals
    """

    id: int | None
    title: str
    state: str
    created_by: str
    authors: list[str]
    created_on: str
    activity_status: str | None
    detail_url: str
    web_url: str
    pr_number: int | None = None


class ProposalSummary(ProposalSummaryBase):
    """Compact proposal information for wiki-tracked (KIP/FLIP) summaries.

    Attributes:
        vote_count: Integer vote counts
    """

    vote_count: VoteCount


class GithubProposalSummary(ProposalSummaryBase):
    """Compact proposal information for GitHub-tracked (SIP/SHIP/KDP)
    summaries.

    Attributes:
        review_count: Unique reviewer counts (accepted / commented /
            changes_requested)
    """

    review_count: ReviewCount


class ProposalDetailBase(BaseModel):
    """Full proposal information shared by all proposal types.

    Attributes:
        id: Proposal ID number
        title: Proposal title
        state: Current state (e.g., "accepted", "under discussion")
        created_by: Name of the wiki page creator
        authors: Merged, deduplicated list of proposal authors (creator + any
            authors/co-authors declared on the wiki page)
        created_on: Creation date (YYYY-MM-DD)
        last_modified_on: Last modification timestamp (YYYY-MM-DDTHH:MM:SSZ)
        last_modified_by: Name of last modifier
        discussion_thread: URL to discussion thread or None
        vote_thread: URL to vote thread or None
        jira: JIRA ticket reference or None
        web_url: URL to the canonical wiki page
        activity_status: Activity level indicator or None
        pr_number: GitHub pull request number for GitHub-tracked proposals, or
            None for wiki-tracked proposals
    """

    id: int | None
    title: str
    state: str
    created_by: str
    authors: list[str]
    created_on: str
    last_modified_on: str
    last_modified_by: str
    discussion_thread: str | None
    vote_thread: str | None
    jira: str | None
    web_url: str
    activity_status: str | None
    pr_number: int | None = None


class ProposalDetail(ProposalDetailBase):
    """Full proposal information with vote details (KIP/FLIP).

    Attributes:
        votes: Full vote details with voter names and timestamps
    """

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
        proposals: List of proposal summaries (wiki-tracked summaries carry
            vote_count, GitHub-tracked ones carry review_count)
    """

    project: str
    proposal_type: str
    last_updated: str
    count: int
    proposals: Sequence[ProposalSummary | GithubProposalSummary]


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
