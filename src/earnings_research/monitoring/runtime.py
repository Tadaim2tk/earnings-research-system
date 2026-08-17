"""Offline single-target monitor state machine."""

import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from earnings_research.identifiers import is_activation_authorizer
from earnings_research.monitoring.fingerprint import FINGERPRINT_VERSION, build_metadata_fingerprint
from earnings_research.monitoring.models import (
    MonitorTransitionResult,
    ObservationFailure,
    ObservationResult,
    SourceObservation,
)
from earnings_research.validation.validator import validate_monitor_bundle

FATAL_ERROR_CODES = {"state_unavailable", "persistence_error"}
_HUMAN_IDENTIFIER = re.compile(r"^human:[A-Za-z0-9][A-Za-z0-9._-]*$")


class MonitorTransitionError(ValueError):
    """Raised when an offline input cannot produce a safe contract bundle."""


class MonitorRuntime:
    """Generate one run/checkpoint transition without network or persistence."""

    def transition(
        self,
        *,
        target: Dict[str, str],
        previous_checkpoint: Optional[Dict[str, str]],
        prior_runs: Sequence[Dict[str, str]],
        resolutions: Sequence[Dict[str, str]],
        observation: ObservationResult,
        run_id: str,
        started_at: datetime,
        finished_at: datetime,
        gap_acknowledgements: Sequence[Dict[str, str]] = (),
        recorded_by: str = "workflow:offline-monitor-v1",
        self_validate: bool = True,
    ) -> MonitorTransitionResult:
        _require_aware(started_at, "started_at")
        _require_aware(finished_at, "finished_at")
        if finished_at < started_at:
            raise MonitorTransitionError("finished_at must not be before started_at")
        if isinstance(observation, SourceObservation):
            _require_aware(observation.observed_at, "observed_at")
        else:
            _require_aware(observation.observed_at, "observed_at")
            if observation.error_code == "persistence_error":
                raise MonitorTransitionError(
                    "persistence_error belongs to the PR D persistence boundary; "
                    "the offline core cannot claim that a failed write committed a checkpoint"
                )

        previous = dict(previous_checkpoint) if previous_checkpoint is not None else None
        runs = [dict(row) for row in prior_runs]
        resolution_rows = [dict(row) for row in resolutions]
        acknowledgement_rows = [dict(row) for row in gap_acknowledgements]
        self._validate_resolution_times(runs, resolution_rows, started_at)
        if previous is None:
            self._require_initial_activation(target, runs, run_id, started_at)
        elif not runs:
            raise MonitorTransitionError("an existing checkpoint requires prior run lineage")
        elif previous.get("monitor_target_id") != target.get("monitor_target_id"):
            raise MonitorTransitionError("checkpoint and target IDs must match")

        previous_pending_id = "" if previous is None else previous.get("pending_change_run_id", "")
        applied_resolution = self._effective_resolution(
            target_id=target.get("monitor_target_id", ""),
            pending_change_id=previous_pending_id,
            prior_runs=runs,
            resolutions=resolution_rows,
            transition_started_at=started_at,
        )
        autonomous_handoff = target.get("change_response") == "autonomous_research_handoff"
        unresolved_change_ids = (
            [] if autonomous_handoff else _unresolved_change_ids(runs, resolution_rows)
        )
        pending_change_id = unresolved_change_ids[-1] if unresolved_change_ids else ""
        if previous_pending_id and applied_resolution is None and previous_pending_id != pending_change_id:
            raise MonitorTransitionError("checkpoint must point to the latest unresolved change")

        run, checkpoint = self._build_records(
            target=target,
            previous=previous,
            runs=runs,
            observation=observation,
            pending_change_id=pending_change_id,
            applied_resolution=applied_resolution,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            recorded_by=recorded_by,
        )
        all_runs = runs + [run]
        report = validate_monitor_bundle(
            {
                "monitor_target": [dict(target)],
                "monitor_run": all_runs,
                "monitor_resolution": resolution_rows,
                "monitor_gap_acknowledgement": acknowledgement_rows,
                "monitor_checkpoint": [checkpoint],
            }
        )
        if self_validate and not report.ok:
            raise MonitorTransitionError(
                "generated monitor bundle failed validation:\n%s"
                % "\n".join(issue.format() for issue in report.issues)
            )
        return MonitorTransitionResult(
            run, checkpoint, report, all_runs, resolution_rows, acknowledgement_rows
        )

    @staticmethod
    def _validate_resolution_times(
        prior_runs: Sequence[Dict[str, str]],
        resolutions: Sequence[Dict[str, str]],
        transition_started_at: datetime,
    ) -> None:
        runs_by_id = {row.get("monitor_run_id", ""): row for row in prior_runs}
        for resolution in resolutions:
            resolved_at = _parse_datetime(resolution.get("resolved_at", ""))
            source_run = runs_by_id.get(resolution.get("source_monitor_run_id", ""))
            source_finished = _parse_datetime(source_run.get("finished_at", "")) if source_run else None
            if (
                resolved_at is None
                or source_finished is None
                or resolved_at < source_finished
                or resolved_at > transition_started_at
            ):
                raise MonitorTransitionError("Human resolution timestamp is outside the valid execution window")

    @staticmethod
    def _require_initial_activation(
        target: Dict[str, str],
        prior_runs: Sequence[Dict[str, str]],
        run_id: str,
        started_at: datetime,
    ) -> None:
        if prior_runs:
            raise MonitorTransitionError("missing checkpoint must not reinitialize existing run lineage")
        activated_at = _parse_datetime(target.get("activated_at", ""))
        if (
            target.get("activation_state") != "activated"
            or target.get("enabled", "").lower() != "true"
            or target.get("automated_access_permitted", "").lower() != "true"
            or not is_activation_authorizer(target.get("activation_approved_by", ""))
            or target.get("initialization_generation") != "1"
            or target.get("initialization_run_id") != run_id
            or activated_at is None
            or activated_at > started_at
        ):
            raise MonitorTransitionError("initialization requires matching authorized activation")

    @staticmethod
    def _effective_resolution(
        *,
        target_id: str,
        pending_change_id: str,
        prior_runs: Sequence[Dict[str, str]],
        resolutions: Sequence[Dict[str, str]],
        transition_started_at: datetime,
    ) -> Optional[Dict[str, str]]:
        if not pending_change_id:
            return None
        source_run = next(
            (row for row in prior_runs if row.get("monitor_run_id") == pending_change_id),
            None,
        )
        if source_run is None or source_run.get("run_result") != "change_detected":
            raise MonitorTransitionError("pending change must reference a prior change_detected run")
        candidates = [
            row
            for row in resolutions
            if row.get("monitor_target_id") == target_id
            and row.get("source_monitor_run_id") == pending_change_id
        ]
        if not candidates:
            return None
        effective_ids = {row.get("resolution_id", "") for row in candidates}
        superseded_ids = {row.get("supersedes_resolution_id", "") for row in candidates}
        tails = [row for row in candidates if row.get("resolution_id", "") not in superseded_ids]
        if len(tails) != 1 or not effective_ids:
            raise MonitorTransitionError("Human resolution lineage must have one effective tail")
        resolution = tails[0]
        resolved_at = _parse_datetime(resolution.get("resolved_at", ""))
        source_finished = _parse_datetime(source_run.get("finished_at", ""))
        if (
            not _HUMAN_IDENTIFIER.fullmatch(resolution.get("resolved_by", ""))
            or resolved_at is None
            or source_finished is None
            or resolved_at < source_finished
            or resolved_at > transition_started_at
        ):
            raise MonitorTransitionError("only a timely valid Human resolution can clear pending state")
        return resolution

    def _build_records(
        self,
        *,
        target: Dict[str, str],
        previous: Optional[Dict[str, str]],
        runs: Sequence[Dict[str, str]],
        observation: ObservationResult,
        pending_change_id: str,
        applied_resolution: Optional[Dict[str, str]],
        run_id: str,
        started_at: datetime,
        finished_at: datetime,
        recorded_by: str,
    ):
        target_id = target.get("monitor_target_id", "")
        previous_fingerprint = "" if previous is None else previous.get("metadata_fingerprint", "")
        version_before = None if previous is None else int(previous["checkpoint_version"])
        version_after = 1 if version_before is None else version_before + 1
        result = ""
        error_code = ""
        error_detail = ""
        change_summary = ""
        fingerprint_after = ""
        replacement_detection = "unavailable" if previous is None else previous.get("replacement_detection", "unavailable")

        if isinstance(observation, ObservationFailure):
            if previous is None:
                raise MonitorTransitionError("initialization requires a successful source observation")
            result = "error"
            error_code = observation.error_code
            error_detail = observation.error_detail
        else:
            fingerprint_after = build_metadata_fingerprint(observation)
            replacement_detection = _replacement_detection(observation)
            if previous is None:
                result = "initialized"
            else:
                replacement_suspected = observation.replacement_suspected or _replacement_indicators_conflict(
                    previous, observation
                )
                if fingerprint_after == previous_fingerprint and replacement_suspected:
                    result = "error"
                    error_code = "content_ambiguous"
                    error_detail = "metadata fingerprint matched while replacement indicators were ambiguous"
                    fingerprint_after = ""
                elif fingerprint_after == previous_fingerprint:
                    result = "no_change"
                else:
                    result = "change_detected"
                    change_summary = _change_summary(previous, observation)
                    if target.get("change_response") != "autonomous_research_handoff":
                        pending_change_id = run_id

        is_success = result in {"initialized", "no_change", "change_detected"}
        notification_required = result in {"change_detected", "error"}
        run = {
            "monitor_run_id": run_id,
            "monitor_target_id": target_id,
            "started_at": _iso(started_at),
            "finished_at": _iso(finished_at),
            "run_result": result,
            "observation_status": "succeeded" if is_success else "failed",
            "error_code": error_code,
            "error_detail": error_detail,
            "retry_count": str(observation.retry_count if isinstance(observation, ObservationFailure) else 0),
            "checkpoint_version_before": "" if version_before is None else str(version_before),
            "checkpoint_version_after": str(version_after),
            "initialization_generation": target.get("initialization_generation", "") if result == "initialized" else "",
            "fingerprint_before": previous_fingerprint,
            "fingerprint_after": fingerprint_after,
            "fingerprint_version": FINGERPRINT_VERSION if previous_fingerprint or fingerprint_after else "",
            "detected_change_summary": change_summary,
            "persistence_status": "committed",
            "notification_required": str(notification_required).lower(),
            "notification_status": "pending" if notification_required else "not_required",
            "notification_error_code": "",
            "notification_reference": "",
            "previous_run_id": "" if not runs else runs[-1].get("monitor_run_id", ""),
            "recorded_by": recorded_by,
        }

        if result == "error":
            state = classify_error_state(error_code, bool(pending_change_id))
        elif pending_change_id:
            state = "pending_human_review"
        else:
            state = "healthy"

        checkpoint = _empty_checkpoint(target_id, recorded_by)
        if previous is not None:
            checkpoint.update(previous)
        checkpoint.update(
            {
                "checkpoint_version": str(version_after),
                "target_state": state,
                "last_checked_at": _iso(finished_at),
                "last_error_code": error_code,
                "consecutive_error_count": str(_next_error_count(previous, error_code)),
                "pending_change_run_id": pending_change_id,
                "resolution_applied_id": (
                    applied_resolution.get("resolution_id", "")
                    if applied_resolution is not None
                    else checkpoint.get("resolution_applied_id", "")
                ),
                "recorded_by": recorded_by,
            }
        )
        if is_success and isinstance(observation, SourceObservation):
            checkpoint.update(
                {
                    "last_success_at": _iso(finished_at),
                    "last_successful_run_id": run_id,
                    "last_seen_document_id": observation.document_id or "",
                    "last_seen_title": observation.title or "",
                    "last_seen_published_at": _iso(observation.published_at) if observation.published_at else "",
                    # Carried so the research handoff can reach the disclosure
                    # itself. Only the provider-published URL is kept, never the
                    # document bytes.
                    "last_seen_document_url": observation.stable_metadata.get(
                        "latest_document_url", ""
                    ),
                    # The published earnings schedule, so a moved announcement
                    # date is readable without opening the page.
                    "last_seen_schedule": _schedule_summary(observation.stable_metadata),
                    "metadata_fingerprint": fingerprint_after,
                    "fingerprint_version": FINGERPRINT_VERSION,
                    "observed_etag": observation.etag or "",
                    "observed_last_modified": observation.last_modified or "",
                    "observed_content_length": "" if observation.content_length is None else str(observation.content_length),
                    "replacement_detection": replacement_detection,
                }
            )
        elif error_code == "content_ambiguous" and isinstance(observation, SourceObservation):
            # Report the ambiguity once, then adopt the indicators that produced
            # it. Leaving the old values in place made every later run compare
            # against the same stale pair, so one page edit held the target in
            # error until it aged into a fatal stale stop.
            checkpoint.update(
                {
                    "replacement_detection": replacement_detection,
                    "observed_etag": observation.etag or "",
                    "observed_last_modified": observation.last_modified or "",
                    "observed_content_length": (
                        "" if observation.content_length is None else str(observation.content_length)
                    ),
                }
            )
        elif error_code == "content_ambiguous":
            checkpoint["replacement_detection"] = replacement_detection
        return run, checkpoint


