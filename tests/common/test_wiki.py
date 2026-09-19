"""Tests for ipper.common.wiki HTTP wiring (retry helper + pagination)."""

import json

import pytest
import requests

from ipper.common.wiki import (
    APACHE_CONFLUENCE_BASE_URL,
    CONTENT_URL,
    child_page_generator,
    get_wiki_page_body,
    get_wiki_page_info,
)


def _json_response(payload: dict, status_code: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    return response


class TestGetWikipediaPageInfo:
    def test_returns_single_result(self, mocker):
        page = {"id": "123", "title": "Kafka Improvement Proposals"}
        mocker.patch(
            "ipper.common.wiki.get_with_retries",
            return_value=_json_response({"results": [page]}),
        )

        result = get_wiki_page_info("KAFKA", "Kafka Improvement Proposals")

        assert result == page

    def test_uses_retry_helper_with_params(self, mocker):
        mock = mocker.patch(
            "ipper.common.wiki.get_with_retries",
            return_value=_json_response({"results": [{"id": "123"}]}),
        )

        get_wiki_page_info("KAFKA", "Kafka Improvement Proposals", timeout=45)

        mock.assert_called_once_with(
            CONTENT_URL,
            params={
                "type": "page",
                "spaceKey": "KAFKA",
                "title": "Kafka Improvement Proposals",
            },
            timeout=45,
        )

    def test_no_results_raises(self, mocker):
        mocker.patch(
            "ipper.common.wiki.get_with_retries",
            return_value=_json_response({"results": []}),
        )

        with pytest.raises(RuntimeError):
            get_wiki_page_info("KAFKA", "Nonexistent Page")

    def test_multiple_results_raises(self, mocker):
        mocker.patch(
            "ipper.common.wiki.get_with_retries",
            return_value=_json_response({"results": [{"id": "1"}, {"id": "2"}]}),
        )

        with pytest.raises(RuntimeError):
            get_wiki_page_info("KAFKA", "Duplicated Page")


class TestGetWikiPageBody:
    def test_returns_body_html(self, mocker):
        mocker.patch(
            "ipper.common.wiki.get_with_retries",
            return_value=_json_response(
                {"body": {"view": {"value": "<p>page body</p>"}}}
            ),
        )

        body = get_wiki_page_body({"id": "123"})

        assert body == "<p>page body</p>"


class TestChildPageGenerator:
    def test_yields_all_children_across_pages(self, mocker):
        """Children are fetched in chunks with pagination; every child of
        every page must be yielded exactly once."""
        children_info = _json_response({"_expandable": {"page": "/children/page"}})
        first_page = _json_response(
            {
                "results": [{"id": "1"}, {"id": "2"}],
                "_links": {"next": "/children/page?start=2"},
            }
        )
        last_page = _json_response(
            {"results": [{"id": "3"}], "_links": {"self": "/children/page"}}
        )
        mock = mocker.patch(
            "ipper.common.wiki.get_with_retries",
            side_effect=[children_info, first_page, last_page],
        )

        results = list(child_page_generator({"_expandable": {"children": "/x"}}, 2, 30))

        assert [child["id"] for child in results] == ["1", "2", "3"]
        assert mock.call_count == 3

    def test_first_child_request_uses_chunk_limit(self, mocker):
        children_info = _json_response({"_expandable": {"page": "/children/page"}})
        first_page = _json_response({"results": [], "_links": {}})
        mock = mocker.patch(
            "ipper.common.wiki.get_with_retries",
            side_effect=[children_info, first_page],
        )

        list(child_page_generator({"_expandable": {"children": "/x"}}, 100, 15))

        assert mock.call_args_list[1].args[0] == (
            APACHE_CONFLUENCE_BASE_URL + "/children/page"
        )
        assert mock.call_args_list[1].kwargs == {
            "params": {"limit": "100", "expand": "history.lastUpdated,body.view"},
            "timeout": 15,
        }

    def test_pagination_follows_next_links(self, mocker):
        children_info = _json_response({"_expandable": {"page": "/children/page"}})
        first_page = _json_response(
            {
                "results": [{"id": "1"}],
                "_links": {"next": "/children/page?start=1"},
            }
        )
        last_page = _json_response({"results": [{"id": "2"}], "_links": {}})
        mock = mocker.patch(
            "ipper.common.wiki.get_with_retries",
            side_effect=[children_info, first_page, last_page],
        )

        list(child_page_generator({"_expandable": {"children": "/x"}}, 1, 30))

        assert (
            mock.call_args_list[2].args[0]
            == APACHE_CONFLUENCE_BASE_URL + "/children/page?start=1"
        )
