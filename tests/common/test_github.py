"""Tests for ipper.common.github (client, config) and github_process."""

import io
import json
import tarfile
from collections import Counter

import pytest
import requests

from ipper.common.github import (
    GITHUB_TOKEN_ENV_VAR,
    GithubClient,
    GithubClientError,
    GithubRateLimitError,
    GithubTokenRejectedError,
    GithubTokenRequiredError,
)
from ipper.common.github_config import (
    KROXYLICIOUS_CONFIG,
    STRIMZI_CONFIG,
)
from ipper.common.github_process import (
    classify_pull,
    derive_pull_state,
    extract_number,
    is_proposal_file,
    last_activity_of,
    normalize_reviews,
    parse_tarball,
    reviews_to_votes,
    reviews_to_votes_from_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _response(
    status_code: int = 200,
    payload: list | dict | None = None,
    headers: dict | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = json.dumps(payload if payload is not None else {}).encode()
    response.url = "https://api.github.com/test"
    return response


def _link_header(next_url: str) -> dict:
    return {"Link": f'<{next_url}>; rel="next"'}


def make_pull(
    number: int,
    state: str = "open",
    merged_at: str | None = None,
    closed_at: str | None = None,
    updated_at: str = "2026-02-10T00:00:00Z",
    created_at: str = "2026-01-01T00:00:00Z",
    head_sha: str = "sha-1",
    title: str = "A proposal",
    user: str = "alice",
) -> dict:
    return {
        "number": number,
        "state": state,
        "title": title,
        "user": {"login": user},
        "created_at": created_at,
        "updated_at": updated_at,
        "merged_at": merged_at,
        "closed_at": closed_at,
        "html_url": f"https://github.com/o/r/pull/{number}",
        "head": {"sha": head_sha},
    }


def make_file(filename: str, status: str = "added") -> dict:
    return {"filename": filename, "status": status}


def make_review(name: str, state: str, timestamp: str = "2026-02-01T00:00:00Z") -> dict:
    return {"user": {"login": name}, "state": state, "submitted_at": timestamp}


def make_comment(name: str, timestamp: str = "2026-02-02T00:00:00Z") -> dict:
    return {"user": {"login": name}, "created_at": timestamp}


def make_tarball(files: dict[str, str]) -> bytes:
    """Build a gzipped tarball like the GitHub codeload endpoint, with the
    <repo>-<sha>/ member prefix."""

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(f"repo-abc123/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeGithubClient:
    """Stand-in for GithubClient with canned data and call tracking."""

    def __init__(
        self,
        pulls: list[dict] | None = None,
        files: dict[int, list[dict]] | None = None,
        reviews: dict[int, list[dict]] | None = None,
        comments: dict[int, list[dict]] | None = None,
        tarball: bytes = b"",
        single_pulls: dict[int, dict] | None = None,
    ):
        self.pulls = pulls or []
        self.files = files or {}
        self.reviews = reviews or {}
        self.comments = comments or {}
        self.tarball = tarball
        self.single_pulls = single_pulls or {}
        self.calls: Counter = Counter()

    def list_pulls(
        self, state: str = "all", sort: str = "updated", direction: str = "desc"
    ):
        self.calls["list_pulls"] += 1
        yield from self.pulls

    def get_pull_files(self, pr_number: int):
        self.calls[f"files:{pr_number}"] += 1
        yield from self.files.get(pr_number, [])

    def get_pull_reviews(self, pr_number: int):
        self.calls[f"reviews:{pr_number}"] += 1
        yield from self.reviews.get(pr_number, [])

    def get_issue_comments(self, pr_number: int):
        self.calls[f"comments:{pr_number}"] += 1
        yield from self.comments.get(pr_number, [])

    def get_pull(self, pr_number: int) -> dict:
        self.calls[f"pull:{pr_number}"] += 1
        return self.single_pulls[pr_number]

    def download_tarball(self, ref: str = "main") -> bytes:
        self.calls["tarball"] += 1
        return self.tarball


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TestGithubClient:
    def test_token_from_env_sets_auth_header(self, monkeypatch):
        monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "env-token")
        client = GithubClient("o", "r")
        assert client.session.headers["Authorization"] == "Bearer env-token"

    def test_explicit_token_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "env-token")
        client = GithubClient("o", "r", token="explicit")
        assert client.session.headers["Authorization"] == "Bearer explicit"

    def test_no_token_omits_auth_header(self, monkeypatch):
        monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
        client = GithubClient("o", "r")
        assert "Authorization" not in client.session.headers

    def test_require_token_raises_without_token(self, monkeypatch):
        monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
        with pytest.raises(GithubTokenRequiredError):
            GithubClient("o", "r", require_token=True)

    def test_require_token_ok_with_token(self, monkeypatch):
        monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "t")
        client = GithubClient("o", "r", require_token=True)
        assert client.token == "t"

    def test_get_single_resource(self, mocker):
        mock = mocker.patch(
            "ipper.common.github.get_with_retries",
            return_value=_response(payload={"number": 1}),
        )
        client = GithubClient("o", "r", token="t")
        assert client.get("pulls/1") == {"number": 1}
        assert mock.call_args.args[0] == "https://api.github.com/repos/o/r/pulls/1"

    def test_requests_carry_auth_header(self, mocker):
        """Regression: get_with_retries must receive the session headers,
        otherwise the token is silently dropped and every request counts
        against the anonymous rate limit."""

        mock = mocker.patch(
            "ipper.common.github.get_with_retries",
            return_value=_response(payload={}),
        )
        client = GithubClient("o", "r", token="secret-token")
        client.get("pulls/1")
        sent = mock.call_args.kwargs["headers"]
        assert sent["Authorization"] == "Bearer secret-token"
        assert sent["Accept"] == "application/vnd.github+json"

    def test_requests_without_token_have_no_auth_header(self, mocker):
        mock = mocker.patch(
            "ipper.common.github.get_with_retries", return_value=_response(payload={})
        )
        client = GithubClient("o", "r")
        client.get("pulls/1")
        assert "Authorization" not in mock.call_args.kwargs["headers"]

    def test_paginate_follows_link_headers(self, mocker):
        page_1 = _response(
            payload=[{"number": 1}, {"number": 2}],
            headers=_link_header("https://api.github.com/repos/o/r/pulls?page=2"),
        )
        page_2 = _response(payload=[{"number": 3}])

        mock = mocker.patch(
            "ipper.common.github.get_with_retries", side_effect=[page_1, page_2]
        )
        client = GithubClient("o", "r", token="t")

        assert list(client.paginate("pulls")) == [
            {"number": 1},
            {"number": 2},
            {"number": 3},
        ]
        assert mock.call_count == 2

    def test_paginate_sends_per_page_param_on_first_request(self, mocker):
        mock = mocker.patch(
            "ipper.common.github.get_with_retries", return_value=_response(payload=[])
        )
        client = GithubClient("o", "r", token="t")
        list(client.paginate("pulls"))
        assert mock.call_args.kwargs["params"]["per_page"] == 100

    def test_rate_limit_exhausted_raises(self, mocker):
        mocker.patch(
            "ipper.common.github.get_with_retries",
            return_value=_response(headers={"X-RateLimit-Remaining": "0"}),
        )
        client = GithubClient("o", "r")
        with pytest.raises(GithubRateLimitError):
            client.get("pulls/1")

    def test_bad_token_raises_token_rejected(self, mocker):
        mocker.patch(
            "ipper.common.github.get_with_retries", return_value=_response(401)
        )
        client = GithubClient("o", "r", token="invalid-token")
        with pytest.raises(GithubTokenRejectedError):
            client.get("pulls/1")

    def test_http_error_raises_client_error(self, mocker):
        mocker.patch(
            "ipper.common.github.get_with_retries", return_value=_response(404)
        )
        client = GithubClient("o", "r", token="t")
        with pytest.raises(GithubClientError):
            client.get("pulls/999")

    def test_download_tarball_returns_bytes(self, mocker):
        mocker.patch(
            "ipper.common.github.get_with_retries", return_value=_response(payload=None)
        )
        client = GithubClient("o", "r", token="t")
        mock_resp = _response()
        mock_resp._content = b"tarball-bytes"
        mocker.patch("ipper.common.github.get_with_retries", return_value=mock_resp)
        assert client.download_tarball() == b"tarball-bytes"


