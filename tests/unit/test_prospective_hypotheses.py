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


# --- 打ち切り基準 -------------------------------------------------------------

def test_a_stop_rule_may_be_tightened_but_never_relaxed():
    """Otherwise a hypothesis is never wrong, only awaiting one more condition."""
    from earnings_research.prospective_hypotheses.models import StopRule

    frozen = StopRule()
    assert StopRule(maximum_revisions=1).at_least_as_strict_as(frozen)
    assert StopRule(stop_below_reserved_effect_ratio=0.8).at_least_as_strict_as(frozen)
    assert not StopRule(maximum_revisions=99).at_least_as_strict_as(frozen)
    assert not StopRule(stop_below_reserved_effect_ratio=0.1).at_least_as_strict_as(frozen)
    assert not StopRule(stop_when_halves_reverse=False).at_least_as_strict_as(frozen)


def stopping_definition(**changes):
    from earnings_research.prospective_hypotheses.models import StopRule

    class _Rule:
        stop_rule = StopRule(**changes)

    class _Definition:
        assessment_rule = _Rule()

    return _Definition()


def test_a_reversal_between_halves_ends_the_hypothesis():
    from earnings_research.prospective_hypotheses.evaluator import should_stop

    assert should_stop(stopping_definition(), halves_reversed=True) is not None
    assert should_stop(stopping_definition(), halves_reversed=False) is None


def test_a_hypothesis_may_declare_that_reversal_is_expected():
    """A model that adapts across regimes is allowed to say so in advance."""
    from earnings_research.prospective_hypotheses.evaluator import should_stop

    definition = stopping_definition(stop_when_halves_reverse=False)
    assert should_stop(definition, halves_reversed=True) is None


def test_falling_short_on_the_reserved_period_ends_it():
    from earnings_research.prospective_hypotheses.evaluator import should_stop

    assert should_stop(stopping_definition(), reserved_effect_ratio=0.2) is not None
    assert should_stop(stopping_definition(), reserved_effect_ratio=0.9) is None


def test_patching_a_hypothesis_indefinitely_ends_it():
    from earnings_research.prospective_hypotheses.evaluator import should_stop

    assert should_stop(stopping_definition(), revisions=3) is not None
    assert should_stop(stopping_definition(), revisions=2) is None


def test_a_registry_frozen_before_stop_rules_keeps_its_hash():
    """A frozen definition is not rewritten to carry a field it never had."""
    from earnings_research.prospective_hypotheses.evaluator import canonical_hash
    from earnings_research.prospective_hypotheses.models import AssessmentRule, StopRule

    plain = AssessmentRule(
        comparison_basis="target_vs_all_eligible_events",
        minimum_target_trials=1,
        minimum_comparator_trials=1,
        retained_effect_ratio=0.5,
        no_material_mean_delta=0.01,
        no_material_positive_rate_delta=0.01,
    )
    assert "stop_rule" not in plain.model_dump()
    before = canonical_hash(registry())
    assert canonical_hash(registry()) == before


def test_a_stop_rule_a_version_does_carry_is_frozen_with_it():
    """Otherwise the conditions could be widened after the results came in."""
    from earnings_research.prospective_hypotheses.evaluator import canonical_hash
    from earnings_research.prospective_hypotheses.models import AssessmentRule, StopRule

    plain = AssessmentRule(
        comparison_basis="target_vs_all_eligible_events",
        minimum_target_trials=1,
        minimum_comparator_trials=1,
        retained_effect_ratio=0.5,
        no_material_mean_delta=0.01,
        no_material_positive_rate_delta=0.01,
    )
    strict = plain.model_copy(update={"stop_rule": StopRule(maximum_revisions=1)})
    loose = plain.model_copy(update={"stop_rule": StopRule(maximum_revisions=9)})
    assert canonical_hash(plain) != canonical_hash(strict)
    assert canonical_hash(strict) != canonical_hash(loose)
    assert strict.model_dump()["stop_rule"]["maximum_revisions"] == 1


def superseding(stop_rule, version=2):
    """A successor registry carrying one hypothesis at a bumped version."""
    from earnings_research.prospective_hypotheses.models import HypothesisRegistry

    base = registry()
    definition = base.hypotheses[0].model_copy(deep=True)
    definition.hypothesis_version += 1
    definition.assessment_rule = definition.assessment_rule.model_copy(
        update={"stop_rule": stop_rule}
    )
    payload = base.model_dump()
    payload["registry_version"] = version
    payload["hypotheses"] = [definition.model_dump()]
    payload["source_candidate_count"] = 1
    return HypothesisRegistry.model_validate(payload)


