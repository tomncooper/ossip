"""Tests for ipper.common.mailing_list module."""

import json

import pytest

from ipper.common.mailing_list import (
    get_months_to_download,
    load_metadata,
    parse_for_vote,
    parse_message_timestamp,
    save_metadata,
    vote_converter,
)


class TestParseMessageTimestamp:
    """Tests for the parse_message_timestamp function."""

    def test_standard_format(self):
        """Test parsing standard email date format."""
        date_str = "Fri, 07 Feb 2026 12:00:00 +0000"
        result = parse_message_timestamp(date_str)

        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 7
        assert result.hour == 12
        assert result.minute == 0

    def test_format_with_timezone_string(self):
        """Test parsing date format with timezone string in parentheses."""
        date_str = "Fri, 07 Feb 2026 12:00:00 +0000 (UTC)"
        result = parse_message_timestamp(date_str)

        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 7

    def test_format_with_different_timezone_string(self):
        """Test parsing with different timezone abbreviations."""
        date_str = "Fri, 07 Feb 2026 12:00:00 +0000 (GMT)"
        result = parse_message_timestamp(date_str)

        assert result is not None
        assert result.year == 2026

    def test_negative_timezone_offset(self):
        """Test parsing with negative timezone offset."""
        date_str = "Fri, 07 Feb 2026 12:00:00 -0500"
        result = parse_message_timestamp(date_str)

        assert result is not None
        assert result.year == 2026
        assert result.month == 2

    def test_invalid_format_returns_none(self):
        """Test that invalid date format returns None."""
        date_str = "This is not a valid date"
        result = parse_message_timestamp(date_str)

        assert result is None

    def test_real_world_date_examples(self):
        """Test with real date strings from Apache mailing lists."""
        test_cases = [
            "Mon, 19 Feb 2015 14:29:32 +0000",
            "Wed, 25 Feb 2015 01:24:15 +0000",
            "Thu, 03 Feb 2026 12:42:00 +0000 (UTC)",
        ]

        for date_str in test_cases:
            result = parse_message_timestamp(date_str)
            assert result is not None, f"Failed to parse: {date_str}"


