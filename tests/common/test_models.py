"""Tests for ipper.common.models module."""

import json

from ipper.common.models import (
    ApiIndex,
    FlipDetail,
    KipDetail,
    ProjectMeta,
    ProjectSummary,
    ProposalDetail,
    ProposalSummary,
    VoteCount,
    VoterInfo,
    VoteSummary,
)


class TestVoterInfo:
    """Tests for the VoterInfo model."""

    def test_serialization_roundtrip(self):
        """Test that VoterInfo can be serialized and deserialized."""
        voter = VoterInfo(name="Alice", timestamp="2025-01-02T10:00:00Z")
        json_str = voter.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["name"] == "Alice"
        assert parsed["timestamp"] == "2025-01-02T10:00:00Z"

        # Roundtrip
        voter2 = VoterInfo.model_validate_json(json_str)
        assert voter2.name == "Alice"
        assert voter2.timestamp == "2025-01-02T10:00:00Z"


class TestVoteSummary:
    """Tests for the VoteSummary model."""

    def test_serialization_with_voters(self):
        """Test VoteSummary serialization with vote lists."""
        summary = VoteSummary(
            plus_one=[VoterInfo(name="Alice", timestamp="2025-01-02T10:00:00Z")],
            zero=[],
            minus_one=[VoterInfo(name="Bob", timestamp="2025-01-03T11:00:00Z")],
        )
        json_str = summary.model_dump_json()
        parsed = json.loads(json_str)
        assert len(parsed["plus_one"]) == 1
        assert parsed["plus_one"][0]["name"] == "Alice"
        assert len(parsed["zero"]) == 0
        assert len(parsed["minus_one"]) == 1
        assert parsed["minus_one"][0]["name"] == "Bob"


class TestVoteCount:
    """Tests for the VoteCount model."""

    def test_integer_counts(self):
        """Test VoteCount uses integer counts."""
        count = VoteCount(plus_one=5, zero=2, minus_one=1)
        assert count.plus_one == 5
        assert count.zero == 2
        assert count.minus_one == 1


class TestProposalSummary:
    """Tests for the ProposalSummary model."""

    def test_with_activity_status(self):
        """Test ProposalSummary with activity_status."""
        summary = ProposalSummary(
            id=1,
            title="Test KIP",
            state="under discussion",
            created_by="Alice",
            created_on="2025-01-02",
            vote_count=VoteCount(plus_one=3, zero=1, minus_one=0),
            activity_status="green",
            detail_url="https://ossip.dev/api/v1/kafka/kips/1.json",
            web_url="https://cwiki.apache.org/confluence/x/test",
        )
        assert summary.activity_status == "green"

    def test_without_activity_status(self):
        """Test ProposalSummary without activity_status (Flink case)."""
        summary = ProposalSummary(
            id=2,
            title="Test FLIP",
            state="accepted",
            created_by="Bob",
            created_on="2025-06-01",
            vote_count=VoteCount(plus_one=5, zero=0, minus_one=0),
            activity_status=None,
            detail_url="https://ossip.dev/api/v1/flink/flips/2.json",
            web_url="https://cwiki.apache.org/confluence/x/test2",
        )
        assert summary.activity_status is None


class TestProposalDetail:
    """Tests for the ProposalDetail model."""

    def test_none_fields_for_sentinel_values(self):
        """Test that None is used for missing/unknown fields."""
        detail = ProposalDetail(
            id=1,
            title="Test Proposal",
            state="unknown",
            created_by="Alice",
            created_on="2025-01-02",
            last_modified_on="2025-01-03T10:00:00Z",
            last_modified_by="Alice",
            discussion_thread=None,
            vote_thread=None,
            jira=None,
            web_url="https://example.com",
            activity_status=None,
            votes=VoteSummary(plus_one=[], zero=[], minus_one=[]),
        )
        assert detail.discussion_thread is None
        assert detail.vote_thread is None
        assert detail.jira is None
        assert detail.activity_status is None


class TestKipDetail:
    """Tests for the KipDetail model."""

    def test_is_subclass_of_proposal_detail(self):
        """Test that KipDetail is a subclass of ProposalDetail."""
        assert issubclass(KipDetail, ProposalDetail)

    def test_schema_export_works(self):
        """Test that schema export produces valid JSON Schema."""
        schema = KipDetail.model_json_schema()
        assert "title" in schema
        assert schema["title"] == "KipDetail"
        # Should have all ProposalDetail fields
        assert "id" in schema["properties"]
        assert "title" in schema["properties"]
        assert "votes" in schema["properties"]


