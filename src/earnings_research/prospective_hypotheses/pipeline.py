"""File boundaries for registry generation, append-only evaluation, and summaries."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .evaluator import evaluate_observation, summarize_trials
from .models import (
    CompletedEventObservation,
    HypothesisRegistry,
    HypothesisTrialBundle,
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
    return [
        HypothesisTrialBundle.model_validate_json(item.read_text(encoding="utf-8"))
        for item in sorted(path.glob("*.json"))
    ]


def evaluate_observation_file(
    registry_path: Path,
    observation_path: Path,
    trials_dir: Path,
    output_path: Path,
    recorded_at: datetime,
):
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    observation = CompletedEventObservation.model_validate_json(
        Path(observation_path).read_text(encoding="utf-8")
    )
    existing = load_trial_bundles(trials_dir)
    if any(bundle.earnings_event_id == observation.earnings_event_id for bundle in existing):
        raise ValueError("this earnings event already has an append-only hypothesis trial bundle")
    bundle = evaluate_observation(registry, observation, recorded_at)
    _write_new(output_path, _render(bundle))
    return bundle


def summarize_trials_file(
    registry_path: Path,
    trials_dir: Path,
    output_path: Path,
    evaluated_at: datetime,
):
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    snapshot = summarize_trials(registry, load_trial_bundles(trials_dir), evaluated_at)
    _write_new(output_path, _render(snapshot))
    return snapshot
