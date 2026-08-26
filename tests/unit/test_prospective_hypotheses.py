import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from earnings_research.cli.__main__ import main
from earnings_research.prospective_hypotheses.evaluator import (
    evaluate_observation,
    summarize_trials,
)
from earnings_research.prospective_hypotheses.models import (
    CompletedEventObservation,
    HypothesisRegistry,
    HypothesisTrialBundle,
)
from earnings_research.prospective_hypotheses.pipeline import (
    build_registry_file,
    evaluate_observation_file,
    verify_registry_file,
)


ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "outputs/historical_research/research_knowledge.json"
REGISTRY = ROOT / "data/prospective_hypotheses/legacy_research_v1.json"
OBSERVATION = ROOT / "data/samples/prospective_hypothesis_event_sample.json"
JST = timezone(timedelta(hours=9))


def registry():
    return HypothesisRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))


def observation():
    return CompletedEventObservation.model_validate_json(OBSERVATION.read_text(encoding="utf-8"))


def test_registry_freezes_all_19_candidates_one_to_one():
    source = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))["learning"]["candidates"]
    result = registry()
    assert len(source) == len(result.hypotheses) == 19
    assert {item["candidate_id"] for item in source} == {
        item.source_candidate_id for item in result.hypotheses
    }
    assert len({item.hypothesis_id for item in result.hypotheses}) == 19
    assert sum(item.phase == "pre_event" for item in result.hypotheses) == 11
    assert sum(item.phase == "post_event" for item in result.hypotheses) == 8
    assert sum(item.priority == "primary" for item in result.hypotheses) == 6
    assert all(item.assessment_rule.minimum_target_trials == 30 for item in result.hypotheses)
    assert all(item.assessment_rule.minimum_comparator_trials == 30 for item in result.hypotheses)
    assert result.promotion_review_policy.automatic_promotion is False


def test_registry_is_reproducible_and_source_tampering_is_rejected(tmp_path):
    assert verify_registry_file(KNOWLEDGE, REGISTRY).source_candidate_count == 19
    changed = tmp_path / "knowledge.json"
    payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    payload["learning"]["candidates"][0]["value"] = "changed"
    changed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        verify_registry_file(changed, REGISTRY)


def test_phase_boundary_and_observation_timestamps_prevent_future_leakage():
    result = registry()
    assert all(
        (item.dimension == "reaction") == (item.phase == "post_event")
        for item in result.hypotheses
    )
    payload = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    payload["pre_event_features"]["captured_at"] = "2026-08-31T16:00:00+09:00"
    with pytest.raises(ValidationError, match="before the event"):
        CompletedEventObservation.model_validate(payload)


