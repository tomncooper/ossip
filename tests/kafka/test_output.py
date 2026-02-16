"""Tests for ipper.kafka.output.create_vote_dict cross-type deduplication."""

import pandas as pd

from ipper.kafka.output import create_vote_dict


def _make_mentions(rows: list[dict]) -> pd.DataFrame:
    """Helper to build a DataFrame matching the expected schema."""
    df = pd.DataFrame(rows, columns=["kip", "from", "vote", "timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


class TestCreateVoteDictCrossTypeDedup:
    """Tests that create_vote_dict keeps only each voter's latest vote across all types."""

    def test_voter_changes_vote_keeps_latest_only(self):
        """Voter casts '0' at T1 then '+1' at T2 -- only '+1' should appear."""
        mentions = _make_mentions(
            [
                {
                    "kip": 1,
                    "from": "Luke Chen",
                    "vote": "0",
                    "timestamp": "2025-01-01 10:00",
                },
                {
                    "kip": 1,
                    "from": "Luke Chen",
                    "vote": "+1",
                    "timestamp": "2025-01-02 10:00",
                },
            ]
        )
        result = create_vote_dict(mentions)

        assert result[1]["+1"] == [
            {"name": "Luke Chen", "timestamp": "Jan 02, 2025 10:00 UTC"}
        ]
        assert result[1]["0"] == []
        assert result[1]["-1"] == []

    def test_voter_changes_vote_from_plus_to_minus(self):
        """Voter casts '+1' at T1 then '-1' at T2 -- only '-1' should appear."""
        mentions = _make_mentions(
            [
                {
                    "kip": 2,
                    "from": "Alice",
                    "vote": "+1",
                    "timestamp": "2025-03-01 08:00",
                },
                {
                    "kip": 2,
                    "from": "Alice",
                    "vote": "-1",
                    "timestamp": "2025-03-02 08:00",
                },
            ]
        )
        result = create_vote_dict(mentions)

        assert result[2]["+1"] == []
        assert result[2]["-1"] == [
            {"name": "Alice", "timestamp": "Mar 02, 2025 08:00 UTC"}
        ]
        assert result[2]["0"] == []

    def test_multiple_voters_different_votes(self):
        """Distinct voters with different vote types are all kept."""
        mentions = _make_mentions(
            [
                {
                    "kip": 3,
                    "from": "Alice",
                    "vote": "+1",
                    "timestamp": "2025-01-01 10:00",
                },
                {
                    "kip": 3,
                    "from": "Bob",
                    "vote": "-1",
                    "timestamp": "2025-01-01 11:00",
                },
                {
                    "kip": 3,
                    "from": "Charlie",
                    "vote": "0",
                    "timestamp": "2025-01-01 12:00",
                },
            ]
        )
        result = create_vote_dict(mentions)

        assert len(result[3]["+1"]) == 1
        assert result[3]["+1"][0]["name"] == "Alice"
        assert len(result[3]["-1"]) == 1
        assert result[3]["-1"][0]["name"] == "Bob"
        assert len(result[3]["0"]) == 1
        assert result[3]["0"][0]["name"] == "Charlie"

    def test_duplicate_same_vote_type_keeps_latest(self):
        """Same voter, same vote type twice -- keeps the latest timestamp."""
        mentions = _make_mentions(
            [
                {
                    "kip": 4,
                    "from": "Alice",
                    "vote": "+1",
                    "timestamp": "2025-01-01 10:00",
                },
                {
                    "kip": 4,
                    "from": "Alice",
                    "vote": "+1",
                    "timestamp": "2025-01-05 10:00",
                },
            ]
        )
        result = create_vote_dict(mentions)

        assert len(result[4]["+1"]) == 1
        assert result[4]["+1"][0]["timestamp"] == "Jan 05, 2025 10:00 UTC"

    def test_voters_sorted_by_timestamp_descending(self):
        """Multiple voters under the same vote type are sorted newest first."""
        mentions = _make_mentions(
            [
                {
                    "kip": 5,
                    "from": "Alice",
                    "vote": "+1",
                    "timestamp": "2025-01-01 10:00",
                },
                {
                    "kip": 5,
                    "from": "Bob",
                    "vote": "+1",
                    "timestamp": "2025-01-03 10:00",
                },
                {
                    "kip": 5,
                    "from": "Charlie",
                    "vote": "+1",
                    "timestamp": "2025-01-02 10:00",
                },
            ]
        )
        result = create_vote_dict(mentions)

        names = [v["name"] for v in result[5]["+1"]]
        assert names == ["Bob", "Charlie", "Alice"]