# ---------------------------------------------------------------------------
# Config & proposal file matching
# ---------------------------------------------------------------------------


class TestProposalFileMatching:
    def test_sequential_root_file_matches(self):
        assert is_proposal_file(STRIMZI_CONFIG, "157-add-support.md")

    def test_sequential_root_rejects_subdirectory(self):
        assert not is_proposal_file(STRIMZI_CONFIG, "docs/157-add-support.md")

    def test_kdp_requires_proposals_directory(self):
        assert is_proposal_file(KROXYLICIOUS_CONFIG, "proposals/135-dedicated.md")
        assert not is_proposal_file(KROXYLICIOUS_CONFIG, "135-dedicated.md")
        assert not is_proposal_file(KROXYLICIOUS_CONFIG, "proposals/nested/135-x.md")

    def test_template_excluded(self):
        assert not is_proposal_file(STRIMZI_CONFIG, "000-template.md")

    def test_readme_excluded(self):
        # README.md does not match the pattern anyway
        assert not is_proposal_file(STRIMZI_CONFIG, "README.md")

    def test_non_markdown_rejected(self):
        assert not is_proposal_file(STRIMZI_CONFIG, "157-notes.txt")

    def test_non_numbered_rejected(self):
        assert not is_proposal_file(STRIMZI_CONFIG, "proposal.md")

    def test_extract_number(self):
        assert extract_number(STRIMZI_CONFIG, "157-add-support.md") == 157
        assert extract_number(KROXYLICIOUS_CONFIG, "proposals/135-dedicated.md") == 135
        assert extract_number(STRIMZI_CONFIG, "template.md") is None


