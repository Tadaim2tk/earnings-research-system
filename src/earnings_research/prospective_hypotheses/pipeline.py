"""File boundaries for registry generation, append-only evaluation, and summaries."""

import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .evaluator import (
    canonical_hash,
    evaluate_observation,
    summarize_trials,
    validate_bundle_history,
)
from .models import (
    CompletedEventObservation,
    HypothesisRegistry,
    HypothesisTrialBundle,
    HypothesisTrialBundleV1,
)
from earnings_research.validation.validator import (
    _calculate_baseline_record_hash,
    load_spec,
    validate_file,
)
from .registry import build_registry, load_knowledge


def _render(model):
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_new(path: Path, text: str):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_registry_file(knowledge_path: Path, output_path: Path, frozen_at: datetime):
    knowledge_path = Path(knowledge_path)
    knowledge, source_hash = load_knowledge(knowledge_path)
    registry = build_registry(knowledge, str(knowledge_path), source_hash, frozen_at)
    _write_new(output_path, _render(registry))
    return registry


def verify_registry_file(knowledge_path: Path, registry_path: Path):
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    recorded_source = Path(registry.source_research_path)
    if not recorded_source.is_absolute():
        recorded_source = Path.cwd() / recorded_source
    if recorded_source.resolve() != Path(knowledge_path).resolve():
        raise ValueError("registry source path does not match the supplied legacy research file")
    knowledge, source_hash = load_knowledge(Path(knowledge_path))
    expected = build_registry(
        knowledge,
        registry.source_research_path,
        source_hash,
        registry.frozen_at,
    )
    if _render(expected) != Path(registry_path).read_text(encoding="utf-8"):
        raise ValueError("committed hypothesis registry does not match its frozen source")
    return registry


def load_trial_bundles(trials_dir: Path):
    path = Path(trials_dir)
    if not path.exists():
        return []
    bundles = []
    for item in sorted(path.glob("*.json")):
        payload = json.loads(item.read_text(encoding="utf-8"))
        version = payload.get("schema_version")
        if version == "prospective_hypothesis_trial_bundle_v1":
            bundles.append(HypothesisTrialBundleV1.model_validate(payload))
        elif version == "prospective_hypothesis_trial_bundle_v2":
            bundles.append(HypothesisTrialBundle.model_validate(payload))
        else:
            raise ValueError(f"unsupported hypothesis trial bundle schema: {version!r}")
    validate_bundle_history(bundles)
    return bundles


def _trial_keys(bundles):
    return {
        (
            trial.hypothesis_id,
            trial.hypothesis_version,
            trial.earnings_event_id,
            trial.evaluation_horizon,
        )
        for bundle in bundles
        for trial in bundle.trials
    }


def _verify_authoritative_baseline(baseline_path, observation):
    baseline_path = Path(baseline_path)
    report = validate_file(baseline_path)
    if not report.ok:
        raise ValueError(
            "authoritative baseline validation failed: "
            + "; ".join(issue.format() for issue in report.issues)
        )
    with baseline_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_id = observation.pre_event_features.baseline_id
    matches = [row for row in rows if row.get("baseline_id", "").strip() == expected_id]
    if len(matches) != 1:
        raise ValueError("baseline_id must resolve to exactly one authoritative row")
    row = matches[0]
    if row.get("earnings_event_id", "").strip() != observation.earnings_event_id:
        raise ValueError("authoritative baseline belongs to a different earnings event")
    if row.get("baseline_version", "").strip() != f"v{observation.pre_event_features.baseline_version}":
        raise ValueError("authoritative baseline version does not match the event observation")
    if row.get("is_locked", "").strip().lower() != "true":
        raise ValueError("authoritative baseline must be locked")
    status = row.get("baseline_status", "").strip()
    if status and status != "locked":
        raise ValueError("authoritative prospective baseline must have locked status")
    try:
        locked_at = datetime.fromisoformat(row.get("locked_at", "").strip())
    except ValueError as exc:
        raise ValueError("authoritative baseline locked_at is invalid") from exc
    if locked_at != observation.pre_event_features.locked_at:
        raise ValueError("authoritative baseline lock timestamp does not match the event observation")
    if locked_at >= observation.event_occurred_at:
        raise ValueError("authoritative baseline must be locked before the event occurs")
    spec = load_spec("pre_earnings_baseline")
    canonical_hash = _calculate_baseline_record_hash(row, spec)
    declared_hash = row.get("baseline_record_hash", "").strip()
    if declared_hash != canonical_hash:
        raise ValueError("authoritative baseline hash does not match its canonical locked content")
    if observation.pre_event_features.baseline_record_hash != canonical_hash:
        raise ValueError("event observation baseline hash does not match the authoritative baseline")
    if expected_id not in observation.source_record_ids:
        raise ValueError("event observation source_record_ids must include the authoritative baseline_id")
    features = observation.pre_event_features
    recorded_rank = row.get("pre_event_grade", "").strip() or None
    if features.rank != recorded_rank:
        raise ValueError("event observation rank must match authoritative pre_event_grade")
    unsupported = {
        "narrative": features.narrative,
        "judge": features.judge,
        "risk_balance": features.risk_balance,
        "volatility_environment": features.volatility_environment,
        "dollar_environment": features.dollar_environment,
    }
    supplied = sorted(name for name, value in unsupported.items() if value is not None)
    if supplied:
        raise ValueError(
            "pre-event hypothesis fields lack an authoritative mapping: " + ", ".join(supplied)
        )
    return row


