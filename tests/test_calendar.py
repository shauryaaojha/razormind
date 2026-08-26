"""runtime.calendar -- 100% branch coverage is a Phase 0 exit criterion.

Correction C-10: the spec had no timezone and no settlement cutoff, so
"settled on time" was undefined. These tests pin the definition.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from runtime.calendar import (
    CAPTURE_CUTOFF,
    IST,
    SETTLEMENT_LAG_BUSINESS_DAYS,
    NaiveDatetimeError,
    add_business_days,
    business_days_between,
    effective_capture_date,
    holidays,
    is_business_day,
    ist_date,
    next_business_day,
    period_contains,
    period_days,
    periods_overlap,
    settlement_due_date,
)


class TestIstDate:
    def test_utc_evening_is_the_next_ist_day(self) -> None:
        """20:00 UTC Aug 1 is 01:30 IST Aug 2. This is why UTC::date is banned."""
        assert ist_date(datetime(2026, 8, 1, 20, 0, tzinfo=UTC)) == date(2026, 8, 2)

    def test_utc_morning_is_the_same_ist_day(self) -> None:
        assert ist_date(datetime(2026, 8, 1, 6, 0, tzinfo=UTC)) == date(2026, 8, 1)

    def test_already_ist(self) -> None:
        assert ist_date(datetime(2026, 8, 1, 9, 0, tzinfo=IST)) == date(2026, 8, 1)

    def test_naive_datetime_is_an_error_not_an_assumption(self) -> None:
        with pytest.raises(NaiveDatetimeError, match="naive datetime has no IST date"):
            ist_date(datetime(2026, 8, 1, 9, 0))  # noqa: DTZ001

    def test_ist_has_no_dst(self) -> None:
        """A fixed +05:30 offset is only safe because Asia/Kolkata has no DST."""
        offsets = {datetime(2026, m, 15, 12, 0, tzinfo=IST).utcoffset() for m in range(1, 13)}
        assert offsets == {timedelta(hours=5, minutes=30)}


class TestBusinessDays:
    def test_weekday_is_a_business_day(self) -> None:
        assert is_business_day(date(2026, 8, 3))  # Monday

    def test_weekend_is_not(self) -> None:
        assert not is_business_day(date(2026, 8, 1))  # Saturday
        assert not is_business_day(date(2026, 8, 2))  # Sunday

    def test_listed_holiday_is_not(self) -> None:
        assert date(2026, 1, 26) in holidays()  # Republic Day, a Monday
        assert not is_business_day(date(2026, 1, 26))

    def test_holiday_list_is_read_once(self) -> None:
        assert holidays() is holidays()

    def test_next_business_day_skips_the_weekend(self) -> None:
        assert next_business_day(date(2026, 8, 7)) == date(2026, 8, 10)  # Fri -> Mon

    def test_next_business_day_skips_a_holiday_run(self) -> None:
        """Fri Aug 14 -> Sat 15 is Independence Day -> Sun 16 -> Mon 17."""
        assert next_business_day(date(2026, 8, 14)) == date(2026, 8, 17)

    def test_add_zero_rolls_a_non_business_day_forward(self) -> None:
        assert add_business_days(date(2026, 8, 1), 0) == date(2026, 8, 3)

    def test_add_zero_leaves_a_business_day_alone(self) -> None:
        assert add_business_days(date(2026, 8, 3), 0) == date(2026, 8, 3)

    def test_add_two(self) -> None:
        assert add_business_days(date(2026, 8, 3), 2) == date(2026, 8, 5)

    def test_negative_count_rejected(self) -> None:
        with pytest.raises(ValueError, match="count must be non-negative"):
            add_business_days(date(2026, 8, 3), -1)

    def test_business_days_between_is_half_open(self) -> None:
        assert business_days_between(date(2026, 8, 3), date(2026, 8, 3)) == 0
        assert business_days_between(date(2026, 8, 3), date(2026, 8, 4)) == 1
        assert business_days_between(date(2026, 8, 3), date(2026, 8, 10)) == 5

    def test_business_days_between_rejects_a_reversed_interval(self) -> None:
        with pytest.raises(ValueError, match="precedes start"):
            business_days_between(date(2026, 8, 10), date(2026, 8, 3))


class TestSettlement:
    def test_cutoff_is_eighteen_hundred_ist(self) -> None:
        assert (CAPTURE_CUTOFF.hour, CAPTURE_CUTOFF.minute) == (18, 0)

    def test_sla_is_t_plus_two(self) -> None:
        assert SETTLEMENT_LAG_BUSINESS_DAYS == 2

    def test_before_cutoff_settles_from_the_same_day(self) -> None:
        captured = datetime(2026, 8, 3, 17, 59, tzinfo=IST)  # Monday
        assert effective_capture_date(captured) == date(2026, 8, 3)
        assert settlement_due_date(captured) == date(2026, 8, 5)

    def test_at_the_cutoff_rolls_to_the_next_cycle(self) -> None:
        """18:00 exactly is after the cutoff. A boundary defined, not guessed."""
        captured = datetime(2026, 8, 3, 18, 0, tzinfo=IST)
        assert effective_capture_date(captured) == date(2026, 8, 4)
        assert settlement_due_date(captured) == date(2026, 8, 6)

    def test_friday_evening_crosses_the_weekend(self) -> None:
        captured = datetime(2026, 8, 7, 19, 30, tzinfo=IST)  # Friday, after cutoff
        assert effective_capture_date(captured) == date(2026, 8, 10)  # Monday
        assert settlement_due_date(captured) == date(2026, 8, 12)

    def test_a_holiday_extends_the_window(self) -> None:
        """Fri Aug 14 after cutoff: Sat is Independence Day, so the cycle is Mon."""
        captured = datetime(2026, 8, 14, 18, 0, tzinfo=IST)
        assert effective_capture_date(captured) == date(2026, 8, 17)
        assert settlement_due_date(captured) == date(2026, 8, 19)

    def test_a_capture_stored_as_utc_still_uses_the_ist_cutoff(self) -> None:
        """13:00 UTC is 18:30 IST -- after the cutoff, despite looking like midday."""
        captured = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)
        assert effective_capture_date(captured) == date(2026, 8, 4)

    def test_saturday_capture_joins_the_monday_cycle(self) -> None:
        captured = datetime(2026, 8, 1, 10, 0, tzinfo=IST)
        assert effective_capture_date(captured) == date(2026, 8, 3)


class TestPeriods:
    def test_the_analysis_window_is_twenty_three_days(self) -> None:
        """docs/08-seed-data.md: 2026-08-01 -> 2026-08-24 covers Aug 1-23."""
        assert period_days(date(2026, 8, 1), date(2026, 8, 24)) == 23
        assert period_days(date(2026, 7, 1), date(2026, 7, 24)) == 23

    def test_membership_is_half_open(self) -> None:
        start, end = date(2026, 8, 1), date(2026, 8, 24)
        assert period_contains(start, start, end)
        assert period_contains(date(2026, 8, 23), start, end)
        assert not period_contains(end, start, end)
        assert not period_contains(date(2026, 7, 31), start, end)

    def test_adjacent_periods_tile_without_gap_or_overlap(self) -> None:
        july = (date(2026, 7, 1), date(2026, 8, 1))
        august = (date(2026, 8, 1), date(2026, 9, 1))
        assert not periods_overlap(*july, *august)
        assert period_contains(date(2026, 8, 1), *august)
        assert not period_contains(date(2026, 8, 1), *july)

    def test_the_golden_comparison_periods_do_not_overlap(self) -> None:
        assert not periods_overlap(
            date(2026, 8, 1), date(2026, 8, 24), date(2026, 7, 1), date(2026, 7, 24)
        )

    def test_overlap_is_detected_from_either_side(self) -> None:
        assert periods_overlap(
            date(2026, 8, 1), date(2026, 8, 24), date(2026, 8, 20), date(2026, 9, 1)
        )
        assert periods_overlap(
            date(2026, 8, 20), date(2026, 9, 1), date(2026, 8, 1), date(2026, 8, 24)
        )

    def test_an_empty_or_reversed_period_is_rejected(self) -> None:
        """Vision 11's period.start < period.end, enforced rather than assumed."""
        with pytest.raises(ValueError, match="is not before end"):
            period_days(date(2026, 8, 1), date(2026, 8, 1))
        with pytest.raises(ValueError, match="is not before end"):
            period_contains(date(2026, 8, 1), date(2026, 8, 24), date(2026, 8, 1))
        with pytest.raises(ValueError, match="is not before end"):
            periods_overlap(
                date(2026, 8, 24), date(2026, 8, 1), date(2026, 7, 1), date(2026, 7, 24)
            )
        with pytest.raises(ValueError, match="is not before end"):
            periods_overlap(
                date(2026, 8, 1), date(2026, 8, 24), date(2026, 7, 24), date(2026, 7, 1)
            )