def test_a_successor_registry_cannot_relax_the_conditions_it_inherited(tmp_path):
    """A registry holds one version per hypothesis, so the widening would land here."""
    from earnings_research.prospective_hypotheses.evaluator import stop_rule_relaxations
    from earnings_research.prospective_hypotheses.models import StopRule

    frozen = superseding(StopRule(maximum_revisions=1), version=1)
    assert stop_rule_relaxations(frozen, superseding(StopRule(maximum_revisions=0))) == []
    assert stop_rule_relaxations(frozen, superseding(StopRule(maximum_revisions=9)))
    assert stop_rule_relaxations(frozen, superseding(None))


def _written(tmp_path, name, registry):
    path = tmp_path / name
    path.write_text(registry.model_dump_json(), encoding="utf-8")
    return path


def test_the_cli_refuses_a_successor_that_widens_its_stop_rule(tmp_path, capsys):
    """The check a version bump has to pass, reachable from CI."""
    from earnings_research.prospective_hypotheses.models import StopRule

    earlier = _written(tmp_path, "v1.json", superseding(StopRule(maximum_revisions=1), version=1))
    widened = _written(tmp_path, "v2.json", superseding(StopRule(maximum_revisions=9)))
    tightened = _written(tmp_path, "v2b.json", superseding(StopRule(maximum_revisions=0)))
    assert main([
        "verify-stop-rule-tightening",
        "--previous-registry", str(earlier),
        "--registry", str(widened),
    ]) == 1
    assert "relaxes the stop rule" in capsys.readouterr().err
    assert main([
        "verify-stop-rule-tightening",
        "--previous-registry", str(earlier),
        "--registry", str(tightened),
    ]) == 0


def test_a_successor_may_not_quietly_drop_an_inherited_stop_rule(tmp_path):
    from earnings_research.prospective_hypotheses.models import StopRule
    from earnings_research.prospective_hypotheses.pipeline import verify_stop_rules_only_tightened

    earlier = _written(tmp_path, "v1.json", superseding(StopRule(), version=1))
    dropped = _written(tmp_path, "v2.json", superseding(None))
    with pytest.raises(ValueError, match="drops the stop rule"):
        verify_stop_rules_only_tightened(earlier, dropped)


def test_a_registry_that_is_not_a_successor_is_refused(tmp_path):
    from earnings_research.prospective_hypotheses.models import StopRule
    from earnings_research.prospective_hypotheses.pipeline import verify_stop_rules_only_tightened

    same = superseding(StopRule(), version=1)
    with pytest.raises(ValueError, match="earlier registry_version"):
        verify_stop_rules_only_tightened(
            _written(tmp_path, "a.json", same), _written(tmp_path, "b.json", same)
        )


def test_a_version_without_a_stop_rule_has_no_stopping_point():
    """All 19 frozen versions carry none, and none is applied to them later."""
    from earnings_research.prospective_hypotheses.evaluator import should_stop

    for definition in registry().hypotheses:
        assert definition.assessment_rule.stop_rule is None
        assert should_stop(definition, halves_reversed=True, revisions=99) is None


def test_the_stop_rule_is_read_where_the_status_is_produced(tmp_path):
    """A condition nobody evaluates is a condition nobody is bound by."""
    from earnings_research.prospective_hypotheses.evaluator import summarize_trials
    from earnings_research.prospective_hypotheses.models import StopRule

    definition = registry().hypotheses[0].model_copy(deep=True)
    definition.hypothesis_version = 4
    definition.assessment_rule = definition.assessment_rule.model_copy(
        update={"stop_rule": StopRule(maximum_revisions=1)}
    )
    one = registry().model_copy(deep=True)
    one.hypotheses = [definition]
    one.source_candidate_count = 1
    snapshot = summarize_trials(one, [], datetime(2026, 10, 1, 12, tzinfo=JST))
    assert "revised 3 times" in snapshot.hypotheses[0].stop_reason
    assert "stop_reason" in snapshot.model_dump()["hypotheses"][0]


def test_an_open_hypothesis_reports_no_stop_reason():
    from earnings_research.prospective_hypotheses.evaluator import summarize_trials

    snapshot = summarize_trials(registry(), [], datetime(2026, 10, 1, 12, tzinfo=JST))
    assert {item.stop_reason for item in snapshot.hypotheses} == {None}
