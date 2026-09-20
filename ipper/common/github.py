"""GitHub REST API client for proposal tracking.

Wraps the GitHub REST API for projects that manage improvement proposals
in GitHub repositories (Strimzi SIPs, StreamsHub SHIPs, Kroxylicious KDPs).

Authentication uses the ``GITHUB_TOKEN`` environment variable when present.
It is *required* for ``init`` / ``refresh`` (a full Strimzi fetch costs ~500
requests against the 60/hr unauthenticated limit) and optional for
``update`` (incremental updates cost ~5-15 requests per project per run).
"""

import logging
import os
from collections.abc import Iterator
from typing import Any

import requests

from ipper.common.http import get_with_retries

logger = logging.getLogger(__name__)

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"


class GithubClientError(Exception):
    """Base error for GitHub API client failures."""


class GithubRateLimitError(GithubClientError):
    """Raised when the GitHub API rate limit is exhausted."""


class GithubTokenRequiredError(GithubClientError):
    """Raised when an operation requires GITHUB_TOKEN but none is set."""


class GithubTokenRejectedError(GithubClientError):
    """Raised when GitHub rejects the provided token (401 Bad credentials)."""


class GithubClient:
    """A thin client over the GitHub REST API with pagination support.

    Args:
        owner: Repository owner (e.g. "strimzi")
        repo: Repository name (e.g. "proposals")
        token: Explicit API token; defaults to the GITHUB_TOKEN env var
        require_token: Raise GithubTokenRequiredError when no token is available
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        require_token: bool = False,
    ) -> None:
        self.owner = owner
        self.repo = repo

        self.token = (
            token if token is not None else os.environ.get(GITHUB_TOKEN_ENV_VAR)
        )
        if require_token and not self.token:
            raise GithubTokenRequiredError(
                f"This operation requires a GitHub API token. Set the "
                f"{GITHUB_TOKEN_ENV_VAR} environment variable (see "
                f"https://github.com/settings/tokens). Unauthenticated "
                f"requests are limited to 60/hour which is not enough for a "
                f"full fetch."
            )

        self._headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ossip-ipper",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
        }
        self.session = requests.Session()
        self.session.headers.update(self._headers)

    def _repo_url(self, path: str) -> str:
        return f"{GITHUB_API_BASE_URL}/repos/{self.owner}/{self.repo}/{path}"

    def _check_response(self, response: requests.Response) -> None:
        if response.status_code == 401:
            raise GithubTokenRejectedError(
                "GitHub rejected the API token (401 Bad credentials). Check that "
                f"the {GITHUB_TOKEN_ENV_VAR} environment variable contains a "
                "valid, unexpired token (https://github.com/settings/tokens)."
            )
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = response.headers.get("X-RateLimit-Reset", "unknown")
            raise GithubRateLimitError(
                "GitHub API rate limit exhausted. "
                + (f"Resets at unix timestamp {reset}. " if reset != "unknown" else "")
                + f"Set the {GITHUB_TOKEN_ENV_VAR} environment variable to "
                + "raise the limit from 60/hour to 5000/hour."
            )
        if response.status_code >= 400:
            raise GithubClientError(
                f"GitHub API error {response.status_code} for {response.url}: "
                f"{response.text[:200]}"
            )

    def _request(
        self, url: str, params: dict[str, Any] | None = None
    ) -> requests.Response:
        response = get_with_retries(
            url, params=params, timeout=30, headers=dict(self._headers)
        )
        self._check_response(response)
        return response

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a single JSON resource under the repository path."""
        response = self._request(self._repo_url(path), params)
        return response.json()

    def paginate(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every item of a paginated collection endpoint.

        Follows RFC 5988 ``Link`` headers returned by the GitHub API.
        """
        params = dict(params or {})
        params.setdefault("per_page", 100)

        url: str | None = self._repo_url(path)
        first = True
        while url:
            response = self._request(url, params if first else None)
            first = False
            yield from response.json()
            url = response.links.get("next", {}).get("url")

    def download_tarball(self, ref: str = "main") -> bytes:
        """Download the gzipped tarball of the repository at the given ref."""
        response = self._request(self._repo_url(f"tarball/{ref}"))
        return response.content

    def list_pulls(
        self,
        state: str = "all",
        sort: str = "updated",
        direction: str = "desc",
    ) -> Iterator[dict[str, Any]]:
        """Yield every pull request in the given state, paginated.

        Entries carry ``updated_at``, ``state`` and ``head.sha`` which drive
        the incremental-update gating.
        """
        yield from self.paginate(
            "pulls",
            params={"state": state, "sort": sort, "direction": direction},
        )

    def get_pull_files(self, pr_number: int) -> Iterator[dict[str, Any]]:
        """Yield the file entries (filename/status) touched by a pull request."""
        yield from self.paginate(f"pulls/{pr_number}/files")

    def get_pull_reviews(self, pr_number: int) -> Iterator[dict[str, Any]]:
        """Yield the reviews submitted on a pull request."""
        yield from self.paginate(f"pulls/{pr_number}/reviews")

    def get_issue_comments(self, pr_number: int) -> Iterator[dict[str, Any]]:
        """Yield the (issue-style) comments posted on a pull request."""
        yield from self.paginate(f"issues/{pr_number}/comments")

    def get_pull(self, pr_number: int) -> dict[str, Any]:
        """Fetch a single pull request."""
        return self.get(f"pulls/{pr_number}")
