"""Shared HTTP helpers with retry support.

The daily CI build talks to the Apache Confluence REST API, the mailing
list archive API and the Apache downloads server. These occasionally
return transient failures (read timeouts, connection resets, 429/5xx
responses) which used to kill the whole workflow. GET is idempotent, so
failed requests can safely be re-issued.
"""

import logging
import time
from collections.abc import Mapping
from typing import Any

import requests

logger = logging.getLogger(__name__)

# HTTP status codes worth retrying (rate limiting + transient server errors)
RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)

# Total attempts = 1 initial + max_retries, sleeping backoff_factor *
# 2**(attempt-1) seconds between attempts (default: 2s, 4s, 8s, 16s)
DEFAULT_MAX_RETRIES: int = 4
DEFAULT_BACKOFF_FACTOR: float = 2.0


def get_with_retries(
    url: str,
    params: Mapping[str, Any] | None = None,
    timeout: int = 30,
    headers: Mapping[str, str] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
) -> requests.Response:
    """Issue a GET request, retrying transient failures with backoff.

    Retries connection errors, timeouts and transient HTTP status codes
    (429 and 5xx). Every retry is logged at WARNING level so transient
    upstream problems are visible in CI logs.

    Args:
        url: The URL to fetch
        params: Optional query-string parameters
        timeout: Per-attempt request timeout in seconds
        headers: Optional request headers (e.g. Authorization)
        max_retries: Number of retries after the initial attempt
        backoff_factor: Exponential backoff base in seconds

    Returns:
        The first successful (non-transient) response

    Raises:
        requests.RequestException: The last failure if all attempts fail
    """
    max_attempts: int = max_retries + 1
    last_exception: requests.RequestException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response: requests.Response = requests.get(
                url, params=params, timeout=timeout, headers=headers
            )
            if response.status_code in RETRY_STATUS_CODES:
                raise requests.HTTPError(
                    f"Transient HTTP {response.status_code}", response=response
                )
            return response
        except requests.RequestException as ex:
            last_exception = ex
            if attempt == max_attempts:
                break
            sleep_for: float = backoff_factor * (2 ** (attempt - 1))
            logger.warning(
                "GET %s failed (attempt %d/%d): %s. Retrying in %.0fs",
                url,
                attempt,
                max_attempts,
                ex,
                sleep_for,
            )
            time.sleep(sleep_for)

    assert last_exception is not None  # loop ran at least once
    logger.error(
        "GET %s failed after %d attempts: %s",
        url,
        max_attempts,
        last_exception,
    )
    raise last_exception
