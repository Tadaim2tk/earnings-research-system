"""Testable operational boundary between workflow glue and monitor runtime."""

from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional

from earnings_research.monitoring.models import ObservationFailure, OfflineSourceInput
from earnings_research.monitoring.offline import OfflineSourceAdapter
from earnings_research.monitoring.persistence import (
    BundleError,
    VerifiedMonitorBundle,
    write_committed_bundle,
)
from earnings_research.monitoring.runtime import MonitorRuntime, MonitorTransitionError
from earnings_research.monitoring.stale import assess_stale_gap


class StateUnavailable(BundleError):
    """Raised when prior committed state is absent outside approved initialization."""


def execute_offline_run(
    *,
    target: Dict[str, str],
    source_input: OfflineSourceInput,
    previous_bundle: Optional[VerifiedMonitorBundle],
    output_dir: Path,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    event_date: Optional[date] = None,
) -> VerifiedMonitorBundle:
    """Run one fixture observation and atomically materialize verified state."""
    _require_operational_target(target, started_at)
    if previous_bundle is None:
        if (
            target.get("activation_state") != "activated"
            or target.get("initialization_run_id") != run_id
            or target.get("initialization_generation") != "1"
        ):
            raise StateUnavailable("previous artifact missing outside Human-approved initialization")
        previous_checkpoint = None
        runs = []
        resolutions = []
        observation = OfflineSourceAdapter().observe(target, source_input)
    else:
        if previous_bundle.manifest.monitor_target_id != target.get("monitor_target_id"):
            raise StateUnavailable("previous artifact belongs to another monitor target")
        previous_checkpoint = previous_bundle.checkpoint
        runs = previous_bundle.runs
        resolutions = previous_bundle.resolutions
        last_success_at = _parse_optional_aware(previous_checkpoint.get("last_success_at", ""))
        assessment = assess_stale_gap(
            last_success_at=last_success_at,
            reference_time=started_at,
            schedule_profile=target.get("schedule_profile", ""),
            event_date=event_date,
            event_date_required=bool(target.get("earnings_event_id")),
        )
        if assessment.is_stale:
            observation = ObservationFailure(
                error_code="state_unavailable",
                error_detail="stale gap exceeded %s-hour %s threshold"
                % (int(assessment.threshold.total_seconds() // 3600), assessment.window),
                observed_at=started_at,
            )
        else:
            observation = OfflineSourceAdapter().observe(target, source_input)

    transition = MonitorRuntime().transition(
        target=target,
        previous_checkpoint=previous_checkpoint,
        prior_runs=runs,
        resolutions=resolutions,
        observation=observation,
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        self_validate=True,
        recorded_by="workflow:github-actions-monitor-v1",
    )
    if not transition.validation_report.ok:
        raise MonitorTransitionError("validation hard gate rejected generated bundle")
    return write_committed_bundle(
        output_dir=output_dir,
        target=target,
        transition=transition,
        created_at=finished_at,
    )


def _parse_optional_aware(value: str) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StateUnavailable("previous checkpoint timestamp is invalid")
    return parsed


def _require_operational_target(target: Dict[str, str], reference_time: datetime) -> None:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise StateUnavailable("run reference time must be timezone-aware")
    active_from = _parse_optional_aware(target.get("active_from", ""))
    active_until = _parse_optional_aware(target.get("active_until", ""))
    if (
        target.get("enabled", "").lower() != "true"
        or target.get("monitoring_level") != "level_2"
        or target.get("automated_access_permitted", "").lower() != "true"
        or target.get("terms_review_state") != "candidate_specific_review_completed"
        or active_from is None
        or reference_time < active_from
        or (active_until is not None and reference_time > active_until)
    ):
        raise StateUnavailable("monitor target is not approved and active at execution time")