class TestTarballParsing:
    def test_parses_number_title_and_blob_url(self):
        tarball = make_tarball(
            {"157-kafka-exporter.md": "# Kafka Exporter re-implementation\n\nbody"}
        )
        merged = parse_tarball(tarball, STRIMZI_CONFIG)
        assert set(merged) == {"157-kafka-exporter.md"}
        proposal = merged["157-kafka-exporter.md"]
        assert proposal.number == 157
        assert proposal.title == "Kafka Exporter re-implementation"
        assert proposal.blob_url == (
            "https://github.com/strimzi/proposals/blob/main/157-kafka-exporter.md"
        )

    def test_strips_kdp_number_prefix_from_title(self):
        tarball = make_tarball(
            {"proposals/124-routing-api.md": "# 124 - Routing API\n\nbody"}
        )
        merged = parse_tarball(tarball, KROXYLICIOUS_CONFIG)
        assert merged["proposals/124-routing-api.md"].title == "Routing API"

    def test_excludes_template_and_non_proposal_files(self):
        tarball = make_tarball(
            {
                "000-template.md": "# Template",
                "README.md": "# README",
                "notes.txt": "hello",
                "docs/158-nested.md": "# Nested",
                "158-valid.md": "# Valid",
            }
        )
        merged = parse_tarball(tarball, STRIMZI_CONFIG)
        assert set(merged) == {"158-valid.md"}

    def test_numbering_gaps_are_just_absent(self):
        tarball = make_tarball({"013-x.md": "# X", "015-y.md": "# Y"})
        merged = parse_tarball(tarball, STRIMZI_CONFIG)
        assert sorted(p.number for p in merged.values()) == [13, 15]


# ---------------------------------------------------------------------------
# Classification & votes
# ---------------------------------------------------------------------------


