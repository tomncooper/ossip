"""Tests for ipper.common.utils module."""

import datetime as dt

from freezegun import freeze_time

from ipper.common.utils import calculate_age, generate_month_list


class TestGenerateMonthList:
    """Tests for the generate_month_list function."""

    def test_same_month(self):
        """Test generating list for same month."""
        now = dt.datetime(2026, 2, 7, tzinfo=dt.UTC)
        then = dt.datetime(2026, 2, 1, tzinfo=dt.UTC)
        result = generate_month_list(now, then)
        assert result == [(2026, 2)]

    def test_year_boundary(self):
        """Test generating list across year boundary."""
        now = dt.datetime(2026, 1, 15, tzinfo=dt.UTC)
        then = dt.datetime(2025, 11, 1, tzinfo=dt.UTC)
        result = generate_month_list(now, then)
        assert result == [(2025, 11), (2025, 12), (2026, 1)]

    def test_multi_year_span(self):
        """Test generating list spanning multiple years."""
        now = dt.datetime(2026, 2, 7, tzinfo=dt.UTC)
        then = dt.datetime(2025, 2, 1, tzinfo=dt.UTC)
        result = generate_month_list(now, then)

        # Should have 13 months (Feb 2025 through Feb 2026)
        assert len(result) == 13
        assert result[0] == (2025, 2)
        assert result[-1] == (2026, 2)

        # Verify continuity
        expected = [
            (2025, 2),
            (2025, 3),
            (2025, 4),
            (2025, 5),
            (2025, 6),
            (2025, 7),
            (2025, 8),
            (2025, 9),
            (2025, 10),
            (2025, 11),
            (2025, 12),
            (2026, 1),
            (2026, 2),
        ]
        assert result == expected

    def test_single_month_different_days(self):
        """Test that different days in the same month still return one month."""
        now = dt.datetime(2026, 2, 28, tzinfo=dt.UTC)
        then = dt.datetime(2026, 2, 1, tzinfo=dt.UTC)
        result = generate_month_list(now, then)
        assert result == [(2026, 2)]

    def test_no_future_months(self):
        """Test that no future months are generated."""
        now = dt.datetime(2026, 2, 7, tzinfo=dt.UTC)
        then = dt.datetime(2025, 12, 1, tzinfo=dt.UTC)
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
        now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        then = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        result = generate_month_list(now, then)

        # Should have 13 months (Jan 2025 through Jan 2026)
        assert len(result) == 13
        assert result[0] == (2025, 1)
        assert result[-1] == (2026, 1)

    def test_december_to_january(self):
        """Test the specific case of December to January transition."""
        now = dt.datetime(2026, 1, 15, tzinfo=dt.UTC)
        then = dt.datetime(2025, 12, 1, tzinfo=dt.UTC)
        result = generate_month_list(now, then)
        assert result == [(2025, 12), (2026, 1)]


class TestCalculateAge:
    """Tests for the calculate_age function."""

    def test_days_format_less_than_week(self):
        """Test age formatting for dates less than 7 days old."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 5 days ago
            date_str = "2026-02-02T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "5 days"

    def test_weeks_format(self):
        """Test age formatting for dates between 7 and 364 days."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 8 weeks ago (Dec 13 to Feb 7 = 1 month, 25 days = 1 month and 3 weeks)
            date_str = "2025-12-13T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "1 month and 3 weeks"

    def test_years_format(self):
        """Test age formatting for dates 365+ days old."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 1 year and 1 month ago (Jan 1, 2025 to Feb 7, 2026)
            date_str = "2025-01-01T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)

            # Should include years and months
            assert "year" in result
            assert "month" in result
            assert result == "1 year and 1 month"

    def test_exact_week(self):
        """Test age formatting for exactly 7 days."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # Exactly 7 days ago
            date_str = "2026-01-31T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            # 7 days should show as "1 week"
            assert result == "1 week"

    def test_single_day(self):
        """Test age formatting for exactly 1 day."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            date_str = "2026-02-06T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "1 day"

    def test_multiple_days_less_than_week(self):
        """Test age formatting for multiple days less than a week."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            date_str = "2026-02-03T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "4 days"

    def test_single_month(self):
        """Test age formatting for exactly 1 month."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 1 month ago (Jan 7 to Feb 7)
            date_str = "2026-01-07T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "1 month"

    def test_months_and_weeks(self):
        """Test age formatting with months and weeks."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 2 months and 2 weeks ago (Nov 24, 2025 to Feb 7, 2026)
            date_str = "2025-11-24T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "2 months and 2 weeks"

    def test_year_without_months_or_weeks(self):
        """Test age formatting for exactly 1 year."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # Exactly 1 year ago
            date_str = "2025-02-07T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "1 year"

    def test_years_and_months_no_weeks(self):
        """Test age formatting with years and months but no weeks."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 2 years and 3 months ago (Nov 7, 2023 to Feb 7, 2026)
            date_str = "2023-11-07T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "2 years and 3 months"

    def test_years_and_weeks_no_months(self):
        """Test age formatting with years and weeks but no months."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 3 years and 2 weeks ago (Jan 24, 2023 to Feb 7, 2026)
            date_str = "2023-01-24T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "3 years and 2 weeks"

    def test_years_months_and_weeks(self):
        """Test age formatting with all three components."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # 3 years, 3 months, and 2 weeks ago (Oct 24, 2022 to Feb 7, 2026)
            date_str = "2022-10-24T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "3 years, 3 months and 2 weeks"

    def test_month_boundary_31_days(self):
        """Test age calculation across month boundary with 31-day month."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # Jan 31 to Feb 7 = 0 months, 7 days = 1 week
            date_str = "2026-01-31T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "1 week"

    def test_leap_year_edge_case(self):
        """Test age calculation over leap year February."""

        with freeze_time("2024-03-01 12:00:00+00:00"):
            # Feb 1 to Mar 1 in leap year = 1 month
            date_str = "2024-02-01T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)
            assert result == "1 month"

    def test_plural_vs_singular(self):
        """Test that plural/singular forms are correct."""

        with freeze_time("2026-02-07 12:00:00+00:00"):
            # Test 2 of each unit (should be plural)
            date_str = "2022-10-24T12:00:00Z"
            date_format = "%Y-%m-%dT%H:%M:%SZ"
            result = calculate_age(date_str, date_format)

            # Should use plural forms
            assert "years" in result
            assert "months" in result
            assert "weeks" in result
