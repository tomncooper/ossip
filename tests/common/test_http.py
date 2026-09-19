"""Tests for ipper.common.http retry helper."""

import logging

import pytest
import requests

from ipper.common.http import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_MAX_RETRIES,
    RETRY_STATUS_CODES,
    get_with_retries,
)


def _response(status_code: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


class TestGetWithRetriesSuccess:
    """The happy path: a successful response is returned without retries."""

    def test_returns_response(self, mocker):
        mock_get = mocker.patch(
            "ipper.common.http.requests.get", return_value=_response()
        )

        result = get_with_retries("https://example.com/api")

        assert result.status_code == 200
        assert mock_get.call_count == 1

    def test_passes_params_and_timeout(self, mocker):
        mock_get = mocker.patch(
            "ipper.common.http.requests.get", return_value=_response()
        )

        get_with_retries(
            "https://example.com/api",
            params={"limit": "100"},
            timeout=60,
        )

        mock_get.assert_called_once_with(
            "https://example.com/api", params={"limit": "100"}, timeout=60
        )

    def test_non_transient_error_status_returned(self, mocker):
        """404/403 are not transient: the response is returned as-is and the
        caller's raise_for_status() decides what to do with it."""
        mock_get = mocker.patch(
            "ipper.common.http.requests.get", return_value=_response(404)
        )

        result = get_with_retries("https://example.com/missing")

        assert result.status_code == 404
        assert mock_get.call_count == 1


class TestGetWithRetriesRetries:
    """Transient failures are retried with exponential backoff."""

    def test_read_timeout_then_success(self, mocker):
        """The exact CI failure: a read timeout on the first attempt."""
        mock_get = mocker.patch(
            "ipper.common.http.requests.get",
            side_effect=[
                requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)"),
                _response(),
            ],
        )
        mock_sleep = mocker.patch("ipper.common.http.time.sleep")

        result = get_with_retries("https://cwiki.apache.org/...")

        assert result.status_code == 200
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(DEFAULT_BACKOFF_FACTOR)

    def test_transient_status_then_success(self, mocker):
        for status in RETRY_STATUS_CODES:
            mock_get = mocker.patch(
                "ipper.common.http.requests.get",
                side_effect=[_response(status), _response()],
            )
            mocker.patch("ipper.common.http.time.sleep")

            result = get_with_retries("https://example.com/api")

            assert result.status_code == 200
            assert mock_get.call_count == 2

    def test_backoff_is_exponential(self, mocker):
        mocker.patch(
            "ipper.common.http.requests.get",
            side_effect=[
                requests.exceptions.ConnectionError("reset"),
                requests.exceptions.ConnectionError("reset"),
                _response(),
            ],
        )
        mock_sleep = mocker.patch("ipper.common.http.time.sleep")

        get_with_retries("https://example.com/api")

        assert [call.args[0] for call in mock_sleep.call_args_list] == [
            DEFAULT_BACKOFF_FACTOR * 1,
            DEFAULT_BACKOFF_FACTOR * 2,
        ]

    def test_retries_are_logged(self, mocker, caplog):
        """Retry warnings must be visible in CI logs."""
        mocker.patch(
            "ipper.common.http.requests.get",
            side_effect=[
                requests.exceptions.ReadTimeout("Read timed out."),
                _response(),
            ],
        )
        mocker.patch("ipper.common.http.time.sleep")

        with caplog.at_level(logging.WARNING, logger="ipper.common.http"):
            get_with_retries("https://example.com/api")

        assert any("attempt 1/5" in record.message for record in caplog.records)

    def test_all_attempts_exhausted_raises_last_exception(self, mocker):
        error = requests.exceptions.ReadTimeout("Read timed out.")
        mock_get = mocker.patch("ipper.common.http.requests.get", side_effect=error)
        mock_sleep = mocker.patch("ipper.common.http.time.sleep")

        with pytest.raises(requests.exceptions.ReadTimeout):
            get_with_retries("https://example.com/api")

        assert mock_get.call_count == DEFAULT_MAX_RETRIES + 1
        assert mock_sleep.call_count == DEFAULT_MAX_RETRIES

    def test_exhaustion_is_logged_as_error(self, mocker, caplog):
        mocker.patch(
            "ipper.common.http.requests.get",
            side_effect=requests.exceptions.ConnectionError("reset"),
        )
        mocker.patch("ipper.common.http.time.sleep")

        with (
            caplog.at_level(logging.ERROR, logger="ipper.common.http"),
            pytest.raises(requests.exceptions.ConnectionError),
        ):
            get_with_retries("https://example.com/api")

        assert any("failed after" in record.message for record in caplog.records)


class TestDefaults:
    def test_default_retry_policy(self):
        assert DEFAULT_MAX_RETRIES == 4
        assert DEFAULT_BACKOFF_FACTOR == 2.0
        assert RETRY_STATUS_CODES == (429, 500, 502, 503, 504)
