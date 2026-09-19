"""Tests for ipper.flink.wiki parsing and author assembly."""

from bs4 import BeautifulSoup

import ipper.flink.wiki as flink_wiki
from ipper.flink.wiki import _add_row_data, get_flip_information, process_child_kip


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


class TestGetFlipInformationBackfill:
    """Tests for the authors-backfill guard in get_flip_information()."""

    def _run_update(self, mocker, cache_data, refresh_days=30):
        child = _make_child_page(700)
        mocker.patch(
            "ipper.flink.wiki.child_page_generator",
            return_value=iter([child]),
        )
        spy = mocker.spy(flink_wiki, "process_child_kip")

        result = get_flip_information(
            {"id": "123"},
            existing_cache={int(k): v for k, v in cache_data.items()},
            refresh_days=refresh_days,
        )

        return result, spy

    def test_old_flip_without_authors_backfilled(self, mocker):
        """A cached FLIP created outside the refresh window but lacking the
        authors field must NOT be skipped (backfill requirement)."""
        cache_data = {
            "700": {
                "id": 700,
                "title": "FLIP-700: Old Title",
                "created_on": "2023-01-01T00:00:00.000Z",
                "last_modified_on": "2024-01-01T00:00:00.000Z",
                "state": "accepted",
            }
        }

        result, spy = self._run_update(mocker, cache_data)

        spy.assert_called()  # entry reprocessed so authors get backfilled
        assert result[700]["authors"] == ["Author"]

    def test_old_flip_with_authors_skipped(self, mocker):
        """A cached FLIP outside the refresh window that already has authors
        is skipped (backfill is self-clearing)."""
        cache_data = {
            "700": {
                "id": 700,
                "title": "FLIP-700: Old Title",
                "created_on": "2023-01-01T00:00:00.000Z",
                "last_modified_on": "2024-01-01T00:00:00.000Z",
                "state": "accepted",
                "authors": ["Existing Author"],
            }
        }

        result, spy = self._run_update(mocker, cache_data)

        spy.assert_not_called()
        assert result[700]["authors"] == ["Existing Author"]

    def test_recent_flip_refreshed_without_authors(self, mocker):
        """A FLIP created inside the refresh window is refreshed even when
        authors are missing (pre-existing behaviour)."""
        cache_data = {
            "700": {
                "id": 700,
                "title": "FLIP-700: Old Title",
                "created_on": "2099-01-01T00:00:00.000Z",
                "last_modified_on": "2099-01-01T00:00:00.000Z",
                "state": "accepted",
            }
        }

        result, spy = self._run_update(mocker, cache_data)

        spy.assert_called()
        assert result[700]["authors"] == ["Author"]
