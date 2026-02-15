"""Tests for Apache KEYS file parsing and committer matching."""

import datetime as dt

import pytest

from ipper.common.keys import (
    CommitterIndex,
    CommitterInfo,
    parse_email_from_header,
    parse_keys_file,
)

# Sample KEYS file content (based on real Apache KEYS format)
SAMPLE_KEYS = """
This file contains the PGP keys of various developers.

pub   4096R/99369B56 2011-10-06
uid                  Neha Narkhede (Key for signing code and releases) <nehanarkhede@apache.org>
sig 3        99369B56 2011-10-06  Neha Narkhede (Key for signing code and releases) <nehanarkhede@apache.org>
sub   4096R/A71D126A 2011-10-06
sig          99369B56 2011-10-06  Neha Narkhede (Key for signing code and releases) <nehanarkhede@apache.org>

-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG/MacGPG2 v2.0.17 (Darwin)
mQENBEt9wioBCADh0bdDopK7wdLLt6YIEA3KWdXmRhhmY2PDikKZq5EQlwkAmdZF
=gNdQ
-----END PGP PUBLIC KEY BLOCK-----

pub   4096R/0CBAAE9F 2011-05-17
uid                  Sean Owen (CODE SIGNING KEY) <srowen@apache.org>
uid                  Sean Owen <sean.owen@gmail.com>
sub   4096R/B031B8DE 2011-05-17

-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v2.0.19 (FreeBSD)
mQINBE3S6EIBEAC1vT2Z0WK/efTD8OfB0EbYNPrHBZI8ZhJFVwec68/Ax7gt/JS5
=eEDK
-----END PGP PUBLIC KEY BLOCK-----

pub   1024D/04D9B832 2009-03-27
uid                  Alan Gates (No comment) <gates@yahoo-inc.com>
sub   1024g/9390F6CB 2009-03-27

pub   rsa4096 2023-05-03 [SC]
      42EFF58EC9BDFD20FA7DF8B16CCECEFAC04AC304
uid           [ultimate] Luke Chen (CODE SIGNING KEY) <showuon@apache.org>
sig 3        6CCECEFAC04AC304 2023-05-03  Luke Chen (CODE SIGNING KEY) <showuon@apache.org>
sub   rsa4096 2023-05-03 [E]

pub   rsa4096 2020-03-11 [SC]
      8C0D0CA6DE4C4F2D88FEA0098060FC0DA962AFE5
uid           [ultimate] Mickael Maison (CODE SIGNING KEY) <mimaison@apache.org>
sig 3        8060FC0DA962AFE5 2020-03-11  Mickael Maison (CODE SIGNING KEY) <mimaison@apache.org>
sub   rsa4096 2020-03-11 [E]
"""


class TestParseKeysFile:
    """Tests for parse_keys_file function."""

    def test_parse_single_key_single_email(self):
        """Test parsing a key with one email."""
        committers = parse_keys_file(SAMPLE_KEYS)

        # Should find all unique committers (5 unique names)
        assert len(committers) == 5

        # Check first committer (Neha Narkhede) - alphabetically first
        assert committers[0].name == "Alan Gates"

        # Find Neha
        neha = next(c for c in committers if "Neha" in c.name)
        assert neha.name == "Neha Narkhede"
        assert "nehanarkhede@apache.org" in neha.emails

    def test_parse_key_with_multiple_emails(self):
        """Test parsing a key with multiple email addresses."""
        committers = parse_keys_file(SAMPLE_KEYS)

        # Find Sean Owen who has two emails
        sean = next(c for c in committers if "Sean" in c.name)
        assert sean.name == "Sean Owen"
        assert len(sean.emails) == 2
        assert "srowen@apache.org" in sean.emails
        assert "sean.owen@gmail.com" in sean.emails

    def test_parse_removes_comments_from_name(self):
        """Test that comments in parentheses are removed from names."""
        committers = parse_keys_file(SAMPLE_KEYS)

        # Alan Gates has "(No comment)" which should be removed
        alan = next(c for c in committers if "Gates" in c.name)
        assert alan.name == "Alan Gates"
        assert "(No comment)" not in alan.name
        assert "gates@yahoo-inc.com" in alan.emails

    def test_parse_empty_content(self):
        """Test parsing empty KEYS content."""
        committers = parse_keys_file("")
        assert committers == []

    def test_parse_malformed_keys(self):
        """Test parsing malformed KEYS content."""
        malformed = "pub   4096R/12345678 2020-01-01\n"  # No uid line
        committers = parse_keys_file(malformed)
        assert committers == []

    def test_parse_new_format_keys(self):
        """Test parsing keys with new format (key ID on separate line)."""
        committers = parse_keys_file(SAMPLE_KEYS)

        # Find Luke Chen (new format)
        luke = next((c for c in committers if "Luke Chen" in c.name), None)
        assert luke is not None, "Luke Chen should be found"
        assert luke.name == "Luke Chen"
        assert "showuon@apache.org" in luke.emails

    def test_parse_removes_brackets_from_name(self):
        """Test that trust indicators in square brackets are removed from names."""
        committers = parse_keys_file(SAMPLE_KEYS)

        # Luke Chen has [ultimate] which should be removed
        luke = next((c for c in committers if "Luke" in c.name), None)
        assert luke is not None
        assert "[ultimate]" not in luke.name
        assert luke.name == "Luke Chen"

        # Mickael has [ultimate] which should be removed
        mickael = next((c for c in committers if "Mickael" in c.name), None)
        assert mickael is not None
        assert "[ultimate]" not in mickael.name
        assert mickael.name == "Mickael Maison"


