"""Tests for ipper.common.authors module."""

import logging

from ipper.common.authors import (
    FUZZY_DEDUPE_THRESHOLD,
    dedupe_authors,
    is_author_line,
    parse_authors_from_text,
)


class TestIsAuthorLine:
    """Tests for is_author_line()."""

    def test_plain_label(self):
        assert is_author_line("Authors: Luke Chen, Federico Valeri")

    def test_label_without_colon(self):
        assert is_author_line("Authors Luke Chen")

    def test_co_author_label(self):
        assert is_author_line("Co Author: Satish Duggana")

    def test_co_dash_author_label(self):
        assert is_author_line("Co-Author: Satish Duggana")

    def test_co_authors_label(self):
        assert is_author_line("Co-Authors: Satish Duggana")

    def test_lowercase(self):
        assert is_author_line("authors: Luke Chen")

    def test_prose_not_author_line(self):
        assert not is_author_line(
            "Many authors have contributed to this proposal over the years"
        )

    def test_empty_string(self):
        assert not is_author_line("")

    def test_other_field(self):
        assert not is_author_line("Discussion thread: https://example.com")


class TestParseAuthorsFromText:
    """Tests for parse_authors_from_text() with real-world formats."""

    def test_kip_1279_plain_comma_separated(self):
        """KIP-1279: <p><span><strong>Authors</strong>: A, B, C</span></p>"""
        html = (
            "<p><span><strong>Authors</strong>: Luke Chen, Federico Valeri, "
            "Omnia Ibrahim, Gaurav Narula</span></p>"
        )
        from bs4 import BeautifulSoup

        para = BeautifulSoup(html, "html.parser").find("p")
        assert parse_authors_from_text(para.text) == [
            "Luke Chen",
            "Federico Valeri",
            "Omnia Ibrahim",
            "Gaurav Narula",
        ]

    def test_kip_1165_colon_inside_bold_label(self):
        """KIP-1165: <strong>Authors:</strong> Greg Harris, Ivan Yurchenko"""
        text = "Authors: Greg Harris, Ivan Yurchenko, Jorge Quilcate"
        assert parse_authors_from_text(text) == [
            "Greg Harris",
            "Ivan Yurchenko",
            "Jorge Quilcate",
        ]

    def test_kip_1134_names_in_em(self):
        """KIP-1134: <strong>Authors: </strong><em>Daniel Urban, ...</em>"""
        html = "<strong>Authors: </strong><em>Daniel Urban, Gergely Harmadas</em>"
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text()
        assert parse_authors_from_text(text) == [
            "Daniel Urban",
            "Gergely Harmadas",
        ]

    def test_kip_1303_nested_spans(self):
        """KIP-1303/1360: names split across nested styled spans."""
        html = (
            '<p><strong>Authors:</strong> <span style="color:#0000ff">'
            "<span>First Author</span> and <span>Second Author</span></span></p>"
        )
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text()
        assert parse_authors_from_text(text) == ["First Author", "Second Author"]

    def test_kip_1320_shared_paragraph_stops_at_discussion_thread(self):
        """KIP-1320: single paragraph shared with other fields, <br/>-separated."""
        html = (
            "<p><strong>Authors:</strong> Eric Chang<br/>"
            "<strong>Discussion thread:</strong> <a href='https://example.com'>"
            "here</a></p>"
        )
        from bs4 import BeautifulSoup

        para = BeautifulSoup(html, "html.parser").find("p")
        # Only "Eric Chang" should be parsed; "Discussion thread: ..." is dropped
        assert parse_authors_from_text(para.text) == ["Eric Chang"]

    def test_shared_paragraph_stops_at_vote_thread(self):
        text = "Authors: Jane DoeVote thread: https://example.com/vote"
        assert parse_authors_from_text(text) == ["Jane Doe"]

    def test_shared_paragraph_stops_at_jira(self):
        text = "Authors: Jane DoeJIRA: KAFKA-1234"
        assert parse_authors_from_text(text) == ["Jane Doe"]

    def test_kip_1255_co_author_single_name(self):
        """KIP-1255: <strong>Co Author: </strong><a>Satish ...</a>"""
        html = '<p><strong>Co Author: </strong><a class="confluence-userlink">Satish Duggana</a></p>'
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text()
        assert parse_authors_from_text(text) == ["Satish Duggana"]

    def test_flip_588_comma_space_style(self):
        """FLIP-588: table cell with user-link anchors and ' , ' separator."""
        html = (
            "<td><p><a class='confluence-userlink'>Aleksandr Savonin</a> , "
            "<a class='confluence-userlink'>Alan Sheinberg</a></p></td>"
        )
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text()
        assert parse_authors_from_text(text) == [
            "Aleksandr Savonin",
            "Alan Sheinberg",
        ]

    def test_kip_1115_names_with_inline_emails(self):
        """KIP-1115: 'Name email Name email' with no other delimiter.

        The email addresses must act as delimiters, otherwise the whole
        paragraph parses as one giant author entry (which used to blow up
        the author filter dropdown width).
        """
        html = (
            "<p><em><strong>Authors</strong>: </em>"
            "<span>Vince Rose </span>"
            "<a class='external-link' href='mailto:vrose@confluent.io'>"
            "<span>vrose@confluent.io</span></a> "
            "<em><span>Farid Zakaria </span>"
            "<a class='external-link' href='mailto:fzakaria@confluent.io'>"
            "<span>fzakaria@confluent.io</span></a></em></p>"
        )
        from bs4 import BeautifulSoup

        para = BeautifulSoup(html, "html.parser").find("p")
        assert parse_authors_from_text(para.text) == [
            "Vince Rose",
            "Farid Zakaria",
        ]

    def test_angle_bracketed_emails_dropped(self):
        """Common 'Name <email>' convention."""
        assert parse_authors_from_text(
            "Authors: Jane Doe <jane@example.com>, John Smith"
        ) == ["Jane Doe", "John Smith"]

    def test_parenthesised_email_dropped(self):
        assert parse_authors_from_text("Authors: John Smith (john@example.com)") == [
            "John Smith"
        ]

    def test_bare_email_is_not_a_name(self):
        """An author line containing only an email yields no names."""
        assert parse_authors_from_text("Authors: jane@example.com") == []

    def test_and_delimiter(self):
        assert parse_authors_from_text("Authors: Jane Doe and John Smith") == [
            "Jane Doe",
            "John Smith",
        ]

    def test_and_within_name_is_not_a_delimiter(self):
        assert parse_authors_from_text("Authors: John Anderson, Jane Doe") == [
            "John Anderson",
            "Jane Doe",
        ]

    def test_semicolon_delimiter(self):
        assert parse_authors_from_text("Authors: Jane Doe; John Smith") == [
            "Jane Doe",
            "John Smith",
        ]

    def test_trailing_punctuation_stripped(self):
        assert parse_authors_from_text("Authors: Jane Doe., John Smith;") == [
            "Jane Doe",
            "John Smith",
        ]

    def test_zero_width_characters_removed(self):
        text = "Authors: Jane\u200b Doe, John Smith\u200c"
        assert parse_authors_from_text(text) == ["Jane Doe", "John Smith"]

    def test_empty_entries_dropped(self):
        assert parse_authors_from_text("Authors: , Jane Doe, , John Smith,") == [
            "Jane Doe",
            "John Smith",
        ]

    def test_no_label_treated_as_name_list(self):
        assert parse_authors_from_text("Jane Doe, John Smith") == [
            "Jane Doe",
            "John Smith",
        ]

    def test_empty_text(self):
        assert parse_authors_from_text("") == []

    def test_single_name(self):
        assert parse_authors_from_text("Authors: Jane Doe") == ["Jane Doe"]

    def test_full_width_colon_label(self):
        assert parse_authors_from_text("Authors：Jane Doe, John Smith") == [
            "Jane Doe",
            "John Smith",
        ]


