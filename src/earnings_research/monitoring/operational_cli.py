"""Operational CLI handlers kept separate from argparse wiring."""

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from earnings_research.monitoring.github_api import GitHubAPIClient
from earnings_research.monitoring.handoff import write_research_handoff
from earnings_research.monitoring.models import OfflineSourceInput
from earnings_research.monitoring.notifications import (
    NotificationReceipt,
    build_issue_plan,
    deliver_issue_notification,
)
from earnings_research.monitoring.operations import execute_live_run, execute_offline_run
from earnings_research.monitoring.persistence import artifact_name, verify_bundle, verify_uploaded_bundle
from earnings_research.monitoring.registry import active_target_plan, find_target, load_registry
from earnings_research.validation.validator import validate_monitor_bundle


def plan_registry(
    registry_path: Path,
    target_id: Optional[str],
    fixture_name: Optional[str],
    planned_at: Optional[str] = None,
    force: bool = False,
) -> int:
    rows = load_registry(registry_path)
    planned = _aware_datetime(planned_at, "planned_at") if planned_at else None
    targets = active_target_plan(rows, planned_at=planned, force=force)
    if target_id:
        targets = [target for target in targets if target.get("monitor_target_id") == target_id]
        if len(targets) != 1:
            raise ValueError("requested active monitor target was not found")
    plan = [
        {
            "monitor_target_id": target["monitor_target_id"],
            "registry": str(registry_path),
            "fixture_name": fixture_name or "",
            "source_mode": "offline" if fixture_name else "live",
            "event_date": target.get("event_date", ""),
        }
        for target in targets
    ]
    print(json.dumps(plan, ensure_ascii=False, separators=(",", ":")))
    return 0


def fetch_state(repository: str, target_id: str, output_dir: Path) -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for artifact lookup")
    bundle = GitHubAPIClient(repository=repository, token=token).fetch_previous_bundle(
        monitor_target_id=target_id,
        output_dir=output_dir,
    )
    print(json.dumps({"state": "missing" if bundle is None else "verified"}, separators=(",", ":")))
    return 0


def run_offline(
    *,
    registry_path: Path,
    target_id: str,
    fixture_dir: Path,
    fixture_name: str,
    previous_dir: Optional[Path],
    output_dir: Path,
    run_id: str,
    started_at: str,
    finished_at: str,
    event_date_value: Optional[str],
    gap_acknowledgement_path: Optional[Path] = None,
) -> int:
    target = find_target(load_registry(registry_path), target_id)
    previous = None
    if previous_dir is not None and (previous_dir / "manifest.json").is_file():
        previous = verify_bundle(previous_dir, expected_target_id=target_id)
    started = _aware_datetime(started_at, "started_at")
    finished = _aware_datetime(finished_at, "finished_at")
    event_date = date.fromisoformat(event_date_value) if event_date_value else None
    acknowledgements = _load_gap_acknowledgement(gap_acknowledgement_path, previous, started)
    html_path = fixture_dir / (fixture_name + ".html")
    metadata_path = fixture_dir / (fixture_name + ".json")
    bundle = execute_offline_run(
        target=target,
        source_input=OfflineSourceInput(
            html_path=html_path if html_path.is_file() else None,
            metadata_path=metadata_path,
            observed_at=started,
        ),
        previous_bundle=previous,
        output_dir=output_dir,
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        event_date=event_date,
        gap_acknowledgements=acknowledgements,
    )
    run_attempt_value = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    run_attempt = int(run_attempt_value) if run_attempt_value else None
    print(
        json.dumps(
            {
                "artifact_name": artifact_name(bundle.manifest, run_attempt=run_attempt),
                "run_result": bundle.latest_run["run_result"],
                "target_state": bundle.checkpoint["target_state"],
                "checkpoint_version": bundle.manifest.checkpoint_version,
            },
            separators=(",", ":"),
        )
    )
    return 0


def run_live(
    *,
    registry_path: Path,
    target_id: str,
    previous_dir: Optional[Path],
    output_dir: Path,
    run_id: str,
    started_at: str,
    finished_at: str,
    gap_acknowledgement_path: Optional[Path] = None,
) -> int:
    target = find_target(load_registry(registry_path), target_id)
    previous = None
    if previous_dir is not None and (previous_dir / "manifest.json").is_file():
        previous = verify_bundle(previous_dir, expected_target_id=target_id)
    started = _aware_datetime(started_at, "started_at")
    finished = _aware_datetime(finished_at, "finished_at")
    acknowledgements = _load_gap_acknowledgement(gap_acknowledgement_path, previous, started)
    bundle = execute_live_run(
        target=target,
        previous_bundle=previous,
        output_dir=output_dir,
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        gap_acknowledgements=acknowledgements,
    )
    run_attempt_value = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    run_attempt = int(run_attempt_value) if run_attempt_value else None
    print(
        json.dumps(
            {
                "artifact_name": artifact_name(bundle.manifest, run_attempt=run_attempt),
                "run_result": bundle.latest_run["run_result"],
                "target_state": bundle.checkpoint["target_state"],
                "checkpoint_version": bundle.manifest.checkpoint_version,
            },
            separators=(",", ":"),
        )
    )
    return 0