class TestParseForVote:
    """Tests for the parse_for_vote function."""

    def test_binding_plus_one_vote(self):
        """Test parsing +1 binding vote."""
        payload = "+1 (binding)"
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "+1"

    def test_binding_minus_one_vote(self):
        """Test parsing -1 binding vote."""
        payload = "-1 (binding)"
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "-1"

    def test_binding_zero_vote(self):
        """Test parsing 0 binding vote."""
        payload = "0 (binding)"
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "0"

    def test_case_insensitive_binding(self):
        """Test that (BINDING) is case insensitive."""
        payloads = [
            "+1 (BINDING)",
            "+1 (Binding)",
            "+1 (BiNdInG)",
        ]

        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result == "+1", f"Failed for: {payload}"

    def test_non_binding_vote_returns_none(self):
        """Test that non-binding votes return None."""
        payloads = [
            "+1",
            "+1 (non-binding)",
            "I vote +1",
        ]

        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result is None, f"Should be None for: {payload}"

    def test_vote_with_extra_whitespace(self):
        """Test parsing votes with various whitespace."""
        payloads = [
            "+1  (binding)",
            "+1   (binding)",
            "+1\t(binding)",
        ]

        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result == "+1", f"Failed for: {payload}"

    def test_vote_in_multiline_message(self):
        """Test parsing vote in a multiline message."""
        payload = """
Hi all,

I'm voting on this proposal.

+1 (binding)

Thanks,
John
"""
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "+1"

    def test_ignores_quoted_votes(self):
        """Test that votes in quoted text (starting with >) are ignored."""
        payload = """
> +1 (binding)
Actually, I vote differently:
-1 (binding)
"""
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "-1"

    def test_no_vote_found(self):
        """Test that messages without votes return None."""
        payloads = [
            "This is just a discussion message",
            "What do you think about this?",
            "I agree with the proposal",
        ]

        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result is None

    def test_plus_one_without_plus_sign(self):
        """Test parsing '1 (binding)' - currently not supported."""
        payload = "1 (binding)"
        result = parse_for_vote(payload, "voter@example.com")
        # The regex requires +1 or -1, plain "1" is not matched
        assert result is None

    def test_binding_vote_no_space(self):
        """Test parsing binding vote with no space before (binding)."""
        payload = "+1(binding)"
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "+1"

    def test_binding_vote_embedded_in_text(self):
        """Test parsing binding vote embedded in prose."""
        payloads = [
            "+1 from me(binding)",
            "+1 from me (binding)",
            "Thanks for this improvement, +1 from me(binding)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result == "+1", f"Failed for: {payload}"

    def test_binding_vote_with_typo_binging(self):
        """Test parsing binding vote with 'binging' typo (actual KIP-927 case)."""
        payloads = [
            "+1(binging)",
            "+1 from me(binging)",
            "Thanks for this improvement, +1 from me(binging)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result == "+1", f"Failed for: {payload}"

    def test_binding_vote_with_typo_bindng(self):
        """Test parsing binding vote with missing 'i' typo."""
        payload = "+1(bindng)"
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "+1"

    def test_binding_vote_with_typo_bindign(self):
        """Test parsing binding vote with transposed 'gn' typo."""
        payload = "+1(bindign)"
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "+1"

    def test_binding_vote_case_insensitive_fuzzy(self):
        """Test that fuzzy matching works with different cases."""
        payloads = [
            "+1(BINGING)",
            "+1(Binging)",
            "+1(BINDNG)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result == "+1", f"Failed for: {payload}"

    def test_non_binding_without_hyphen(self):
        """Test parsing non-binding vote without hyphen (1,037 real votes!)."""
        payloads = [
            "+1 (non binding)",
            "+1(non binding)",
            "-1 (non binding)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result is None, f"Should be non-binding for: {payload}"

    def test_non_binding_no_space_or_hyphen(self):
        """Test parsing non-binding vote with no space or hyphen (116 real votes!)."""
        payloads = [
            "+1(nonbinding)",
            "+1 (nonbinding)",
            "0(nonbinding)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result is None, f"Should be non-binding for: {payload}"

    def test_non_binding_with_typo_in_binding_part(self):
        """Test parsing non-binding vote with typo in 'binding' part."""
        payloads = [
            "+1(non-binging)",
            "+1 (non bindng)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result is None, f"Should be non-binding for: {payload}"

    def test_non_binding_case_insensitive(self):
        """Test that non-binding fuzzy matching is case insensitive."""
        payloads = [
            "+1(NON-BINDING)",
            "+1(Non-Binding)",
            "+1(NON BINDING)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            assert result is None, f"Should be non-binding for: {payload}"

    def test_unrelated_parenthetical_text(self):
        """Test that unrelated parenthetical text doesn't match."""
        payloads = [
            "+1 (opinion)",
            "+1 (see KIP-123)",
            "+1 (my thoughts)",
        ]
        for payload in payloads:
            result = parse_for_vote(payload, "voter@example.com")
            # Should not match binding or non-binding, returns None (no committer index)
            assert result is None, f"Should not match for: {payload}"

    def test_explicit_binding_takes_precedence_over_incidental_zero(self):
        """Test that explicit binding votes are prioritized over incidental zeros.

        Regression test for bug where "0 concerns" was incorrectly matched as a
        vote instead of the explicit "+1 (binding)" that appeared later.
        """
        payload = """I have 0 concerns about this proposal.

I'm +1 (binding)

Thanks, Federico!

It looks like a nice improvement to me.

-John"""
        result = parse_for_vote(payload, "voter@example.com")
        assert result == "+1", (
            "Explicit +1 (binding) should be detected, not incidental 0"
        )


class TestVoteConverter:
    """Tests for the vote_converter function."""

    def test_convert_positive_vote(self):
        """Test converting +1 vote."""
        result = vote_converter("1.0")
        assert result == "+1"

    def test_convert_negative_vote(self):
        """Test converting -1 vote."""
        result = vote_converter("-1.0")
        assert result == "-1"

    def test_convert_zero_vote(self):
        """Test converting 0 vote."""
        result = vote_converter("0.0")
        assert result == "0"

    def test_empty_string_returns_none(self):
        """Test that empty string returns None."""
        result = vote_converter("")
        assert result is None

    def test_none_input_returns_none(self):
        """Test that None input causes TypeError (as expected by pandas)."""
        with pytest.raises(TypeError):
            vote_converter(None)


class TestMetadataFunctions:
    """Tests for metadata save/load functions."""

    def test_save_metadata(self, tmp_path):
        """Test saving metadata to a file."""
        metadata_path = tmp_path / "test_metadata.json"

        save_metadata(metadata_path, 2026, 2)

        assert metadata_path.exists()

        with open(metadata_path) as f:
            data = json.load(f)

        assert data["latest_mbox_year"] == 2026
        assert data["latest_mbox_month"] == 2
        assert "last_updated" in data

    def test_load_metadata(self, tmp_path):
        """Test loading metadata from a file."""
        metadata_path = tmp_path / "test_metadata.json"

        # Create metadata file
        metadata = {
            "last_updated": "2026-02-07T12:00:00+00:00",
            "latest_mbox_year": 2026,
            "latest_mbox_month": 2,
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        # Load it back
        result = load_metadata(metadata_path)

        assert result is not None
        assert result["latest_mbox_year"] == 2026
        assert result["latest_mbox_month"] == 2

    def test_load_metadata_nonexistent_file(self, tmp_path):
        """Test loading metadata from nonexistent file returns None."""
        metadata_path = tmp_path / "nonexistent.json"
        result = load_metadata(metadata_path)
        assert result is None


class TestGetMonthsToDownload:
    """Tests for the get_months_to_download function."""

    def test_with_existing_metadata(self, tmp_path):
        """Test getting months with existing metadata (incremental update)."""
        metadata_path = tmp_path / "metadata.json"

        # Create metadata indicating last download was December 2025
        metadata = {
            "last_updated": "2025-12-15T12:00:00+00:00",
            "latest_mbox_year": 2025,
            "latest_mbox_month": 12,
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        # Should return months from December 2025 onwards
        result = get_months_to_download(metadata_path)

        assert len(result) >= 2  # At least Dec 2025 and current months
        assert result[0] == (2025, 12)

    def test_without_metadata_uses_days_back(self, tmp_path):
        """Test getting months without metadata uses days_back parameter."""
        metadata_path = tmp_path / "nonexistent.json"

        # Request 60 days back
        result = get_months_to_download(metadata_path, days_back=60)

        # Should return approximately 2-3 months
        assert len(result) >= 2
        assert len(result) <= 3

    def test_days_back_overrides_metadata(self, tmp_path):
        """Test that days_back parameter overrides metadata."""
        metadata_path = tmp_path / "metadata.json"

        # Create metadata
        metadata = {
            "last_updated": "2025-01-01T12:00:00+00:00",
            "latest_mbox_year": 2025,
            "latest_mbox_month": 1,
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        # Override with days_back=30
        result = get_months_to_download(metadata_path, days_back=30)

        # Should only return ~1-2 months, not from January 2025
        assert len(result) <= 2


class TestParseForVoteWithCommitters:
    """Tests for parse_for_vote with committer index integration."""

    @pytest.fixture
    def sample_committer_index(self):
        """Create a sample committer index for testing."""
        import datetime as dt

        from ipper.common.keys import CommitterIndex, CommitterInfo

        committers = [
            CommitterInfo(
                name="Alice Johnson",
                emails=["alice@apache.org"],
                raw_uid="Alice Johnson <alice@apache.org>",
            ),
            CommitterInfo(
                name="Bob Smith",
                emails=["bob@apache.org", "bob.smith@company.com"],
                raw_uid="Bob Smith <bob@apache.org>",
            ),
        ]
        return CommitterIndex(
            committers=committers,
            last_updated=dt.datetime.now(dt.UTC),
            source_url="https://example.com/KEYS",
        )

    def test_unmarked_vote_from_committer_by_email(
        self, sample_committer_index, capsys
    ):
        """Test that unmarked vote from committer (matched by email) is counted as binding."""
        payload = "+1"
        result = parse_for_vote(
            payload, "Alice Johnson <alice@apache.org>", sample_committer_index
        )
        assert result == "+1"

        # Check that detection was logged
        captured = capsys.readouterr()
        assert "binding vote from committer" in captured.out
        assert "Alice Johnson" in captured.out
        assert "email" in captured.out

    def test_unmarked_vote_from_committer_by_name(self, sample_committer_index, capsys):
        """Test that unmarked vote from committer (matched by name) is counted as binding."""
        payload = "+1"
        # Different email but same name
        result = parse_for_vote(
            payload, "Alice Johnson <alice@different.com>", sample_committer_index
        )
        assert result == "+1"

        # Check that detection was logged
        captured = capsys.readouterr()
        assert "binding vote from committer" in captured.out
        assert "Alice Johnson" in captured.out
        assert "name" in captured.out

    def test_unmarked_vote_from_non_committer(self, sample_committer_index):
        """Test that unmarked vote from non-committer is not counted."""
        payload = "+1"
        result = parse_for_vote(
            payload, "Charlie Brown <charlie@example.com>", sample_committer_index
        )
        assert result is None

    def test_explicit_binding_always_counted(self, sample_committer_index):
        """Test that explicit (binding) votes are always counted, even from non-committers."""
        payload = "+1 (binding)"
        result = parse_for_vote(
            payload, "Charlie Brown <charlie@example.com>", sample_committer_index
        )
        assert result == "+1"

    def test_explicit_non_binding_never_counted(self, sample_committer_index):
        """Test that explicit (non-binding) votes are never counted, even from committers."""
        payload = "+1 (non-binding)"
        result = parse_for_vote(
            payload, "Alice Johnson <alice@apache.org>", sample_committer_index
        )
        assert result is None

    def test_committer_with_secondary_email(self, sample_committer_index, capsys):
        """Test that committer is matched by secondary email."""
        payload = "-1"
        result = parse_for_vote(
            payload, "Bob Smith <bob.smith@company.com>", sample_committer_index
        )
        assert result == "-1"

        # Check email match
        captured = capsys.readouterr()
        assert "binding vote from committer" in captured.out
        assert "email" in captured.out

    def test_no_committer_index_treats_unmarked_as_non_binding(self):
        """Test that without committer index, unmarked votes are treated as non-binding."""
        payload = "+1"
        result = parse_for_vote(payload, "Alice Johnson <alice@apache.org>", None)
        assert result is None

    def test_backward_compatibility_explicit_binding(self):
        """Test backward compatibility: explicit (binding) works without committer index."""
        payload = "+1 (binding)"
        result = parse_for_vote(payload, "anyone@example.com", None)
        assert result == "+1"