class TestClassification:
    def test_added_proposal_file_is_proposal(self):
        result = classify_pull(
            STRIMZI_CONFIG, [make_file("158-new-proposal.md")], set()
        )
        assert result["classification"] == "proposal"
        assert result["proposal_files"] == ["158-new-proposal.md"]

    def test_added_proposal_plus_readme_is_still_proposal(self):
        result = classify_pull(
            STRIMZI_CONFIG,
            [make_file("158-new-proposal.md"), make_file("README.md", "modified")],
            {"README.md"},
        )
        assert result["classification"] == "proposal"

    def test_modified_merged_file_is_amendment(self):
        result = classify_pull(
            STRIMZI_CONFIG,
            [make_file("157-kafka-exporter.md", "modified")],
            {"157-kafka-exporter.md"},
        )
        assert result["classification"] == "amendment"

    def test_renamed_merged_file_is_amendment(self):
        result = classify_pull(
            STRIMZI_CONFIG,
            [make_file("157-kafka-exporter.md", "renamed")],
            {"157-kafka-exporter.md"},
        )
        assert result["classification"] == "amendment"

    def test_modified_unmerged_file_is_plumbing(self):
        result = classify_pull(
            STRIMZI_CONFIG,
            [make_file("README.md", "modified")],
            {"157-kafka-exporter.md"},
        )
        assert result["classification"] == "plumbing"

    def test_kdp_added_000_placeholder_is_proposal(self):
        """KDP draft files (000-<name>.md, not the template) count as
        proposals; the numbering workflow renames them to the PR number."""

        result = classify_pull(
            KROXYLICIOUS_CONFIG,
            [make_file("proposals/000-scatter-gather-routing-api.md")],
            set(),
        )
        assert result["classification"] == "proposal"

    def test_empty_files_is_plumbing(self):
        result = classify_pull(STRIMZI_CONFIG, [], set())
        assert result["classification"] == "plumbing"


class TestVotes:
    def test_review_mapping(self):
        votes = reviews_to_votes(
            [
                make_review("alice", "APPROVED"),
                make_review("bob", "CHANGES_REQUESTED"),
                make_review("carol", "COMMENTED"),
                make_review("dave", "DISMISSED"),
            ]
        )
        assert [v["name"] for v in votes["+1"]] == ["alice"]
        assert [v["name"] for v in votes["-1"]] == ["bob"]
        assert votes["0"] == []
        assert votes["+1"][0]["timestamp"] == "2026-02-01T00:00:00Z"

    def test_empty_reviews(self):
        assert reviews_to_votes([]) == {"+1": [], "0": [], "-1": []}

    def test_votes_from_snapshot(self):
        snapshot = normalize_reviews(
            [make_review("alice", "APPROVED"), make_review("bob", "CHANGES_REQUESTED")]
        )
        votes = reviews_to_votes_from_snapshot(snapshot)
        assert [v["name"] for v in votes["+1"]] == ["alice"]
        assert [v["name"] for v in votes["-1"]] == ["bob"]

    def test_normalize_reviews_skips_missing_user(self):
        normalized = normalize_reviews([{"state": "APPROVED", "user": None}])
        assert normalized == []


class TestActivityHelpers:
    def test_derive_pull_state(self):
        assert derive_pull_state(make_pull(1)) == "open"
        assert (
            derive_pull_state(
                make_pull(2, state="closed", merged_at="2026-02-01T00:00:00Z")
            )
            == "merged"
        )
        assert derive_pull_state(
            make_pull(3, state="closed", closed_at="2026-02-01T00:00:00Z")
        )
        assert (
            derive_pull_state(
                make_pull(3, state="closed", closed_at="2026-02-01T00:00:00Z")
            )
            == "closed"
        )

    def test_last_activity_is_max_of_sources(self):
        pull = make_pull(1, updated_at="2026-02-05T00:00:00Z")
        reviews = [make_review("a", "APPROVED", "2026-02-10T00:00:00Z")]
        comments = [make_comment("b", "2026-02-08T00:00:00Z")]
        assert last_activity_of(pull, reviews, comments) == "2026-02-10T00:00:00Z"

    def test_last_activity_defaults_to_updated_at(self):
        pull = make_pull(1, updated_at="2026-02-05T00:00:00Z")
        assert last_activity_of(pull, [], []) == "2026-02-05T00:00:00Z"


