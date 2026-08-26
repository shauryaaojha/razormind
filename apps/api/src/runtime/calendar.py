"""The IST business calendar. One implementation, used everywhere.

Rules (docs/02-data-model.md#time, correction C-10):

* Timestamps are stored as UTC ``TIMESTAMPTZ``. A "date" always means the
  **IST calendar date**, derived here -- never ``UTC::date``.
* Capture cutoff is 18:00 IST. A capture at or after the cutoff joins the next
  business day's settlement cycle.
* Settlement SLA is T+2 **business** days from the cutoff-adjusted date.
* Business days are Mon-Fri minus the fixed holiday list in
  ``data/seed/holidays_2026.json``.
* Periods are half-open ``[from, to)`` in IST, so adjacent periods tile with
  neither overlap nor gap.

``Asia/Kolkata`` has no DST, which is the only reason a fixed +05:30 offset is
safe to reason about.
"""

import json
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

__all__ = [
    "CAPTURE_CUTOFF",
    "IST",
    "SETTLEMENT_LAG_BUSINESS_DAYS",
    "NaiveDatetimeError",
    "add_business_days",
    "business_days_between",
    "effective_capture_date",
    "holidays",
    "is_business_day",
    "ist_date",
    "next_business_day",
    "period_contains",
    "period_days",
    "periods_overlap",
    "settlement_due_date",
]

IST = ZoneInfo("Asia/Kolkata")

CAPTURE_CUTOFF = time(18, 0)
"""Captures at or after 18:00 IST settle on the next business day's cycle."""

SETTLEMENT_LAG_BUSINESS_DAYS = 2
"""T+2, counted in business days from the cutoff-adjusted capture date."""

_HOLIDAY_FILE = Path(__file__).resolve().parents[4] / "data" / "seed" / "holidays_2026.json"


class NaiveDatetimeError(ValueError):
    """A naive datetime reached the calendar.

    Every timestamp in this system is timezone-aware. A naive one has an
    unknowable IST date, so it is an error rather than an assumption.
    """


@lru_cache(maxsize=1)
def holidays() -> frozenset[date]:
    """The fixed holiday list, read once.

    Cached because it is read on every settlement-date computation and the file
    is immutable at runtime -- changing it is a fixture change (see the note in
    the JSON), not a hot reload.
    """
    payload = json.loads(_HOLIDAY_FILE.read_text(encoding="utf-8"))
    return frozenset(date.fromisoformat(entry["date"]) for entry in payload["holidays"])


def ist_date(moment: datetime) -> date:
    """The IST calendar date of an aware datetime.

    A capture at 20:00 UTC on Aug 1 is 01:30 IST on Aug 2, and belongs to
    the Aug 2 business date -- which is why ``UTC::date`` is banned.
    """
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise NaiveDatetimeError(f"naive datetime has no IST date: {moment!r}")
    return moment.astimezone(IST).date()


def is_business_day(day: date) -> bool:
    """Mon-Fri and not a listed holiday."""
    return day.weekday() < 5 and day not in holidays()


def next_business_day(day: date) -> date:
    """The first business day strictly after ``day``."""
    candidate = day + timedelta(days=1)
    while not is_business_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def add_business_days(day: date, count: int) -> date:
    """Advance ``count`` business days from ``day``.

    ``count`` of zero rolls forward to ``day`` itself if it is a business day,
    or to the next one if it is not -- so the result is always a business day.
    """
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    current = day
    while not is_business_day(current):
        current += timedelta(days=1)
    for _ in range(count):
        current = next_business_day(current)
    return current


def business_days_between(start: date, end: date) -> int:
    """Business days in the half-open interval ``[start, end)``.

    Used by the matcher's timing-lag windows, so it counts intervals rather
    than endpoints: a settlement one business day late is a lag of 1.
    """
    if end < start:
        raise ValueError(f"end {end} precedes start {start}")
    count = 0
    current = start
    while current < end:
        if is_business_day(current):
            count += 1
        current += timedelta(days=1)
    return count


def effective_capture_date(captured_at: datetime) -> date:
    """The settlement cycle a capture joins.

    The IST capture date, pushed to the next day if the capture was at or after
    the 18:00 cutoff, then rolled forward to a business day.
    """
    day = ist_date(captured_at)
    if captured_at.astimezone(IST).time() >= CAPTURE_CUTOFF:
        day += timedelta(days=1)
    return add_business_days(day, 0)


def settlement_due_date(captured_at: datetime) -> date:
    """T+2 business days from the cutoff-adjusted capture date."""
    return add_business_days(effective_capture_date(captured_at), SETTLEMENT_LAG_BUSINESS_DAYS)


def period_contains(day: date, period_from: date, period_to: date) -> bool:
    """Half-open membership: ``period_from <= day < period_to``."""
    _require_ordered(period_from, period_to)
    return period_from <= day < period_to


def period_days(period_from: date, period_to: date) -> int:
    """Calendar days in ``[period_from, period_to)``.

    >>> period_days(date(2026, 8, 1), date(2026, 8, 24))
    23
    """
    _require_ordered(period_from, period_to)
    return (period_to - period_from).days


def periods_overlap(a_from: date, a_to: date, b_from: date, b_to: date) -> bool:
    """Whether two half-open periods share any day.

    The analysis period and its comparison period must not overlap; the plan
    validator uses this (docs/05-agent-runtime.md).
    """
    _require_ordered(a_from, a_to)
    _require_ordered(b_from, b_to)
    return a_from < b_to and b_from < a_to


def _require_ordered(period_from: date, period_to: date) -> None:
    """Vision §11's ``period.start < period.end``, enforced not assumed."""
    if period_from >= period_to:
        raise ValueError(f"period start {period_from} is not before end {period_to}")
