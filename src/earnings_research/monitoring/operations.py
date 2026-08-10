"""Testable operational boundary between workflow glue and monitor runtime."""

from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from earnings_research.monitoring.live import LiveSourceAdapter
from earnings_research.monitoring.models import (
    LiveSourceContext,
    ObservationFailure,
    OfflineSourceInput,
)
from earnings_research.monitoring.offline import OfflineSourceAdapter
from earnings_research.monitoring.persistence import (
    BundleError,
    VerifiedMonitorBundle,
    write_committed_bundle,
)
from earnings_research.monitoring.runtime import MonitorRuntime, MonitorTransitionError
from earnings_research.monitoring.stale import assess_stale_gap
from earnings_research.validation.validator import validate_monitor_bundle


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
    gap_acknowledgements: Sequence[Dict[str, str]] = (),
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
        acknowledgements = []
        observation = OfflineSourceAdapter().observe(target, source_input)
    else:
        if previous_bundle.manifest.monitor_target_id != target.get("monitor_target_id"):
            raise StateUnavailable("previous artifact belongs to another monitor target")
        previous_checkpoint = previous_bundle.checkpoint
        runs = previous_bundle.runs
        resolutions = previous_bundle.resolutions
        acknowledgements = previous_bundle.gap_acknowledgements + [
            dict(row) for row in gap_acknowledgements
        ]
        _validate_gap_acknowledgements(
            target, previous_checkpoint, runs, resolutions, acknowledgements,
            gap_acknowledgements, started_at
        )
        last_success_at = _stale_reference(previous_checkpoint, acknowledgements, started_at)
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
        gap_acknowledgements=acknowledgements,
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