# ---------------------------------------------------------------------------
# End-to-end cache building (init) and incremental update
# ---------------------------------------------------------------------------


from ipper.common.github_process import (  # noqa: E402
    init_cache,
    load_cache,
    save_cache,
    update_cache,
)


def _strimzi_init_client() -> FakeGithubClient:
    tarball = make_tarball(
        {
            "157-kafka-exporter.md": "# Kafka Exporter re-implementation\n\nbody",
            "000-template.md": "# Template",
        }
    )
    return FakeGithubClient(
        pulls=[
            # merged proposal PR
            make_pull(
                245,
                state="closed",
                merged_at="2026-02-01T00:00:00Z",
                closed_at="2026-02-01T00:00:00Z",
                created_at="2026-01-10T00:00:00Z",
                title="Add Kafka Exporter proposal",
            ),
            # open proposal PR
            make_pull(
                247,
                created_at="2026-02-05T00:00:00Z",
                updated_at="2026-02-09T00:00:00Z",
                title="Add new proposal",
            ),
            # closed unmerged proposal PR
            make_pull(
                248,
                state="closed",
                closed_at="2026-02-03T00:00:00Z",
                title="Bad proposal",
            ),
            # amendment PR on the merged proposal
            make_pull(
                250,
                state="closed",
                merged_at="2026-02-04T00:00:00Z",
                closed_at="2026-02-04T00:00:00Z",
                title="Update proposal 157",
            ),
            # plumbing PR (README only)
            make_pull(
                251,
                state="closed",
                merged_at="2026-02-02T00:00:00Z",
                closed_at="2026-02-02T00:00:00Z",
                title="Update README",
            ),
        ],
        files={
            245: [
                make_file("157-kafka-exporter.md"),
                make_file("README.md", "modified"),
            ],
            247: [make_file("158-new-proposal.md")],
            248: [make_file("159-bad-proposal.md")],
            250: [make_file("157-kafka-exporter.md", "modified")],
            251: [make_file("README.md", "modified")],
        },
        reviews={
            245: [
                make_review("committer1", "APPROVED"),
                make_review("dev1", "COMMENTED"),
            ],
            247: [make_review("dev1", "COMMENTED")],
            248: [make_review("dev2", "CHANGES_REQUESTED")],
        },
        comments={247: [make_comment("reviewer", "2026-02-09T00:00:00Z")]},
        tarball=tarball,
    )


class TestInitCache:
    def test_builds_merged_open_and_rejected_records(self):
        config = STRIMZI_CONFIG
        client = _strimzi_init_client()
        cache = init_cache(config, client)

        # merged proposal promoted to its numbered key
        assert "157" in cache["proposals"]
        merged_record = cache["proposals"]["157"]
        assert merged_record["state"] == "accepted"
        assert merged_record["id"] == 157
        assert merged_record["pr_number"] == 245
        assert merged_record["title"] == "Kafka Exporter re-implementation"
        assert merged_record["created_on"] == "2026-01-10"
        assert merged_record["merged_on"] == "2026-02-01T00:00:00Z"
        assert merged_record["frozen"] is True
        assert merged_record["web_url"].endswith("blob/main/157-kafka-exporter.md")
        # frozen approval history: APPROVED review captured, COMMENTED not
        assert [v["name"] for v in merged_record["votes"]["+1"]] == ["committer1"]
        assert merged_record["activity_status"] is None

        # open proposal: no number yet
        open_record = cache["proposals"]["pr-247"]
        assert open_record["state"] == "under discussion"
        assert open_record["id"] is None
        assert open_record["activity_status"] is not None

        # rejected proposal: frozen
        rejected_record = cache["proposals"]["pr-248"]
        assert rejected_record["state"] == "not accepted"
        assert rejected_record["frozen"] is True
        assert [v["name"] for v in rejected_record["votes"]["-1"]] == ["dev2"]

        # amendment PR recorded on the merged proposal
        assert merged_record["amendments"] == [
            {
                "pr_number": 250,
                "url": "https://github.com/o/r/pull/250",
                "date": "2026-02-04",
            }
        ]
        assert merged_record["last_modified_on"] == "2026-02-04T00:00:00Z"

        # plumbing PR never created a record
        assert "pr-251" not in cache["proposals"]

        # pr_index classification
        assert cache["pr_index"]["245"]["classification"] == "proposal"
        assert cache["pr_index"]["251"]["classification"] == "plumbing"
        assert cache["pr_index"]["250"]["classification"] == "amendment"

    def test_watermark_is_max_updated_at(self):
        client = _strimzi_init_client()
        cache = init_cache(STRIMZI_CONFIG, client)
        assert cache["watermark"] == max(
            entry["updated_at"] for entry in cache["pr_index"].values()
        )

    def test_cache_roundtrip(self, tmp_path):
        client = _strimzi_init_client()
        cache = init_cache(STRIMZI_CONFIG, client)
        path = tmp_path / "cache.json"
        save_cache(cache, path)
        assert load_cache(path) == cache


