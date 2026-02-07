"""Pytest configuration and shared fixtures."""
import datetime as dt
import pytest


@pytest.fixture
def sample_datetime_utc():
    """Returns a sample datetime with UTC timezone for testing."""
    return dt.datetime(2026, 2, 7, 12, 0, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def sample_email_date_strings():
    """Returns sample email date strings in various formats."""
    return {
        "standard": "Fri, 07 Feb 2026 12:00:00 +0000",
        "with_tz": "Fri, 07 Feb 2026 12:00:00 +0000 (UTC)",
        "with_tz_string": "Fri, 07 Feb 2026 12:00:00 +0000 (GMT)",
    }
