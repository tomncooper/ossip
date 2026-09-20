"""Pydantic models for GitHub-based proposal tracking (SIP/SHIP/KDP)."""

from pydantic import BaseModel

from ipper.common.models import ProposalDetailBase, ReviewSummary


class Amendment(BaseModel):
    """A proposal amendment: a PR that modifies an already-merged proposal.

    Attributes:
        pr_number: The amendment pull request number
        url: URL to the amendment pull request
        date: Date the amendment PR was merged or closed (YYYY-MM-DD)
    """

    pr_number: int
    url: str
    date: str


class GithubProposalDetail(ProposalDetailBase):
    """Detail model for GitHub-tracked proposals (SIP/SHIP/KDP).

    Attributes:
        merged_on: Merge timestamp (ISO 8601) or None for unmerged proposals
        pr_url: URL to the originating pull request
        amendments: List of amendment PRs that modified the merged proposal
        reviews: Unique reviewers per interaction type with latest
            timestamps
    """

    merged_on: str | None = None
    pr_url: str | None = None
    amendments: list[Amendment] = []
    reviews: ReviewSummary