def _validate_observation_chain(existing, observation):
    if any(
        isinstance(item, HypothesisTrialBundleV1)
        and item.earnings_event_id == observation.earnings_event_id
        for item in existing
    ):
        raise ValueError("a v1 event bundle cannot be extended as a staged v2 observation")
    event_bundles = sorted(
        (
            item for item in existing
            if isinstance(item, HypothesisTrialBundle)
            and item.earnings_event_id == observation.earnings_event_id
        ),
        key=lambda item: item.observation_version,
    )
    if not event_bundles:
        if observation.observation_version != 1 or observation.supersedes_observation_id is not None:
            raise ValueError("first staged observation must be version 1 without a predecessor")
        return
    versions = [item.observation_version for item in event_bundles]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError("existing staged observation versions are not contiguous")
    previous = event_bundles[-1]
    if observation.observation_version != previous.observation_version + 1:
        raise ValueError("staged observation version must increment by one")
    if observation.supersedes_observation_id != previous.observation_id:
        raise ValueError("staged observation must supersede the current event observation")
    identity = (
        observation.company_name,
        observation.ticker,
        observation.event_quarter,
        observation.event_occurred_at,
    )
    previous_identity = (
        previous.company_name,
        previous.ticker,
        previous.event_quarter,
        previous.event_occurred_at,
    )
    if identity != previous_identity:
        raise ValueError("staged observation cannot change event identity")
    if canonical_hash(observation.pre_event_features) != previous.pre_event_features_sha256:
        raise ValueError("staged observation cannot change frozen pre-event features")
    if previous.reaction is not None and observation.post_event_features.reaction != previous.reaction:
        raise ValueError("staged observation cannot change an already recorded reaction")
    order = {"D1": 1, "D5": 2, "D20": 3}
    if order[observation.observation_stage] <= order[previous.observation_stage]:
        raise ValueError("staged observation horizon must advance")
    if observation.observed_through <= previous.observed_through:
        raise ValueError("staged observation time must advance")
    current_returns = {item.horizon: item for item in observation.returns}
    for old_return in previous.return_snapshots:
        current = current_returns.get(old_return.horizon)
        if current is None or current.model_dump(mode="json") != old_return.model_dump(mode="json"):
            raise ValueError("staged observation cannot remove or change a matured return")


def evaluate_observation_file(
    registry_path: Path,
    observation_path: Path,
    trials_dir: Path,
    output_path: Path,
    recorded_at: datetime,
    baseline_path: Path,
):
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    observation = CompletedEventObservation.model_validate_json(
        Path(observation_path).read_text(encoding="utf-8")
    )
    _verify_authoritative_baseline(baseline_path, observation)
    existing = load_trial_bundles(trials_dir)
    _validate_observation_chain(existing, observation)
    bundle = evaluate_observation(
        registry,
        observation,
        recorded_at,
        existing_trial_keys=_trial_keys(existing),
    )
    _write_new(output_path, _render(bundle))
    return bundle


def evaluate_observation_and_status_file(
    registry_path: Path,
    observation_path: Path,
    trials_dir: Path,
    trial_output_path: Path,
    status_output_path: Path,
    recorded_at: datetime,
    evaluated_at: datetime,
    baseline_path: Path,
):
    trials_dir = Path(trials_dir)
    if Path(trial_output_path).parent.resolve() != trials_dir.resolve():
        raise ValueError("trial output must be a direct child of the append-only trials directory")
    if Path(status_output_path).parent.resolve() == trials_dir.resolve():
        raise ValueError("derived status output must stay outside the trial source directory")
    if Path(trial_output_path).exists() or Path(status_output_path).exists():
        raise FileExistsError("append-only trial and status output paths must both be new")
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    observation = CompletedEventObservation.model_validate_json(
        Path(observation_path).read_text(encoding="utf-8")
    )
    _verify_authoritative_baseline(baseline_path, observation)
    existing = load_trial_bundles(trials_dir)
    _validate_observation_chain(existing, observation)
    bundle = evaluate_observation(
        registry,
        observation,
        recorded_at,
        existing_trial_keys=_trial_keys(existing),
    )
    snapshot = summarize_trials(registry, existing + [bundle], evaluated_at)
    _write_new(trial_output_path, _render(bundle))
    _write_new(status_output_path, _render(snapshot))
    return bundle, snapshot


def summarize_trials_file(
    registry_path: Path,
    trials_dir: Path,
    output_path: Path,
    evaluated_at: datetime,
):
    if Path(output_path).parent.resolve() == Path(trials_dir).resolve():
        raise ValueError("derived status output must stay outside the trial source directory")
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    snapshot = summarize_trials(registry, load_trial_bundles(trials_dir), evaluated_at)
    _write_new(output_path, _render(snapshot))
    return snapshot
