"""Strict, hash-addressed monitor state bundles for temporary artifacts."""

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from earnings_research.monitoring.models import MonitorTransitionResult
from earnings_research.validation.validator import ValidationReport, validate_monitor_bundle

BUNDLE_FORMAT_VERSION = "monitor_state_bundle_v1"
BUNDLE_FILES = {
    "target.json",
    "checkpoint.json",
    "run.json",
    "run_history.json",
    "resolution_history.json",
    "manifest.json",
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")


class BundleError(ValueError):
    """Raised when an artifact cannot be trusted as committed state."""


class PersistenceError(BundleError):
    """Raised when uploaded state cannot be re-read as the committed bundle."""


class MonitorBundleManifest(BaseModel):
    """Machine-readable commit marker for one immutable state bundle."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str = Field(pattern=r"^monitor_state_bundle_v1$")
    monitor_target_id: str = Field(min_length=1)
    monitor_run_id: str = Field(min_length=1)
    checkpoint_version: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    previous_run_id: Optional[str]
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution_history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_status: str = Field(pattern=r"^committed$")


@dataclass(frozen=True)
class VerifiedMonitorBundle:
    """Fully verified artifact contents."""

    path: Path
    manifest: MonitorBundleManifest
    target: Dict[str, str]
    checkpoint: Dict[str, str]
    latest_run: Dict[str, str]
    runs: List[Dict[str, str]]
    resolutions: List[Dict[str, str]]
    validation_report: ValidationReport


def artifact_name(
    manifest: MonitorBundleManifest, *, run_attempt: Optional[int] = None
) -> str:
    """Return a target/version/run-addressed immutable artifact name."""
    for value in (manifest.monitor_target_id, manifest.monitor_run_id):
        if not _SAFE_IDENTIFIER.fullmatch(value):
            raise BundleError("artifact identifiers must contain only safe characters")
    if run_attempt is not None:
        if run_attempt < 1:
            raise BundleError("run_attempt must be a positive integer")
        return "ers-monitor-state-%s-v%s-a%s-%s" % (
            manifest.monitor_target_id,
            manifest.checkpoint_version,
            run_attempt,
            manifest.monitor_run_id,
        )
    return "ers-monitor-state-%s-v%s-%s" % (
        manifest.monitor_target_id,
        manifest.checkpoint_version,
        manifest.monitor_run_id,
    )


def write_committed_bundle(
    *,
    output_dir: Path,
    target: Dict[str, str],
    transition: MonitorTransitionResult,
    created_at: datetime,
) -> VerifiedMonitorBundle:
    """Validate, stage, hash, verify, then atomically publish a local bundle."""
    if not transition.validation_report.ok:
        raise BundleError("validation_report.ok must be true before persistence")
    _require_aware(created_at, "created_at")
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        raise BundleError("bundle output already exists")

    stage = Path(tempfile.mkdtemp(prefix=".%s-staging-" % output_dir.name, dir=output_dir.parent))
    try:
        payloads = {
            "target.json": dict(target),
            "checkpoint.json": transition.checkpoint_after,
            "run.json": transition.monitor_run,
            "run_history.json": transition.monitor_runs,
            "resolution_history.json": transition.monitor_resolutions,
        }
        for filename, payload in payloads.items():
            _write_json(stage / filename, payload)
        run = transition.monitor_run
        checkpoint = transition.checkpoint_after
        manifest = MonitorBundleManifest(
            schema_version=BUNDLE_FORMAT_VERSION,
            monitor_target_id=run["monitor_target_id"],
            monitor_run_id=run["monitor_run_id"],
            checkpoint_version=int(checkpoint["checkpoint_version"]),
            created_at=created_at.isoformat(),
            previous_run_id=run.get("previous_run_id") or None,
            target_sha256=_sha256_file(stage / "target.json"),
            checkpoint_sha256=_sha256_file(stage / "checkpoint.json"),
            run_sha256=_sha256_file(stage / "run.json"),
            run_history_sha256=_sha256_file(stage / "run_history.json"),
            resolution_history_sha256=_sha256_file(stage / "resolution_history.json"),
            bundle_status="committed",
        )
        _write_json(stage / "manifest.json", manifest.model_dump())
        verify_bundle(stage)
        os.replace(stage, output_dir)
        return verify_bundle(output_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_bundle(
    bundle_dir: Path,
    *,
    expected_target_id: Optional[str] = None,
    expected_checkpoint_version: Optional[int] = None,
) -> VerifiedMonitorBundle:
    """Reject partial, corrupt, mismatched, or validator-invalid bundles."""
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.is_dir():
        raise BundleError("monitor state bundle directory is unavailable")
    actual_files = {path.name for path in bundle_dir.iterdir() if path.is_file()}
    if actual_files != BUNDLE_FILES:
        raise BundleError("monitor state bundle file set is incomplete or unexpected")

    try:
        manifest = MonitorBundleManifest.model_validate(_read_json(bundle_dir / "manifest.json"))
    except Exception as exc:
        raise BundleError("manifest is invalid") from exc
    created_at = _parse_aware(manifest.created_at)
    if created_at is None:
        raise BundleError("manifest created_at must be timezone-aware")
    if expected_target_id and manifest.monitor_target_id != expected_target_id:
        raise BundleError("manifest target does not match requested target")
    if expected_checkpoint_version is not None and manifest.checkpoint_version != expected_checkpoint_version:
        raise BundleError("manifest checkpoint version does not match artifact identity")

    expected_hashes = {
        "target.json": manifest.target_sha256,
        "checkpoint.json": manifest.checkpoint_sha256,
        "run.json": manifest.run_sha256,
        "run_history.json": manifest.run_history_sha256,
        "resolution_history.json": manifest.resolution_history_sha256,
    }
    for filename, expected_hash in expected_hashes.items():
        if _sha256_file(bundle_dir / filename) != expected_hash:
            raise BundleError("bundle hash mismatch for %s" % filename)

    target = _require_dict(_read_json(bundle_dir / "target.json"), "target.json")
    checkpoint = _require_dict(_read_json(bundle_dir / "checkpoint.json"), "checkpoint.json")
    latest_run = _require_dict(_read_json(bundle_dir / "run.json"), "run.json")
    runs = _require_dict_list(_read_json(bundle_dir / "run_history.json"), "run_history.json")
    resolutions = _require_dict_list(
        _read_json(bundle_dir / "resolution_history.json"), "resolution_history.json"
    )
    if not runs or runs[-1] != latest_run:
        raise BundleError("run.json must equal the final run_history record")
    if target.get("monitor_target_id") != manifest.monitor_target_id:
        raise BundleError("target snapshot does not match manifest")
    if checkpoint.get("monitor_target_id") != manifest.monitor_target_id:
        raise BundleError("checkpoint target does not match manifest")
    if latest_run.get("monitor_target_id") != manifest.monitor_target_id:
        raise BundleError("run target does not match manifest")
    if latest_run.get("monitor_run_id") != manifest.monitor_run_id:
        raise BundleError("run ID does not match manifest")
    if int(checkpoint.get("checkpoint_version", "-1")) != manifest.checkpoint_version:
        raise BundleError("checkpoint version does not match manifest")
    if (latest_run.get("previous_run_id") or None) != manifest.previous_run_id:
        raise BundleError("previous_run_id does not match manifest")

    report = validate_monitor_bundle(
        {
            "monitor_target": [target],
            "monitor_run": runs,
            "monitor_resolution": resolutions,
            "monitor_checkpoint": [checkpoint],
        }
    )
    if not report.ok:
        raise BundleError(
            "persisted monitor bundle failed contract validation:\n%s"
            % "\n".join(issue.format() for issue in report.issues)
        )
    return VerifiedMonitorBundle(
        bundle_dir,
        manifest,
        target,
        checkpoint,
        latest_run,
        runs,
        resolutions,
        report,
    )


def select_previous_bundle(
    candidate_dirs: Sequence[Path], monitor_target_id: str
) -> Optional[VerifiedMonitorBundle]:
    """Select one verified highest-version bundle; reject ambiguous state."""
    if not candidate_dirs:
        return None
    verified = [verify_bundle(path, expected_target_id=monitor_target_id) for path in candidate_dirs]
    highest = max(bundle.manifest.checkpoint_version for bundle in verified)
    tails = [bundle for bundle in verified if bundle.manifest.checkpoint_version == highest]
    if len(tails) != 1:
        raise BundleError("multiple artifacts claim the same current checkpoint version")
    return tails[0]


def verify_uploaded_bundle(bundle_dir: Path) -> VerifiedMonitorBundle:
    """Translate post-upload re-read failure into the persistence error contract."""
    try:
        return verify_bundle(bundle_dir)
    except BundleError as exc:
        raise PersistenceError("persistence_error: uploaded artifact re-read validation failed") from exc


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError("could not read valid JSON from %s" % path.name) from exc


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_dict(value, filename: str) -> Dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise BundleError("%s must contain one string record" % filename)
    return value


def _require_dict_list(value, filename: str) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not all(
        isinstance(row, dict)
        and all(isinstance(key, str) and isinstance(item, str) for key, item in row.items())
        for row in value
    ):
        raise BundleError("%s must contain a list of string records" % filename)
    return value


def _parse_aware(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BundleError("%s must be timezone-aware" % name)
