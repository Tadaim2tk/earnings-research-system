"""Read-only loading and planning for Human-owned monitor targets."""

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from earnings_research.monitoring.stale import _business_days_until
from earnings_research.validation.validator import load_spec, validate_monitor_registry


class RegistryError(ValueError):
    """Raised when Human-owned configuration is incomplete or invalid."""


def load_registry(path: Path) -> List[Dict[str, str]]:
    """Load and validate target configuration without exposing a write API."""
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = [column.name for column in load_spec("monitor_target").columns]
        if reader.fieldnames != expected:
            raise RegistryError("monitor registry columns must exactly match monitor_target schema")
        rows = list(reader)
    report = validate_monitor_registry(rows)
    if not report.ok:
        raise RegistryError("\n".join(issue.format() for issue in report.issues))
    return rows


def active_target_plan(
    rows: List[Dict[str, str]],
    *,
    planned_at: Optional[datetime] = None,
    force: bool = False,
    observed_event_dates: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """Return only explicitly enabled, activated, approved Level 2 targets.

    ``observed_event_dates`` maps a target to the announcement date read from
    its schedule source. It takes precedence over the registry column so a date
    the company moved does not have to be retyped by hand.
    """
    active = [
        dict(row)
        for row in rows
        if row.get("enabled", "").lower() == "true"
        and row.get("activation_state") == "activated"
        and row.get("monitoring_level") == "level_2"
        and row.get("automated_access_permitted", "").lower() == "true"
    ]
    for row in active:
        observed = (observed_event_dates or {}).get(row["monitor_target_id"], "")
        if observed:
            row["event_date"] = observed
    if force or planned_at is None:
        return active
    return [row for row in active if _is_due(row, planned_at)]


def _is_due(target: Dict[str, str], planned_at: datetime) -> bool:
    if planned_at.tzinfo is None or planned_at.utcoffset() is None:
        raise RegistryError("planned_at must be timezone-aware")
    local = planned_at.astimezone(timezone(timedelta(hours=9)))
    if local.weekday() >= 5:
        return False
    event_date = target.get("event_date", "")
    # The workflow fires every four hours at 01:17 through 21:17 JST, but a scheduled run can
    # start hours late. Matching the hour exactly meant a delayed run never
    # became due, so each cron slot owns the window that follows it instead.
    if event_date:
        parsed_event_date = datetime.fromisoformat(event_date).date()
        if local.date() == parsed_event_date:
            return True
        if local.date() < parsed_event_date and _business_days_until(local.date(), parsed_event_date) <= 5:
            return True
    # Only the 17:17 slot owns the normal-day window, preserving one request per
    # day. It follows the close, so a same-day disclosure is seen the same day
    # instead of waiting for the next morning.
    return 17 <= local.hour < 21


def next_announcement_date(schedule: str, on_or_after: date) -> Optional[str]:
    """Return the first announced date that has not passed, or None.

    ``schedule`` is the checkpoint field written by the calendar source, for
    example ``2026-08-13=...;2026-11-13=... | 2027-02-中旬=...``. Rows whose day
    was never published sit after the separator and are ignored here: a window
    cannot be opened on a date the company has not given.
    """
    dated = schedule.split("|", 1)[0]
    upcoming = []
    for entry in dated.split(";"):
        candidate = entry.split("=", 1)[0].strip()
        if not candidate:
            continue
        try:
            parsed = date.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed >= on_or_after:
            upcoming.append(parsed)
    return min(upcoming).isoformat() if upcoming else None


def observed_event_dates(
    rows: List[Dict[str, str]],
    schedules: Dict[str, str],
    on_or_after: date,
) -> Dict[str, str]:
    """Map each target to the announcement date its schedule source published."""
    resolved = {}
    for row in rows:
        source = row.get("schedule_source_target_id", "")
        if not source:
            continue
        announced = next_announcement_date(schedules.get(source, ""), on_or_after)
        if announced:
            resolved[row["monitor_target_id"]] = announced
    return resolved


def find_target(rows: List[Dict[str, str]], monitor_target_id: str) -> Dict[str, str]:
    matches = [row for row in rows if row.get("monitor_target_id") == monitor_target_id]
    if len(matches) != 1:
        raise RegistryError("monitor target must exist exactly once in registry")
    return dict(matches[0])