class TestFlipDetail:
    """Tests for the FlipDetail model."""

    def test_has_flink_specific_fields(self):
        """Test that FlipDetail has Flink-specific fields."""
        detail = FlipDetail(
            id=1,
            title="Test FLIP",
            state="in progress",
            created_by="Alice",
            created_on="2025-01-02",
            last_modified_on="2025-01-03T10:00:00Z",
            last_modified_by="Alice",
            discussion_thread=None,
            vote_thread=None,
            jira=None,
            web_url="https://example.com",
            activity_status=None,
            votes=VoteSummary(plus_one=[], zero=[], minus_one=[]),
            release_version="1.18",
            release_component="Flink",
            jira_id="FLINK-12345",
            jira_link="https://issues.apache.org/jira/browse/FLINK-12345",
        )
        assert detail.release_version == "1.18"
        assert detail.release_component == "Flink"
        assert detail.jira_id == "FLINK-12345"
        assert detail.jira_link == "https://issues.apache.org/jira/browse/FLINK-12345"

    def test_flink_fields_can_be_none(self):
        """Test that Flink-specific fields can be None."""
        detail = FlipDetail(
            id=2,
            title="Test",
            state="unknown",
            created_by="Bob",
            created_on="2025-06-01",
            last_modified_on="2025-06-02T10:00:00Z",
            last_modified_by="Bob",
            discussion_thread=None,
            vote_thread=None,
            jira=None,
            web_url="https://example.com",
            activity_status=None,
            votes=VoteSummary(plus_one=[], zero=[], minus_one=[]),
            release_version=None,
            release_component=None,
            jira_id=None,
            jira_link=None,
        )
        assert detail.release_version is None
        assert detail.release_component is None
        assert detail.jira_id is None
        assert detail.jira_link is None


class TestProjectMeta:
    """Tests for the ProjectMeta model."""

    def test_serialization(self):
        """Test ProjectMeta serialization."""
        meta = ProjectMeta(
            name="Kafka",
            proposal_type="KIP",
            count=1284,
            summary_url="https://ossip.dev/api/v1/kafka/kips.json",
        )
        assert meta.name == "Kafka"
        assert meta.proposal_type == "KIP"
        assert meta.count == 1284
        assert meta.summary_url == "https://ossip.dev/api/v1/kafka/kips.json"


class TestProjectSummary:
    """Tests for the ProjectSummary model."""

    def test_with_proposals(self):
        """Test ProjectSummary with proposal list."""
        summary = ProjectSummary(
            project="Kafka",
            proposal_type="KIP",
            last_updated="2025-01-10T12:00:00Z",
            count=2,
            proposals=[
                ProposalSummary(
                    id=1,
                    title="Test KIP 1",
                    state="accepted",
                    created_by="Alice",
                    created_on="2025-01-01",
                    vote_count=VoteCount(plus_one=3, zero=0, minus_one=0),
                    activity_status=None,
                    detail_url="https://ossip.dev/api/v1/kafka/kips/1.json",
                    web_url="https://cwiki.apache.org/confluence/x/test1",
                ),
                ProposalSummary(
                    id=2,
                    title="Test KIP 2",
                    state="under discussion",
                    created_by="Bob",
                    created_on="2025-01-05",
                    vote_count=VoteCount(plus_one=1, zero=1, minus_one=0),
                    activity_status="green",
                    detail_url="https://ossip.dev/api/v1/kafka/kips/2.json",
                    web_url="https://cwiki.apache.org/confluence/x/test2",
                ),
            ],
        )
        assert summary.count == 2
        assert len(summary.proposals) == 2
        assert summary.proposals[0].id == 1


class TestApiIndex:
    """Tests for the ApiIndex model."""

    def test_empty_projects(self):
        """Test ApiIndex with no projects."""
        index = ApiIndex(
            version=1, last_updated="2025-01-10T12:00:00Z", projects={}
        )
        assert index.version == 1
        assert index.projects == {}

    def test_with_projects(self):
        """Test ApiIndex with multiple projects."""
        index = ApiIndex(
            version=1,
            last_updated="2025-01-10T12:00:00Z",
            projects={
                "kafka": ProjectMeta(
                    name="Kafka",
                    proposal_type="KIP",
                    count=1284,
                    summary_url="https://ossip.dev/api/v1/kafka/kips.json",
                ),
                "flink": ProjectMeta(
                    name="Flink",
                    proposal_type="FLIP",
                    count=570,
                    summary_url="https://ossip.dev/api/v1/flink/flips.json",
                ),
            },
        )
        assert index.version == 1
        assert len(index.projects) == 2
        assert "kafka" in index.projects
        assert "flink" in index.projects
        assert index.projects["kafka"].count == 1284
        assert index.projects["flink"].count == 570
