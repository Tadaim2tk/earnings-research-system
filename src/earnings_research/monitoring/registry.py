"""Read-only loading and planning for Human-owned monitor targets."""

import csv
from pathlib import Path
from typing import Dict, List

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


def active_target_plan(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Return only explicitly enabled, activated, approved Level 2 targets."""
    return [
        dict(row)
        for row in rows
        if row.get("enabled", "").lower() == "true"
        and row.get("activation_state") == "activated"
        and row.get("monitoring_level") == "level_2"
        and row.get("automated_access_permitted", "").lower() == "true"
    ]


def find_target(rows: List[Dict[str, str]], monitor_target_id: str) -> Dict[str, str]:
    matches = [row for row in rows if row.get("monitor_target_id") == monitor_target_id]
    if len(matches) != 1:
        raise RegistryError("monitor target must exist exactly once in registry")
    return dict(matches[0])
