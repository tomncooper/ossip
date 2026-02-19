"""Tests for ipper.kafka.wiki state parsing and cache update logic."""

import json

import pytest

from ipper.common.constants import NOT_SET_STR, IPState
from ipper.kafka.wiki import (
    ACCEPTED_TERMS,
    NOT_ACCEPTED_TERMS,
    UNDER_DISCUSSION_TERMS,
    enrich_kip_info,
    get_current_state,
    get_kip_information,
)

# The exact template placeholder text from the KIP wiki template
TEMPLATE_PLACEHOLDER = '[One of "Under Discussion", "Accepted", "Rejected"]'


def _make_child_page(
    kip_id: int,
    title: str | None = None,
    body_html: str = "<p>Current state: Accepted</p>",
    last_updated: str = "2025-06-01T00:00:00.000Z",
    created: str = "2025-01-01T00:00:00.000Z",
) -> dict:
    """Build a minimal Confluence child page dict matching the API shape."""
    if title is None:
        title = f"KIP-{kip_id}: Test Proposal"
    return {
        "title": title,
        "_links": {
            "webui": f"/wiki/kip-{kip_id}",
            "self": f"https://cwiki.apache.org/rest/api/content/{kip_id}",
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


class TestGetCurrentState:
    """Tests for get_current_state()."""

    def test_template_default_returns_none(self):
        """Regression test: template placeholder must not match 'accepted'."""
        result = get_current_state(f"Current state: {TEMPLATE_PLACEHOLDER}")
        assert result is None

    def test_template_default_case_insensitive(self):
        """Template detection is case-insensitive."""
        result = get_current_state(
            'Current state: [one of "Under Discussion", "Accepted", "Rejected"]'
        )
        assert result is None

    def test_template_default_extra_whitespace(self):
        """Template detection handles extra whitespace after 'one of'."""
        result = get_current_state(
            'Current state: [One of   "Under Discussion", "Accepted"]'
        )
        assert result is None

    @pytest.mark.parametrize("term", ACCEPTED_TERMS)
    def test_accepted_terms(self, term):
        result = get_current_state(f"Current state: {term}")
        assert result == IPState.ACCEPTED

    @pytest.mark.parametrize("term", UNDER_DISCUSSION_TERMS)
    def test_under_discussion_terms(self, term):
        result = get_current_state(f"Current state: {term}")
        assert result == IPState.UNDER_DISCUSSION

    @pytest.mark.parametrize("term", NOT_ACCEPTED_TERMS)
    def test_not_accepted_terms(self, term):
        result = get_current_state(f"Current state: {term}")
        assert result == IPState.NOT_ACCEPTED

    def test_case_insensitivity(self):
        assert get_current_state("Current state: ACCEPTED") == IPState.ACCEPTED
        assert (
            get_current_state("Current state: Under Discussion")
            == IPState.UNDER_DISCUSSION
        )
        assert get_current_state("Current state: REJECTED") == IPState.NOT_ACCEPTED

    def test_unrecognized_state_returns_none(self):
        assert get_current_state("Current state: something random") is None

    def test_empty_string_returns_none(self):
        assert get_current_state("") is None


class TestEnrichKipInfo:
    """Integration tests for enrich_kip_info()."""

    def test_template_default_produces_unknown(self):
        """When the state paragraph has the template placeholder, state should be UNKNOWN."""
        body = f"<p>Current state: {TEMPLATE_PLACEHOLDER}</p>"
        kip_dict: dict = {}
        enrich_kip_info(body, kip_dict)
        assert kip_dict["state"] == IPState.UNKNOWN

    def test_normal_accepted_state(self):
        body = "<p>Current state: Accepted</p>"
        kip_dict: dict = {}
        enrich_kip_info(body, kip_dict)
        assert kip_dict["state"] == IPState.ACCEPTED

    def test_normal_under_discussion_state(self):
        body = "<p>Current state: Under Discussion</p>"
        kip_dict: dict = {}
        enrich_kip_info(body, kip_dict)
        assert kip_dict["state"] == IPState.UNDER_DISCUSSION

    def test_normal_rejected_state(self):
        body = "<p>Current state: Rejected</p>"
        kip_dict: dict = {}
        enrich_kip_info(body, kip_dict)
        assert kip_dict["state"] == IPState.NOT_ACCEPTED

    def test_missing_state_paragraph_defaults_to_unknown(self):
        body = "<p>Some other content</p>"
        kip_dict: dict = {}
        enrich_kip_info(body, kip_dict)
        assert kip_dict["state"] == "unknown"

    def test_missing_paragraphs_default_properly(self):
        body = ""
        kip_dict: dict = {}
        enrich_kip_info(body, kip_dict)
        assert kip_dict["state"] == "unknown"
        assert kip_dict["jira"] == NOT_SET_STR
        assert kip_dict["discussion_thread"] == NOT_SET_STR
        assert kip_dict["vote_thread"] == NOT_SET_STR


class TestGetKipInformationCacheUpdate:
    """Tests for cache update logic in get_kip_information()."""

    def _write_cache(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf8") as f:
            json.dump(data, f)

    def test_new_kip_added(self, tmp_path, mocker):
        """A KIP not in the cache is added."""
        cache_file = tmp_path / "cache" / "kip_cache.json"
        self._write_cache(cache_file, {})

        child = _make_child_page(100)
        mocker.patch(
            "ipper.kafka.wiki.child_page_generator",
            return_value=iter([child]),
        )

        result = get_kip_information(
            {"id": "123"},
            update=True,
            cache_filepath=str(cache_file),
        )

        assert 100 in result
        assert result[100]["title"] == "KIP-100: Test Proposal"

    def test_unmodified_kip_skipped(self, tmp_path, mocker):
        """A KIP with the same last_modified_on is not re-processed."""
        timestamp = "2025-06-01T00:00:00.000Z"
        cache_data = {
            "200": {
                "kip_id": 200,
                "title": "KIP-200: Old Title",
                "last_modified_on": timestamp,
                "state": IPState.ACCEPTED,
            }
        }
        cache_file = tmp_path / "cache" / "kip_cache.json"
        self._write_cache(cache_file, cache_data)

        child = _make_child_page(200, last_updated=timestamp)
        mocker.patch(
            "ipper.kafka.wiki.child_page_generator",
            return_value=iter([child]),
        )
        spy = mocker.spy(
            __import__("ipper.kafka.wiki", fromlist=["process_child_kip"]),
            "process_child_kip",
        )

        result = get_kip_information(
            {"id": "123"},
            update=True,
            cache_filepath=str(cache_file),
        )

        spy.assert_not_called()
        assert result[200]["title"] == "KIP-200: Old Title"

    def test_modified_kip_refreshed(self, tmp_path, mocker):
        """A KIP with a different last_modified_on is re-processed."""
        cache_data = {
            "300": {
                "kip_id": 300,
                "title": "KIP-300: Old Title",
                "last_modified_on": "2025-01-01T00:00:00.000Z",
                "state": IPState.UNDER_DISCUSSION,
            }
        }
        cache_file = tmp_path / "cache" / "kip_cache.json"
        self._write_cache(cache_file, cache_data)

        child = _make_child_page(
            300,
            title="KIP-300: Updated Title",
            body_html="<p>Current state: Accepted</p>",
            last_updated="2025-06-15T00:00:00.000Z",
        )
        mocker.patch(
            "ipper.kafka.wiki.child_page_generator",
            return_value=iter([child]),
        )

        result = get_kip_information(
            {"id": "123"},
            update=True,
            cache_filepath=str(cache_file),
        )

        assert result[300]["title"] == "KIP-300: Updated Title"
        assert result[300]["state"] == IPState.ACCEPTED
        assert result[300]["last_modified_on"] == "2025-06-15T00:00:00.000Z"

    def test_missing_last_modified_forces_refresh(self, tmp_path, mocker):
        """A cached KIP without last_modified_on is refreshed."""
        cache_data = {
            "400": {
                "kip_id": 400,
                "title": "KIP-400: Legacy Entry",
                "state": IPState.UNKNOWN,
            }
        }
        cache_file = tmp_path / "cache" / "kip_cache.json"
        self._write_cache(cache_file, cache_data)

        child = _make_child_page(
            400,
            body_html="<p>Current state: Accepted</p>",
            last_updated="2025-07-01T00:00:00.000Z",
        )
        mocker.patch(
            "ipper.kafka.wiki.child_page_generator",
            return_value=iter([child]),
        )

        result = get_kip_information(
            {"id": "123"},
            update=True,
            cache_filepath=str(cache_file),
        )

        assert result[400]["state"] == IPState.ACCEPTED
        assert result[400]["last_modified_on"] == "2025-07-01T00:00:00.000Z"