class TestDedupeAuthors:
    """Tests for dedupe_authors()."""

    def test_exact_duplicates_collapse(self):
        assert dedupe_authors(["Jane Doe", "Jane Doe"]) == ["Jane Doe"]

    def test_case_differences_collapse(self):
        assert dedupe_authors(["Jane Doe", "JANE DOE"]) == ["Jane Doe"]

    def test_whitespace_differences_collapse(self):
        assert dedupe_authors(["Jane Doe", "  Jane Doe  "]) == ["Jane Doe"]

    def test_fuzzy_duplicates_collapse(self):
        assert dedupe_authors(["Greg Harris", "Gregory Harris"]) == ["Greg Harris"]

    def test_distinct_names_not_collapsed(self):
        """Names below the fuzzy threshold must both survive.

        Note: the plan originally suggested "Tom Cooper" vs "Tim Cooper",
        but token_sort_ratio scores that pair at 90 (above the 85 threshold),
        so "Tom Cooper" vs "Bob Cooper" (score 60) is used instead.
        """
        assert dedupe_authors(["Tom Cooper", "Bob Cooper"]) == [
            "Tom Cooper",
            "Bob Cooper",
        ]

    def test_fuzzy_dedupe_preserves_order(self):
        names = ["Carol", "Greg Harris", "Alice", "Gregory Harris"]
        assert dedupe_authors(names) == ["Carol", "Greg Harris", "Alice"]

    def test_empty_names_dropped(self):
        assert dedupe_authors(["", "   ", "Jane Doe"]) == ["Jane Doe"]

    def test_empty_input(self):
        assert dedupe_authors([]) == []

    def test_custom_threshold(self):
        # "Greg Harris" vs "Harry Gregson" scores ~75, so a threshold of 70
        # merges them while the default (85) does not
        assert dedupe_authors(["Greg Harris", "Harry Gregson"], threshold=70.0) == [
            "Greg Harris"
        ]
        assert dedupe_authors(["Greg Harris", "Harry Gregson"]) == [
            "Greg Harris",
            "Harry Gregson",
        ]

    def test_default_threshold_is_85(self):
        assert FUZZY_DEDUPE_THRESHOLD == 85.0

    def test_fuzzy_merge_logged(self, caplog):
        with caplog.at_level(logging.INFO):
            dedupe_authors(["Greg Harris", "Gregory Harris"])
        assert any(
            "Gregory Harris" in record.message and "Greg Harris" in record.message
            for record in caplog.records
        )