def verify_state(bundle_dir: Path) -> int:
    bundle = verify_uploaded_bundle(bundle_dir)
    print(
        json.dumps(
            {
                "artifact_name": artifact_name(bundle.manifest),
                "run_result": bundle.latest_run["run_result"],
                "target_state": bundle.checkpoint["target_state"],
            },
            separators=(",", ":"),
        )
    )
    return 0


def build_handoff(bundle_dir: Path, output_path: Path) -> int:
    bundle = verify_bundle(bundle_dir)
    created = write_research_handoff(bundle, output_path)
    print(json.dumps({"handoff_required": created}, separators=(",", ":")))
    return 0


def notify_state(
    *,
    bundle_dir: Path,
    repository: str,
    receipt_path: Path,
    recorded_at: str,
) -> int:
    bundle = verify_bundle(bundle_dir)
    timestamp = _aware_datetime(recorded_at, "recorded_at")
    plan = build_issue_plan(bundle)
    if plan is None:
        receipt = NotificationReceipt(
            bundle.manifest.monitor_target_id,
            bundle.manifest.monitor_run_id,
            "",
            "not_required",
            0,
            None,
            None,
            None,
            timestamp.isoformat(),
        )
    else:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise ValueError("GITHUB_TOKEN is required for Issue notification")
        receipt = deliver_issue_notification(
            client=GitHubAPIClient(repository=repository, token=token),
            plan=plan,
            target_id=bundle.manifest.monitor_target_id,
            run_id=bundle.manifest.monitor_run_id,
            recorded_at=timestamp,
        )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt.write(receipt_path)
    print(json.dumps({"notification_status": receipt.status}, separators=(",", ":")))
    return 1 if receipt.status == "failed" else 0


def record_gap_acknowledgement(
    *,
    previous_dir: Path,
    output_path: Path,
    acknowledgement_id: str,
    gap_start: str,
    gap_end: str,
    acknowledged_at: str,
    acknowledged_by: str,
    reason: str,
    supersedes_id: str = "",
) -> int:
    bundle = verify_bundle(previous_dir)
    row = {
        "acknowledgement_id": acknowledgement_id,
        "monitor_target_id": bundle.manifest.monitor_target_id,
        "acknowledged_gap_start": _aware_datetime(gap_start, "acknowledged_gap_start").isoformat(),
        "acknowledged_gap_end": _aware_datetime(gap_end, "acknowledged_gap_end").isoformat(),
        "acknowledged_at": _aware_datetime(acknowledged_at, "acknowledged_at").isoformat(),
        "acknowledged_by": acknowledged_by,
        "reason": reason,
        "supersedes_acknowledgement_id": supersedes_id,
    }
    _validate_new_gap_acknowledgement(bundle, row)
    if output_path.exists():
        raise ValueError("gap acknowledgement output already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"acknowledgement_id": acknowledgement_id}, separators=(",", ":")))
    return 0


def _load_gap_acknowledgement(
    path: Optional[Path], bundle, transition_started_at: datetime
):
    if path is None:
        return []
    if bundle is None:
        raise ValueError("gap acknowledgement requires verified previous state")
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("gap acknowledgement must be valid JSON") from exc
    if not isinstance(row, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in row.items()
    ):
        raise ValueError("gap acknowledgement must be one string record")
    _validate_new_gap_acknowledgement(bundle, row)
    if _aware_datetime(row["acknowledged_at"], "acknowledged_at") > transition_started_at:
        raise ValueError("gap acknowledgement cannot be future-dated for this run")
    return [row]


def _validate_new_gap_acknowledgement(bundle, row) -> None:
    if (
        bundle.checkpoint.get("target_state") != "stopped"
        or bundle.checkpoint.get("last_error_code") != "state_unavailable"
    ):
        raise ValueError("gap acknowledgement requires a stale stopped checkpoint")
    rows = bundle.gap_acknowledgements + [row]
    report = validate_monitor_bundle(
        {
            "monitor_target": [bundle.target],
            "monitor_run": bundle.runs,
            "monitor_resolution": bundle.resolutions,
            "monitor_gap_acknowledgement": rows,
            "monitor_checkpoint": [bundle.checkpoint],
        }
    )
    if not report.ok:
        raise ValueError(
            "gap acknowledgement failed validation:\n%s"
            % "\n".join(issue.format() for issue in report.issues)
        )
    gap_end = _aware_datetime(row["acknowledged_gap_end"], "acknowledged_gap_end")
    last_success = _aware_datetime(bundle.checkpoint["last_success_at"], "last_success_at")
    if gap_end < last_success:
        raise ValueError("acknowledged gap was already resolved by the latest success")


def _aware_datetime(value: str, name: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("%s must be timezone-aware" % name)
    return parsed
