"""Tests for ipper.common.github_output rendering and JSON API output."""

import json

from ipper.common.github_config import KROXYLICIOUS_CONFIG, STRIMZI_CONFIG
from ipper.common.github_output import (
    detail_json_filename,
    detail_page_filename,
    display_id,
    generate_github_json_api,
    render_detail_pages,
    render_index_page,
)


def make_record(
    key: str,
    state: str = "accepted",
    id: int | None = 157,
    pr_number: int | None = None,
    created_on: str = "2026-01-10",
    reviews: dict | None = None,
    amendments: list | None = None,
) -> dict:
    if pr_number is None:
        pr_number = int(key.split("-")[1]) if key.startswith("pr-") else 245
    return {
        "key": key,
        "id": id,
        "pr_number": pr_number,
        "title": f"Proposal {key}",
        "state": state,
        "created_by": "alice",
        "authors": ["alice"],
        "created_on": created_on,
        "merged_on": "2026-02-01T00:00:00Z" if state == "accepted" else None,
        "last_modified_on": "2026-02-01T00:00:00Z" if state == "accepted" else None,
        "web_url": "https://github.com/o/r/blob/main/x.md",
        "pr_url": f"https://github.com/o/r/pull/{pr_number}",
        "reviews": reviews
        or {"accepted": [], "commented": [], "changes_requested": []},
        "last_activity": None,
        "activity_status": "green" if state == "under discussion" else None,
        "last_activity_age": "2 days" if state == "under discussion" else None,
        "amendments": amendments or [],
        "frozen": True,
    }


class TestFilenamesAndDisplay:
    def test_numbered_detail_page_filename(self):
        record = make_record("157")
        assert detail_page_filename(STRIMZI_CONFIG, record) == "SIP-157.html"

    def test_unnumbered_detail_page_filename(self):
        record = make_record("pr-247", state="under discussion", id=None)
        assert detail_page_filename(STRIMZI_CONFIG, record) == "SIP-PR-247.html"

    def test_kdp_uses_pr_number_for_open_proposals(self):
        record = make_record("pr-135", id=135, pr_number=135)
        assert detail_page_filename(KROXYLICIOUS_CONFIG, record) == "KDP-135.html"

    def test_detail_json_filename(self):
        assert detail_json_filename(STRIMZI_CONFIG, make_record("157")) == "157"
        record = make_record("pr-247", id=None)
        assert detail_json_filename(STRIMZI_CONFIG, record) == "PR-247"

    def test_display_id(self):
        assert display_id(STRIMZI_CONFIG, make_record("157")) == "157"
        record = make_record("pr-247", id=None)
        assert display_id(STRIMZI_CONFIG, record) == "PR #247"


class TestIndexRendering:
    def _cache(self) -> dict:
        return {
            "last_updated": "2026-02-10T00:00:00Z",
            "proposals": {
                "157": make_record("157", created_on="2026-01-10"),
                "pr-247": make_record(
                    "pr-247",
                    state="under discussion",
                    id=None,
                    pr_number=247,
                    created_on="2026-02-05",
                    reviews={
                        "accepted": [
                            {"name": "dev", "timestamp": "2026-02-08T00:00:00Z"}
                        ],
                        "commented": [],
                        "changes_requested": [],
                    },
                ),
                "pr-248": make_record(
                    "pr-248",
                    state="not accepted",
                    id=None,
                    pr_number=248,
                    created_on="2026-01-01",
                ),
            },
            "pr_index": {},
        }

    def test_rows_sorted_by_created_on_desc(self, tmp_path):
        output = tmp_path / "strimzi.html"
        render_index_page(STRIMZI_CONFIG, self._cache(), str(output))
        html = output.read_text()
        pr247_pos = html.index("PR #247")
        sip157_pos = html.index("SIP-157")
        sip248_pos = html.index("SIP-PR-248")
        assert pr247_pos < sip157_pos < sip248_pos

    def test_renders_title_state_and_prefix(self, tmp_path):
        output = tmp_path / "strimzi.html"
        render_index_page(STRIMZI_CONFIG, self._cache(), str(output))
        html = output.read_text()
        assert "Strimzi Improvement Proposals (SIPs)" in html
        assert "under discussion" in html
        assert "accepted" in html

    def test_activity_indicator_for_open_proposals(self, tmp_path):
        output = tmp_path / "strimzi.html"
        render_index_page(STRIMZI_CONFIG, self._cache(), str(output))
        html = output.read_text()
        assert "background-color:green" in html

    def test_emoji_for_closed_states(self, tmp_path):
        output = tmp_path / "strimzi.html"
        render_index_page(STRIMZI_CONFIG, self._cache(), str(output))
        html = output.read_text()
        assert "✅" in html
        assert "❌" in html

    def test_review_tooltip(self, tmp_path):
        output = tmp_path / "strimzi.html"
        render_index_page(STRIMZI_CONFIG, self._cache(), str(output))
        html = output.read_text()
        assert "dev" in html