class TestKroxyliciousInit:
    def test_kdp_numbering_and_shortcut(self):
        tarball = make_tarball(
            {
                "proposals/099-micrometer-configuration.md": "# 099 - Micrometer configuration\n\nbody",
                "000-template.md": "# Template",
            }
        )
        client = FakeGithubClient(
            pulls=[
                # merged KDP proposal PR: number == PR number, no files call
                make_pull(
                    99,
                    state="closed",
                    merged_at="2026-02-01T00:00:00Z",
                    closed_at="2026-02-01T00:00:00Z",
                    title="Add micrometer proposal",
                ),
                # plumbing PR that was merged
                make_pull(
                    107,
                    state="closed",
                    merged_at="2026-02-02T00:00:00Z",
                    closed_at="2026-02-02T00:00:00Z",
                    title="Fix numbering workflow",
                ),
                # rejected draft PR using the 000- placeholder convention
                make_pull(
                    113,
                    state="closed",
                    closed_at="2026-02-03T00:00:00Z",
                    title="docs: scatter-gather routing API",
                ),
                # open KDP proposal PR
                make_pull(
                    135,
                    created_at="2026-02-05T00:00:00Z",
                    updated_at="2026-02-09T00:00:00Z",
                    title="Proposal: Dedicated ServiceAccount",
                ),
            ],
            files={
                107: [make_file(".github/workflows/numbering.yml", "modified")],
                113: [make_file("proposals/000-scatter-gather-routing-api.md")],
                135: [make_file("proposals/135-dedicated-service-account.md")],
            },
            reviews={113: [make_review("dev", "CHANGES_REQUESTED")]},
            tarball=tarball,
        )
        cache = init_cache(KROXYLICIOUS_CONFIG, client)

        # merged KDP proposal: no files call made for PR 99 (shortcut)
        assert client.calls["files:99"] == 0
        assert "99" in cache["proposals"]
        record = cache["proposals"]["99"]
        assert record["id"] == 99
        assert record["title"] == "Micrometer configuration"

        # merged plumbing PR resolved via the shortcut (no file 107 on main)
        assert cache["pr_index"]["107"]["classification"] == "plumbing"
        assert "pr-107" not in cache["proposals"]

        # rejected draft keeps the PR number as its id
        assert cache["proposals"]["pr-113"]["id"] == 113
        assert cache["proposals"]["pr-113"]["state"] == "not accepted"

        # open KDP proposal carries its PR number
        assert cache["proposals"]["pr-135"]["id"] == 135
        assert cache["proposals"]["pr-135"]["state"] == "under discussion"


