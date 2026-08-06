"""Fail-safe stale-gap policy for the prospective_event_v1 profile."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

NORMAL_THRESHOLD = timedelta(hours=36)
EVENT_WINDOW_THRESHOLD = timedelta(hours=24)
EVENT_DAY_THRESHOLD = timedelta(hours=12)


@dataclass(frozen=True)
class StaleAssessment:
    window: str
    threshold: timedelta
    age: Optional[timedelta]
    is_stale: bool


def assess_stale_gap(
    *,
    last_success_at: Optional[datetime],
    reference_time: datetime,
    schedule_profile: str,
    event_date: Optional[date] = None,
    event_date_required: bool = False,
) -> StaleAssessment:
    """Apply fixed pilot thresholds; ambiguity selects the strictest window."""
    _require_aware(reference_time, "reference_time")
    if last_success_at is not None:
        _require_aware(last_success_at, "last_success_at")
        if last_success_at > reference_time:
            raise ValueError("last_success_at must not be future-dated")
    if schedule_profile != "prospective_event_v1":
        raise ValueError("unsupported monitoring schedule profile")

    if event_date is None and event_date_required:
        window = "event_day"
        threshold = EVENT_DAY_THRESHOLD
    elif event_date == reference_time.date():
        window = "event_day"
        threshold = EVENT_DAY_THRESHOLD
    elif event_date is not None and reference_time.date() < event_date:
        business_days = _business_days_until(reference_time.date(), event_date)
        if business_days <= 5:
            window = "event_window"
            threshold = EVENT_WINDOW_THRESHOLD
        else:
            window = "normal"
            threshold = NORMAL_THRESHOLD
    else:
        window = "normal"
        threshold = NORMAL_THRESHOLD

    age = None if last_success_at is None else reference_time - last_success_at
    return StaleAssessment(window, threshold, age, age is None or age > threshold)


def _business_days_until(start: date, end: date) -> int:
    current = start
    count = 0
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("%s must be timezone-aware" % name)
