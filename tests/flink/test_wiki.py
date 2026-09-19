"""Tests for ipper.flink.wiki parsing and author assembly."""

from bs4 import BeautifulSoup

from ipper.flink.wiki import _add_row_data, process_child_kip


def _make_child_page(
    flip_id: int,
    title: str | None = None,
    body_html: str = "<table><tr><th>Discussion Thread</th><td><a href='https://example.com'>here</a></td></tr></table>",
    last_updated: str = "2025-06-01T00:00:00.000Z",
    created: str = "2025-01-01T00:00:00.000Z",
) -> dict:
    """Build a minimal Confluence child page dict matching the API shape."""
    if title is None:
        title = f"FLIP-{flip_id}: Test Proposal"
    return {
        "title": title,
        "_links": {
            "webui": f"/wiki/flip-{flip_id}",
            "self": f"https://cwiki.apache.org/rest/api/content/{flip_id}",
        },
        "history": {
            "createdDate": created,
            "createdBy": {"displayName": "Author"},
            "lastUpdated": {
                "when": last_updated,
                "by": {"displayName": "Editor"},
            },
        },
        "body": {"view": {"value": body_html}},
    }


class TestAddRowDataAuthors:
    """Tests for the Authors table row handling in _add_row_data()."""

    def test_flip_588_comma_separated_user_links(self):
        """FLIP-588 style: cell with user-link anchors and ' , ' separator."""
        html = (
            "<td><p><a class='confluence-userlink'>Aleksandr Savonin</a> , "
            "<a class='confluence-userlink'>Alan Sheinberg</a></p></td>"
        )
        row_data = BeautifulSoup(html, "html.parser").find("td")
        flip_dict: dict = {}

        _add_row_data("authors", row_data, flip_dict)

        assert flip_dict["wiki_authors"] == ["Aleksandr Savonin", "Alan Sheinberg"]

    def test_single_author(self):
        html = "<td><p>Jane Doe</p></td>"
        row_data = BeautifulSoup(html, "html.parser").find("td")
        flip_dict: dict = {}

        _add_row_data("authors", row_data, flip_dict)

        assert flip_dict["wiki_authors"] == ["Jane Doe"]

    def test_empty_authors_cell(self):
        html = "<td></td>"
        row_data = BeautifulSoup(html, "html.parser").find("td")
        flip_dict: dict = {}

        _add_row_data("authors", row_data, flip_dict)

        assert flip_dict["wiki_authors"] == []


class TestProcessChildKipAuthors:
    """Tests for author assembly in process_child_kip()."""

    def test_authors_row_merged_with_creator(self):
        body_html = (
            "<table>"
            "<tr><th>Discussion Thread</th>"
            "<td><a href='https://example.com/thread'>here</a></td></tr>"
            "<tr><th>Authors</th><td><p>Aleksandr Savonin , Alan Sheinberg</p></td></tr>"
            "</table>"
        )
        child = _make_child_page(588, body_html=body_html)

        result = process_child_kip(588, child)

        # Creator first, then the declared authors
        assert result["authors"] == ["Author", "Aleksandr Savonin", "Alan Sheinberg"]
        # Intermediate key must not leak into the persisted dict
        assert "wiki_authors" not in result
        assert result["created_by"] == "Author"

    def test_authorless_flip_falls_back_to_creator(self):
        body_html = (
            "<table>"
            "<tr><th>Discussion Thread</th>"
            "<td><a href='https://example.com/thread'>here</a></td></tr>"
            "</table>"
        )
        child = _make_child_page(100, body_html=body_html)

        result = process_child_kip(100, child)

        assert result["authors"] == ["Author"]