class TestParseEmailFromHeader:
    """Tests for parse_email_from_header function."""

    def test_parse_standard_format(self):
        """Test parsing standard 'Name <email>' format."""
        name, email = parse_email_from_header('"John Doe" <john@example.com>')
        assert name == "John Doe"
        assert email == "john@example.com"

    def test_parse_name_without_quotes(self):
        """Test parsing 'Name <email>' without quotes."""
        name, email = parse_email_from_header("John Doe <john@example.com>")
        assert name == "John Doe"
        assert email == "john@example.com"

    def test_parse_email_only(self):
        """Test parsing email address without name."""
        name, email = parse_email_from_header("john@example.com")
        assert name == ""
        assert email == "john@example.com"

    def test_parse_email_with_comment(self):
        """Test parsing 'email (Name)' format."""
        name, email = parse_email_from_header("john@example.com (John Doe)")
        assert name == "John Doe"
        assert email == "john@example.com"


class TestCommitterInfo:
    """Tests for CommitterInfo dataclass."""

    def test_email_normalization(self):
        """Test that emails are normalized to lowercase."""
        info = CommitterInfo(
            name="Test User",
            emails=["Test@Example.COM", "  user@domain.org  "],
            raw_uid="Test User <test@example.com>",
        )
        assert info.emails == ["test@example.com", "user@domain.org"]


