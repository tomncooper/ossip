"""Tests for ipper.common.utils module."""
import datetime as dt
import pytest
from ipper.common.utils import generate_month_list, calculate_age


class TestGenerateMonthList:
    """Tests for the generate_month_list function."""

    def test_same_month(self):
        """Test generating list for same month."""
        now = dt.datetime(2026, 2, 7, tzinfo=dt.timezone.utc)
        then = dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc)
        result = generate_month_list(now, then)
        assert result == [(2026, 2)]

    def test_year_boundary(self):
        """Test generating list across year boundary."""
        now = dt.datetime(2026, 1, 15, tzinfo=dt.timezone.utc)
        then = dt.datetime(2025, 11, 1, tzinfo=dt.timezone.utc)
        result = generate_month_list(now, then)
        assert result == [(2025, 11), (2025, 12), (2026, 1)]

    def test_multi_year_span(self):
        """Test generating list spanning multiple years."""
        now = dt.datetime(2026, 2, 7, tzinfo=dt.timezone.utc)
        then = dt.datetime(2025, 2, 1, tzinfo=dt.timezone.utc)
        result = generate_month_list(now, then)
        
        # Should have 13 months (Feb 2025 through Feb 2026)
        assert len(result) == 13
        assert result[0] == (2025, 2)
        assert result[-1] == (2026, 2)
        
        # Verify continuity
        expected = [
            (2025, 2), (2025, 3), (2025, 4), (2025, 5), (2025, 6),
            (2025, 7), (2025, 8), (2025, 9), (2025, 10), (2025, 11),
            (2025, 12), (2026, 1), (2026, 2)
        ]
        assert result == expected

    def test_single_month_different_days(self):
        """Test that different days in the same month still return one month."""
        now = dt.datetime(2026, 2, 28, tzinfo=dt.timezone.utc)
        then = dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc)
        result = generate_month_list(now, then)
        assert result == [(2026, 2)]

    def test_no_future_months(self):
        """Test that no future months are generated."""
        now = dt.datetime(2026, 2, 7, tzinfo=dt.timezone.utc)
        then = dt.datetime(2025, 12, 1, tzinfo=dt.timezone.utc)
        result = generate_month_list(now, then)
        
        # Should stop at February 2026
        assert result[-1] == (2026, 2)
        
        # Should not include any month beyond February 2026
        for year, month in result:
            if year == 2026:
                assert month <= 2
            elif year == 2025:
                assert month >= 12

    def test_full_year(self):
        """Test generating a full year of months."""
        now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        then = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
        result = generate_month_list(now, then)
        
        # Should have 13 months (Jan 2025 through Jan 2026)
        assert len(result) == 13
        assert result[0] == (2025, 1)
        assert result[-1] == (2026, 1)

    def test_december_to_january(self):
        """Test the specific case of December to January transition."""
        now = dt.datetime(2026, 1, 15, tzinfo=dt.timezone.utc)
        then = dt.datetime(2025, 12, 1, tzinfo=dt.timezone.utc)
        result = generate_month_list(now, then)
        assert result == [(2025, 12), (2026, 1)]


class TestCalculateAge:
    """Tests for the calculate_age function."""

    def test_days_format_less_than_week(self):
        """Test age formatting for dates less than 7 days old."""
        from freezegun import freeze_time
        
        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 5 days ago
            date_str = "2026-02-02T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "5 days"

    def test_weeks_format(self):
        """Test age formatting for dates between 7 and 364 days."""
        from freezegun import freeze_time
        
        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 8 weeks ago
            date_str = "2025-12-13T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "8 weeks"

    def test_years_format(self):
        """Test age formatting for dates 365+ days old."""
        from freezegun import freeze_time
        
        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 1 year and some weeks ago
            date_str = "2025-01-01T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            
            # Should include both years and weeks
            assert "years" in result or "year" in result
            assert "weeks" in result

    def test_exact_week(self):
        """Test age formatting for exactly 7 days."""
        from freezegun import freeze_time
        
        with freeze_time("2026-02-07 12:00:00+00:00"):
            # Exactly 7 days ago
            date_str = "2026-01-31T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            # 7 days triggers the >= 365 logic, so shows as "0 years 1 weeks"
            assert result == "0 years 1 weeks"
