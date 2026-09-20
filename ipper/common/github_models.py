"""Pydantic models for GitHub-based proposal tracking (SIP/SHIP/KDP)."""

from pydantic import BaseModel

from ipper.common.models import ProposalDetail


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


class GithubProposalDetail(ProposalDetail):
    """Detail model for GitHub-tracked proposals (SIP/SHIP/KDP).

    Extends ProposalDetail with GitHub-specific fields.

    Attributes:
        pr_number: Originating pull request number (inherited, always set)
        merged_on: Merge timestamp (ISO 8601) or None for unmerged proposals
        pr_url: URL to the originating pull request
        amendments: List of amendment PRs that modified the merged proposal
    """

    merged_on: str | None = None
    pr_url: str | None = None
    amendments: list[Amendment] = []