class TestDetailRendering:
    def test_detail_pages_written_with_correct_names(self, tmp_path):
        cache = {
            "last_updated": "2026-02-10T00:00:00Z",
            "proposals": {
                "157": make_record("157"),
                "pr-247": make_record(
                    "pr-247", state="under discussion", id=None, pr_number=247
                ),
            },
            "pr_index": {},
        }
        detail_dir = tmp_path / "sips"
        render_detail_pages(STRIMZI_CONFIG, cache, str(detail_dir))
        assert (detail_dir / "SIP-157.html").exists()
        assert (detail_dir / "SIP-PR-247.html").exists()

    def test_detail_page_contains_metadata_and_reviews(self, tmp_path):
        cache = {
            "last_updated": "2026-02-10T00:00:00Z",
            "proposals": {
                "157": make_record(
                    "157",
                    reviews={
                        "accepted": [
                            {"name": "committer", "timestamp": "2026-02-01T00:00:00Z"}
                        ],
                        "commented": [],
                        "changes_requested": [],
                    },
                    amendments=[
                        {
                            "pr_number": 250,
                            "url": "https://github.com/o/r/pull/250",
                            "date": "2026-02-04",
                        }
                    ],
                ),
            },
            "pr_index": {},
        }
        detail_dir = tmp_path / "sips"
        render_detail_pages(STRIMZI_CONFIG, cache, str(detail_dir))
        html = (detail_dir / "SIP-157.html").read_text()
        assert "SIP-157" in html
        assert "committer" in html
        assert "2026-02-01T00:00:00Z" in html
        assert "PR #250" in html
        assert "Merged" in html
        assert "Accepted" in html
        assert "Requested Changes" in html
        assert "1 user" in html


class TestJsonApi:
    def test_summary_and_detail_files(self, tmp_path):
        cache = {
            "last_updated": "2026-02-10T00:00:00Z",
            "proposals": {
                "157": make_record("157"),
                "pr-247": make_record(
                    "pr-247",
                    state="under discussion",
                    id=None,
                    pr_number=247,
                    created_on="2026-02-05",
                    reviews={
                        "accepted": [
                            {"name": "dev", "timestamp": "2026-02-08T00:00:00Z"}
                        ],
                        "commented": [
                            {"name": "bob", "timestamp": "2026-02-07T00:00:00Z"}
                        ],
                        "changes_requested": [
                            {"name": "carol", "timestamp": "2026-02-06T00:00:00Z"}
                        ],
                    },
                ),
            },
            "pr_index": {},
        }
        api_dir = tmp_path / "api" / "v1" / "strimzi"
        generate_github_json_api(STRIMZI_CONFIG, cache, api_dir)

        summary_path = api_dir / "sips.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text())
        assert summary["project"] == "strimzi"
        assert summary["proposal_type"] == "SIP"
        assert summary["count"] == 2

        # detail files: numbered + PR-named
        assert (api_dir / "sips" / "157.json").exists()
        assert (api_dir / "sips" / "PR-247.json").exists()

        detail = json.loads((api_dir / "sips" / "PR-247.json").read_text())
        assert detail["id"] is None
        assert detail["pr_number"] == 247
        assert detail["state"] == "under discussion"
        assert detail["activity_status"] == "green"
        assert detail["reviews"]["accepted"][0]["login"] == "dev"
        assert detail["reviews"]["accepted"][0]["timestamp"] == "2026-02-08T00:00:00Z"
        assert detail["reviews"]["commented"][0]["login"] == "bob"
        assert detail["reviews"]["changes_requested"][0]["login"] == "carol"
        assert "votes" not in detail

        # summary carries integer review counts, not vote counts
        pr247_summary = next(p for p in summary["proposals"] if p["pr_number"] == 247)
        assert pr247_summary["review_count"] == {
            "accepted": 1,
            "commented": 1,
            "changes_requested": 1,
        }
        assert "vote_count" not in pr247_summary

        merged_detail = json.loads((api_dir / "sips" / "157.json").read_text())
        assert merged_detail["id"] == 157
        assert merged_detail["merged_on"] == "2026-02-01T00:00:00Z"
        assert merged_detail["pr_url"].endswith("/pull/245")

        # summary detail_url entries match actual files
        urls = {p["detail_url"] for p in summary["proposals"]}
        assert "sips/157.json" in urls
        assert "sips/PR-247.json" in urls

    def test_summary_ids_can_be_null(self, tmp_path):
        cache = {
            "last_updated": "2026-02-10T00:00:00Z",
            "proposals": {
                "pr-247": make_record(
                    "pr-247", state="under discussion", id=None, pr_number=247
                ),
            },
            "pr_index": {},
        }
        api_dir = tmp_path / "api"
        generate_github_json_api(STRIMZI_CONFIG, cache, api_dir)
        summary = json.loads((api_dir / "sips.json").read_text())
        assert summary["proposals"][0]["id"] is None