def execute_live_run(
    *,
    target: Dict[str, str],
    previous_bundle: Optional[VerifiedMonitorBundle],
    output_dir: Path,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    adapter_factory: Callable[[], LiveSourceAdapter] = LiveSourceAdapter,
    gap_acknowledgements: Sequence[Dict[str, str]] = (),
) -> VerifiedMonitorBundle:
    """Check robots, observe one live source, then persist one validated transition."""
    _require_operational_target(target, started_at)
    event_date = date.fromisoformat(target["event_date"]) if target.get("event_date") else None
    if previous_bundle is None:
        if (
            target.get("activation_state") != "activated"
            or target.get("initialization_run_id") != run_id
            or target.get("initialization_generation") != "1"
        ):
            raise StateUnavailable("previous artifact missing outside authorized initialization")
        previous_checkpoint = None
        runs = []
        resolutions = []
        acknowledgements = []
    else:
        if previous_bundle.manifest.monitor_target_id != target.get("monitor_target_id"):
            raise StateUnavailable("previous artifact belongs to another monitor target")
        previous_checkpoint = previous_bundle.checkpoint
        runs = previous_bundle.runs
        resolutions = previous_bundle.resolutions
        acknowledgements = previous_bundle.gap_acknowledgements + [
            dict(row) for row in gap_acknowledgements
        ]
        _validate_gap_acknowledgements(
            target, previous_checkpoint, runs, resolutions, acknowledgements,
            gap_acknowledgements, started_at
        )

    if previous_checkpoint is not None:
        assessment = assess_stale_gap(
            last_success_at=_stale_reference(previous_checkpoint, acknowledgements, started_at),
            reference_time=started_at,
            schedule_profile=target.get("schedule_profile", ""),
            event_date=event_date,
            event_date_required=bool(event_date),
        )
        if assessment.is_stale:
            observation = ObservationFailure(
                error_code="state_unavailable",
                error_detail="stale gap exceeded %s-hour %s threshold"
                % (int(assessment.threshold.total_seconds() // 3600), assessment.window),
                observed_at=started_at,
            )
        else:
            observation = _observe_live(target, previous_checkpoint, started_at, adapter_factory)
    else:
        observation = _observe_live(target, {}, started_at, adapter_factory)

    transition = MonitorRuntime().transition(
        target=target,
        previous_checkpoint=previous_checkpoint,
        prior_runs=runs,
        resolutions=resolutions,
        gap_acknowledgements=acknowledgements,
        observation=observation,
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        self_validate=True,
        recorded_by="workflow:github-actions-live-monitor-v1",
    )
    if not transition.validation_report.ok:
        raise MonitorTransitionError("validation hard gate rejected generated live bundle")
    return write_committed_bundle(
        output_dir=output_dir,
        target=target,
        transition=transition,
        created_at=finished_at,
    )


def _observe_live(
    target: Dict[str, str],
    previous_checkpoint: Dict[str, str],
    observed_at: datetime,
    adapter_factory: Callable[[], LiveSourceAdapter],
):
    context = LiveSourceContext(
        observed_at=observed_at,
        previous_checkpoint=previous_checkpoint,
    )
    with adapter_factory() as adapter:
        robots_failure = adapter.check_robots(target, context)
        if robots_failure is not None:
            return robots_failure
        return adapter.observe(target, context)


def _parse_optional_aware(value: str) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StateUnavailable("previous checkpoint timestamp is invalid")
    return parsed


def _stale_reference(
    checkpoint: Dict[str, str],
    acknowledgements: Sequence[Dict[str, str]],
    transition_started_at: datetime,
) -> Optional[datetime]:
    last_success = _parse_optional_aware(checkpoint.get("last_success_at", ""))
    target_id = checkpoint.get("monitor_target_id", "")
    rows = [row for row in acknowledgements if row.get("monitor_target_id") == target_id]
    superseded = {row.get("supersedes_acknowledgement_id", "") for row in rows}
    tails = [row for row in rows if row.get("acknowledgement_id", "") not in superseded]
    eligible = []
    for row in tails:
        gap_end = _parse_optional_aware(row.get("acknowledged_gap_end", ""))
        acknowledged_at = _parse_optional_aware(row.get("acknowledged_at", ""))
        if (
            gap_end is not None
            and acknowledged_at is not None
            and gap_end <= acknowledged_at <= transition_started_at
            and (last_success is None or gap_end >= last_success)
        ):
            eligible.append(gap_end)
    return max([last_success] + eligible) if last_success is not None else (max(eligible) if eligible else None)


def _validate_gap_acknowledgements(
    target: Dict[str, str],
    checkpoint: Dict[str, str],
    runs: Sequence[Dict[str, str]],
    resolutions: Sequence[Dict[str, str]],
    acknowledgements: Sequence[Dict[str, str]],
    new_acknowledgements: Sequence[Dict[str, str]],
    transition_started_at: datetime,
) -> None:
    if new_acknowledgements and (
        checkpoint.get("target_state") != "stopped"
        or checkpoint.get("last_error_code") != "state_unavailable"
    ):
        raise StateUnavailable("gap acknowledgement requires a stale stopped checkpoint")
    report = validate_monitor_bundle(
        {
            "monitor_target": [dict(target)],
            "monitor_run": [dict(row) for row in runs],
            "monitor_resolution": [dict(row) for row in resolutions],
            "monitor_gap_acknowledgement": [dict(row) for row in acknowledgements],
            "monitor_checkpoint": [dict(checkpoint)],
        }
    )
    if not report.ok:
        raise StateUnavailable(
            "gap acknowledgement history is invalid:\n%s"
            % "\n".join(issue.format() for issue in report.issues)
        )
    last_success = _parse_optional_aware(checkpoint.get("last_success_at", ""))
    for row in new_acknowledgements:
        gap_end = _parse_optional_aware(row.get("acknowledged_gap_end", ""))
        acknowledged_at = _parse_optional_aware(row.get("acknowledged_at", ""))
        if acknowledged_at is None or acknowledged_at > transition_started_at:
            raise StateUnavailable("gap acknowledgement is future-dated for this run")
        if gap_end is None or (last_success is not None and gap_end < last_success):
            raise StateUnavailable("acknowledged gap was already resolved by the latest success")


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