def _schedule_summary(stable_metadata) -> str:
    """Join the dated and the month-only announcement rows for one field."""
    parts = [
        stable_metadata.get(key, "")
        for key in ("earnings_schedule", "approximate_schedule")
    ]
    present = [part for part in parts if part and part != "none"]
    return " | ".join(present)


def _empty_checkpoint(target_id: str, recorded_by: str) -> Dict[str, str]:
    return {
        "monitor_target_id": target_id,
        "checkpoint_version": "0",
        "target_state": "uninitialized",
        "last_checked_at": "",
        "last_success_at": "",
        "last_successful_run_id": "",
        "last_seen_document_id": "",
        "last_seen_title": "",
        "last_seen_published_at": "",
        "last_seen_document_url": "",
        "last_seen_schedule": "",
        "metadata_fingerprint": "",
        "fingerprint_version": "",
        "observed_etag": "",
        "observed_last_modified": "",
        "observed_content_length": "",
        "replacement_detection": "unavailable",
        "last_error_code": "",
        "consecutive_error_count": "0",
        "pending_change_run_id": "",
        "resolution_applied_id": "",
        "recorded_by": recorded_by,
    }


def classify_error_state(error_code: str, has_pending_change: bool) -> str:
    """Map monitoring health to a safe state without discarding pending work."""
    if error_code in FATAL_ERROR_CODES:
        return "stopped"
    if has_pending_change:
        return "pending_human_review"
    return "degraded"