class TestCommitterIndex:
    """Tests for CommitterIndex class."""

    @pytest.fixture
    def sample_index(self):
        """Create a sample CommitterIndex for testing."""
        committers = [
            CommitterInfo(
                name="John Smith",
                emails=["john@apache.org", "jsmith@company.com"],
                raw_uid="John Smith <john@apache.org>",
            ),
            CommitterInfo(
                name="Jane Doe",
                emails=["jane@apache.org"],
                raw_uid="Jane Doe <jane@apache.org>",
            ),
        ]
        return CommitterIndex(
            committers=committers,
            last_updated=dt.datetime.now(dt.UTC),
            source_url="https://example.com/KEYS",
        )

    def test_exact_email_match(self, sample_index):
        """Test exact email matching."""
        result = sample_index.match_email_exact("john@apache.org")
        assert result is not None
        assert result.name == "John Smith"

    def test_exact_email_match_case_insensitive(self, sample_index):
        """Test that email matching is case-insensitive."""
        result = sample_index.match_email_exact("JOHN@APACHE.ORG")
        assert result is not None
        assert result.name == "John Smith"

    def test_exact_email_match_with_whitespace(self, sample_index):
        """Test that email matching handles whitespace."""
        result = sample_index.match_email_exact("  john@apache.org  ")
        assert result is not None
        assert result.name == "John Smith"

    def test_exact_email_match_secondary_email(self, sample_index):
        """Test matching against secondary email."""
        result = sample_index.match_email_exact("jsmith@company.com")
        assert result is not None
        assert result.name == "John Smith"

    def test_exact_email_no_match(self, sample_index):
        """Test email matching with no match."""
        result = sample_index.match_email_exact("unknown@example.com")
        assert result is None

    def test_exact_email_empty_string(self, sample_index):
        """Test email matching with empty string."""
        result = sample_index.match_email_exact("")
        assert result is None

    def test_fuzzy_name_match_exact(self, sample_index):
        """Test fuzzy name matching with exact match."""
        result, score = sample_index.match_name_fuzzy("John Smith")
        assert result is not None
        assert result.name == "John Smith"
        assert score == 100.0

    def test_fuzzy_name_match_case_insensitive(self, sample_index):
        """Test that name matching is case-insensitive."""
        result, score = sample_index.match_name_fuzzy("john smith")
        assert result is not None
        assert result.name == "John Smith"
        assert score == 100.0

    def test_fuzzy_name_match_with_typo(self, sample_index):
        """Test fuzzy name matching with minor typo."""
        result, score = sample_index.match_name_fuzzy("Jon Smith")
        assert result is not None
        assert result.name == "John Smith"
        assert score >= 70.0  # Should meet threshold

    def test_fuzzy_name_match_with_middle_initial(self, sample_index):
        """Test fuzzy name matching with middle initial."""
        result, score = sample_index.match_name_fuzzy("John A. Smith")
        assert result is not None
        assert result.name == "John Smith"
        # Score may vary but should be reasonably high

    def test_fuzzy_name_match_below_threshold(self, sample_index):
        """Test fuzzy name matching below threshold."""
        result, score = sample_index.match_name_fuzzy("Bob Johnson", threshold=70.0)
        assert result is None
        assert score < 70.0

    def test_fuzzy_name_match_empty_string(self, sample_index):
        """Test fuzzy name matching with empty string."""
        result, score = sample_index.match_name_fuzzy("")
        assert result is None
        assert score == 0.0

    def test_is_committer_by_email(self, sample_index):
        """Test is_committer with email match."""
        is_match, confidence, method = sample_index.is_committer(
            name="Unknown Name",
            email="john@apache.org",
        )
        assert is_match is True
        assert confidence == 100.0
        assert method == "email"

    def test_is_committer_by_name(self, sample_index):
        """Test is_committer with name match only."""
        is_match, confidence, method = sample_index.is_committer(
            name="John Smith",
            email="different@example.com",
        )
        assert is_match is True
        assert confidence == 100.0
        assert method == "name"

    def test_is_committer_email_priority_over_name(self, sample_index):
        """Test that email match takes priority over name match."""
        is_match, confidence, method = sample_index.is_committer(
            name="Jane Doe",  # Would match Jane by name
            email="john@apache.org",  # But matches John by email
        )
        assert is_match is True
        assert confidence == 100.0
        assert method == "email"

    def test_is_committer_no_match(self, sample_index):
        """Test is_committer with no match."""
        is_match, confidence, method = sample_index.is_committer(
            name="Bob Johnson",
            email="bob@example.com",
        )
        assert is_match is False
        assert confidence == 0.0
        assert method == "none"

    def test_is_committer_empty_inputs(self, sample_index):
        """Test is_committer with empty inputs."""
        is_match, confidence, method = sample_index.is_committer(
            name="",
            email="",
        )
        assert is_match is False
        assert confidence == 0.0
        assert method == "none"

    def test_parse_new_format_keys(self):
        """Test parsing keys with new format (key ID on separate line)."""
        committers = parse_keys_file(SAMPLE_KEYS)

        # Find Luke Chen (new format)
        luke = next((c for c in committers if "Luke Chen" in c.name), None)
        assert luke is not None, "Luke Chen should be found"
        assert luke.name == "Luke Chen"
        assert "showuon@apache.org" in luke.emails

    def test_parse_removes_brackets_from_name(self):
        """Test that trust indicators in square brackets are removed from names."""
        committers = parse_keys_file(SAMPLE_KEYS)

        # Luke Chen has [ultimate] which should be removed
        luke = next((c for c in committers if "Luke" in c.name), None)
        assert luke is not None
        assert "[ultimate]" not in luke.name
        assert luke.name == "Luke Chen"

        # Mickael has [ultimate] which should be removed
        mickael = next((c for c in committers if "Mickael" in c.name), None)
        assert mickael is not None
        assert "[ultimate]" not in mickael.name
        assert mickael.name == "Mickael Maison"