class TestIncrementalUpdate:
    def _initial_cache(self) -> tuple[dict, FakeGithubClient]:
        client = _strimzi_init_client()
        cache = init_cache(STRIMZI_CONFIG, client)
        return cache, client

    def test_no_changes_means_no_per_pr_calls(self):
        cache, _ = self._initial_cache()
        client = _strimzi_init_client()  # same payloads
        update_cache(STRIMZI_CONFIG, cache, client)

        per_pr_calls = [k for k in client.calls if k != "list_pulls" and k != "tarball"]
        assert per_pr_calls == []

    def test_label_only_bump_skips_file_refetch(self):
        cache, _ = self._initial_cache()

        pulls = [
            make_pull(
                247,
                updated_at="2026-02-11T00:00:00Z",  # bumped, head unchanged
                title="Add new proposal",
            ),
            make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
            make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
            make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
            make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
        ]
        client = FakeGithubClient(
            pulls=pulls,
            files={247: [make_file("158-new-proposal.md")]},
            reviews={247: [make_review("dev1", "COMMENTED")]},
            comments={247: []},
            tarball=make_tarball(
                {"157-kafka-exporter.md": "# Kafka Exporter re-implementation\n"}
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)
        assert client.calls["files:247"] == 0
        assert client.calls["reviews:247"] == 1

    def test_push_triggers_file_refetch(self):
        cache, _ = self._initial_cache()

        pulls = [
            make_pull(
                247,
                updated_at="2026-02-11T00:00:00Z",
                head_sha="sha-2",  # pushed
            ),
            make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
            make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
            make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
            make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
        ]
        client = FakeGithubClient(
            pulls=pulls,
            files={
                247: [
                    make_file("158-new-proposal.md"),
                    make_file("docs/x.md", "modified"),
                ]
            },
            reviews={247: []},
            comments={247: []},
            tarball=make_tarball(
                {"157-kafka-exporter.md": "# Kafka Exporter re-implementation\n"}
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)
        assert client.calls["files:247"] == 1

    def test_close_transition_freezes_votes(self):
        cache, _ = self._initial_cache()

        pulls = [
            make_pull(
                247,
                state="closed",
                closed_at="2026-02-12T00:00:00Z",
                updated_at="2026-02-12T00:00:00Z",
            ),
            make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
            make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
            make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
            make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
        ]
        client = FakeGithubClient(
            pulls=pulls,
            files={247: [make_file("158-new-proposal.md")]},
            reviews={
                247: [
                    make_review("final1", "APPROVED"),
                    make_review("final2", "CHANGES_REQUESTED"),
                ]
            },
            comments={247: []},
            tarball=make_tarball(
                {"157-kafka-exporter.md": "# Kafka Exporter re-implementation\n"}
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)

        record = cache["proposals"]["pr-247"]
        assert record["state"] == "not accepted"
        assert record["frozen"] is True
        assert record["activity_status"] is None
        assert [v["name"] for v in record["votes"]["+1"]] == ["final1"]
        assert [v["name"] for v in record["votes"]["-1"]] == ["final2"]
        assert cache["pr_index"]["247"]["frozen"] is True

    def test_reopen_unfreezes_and_resumes_tracking(self):
        cache, _ = self._initial_cache()
        # first: close the PR
        pulls = [
            make_pull(
                247,
                state="closed",
                closed_at="2026-02-12T00:00:00Z",
                updated_at="2026-02-12T00:00:00Z",
            ),
            make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
            make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
            make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
            make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
        ]
        client = FakeGithubClient(
            pulls=pulls,
            files={247: [make_file("158-new-proposal.md")]},
            reviews={247: []},
            comments={247: []},
            tarball=make_tarball(
                {"157-kafka-exporter.md": "# Kafka Exporter re-implementation\n"}
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)
        assert cache["proposals"]["pr-247"]["state"] == "not accepted"

        # then: reopen it
        reviews = [make_review("dev1", "APPROVED", "2026-02-13T00:00:00Z")]
        pulls = [
            make_pull(247, updated_at="2026-02-13T00:00:00Z"),
            make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
            make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
            make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
            make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
        ]
        client = FakeGithubClient(
            pulls=pulls,
            files={247: [make_file("158-new-proposal.md")]},
            reviews={247: reviews},
            comments={247: []},
            tarball=make_tarball(
                {"157-kafka-exporter.md": "# Kafka Exporter re-implementation\n"}
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)

        record = cache["proposals"]["pr-247"]
        assert record["state"] == "under discussion"
        assert record["frozen"] is False
        assert [v["name"] for v in record["votes"]["+1"]] == ["dev1"]
        assert record["activity_status"] is not None

    def test_new_merge_reconciles_to_numbered_record(self):
        cache, _ = self._initial_cache()

        pulls = [
            make_pull(
                247,
                state="closed",
                merged_at="2026-02-12T00:00:00Z",
                closed_at="2026-02-12T00:00:00Z",
                updated_at="2026-02-12T00:00:00Z",
                user="author2",
            ),
            make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
            make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
            make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
            make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
        ]
        client = FakeGithubClient(
            pulls=pulls,
            files={247: [make_file("158-new-proposal.md")]},
            reviews={
                247: [make_review("approver", "APPROVED", "2026-02-11T00:00:00Z")]
            },
            comments={247: []},
            tarball=make_tarball(
                {
                    "157-kafka-exporter.md": "# Kafka Exporter re-implementation\n",
                    "158-new-proposal.md": "# New Proposal\n",
                }
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)

        assert "pr-247" not in cache["proposals"]
        record = cache["proposals"]["158"]
        assert record["id"] == 158
        assert record["state"] == "accepted"
        assert record["pr_number"] == 247
        assert record["created_by"] == "author2"
        assert record["merged_on"] == "2026-02-12T00:00:00Z"
        assert record["frozen"] is True
        assert [v["name"] for v in record["votes"]["+1"]] == ["approver"]
        assert cache["pr_index"]["247"]["proposal_key"] == "158"

    def test_renumbered_merge_maps_via_slug(self):
        """A proposal merged with a different number than the PR's original
        file (renumbered on merge) still maps back via the slug."""

        cache, _ = self._initial_cache()

        pulls = [
            make_pull(
                247,
                state="closed",
                merged_at="2026-02-12T00:00:00Z",
                closed_at="2026-02-12T00:00:00Z",
                updated_at="2026-02-12T00:00:00Z",
            ),
            make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
            make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
            make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
            make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
        ]
        client = FakeGithubClient(
            pulls=pulls,
            files={247: [make_file("158-new-proposal.md")]},
            reviews={247: []},
            comments={247: []},
            tarball=make_tarball(
                {
                    "157-kafka-exporter.md": "# Kafka Exporter re-implementation\n",
                    "160-new-proposal.md": "# New Proposal\n",  # renumbered on merge
                }
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)

        assert "160" in cache["proposals"]
        assert cache["proposals"]["160"]["pr_number"] == 247

    def test_watermark_stops_paging(self):
        """PRs at/below the watermark with unchanged state are never
        re-fetched, and older entries after a changed PR are skipped."""

        cache, _ = self._initial_cache()
        before = dict(cache["pr_index"])

        client = FakeGithubClient(
            pulls=[
                make_pull(245, state="closed", merged_at="2026-02-01T00:00:00Z"),
                make_pull(248, state="closed", closed_at="2026-02-03T00:00:00Z"),
                make_pull(250, state="closed", merged_at="2026-02-04T00:00:00Z"),
                make_pull(251, state="closed", merged_at="2026-02-02T00:00:00Z"),
                make_pull(
                    247,
                    updated_at="2026-02-11T00:00:00Z",
                    title="Add new proposal",
                ),
            ],
            reviews={247: [make_review("dev1", "COMMENTED")]},
            comments={247: []},
            tarball=make_tarball(
                {"157-kafka-exporter.md": "# Kafka Exporter re-implementation\n"}
            ),
        )
        update_cache(STRIMZI_CONFIG, cache, client)

        # PRs after the changed one were not visited and their entries are
        # untouched
        for key in ("245", "248", "250", "251"):
            assert cache["pr_index"][key] == before[key]

    def test_tarball_always_downloaded(self):
        cache, _ = self._initial_cache()
        client = _strimzi_init_client()
        update_cache(STRIMZI_CONFIG, cache, client)
        assert client.calls["tarball"] == 1
