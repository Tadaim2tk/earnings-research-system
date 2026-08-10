"""File entry points for market reaction tracking."""

import csv
import json
from datetime import datetime
from pathlib import Path

from earnings_research.earnings_evaluation.models import EarningsEvaluation
from earnings_research.market_reaction.models import (
    MarketReactionObservationBundle,
    MarketReactionTracking,
)
from earnings_research.market_reaction.tracker import track_market_reaction


def track_files(
    observations_path: Path,
    evaluation_path: Path,
    events_path: Path,
    event_status_history_path: Path,
    companies_path: Path,
) -> MarketReactionTracking:
    observations = MarketReactionObservationBundle.model_validate_json(
        Path(observations_path).read_text(encoding="utf-8")
    )
    evaluation = EarningsEvaluation.model_validate_json(
        Path(evaluation_path).read_text(encoding="utf-8")
    )
    _validate_dataset_context(
        observations,
        _read_csv(events_path),
        _read_csv(event_status_history_path),
        _read_csv(companies_path),
    )
    return track_market_reaction(observations, evaluation)


def write_reaction(result: MarketReactionTracking, output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _one(rows, field, value, label):
    matches = [row for row in rows if row.get(field) == value]
    if len(matches) != 1:
        raise ValueError("%s must resolve to exactly one row" % label)
    return matches[0]


def _validate_dataset_context(observations, events, status_history, companies) -> None:
    event = _one(events, "earnings_event_id", observations.earnings_event_id, "earnings_event_id")
    company = _one(companies, "company_id", event.get("company_id"), "event company_id")
    occurred = [
        row for row in status_history
        if row.get("earnings_event_id") == observations.earnings_event_id
        and row.get("event_status") == "occurred"
    ]
    if len(occurred) != 1 or not occurred[0].get("occurred_at"):
        raise ValueError("market reaction tracking requires one occurred event status")
    occurred_id = occurred[0].get("event_status_record_id")
    if not occurred_id or any(
        row.get("supersedes_status_record_id") == occurred_id for row in status_history
    ):
        raise ValueError("occurred event status must be the current status tail")
    checks = (
        (event.get("announcement_session"), observations.announcement_session, "announcement_session"),
        (company.get("ticker"), observations.ticker, "ticker"),
        (company.get("company_name"), observations.company_name, "company_name"),
    )
    for expected, actual, label in checks:
        if expected != actual:
            raise ValueError("%s does not match dataset truth" % label)
    try:
        occurred_at = datetime.fromisoformat(occurred[0]["occurred_at"])
    except ValueError as exc:
        raise ValueError("occurred_at must be a valid timezone-aware datetime") from exc
    if occurred_at.tzinfo is None or occurred_at != observations.announcement_datetime:
        raise ValueError("occurred_at does not match dataset truth")
    currencies = {item.currency for item in observations.observations}
    if not company.get("primary_currency") or currencies != {company["primary_currency"]}:
        raise ValueError("price currency does not match company primary_currency")