def _replacement_detection(observation: SourceObservation) -> str:
    indicators = (observation.etag, observation.last_modified, observation.content_length)
    present = sum(value is not None for value in indicators)
    if present == len(indicators):
        return "available"
    if present:
        return "partial"
    return "unavailable"


def _replacement_indicators_conflict(
    previous: Dict[str, str], observation: SourceObservation
) -> bool:
    pairs = (
        (previous.get("observed_etag", ""), observation.etag),
        (previous.get("observed_last_modified", ""), observation.last_modified),
        (previous.get("observed_content_length", ""), observation.content_length),
    )
    for old, new in pairs:
        old_value = None if old == "" else str(old)
        new_value = None if new is None else str(new)
        if old_value is not None and old_value != new_value:
            return True
    return False


def _change_summary(previous: Dict[str, str], observation: SourceObservation) -> str:
    changes = []
    comparisons = (
        ("document_id", previous.get("last_seen_document_id", ""), observation.document_id),
        ("title", previous.get("last_seen_title", ""), observation.title),
        (
            "published_at",
            previous.get("last_seen_published_at", ""),
            _iso(observation.published_at) if observation.published_at else None,
        ),
    )
    for name, before, after in comparisons:
        if (before or None) != after:
            changes.append(name)
    return "Changed metadata fields: %s" % ", ".join(changes or ["stable_metadata"])


def _next_error_count(previous: Optional[Dict[str, str]], error_code: str) -> int:
    if not error_code:
        return 0
    if previous is not None and previous.get("last_error_code") == error_code:
        return int(previous.get("consecutive_error_count", "0")) + 1
    return 1


def _unresolved_change_ids(
    runs: Sequence[Dict[str, str]], resolutions: Sequence[Dict[str, str]]
) -> List[str]:
    current_resolution_by_source = {}
    for resolution in resolutions:
        source_id = resolution.get("source_monitor_run_id", "")
        current_resolution_by_source[source_id] = resolution.get("resolution_id", "")
    return [
        row.get("monitor_run_id", "")
        for row in runs
        if row.get("run_result") == "change_detected"
        and row.get("monitor_run_id", "") not in current_resolution_by_source
    ]


def _parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonitorTransitionError("%s must be timezone-aware" % name)


def _iso(value: datetime) -> str:
    return value.isoformat()
