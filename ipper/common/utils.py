import datetime as dt

from dateutil.relativedelta import relativedelta


def generate_month_list(now: dt.datetime, then: dt.datetime) -> list[tuple[int, int]]:
    """Generates a list of year-month strings spanning from then to now"""

    month_list: list[tuple[int, int]] = []

    year: int = then.year
    month: int = then.month
    finished: bool = False

    while not finished:
        month_list.append((year, month))

        # Check if we've reached or passed the current month/year
        if year > now.year or (year == now.year and month >= now.month):
            finished = True
        else:
            # Move to next month
            month = (month + 1) % 13
            if month == 0:
                year += 1
                month = 1

    return month_list


def calculate_age(date_str: str, date_format: str) -> str:
    """Calculate the age string for the given date string"""

    then: dt.datetime = dt.datetime.strptime(date_str, date_format).replace(
        tzinfo=dt.UTC
    )
    now: dt.datetime = dt.datetime.now(dt.UTC)

    # Get timedelta for day count
    diff: dt.timedelta = now - then

    # For very recent dates, just show days
    if diff.days < 7:
        day_word = "day" if diff.days == 1 else "days"
        return f"{diff.days} {day_word}"

    # Use relativedelta for accurate calendar-based calculations
    delta = relativedelta(now, then)
    years = delta.years
    months = delta.months

    # Calculate remaining weeks from leftover days
    remaining_days = delta.days
    weeks = remaining_days // 7

    # Build output components
    parts = []

    if years > 0:
        # For 1+ years: show years, months (if non-zero), and weeks (if non-zero)
        year_word = "year" if years == 1 else "years"
        parts.append(f"{years} {year_word}")

        if months > 0:
            month_word = "month" if months == 1 else "months"
            parts.append(f"{months} {month_word}")

        if weeks > 0:
            week_word = "week" if weeks == 1 else "weeks"
            parts.append(f"{weeks} {week_word}")
    elif months > 0:
        # For 1-11 months: show months and weeks (if non-zero)
        month_word = "month" if months == 1 else "months"
        parts.append(f"{months} {month_word}")

        if weeks > 0:
            week_word = "week" if weeks == 1 else "weeks"
            parts.append(f"{weeks} {week_word}")
    else:
        # Less than 1 month but >= 7 days: show weeks only
        week_word = "week" if weeks == 1 else "weeks"
        return f"{weeks} {week_word}"

    # Format output with commas and "and"
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    else:
        # 3 parts: "X years, Y months and Z weeks"
        return f"{parts[0]}, {parts[1]} and {parts[2]}"