def test_completed_event_creates_target_and_overall_comparison_trials():
    bundle = evaluate_observation(
        registry(), observation(), datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    assert len(bundle.trials) == 19
    assert bundle.ineligible_hypotheses == {}
    assert {item.phase for item in bundle.trials} == {"pre_event", "post_event"}
    assert all(item.evaluation_horizon in {"D5", "D20"} for item in bundle.trials)
    b_plus_d5 = next(
        item for item in bundle.trials
        if item.observed_dimension == "rank" and item.evaluation_horizon == "D5" and item.cohort == "target"
    )
    assert b_plus_d5.individual_outcome == "success"


def test_missing_or_noncomparable_horizon_is_not_counted_as_failure():
    payload = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    payload["returns"] = [item for item in payload["returns"] if item["horizon"] != "D20"]
    bundle = evaluate_observation(
        registry(),
        CompletedEventObservation.model_validate(payload),
        datetime(2026, 9, 30, 18, tzinfo=JST),
    )
    assert all(item.evaluation_horizon == "D5" for item in bundle.trials)
    assert any(reason == "evaluation horizon has not matured" for reason in bundle.ineligible_hypotheses.values())


def test_append_only_writer_rejects_duplicate_event_and_existing_output(tmp_path):
    trials = tmp_path / "trials"
    output = trials / "event.json"
    evaluate_observation_file(
        REGISTRY, OBSERVATION, trials, output, datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    with pytest.raises((ValueError, FileExistsError), match="already"):
        evaluate_observation_file(
            REGISTRY, OBSERVATION, trials, output, datetime(2026, 9, 30, 19, tzinfo=JST)
        )


def _bundle_for(definition, index, target, value):
    base = observation()
    event = base.model_copy(deep=True)
    event.earnings_event_id = f"EE-{index:03d}"
    event.observation_id = f"OBS-{index:03d}"
    event.event_quarter = f"2026-Q{index % 2 + 1}"
    if definition.phase == "pre_event":
        setattr(event.pre_event_features, definition.dimension, definition.target_value if target else "other")
    else:
        setattr(event.post_event_features, definition.dimension, definition.target_value if target else "other")
    for item in event.returns:
        if item.horizon == definition.evaluation_horizon:
            item.return_value = value
    one = registry().model_copy(deep=True)
    one.hypotheses = [definition]
    one.source_candidate_count = 1
    return evaluate_observation(one, event, datetime(2026, 10, 1, 12, tzinfo=JST))


def test_fixed_minimum_and_effect_rules_derive_status_without_mutating_registry():
    definition = next(
        item for item in registry().hypotheses
        if item.expected_direction == "higher_than_comparator" and item.phase == "pre_event"
    )
    one = registry().model_copy(deep=True)
    one.hypotheses = [definition]
    one.source_candidate_count = 1
    few = [_bundle_for(definition, index, index < 5, 0.04 if index < 5 else 0.0) for index in range(10)]
    status = summarize_trials(one, few, datetime(2026, 10, 2, 12, tzinfo=JST)).hypotheses[0]
    assert status.status == "insufficient"
    bundles = [
        _bundle_for(definition, index, index < 30, 0.06 if index < 30 else 0.0)
        for index in range(60)
    ]
    status = summarize_trials(one, bundles, datetime(2026, 10, 2, 12, tzinfo=JST)).hypotheses[0]
    assert status.status == "supported"
    assert status.prospective_trials == 30
    assert status.comparator_observations == 60
    assert status.production_review_eligible is False


def test_duplicate_trial_identity_is_rejected():
    bundle = evaluate_observation(
        registry(), observation(), datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    with pytest.raises(ValueError, match="duplicate"):
        summarize_trials(registry(), [bundle, bundle], datetime(2026, 10, 1, 12, tzinfo=JST))


def test_trial_tampering_cannot_change_registry_or_phase_contract():
    bundle = evaluate_observation(
        registry(), observation(), datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    changed_hash = bundle.model_copy(deep=True)
    changed_hash.registry_sha256 = "0" * 64
    with pytest.raises(ValueError, match="registry hash"):
        summarize_trials(registry(), [changed_hash], datetime(2026, 10, 1, 12, tzinfo=JST))
    changed_phase = bundle.model_copy(deep=True)
    changed_phase.trials[0].phase = "pre_event" if changed_phase.trials[0].phase == "post_event" else "post_event"
    with pytest.raises(ValueError, match="frozen hypothesis"):
        summarize_trials(registry(), [changed_phase], datetime(2026, 10, 1, 12, tzinfo=JST))


def test_contract_schemas_accept_committed_registry_and_sample():
    pairs = [
        ("prospective_hypothesis_registry.schema.json", json.loads(REGISTRY.read_text(encoding="utf-8"))),
        ("prospective_hypothesis_event_observation.schema.json", json.loads(OBSERVATION.read_text(encoding="utf-8"))),
    ]
    for schema_name, instance in pairs:
        schema = json.loads((ROOT / "schemas/analysis" / schema_name).read_text(encoding="utf-8"))
        jsonschema.validate(instance, schema)


def test_cli_verifies_registry_and_builds_append_only_outputs(tmp_path):
    assert main([
        "verify-hypothesis-registry", "--knowledge", str(KNOWLEDGE), "--registry", str(REGISTRY)
    ]) == 0
    trials = tmp_path / "trials"
    output = trials / "event.json"
    assert main([
        "evaluate-hypothesis-event",
        "--registry", str(REGISTRY),
        "--observation", str(OBSERVATION),
        "--trials-dir", str(trials),
        "--recorded-at", "2026-09-30T18:00:00+09:00",
        "--output", str(output),
    ]) == 0
    summary = tmp_path / "status.json"
    assert main([
        "summarize-hypothesis-registry",
        "--registry", str(REGISTRY),
        "--trials-dir", str(trials),
        "--evaluated-at", "2026-10-01T09:00:00+09:00",
        "--output", str(summary),
    ]) == 0
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert len(result["hypotheses"]) == 19
    assert result["automatic_weight_change"] is False
