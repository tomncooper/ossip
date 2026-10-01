"""Tests for ipper.common.feed_output and the feed wiring on the index pages."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ipper.common.feed_names import (
    COMBINED_FEED,
    COMBINED_FEED_TITLE,
    feed_file,
    feed_title,
)
from ipper.common.feed_output import (
    ATOM_NS,
    ICON_PATH,
    LOGO_PATH,
    MAX_ENTRIES,
    write_feeds,
)
from ipper.common.github_config import GITHUB_PROJECT_CONFIGS, STRIMZI_CONFIG
from ipper.common.github_output import (
    generate_github_json_api,
    render_detail_pages,
    render_index_page,
)
from ipper.flink.output import render_flink_main_page
from ipper.kafka.output import render_standalone_status_page
from ipper.social.config import SOCIAL_PROJECTS

from .test_github_output import make_record

NS = {"a": ATOM_NS}
BASE = "https://ossip.dev"


@pytest.fixture(autouse=True)
def _default_base_url(monkeypatch):
    """Keep the tests independent of any OSSIP_BASE_URL in the environment."""
    monkeypatch.delenv("OSSIP_BASE_URL", raising=False)


def _proposal(id_, title, created_on, pr_number=None, authors=("Ada",)):
    return {
        "id": id_,
        "title": title,
        "state": "under discussion",
        "authors": list(authors),
        "created_on": created_on,
        "pr_number": pr_number,
    }


def _write_summary(api_dir: Path, project: str, proposals: list) -> None:
    path = api_dir / project / f"{SOCIAL_PROJECTS[project].detail_dir}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"count": len(proposals), "proposals": proposals}))


def _parse(feed_path: Path):
    root = ET.fromstring(feed_path.read_bytes())
    return root, root.findall("a:entry", NS)


def _titles(entries) -> list[str]:
    return [e.find("a:title", NS).text for e in entries]


def _links(root) -> dict[str, str]:
    return {link.get("rel"): link.get("href") for link in root.findall("a:link", NS)}


class TestFeedContent:
    def test_orders_newest_first_and_links_to_detail_page(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(
            api,
            "kafka",
            [_proposal(1, "Old", "2024-01-01"), _proposal(2, "New", "2025-06-01")],
        )
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert _titles(entries) == ["KIP-2: New", "KIP-1: Old"]
        link = entries[0].find("a:link", NS).get("href")
        assert link == f"{BASE}/kips/KIP-2.html"

    def test_combined_feed_prefixes_project_and_merges(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        _write_summary(api, "flink", [_proposal(9, "B", "2025-02-01")])
        write_feeds(api, site)

        _, entries = _parse(site / "feed.xml")
        assert _titles(entries) == ["Flink FLIP-9: B", "Kafka KIP-1: A"]

    def test_unnumbered_github_proposal_uses_pr_reference(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(
            api, "strimzi", [_proposal(None, "Draft", "2025-03-01", pr_number=245)]
        )
        write_feeds(api, site)

        _, entries = _parse(site / "strimzi.xml")
        assert _titles(entries) == ["SIP-PR-245: Draft"]
        link = entries[0].find("a:link", NS).get("href")
        assert link == f"{BASE}/sips/SIP-PR-245.html"

    def test_wiki_title_prefix_is_not_duplicated(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(7, "KIP-7: Do a thing", "2025-01-01")])
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert _titles(entries) == ["KIP-7: Do a thing"]

    def test_summary_omits_state_and_lists_authors(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(
            api, "kafka", [_proposal(1, "A", "2025-01-01", authors=("Ada", "Bob"))]
        )
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert entries[0].find("a:summary", NS).text == "New proposal by Ada, Bob"

    def test_caps_to_the_newest_entries(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        total = MAX_ENTRIES + 10
        # A higher id is created on a later day
        proposals = [
            _proposal(i, f"P{i}", f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}")
            for i in range(total)
        ]
        _write_summary(api, "kafka", proposals)
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        titles = _titles(entries)
        assert len(entries) == MAX_ENTRIES
        assert titles[0] == f"KIP-{total - 1}: P{total - 1}"
        oldest = total - MAX_ENTRIES
        assert titles[-1] == f"KIP-{oldest}: P{oldest}"

    def test_same_day_ties_break_numerically(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(
            api,
            "kafka",
            [
                _proposal(999, "Nine", "2025-01-01"),
                _proposal(1000, "Thousand", "2025-01-01"),
            ],
        )
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert _titles(entries) == ["KIP-1000: Thousand", "KIP-999: Nine"]


class TestFeedStructure:
    def test_required_atom_elements(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        write_feeds(api, site)

        root, entries = _parse(site / "kafka.xml")
        assert root.find("a:title", NS).text == feed_title("kafka")
        assert root.find("a:id", NS).text == "tag:ossip.dev,2026:feed/kafka.xml"
        assert root.find("a:updated", NS).text == "2025-01-01T00:00:00Z"
        assert root.find("a:author/a:name", NS).text == "OSSIP"
        assert _links(root) == {
            "self": f"{BASE}/kafka.xml",
            "alternate": f"{BASE}/kafka.html",
        }
        for entry in entries:
            for name in ("title", "id", "updated", "published", "summary"):
                assert entry.find(f"a:{name}", NS) is not None

    def test_combined_feed_links_to_homepage(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        write_feeds(api, site)

        root, _ = _parse(site / "feed.xml")
        assert _links(root)["alternate"] == f"{BASE}/"

    def test_icon_is_square_asset_and_logo_is_wide_banner(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        write_feeds(api, site)

        root, _ = _parse(site / "kafka.xml")
        assert root.find("a:icon", NS).text == f"{BASE}/{ICON_PATH}"
        assert root.find("a:logo", NS).text == f"{BASE}/{LOGO_PATH}"
        templates = Path(__file__).parents[2] / "templates"
        assert (templates / ICON_PATH).exists()
        assert (templates / LOGO_PATH).exists()

    def test_base_url_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OSSIP_BASE_URL", "http://localhost:8765/")
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        write_feeds(api, site)

        root, entries = _parse(site / "kafka.xml")
        assert root.find("a:id", NS).text == "tag:ossip.dev,2026:feed/kafka.xml"
        assert _links(root)["self"] == "http://localhost:8765/kafka.xml"
        link = entries[0].find("a:link", NS).get("href")
        assert link == "http://localhost:8765/kips/KIP-1.html"

    def test_output_is_deterministic(self, tmp_path):
        api = tmp_path / "api"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        write_feeds(api, tmp_path / "one")
        write_feeds(api, tmp_path / "two")

        one = (tmp_path / "one/feed.xml").read_bytes()
        assert one == (tmp_path / "two/feed.xml").read_bytes()


class TestEntryIds:
    def test_github_entry_id_survives_renumbering_on_merge(self, tmp_path):
        """An open SIP-PR-242 becomes SIP-155 on merge: same PR, same entry id."""
        api = tmp_path / "api"
        _write_summary(
            api, "strimzi", [_proposal(None, "Thing", "2026-08-14", pr_number=242)]
        )
        write_feeds(api, tmp_path / "before")
        _write_summary(
            api, "strimzi", [_proposal(155, "Thing", "2026-08-14", pr_number=242)]
        )
        write_feeds(api, tmp_path / "after")

        _, before = _parse(tmp_path / "before/strimzi.xml")
        _, after = _parse(tmp_path / "after/strimzi.xml")
        assert before[0].find("a:id", NS).text == after[0].find("a:id", NS).text
        assert before[0].find("a:link", NS).get("href").endswith("SIP-PR-242.html")
        assert after[0].find("a:link", NS).get("href").endswith("SIP-155.html")

    def test_entry_ids_are_unique_across_projects(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        # The same numbers in two projects must not collide in the combined feed
        _write_summary(api, "strimzi", [_proposal(1, "S", "2025-01-01", pr_number=1)])
        _write_summary(
            api, "streamshub", [_proposal(1, "H", "2025-01-01", pr_number=1)]
        )
        write_feeds(api, site)

        _, entries = _parse(site / "feed.xml")
        ids = [e.find("a:id", NS).text for e in entries]
        assert len(ids) == len(set(ids)) == 2

    def test_ids_do_not_depend_on_base_url(self, tmp_path, monkeypatch):
        api = tmp_path / "api"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        write_feeds(api, tmp_path / "prod")
        monkeypatch.setenv("OSSIP_BASE_URL", "http://localhost:1")
        write_feeds(api, tmp_path / "local")

        _, prod = _parse(tmp_path / "prod/kafka.xml")
        _, local = _parse(tmp_path / "local/kafka.xml")
        assert prod[0].find("a:id", NS).text == local[0].find("a:id", NS).text


class TestRobustness:
    def test_escapes_markup_in_titles_and_authors(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(
            api,
            "kafka",
            [_proposal(1, "A <b> & B", "2025-01-01", authors=("Eve <x>",))],
        )
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")  # parsing proves well-formed
        assert _titles(entries) == ["KIP-1: A <b> & B"]
        assert entries[0].find("a:author/a:name", NS).text == "Eve <x>"

    def test_control_characters_are_stripped(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(
            api,
            "kafka",
            [
                _proposal(
                    1, "bad \x0b\x1b\x00 title", "2025-01-01", authors=("E\x0cve",)
                )
            ],
        )
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert _titles(entries) == ["KIP-1: bad  title"]
        assert entries[0].find("a:author/a:name", NS).text == "Eve"

    def test_lone_surrogates_are_stripped(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "a\ud800b\ufffe", "2025-01-01")])
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert _titles(entries) == ["KIP-1: ab"]

    def test_one_unreadable_summary_does_not_stop_other_feeds(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        bad = api / "flink" / "flips.json"
        bad.parent.mkdir(parents=True)
        bad.write_text('{"count": 1, "propos')  # truncated
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert _titles(entries) == ["KIP-1: A"]
        assert not (site / "flink.xml").exists()
        _, combined = _parse(site / COMBINED_FEED)
        assert _titles(combined) == ["Kafka KIP-1: A"]

    def test_missing_projects_are_skipped(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [_proposal(1, "A", "2025-01-01")])
        write_feeds(api, site)

        assert (site / "kafka.xml").exists()
        assert not (site / "flink.xml").exists()

    def test_project_with_no_proposals_still_gets_a_feed(self, tmp_path):
        """Its index page links to the feed, so the file must exist."""
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "kafka", [])
        write_feeds(api, site)

        _, entries = _parse(site / "kafka.xml")
        assert entries == []

    def test_no_projects_yields_valid_empty_combined_feed(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        api.mkdir()
        write_feeds(api, site)

        _, entries = _parse(site / "feed.xml")
        assert entries == []


class TestFeedLinksResolve:
    def test_every_github_entry_link_is_a_generated_page(self, tmp_path):
        """Open, merged-and-renumbered and unnumbered proposals all resolve."""
        cache = {
            "last_updated": "2026-02-10T00:00:00Z",
            "proposals": {
                "157": make_record("157", pr_number=242),
                "pr-247": make_record(
                    "pr-247",
                    state="under discussion",
                    id=None,
                    pr_number=247,
                    created_on="2026-02-05",
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
        site = tmp_path / "site"
        api = site / "api" / "v1"
        render_detail_pages(STRIMZI_CONFIG, cache, str(site / "sips"))
        generate_github_json_api(STRIMZI_CONFIG, cache, api / "strimzi")
        write_feeds(api, site)

        _, entries = _parse(site / "strimzi.xml")
        assert len(entries) == 3
        for entry in entries:
            href = entry.find("a:link", NS).get("href")
            assert href.startswith(f"{BASE}/")
            assert (site / href.removeprefix(f"{BASE}/")).exists(), href


class TestHomepageWiring:
    """The static homepage (not a Jinja template) advertises the combined feed."""

    def test_homepage_links_and_advertises_combined_feed(self):
        html = (Path(__file__).parents[2] / "templates" / "index.html").read_text()
        assert f'<a href="{COMBINED_FEED}">RSS</a>' in html
        assert (
            f'<link rel="alternate" type="application/atom+xml" '
            f'title="{COMBINED_FEED_TITLE}" href="{COMBINED_FEED}">'
        ) in html
        assert "<img" not in html.split('class="social-links"')[1].split("</p>")[0]


class TestIndexPageWiring:
    """Each index page links to (and advertises) its own project's feed."""

    def _assert_wired(self, html: str, key: str) -> None:
        assert f'<a href="{feed_file(key)}">RSS</a>' in html
        assert (
            f'<link rel="alternate" type="application/atom+xml" '
            f'title="{feed_title(key)}" href="{feed_file(key)}">'
        ) in html

    def test_kafka_index(self, tmp_path):
        out = tmp_path / "kafka.html"
        render_standalone_status_page([], str(out))
        self._assert_wired(out.read_text(), "kafka")

    def test_flink_index(self, tmp_path):
        out = tmp_path / "flink.html"
        render_flink_main_page({}, str(out))
        self._assert_wired(out.read_text(), "flink")

    @pytest.mark.parametrize("key", sorted(GITHUB_PROJECT_CONFIGS))
    def test_github_indexes(self, tmp_path, key):
        out = tmp_path / f"{key}.html"
        cache = {"last_updated": "2026-02-10T00:00:00Z", "proposals": {}}
        render_index_page(GITHUB_PROJECT_CONFIGS[key], cache, str(out))
        self._assert_wired(out.read_text(), key)

    def test_feed_title_matches_written_feed(self, tmp_path):
        api, site = tmp_path / "api", tmp_path / "site"
        _write_summary(api, "flink", [_proposal(9, "B", "2025-02-01")])
        write_feeds(api, site)

        root, _ = _parse(site / feed_file("flink"))
        assert root.find("a:title", NS).text == feed_title("flink")
