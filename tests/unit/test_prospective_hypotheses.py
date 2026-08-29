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
    _write_new,
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


def usable_registry(tmp_path):
    """A registry the gate permits, with a ledger saying so.

    The ledger is written by hand here rather than by `judge`, because under
    the rules as they stand no frozen hypothesis is affirmatively valid: every
    one of them is scored on a previous-close return, and every cohort the
    rules cover is fixed after that close. That is the finding, not a fixture
    problem — see test_no_frozen_hypothesis_is_currently_affirmatively_valid.
    What these tests need is the recording path, and what the recording path
    asks for is a ledger that clears the hypothesis.
    """
    from earnings_research.prospective_hypotheses.source_validity import (
        VALID,
        Verdict,
        append_ledger,
        source_fields_digest,
    )
    from earnings_research.statistics.lookahead import rules_digest

    base = registry()
    keep = base.hypotheses[:3]
    payload = base.model_dump()
    payload["hypotheses"] = [item.model_dump() for item in keep]
    payload["source_candidate_count"] = len(keep)
    directory = tmp_path / "registry"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "usable.json"
    path.write_text(
        HypothesisRegistry.model_validate(payload).model_dump_json(indent=2), encoding="utf-8"
    )
    append_ledger(directory / "source_validity.jsonl", [
        Verdict(
            hypothesis_id=item.hypothesis_id, hypothesis_version=item.hypothesis_version,
            registry_id=base.registry_id, registry_version=base.registry_version,
            dimension=item.dimension, evaluation_horizon=item.evaluation_horizon,
            source_field="open_d5", verdict=VALID, reason=None,
            contamination_rules_sha256=rules_digest(),
            source_fields_sha256=source_fields_digest(),
            evaluated_at="2026-09-01T00:00:00+09:00",
        )
        for item in keep
    ])
    return path, len(keep)


def test_no_frozen_hypothesis_is_currently_affirmatively_valid():
    """Every one is scored on a previous-close return, and every cohort the
    rules cover is fixed after that close. Nothing in this registry may gather
    prospective evidence until a registry is frozen from research that does not
    measure from there."""
    from earnings_research.prospective_hypotheses.source_validity import VALID, judge

    verdicts = judge(registry(), "2026-09-01T00:00:00+09:00")
    assert verdicts
    assert not [item for item in verdicts if item.verdict == VALID]


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


def test_the_same_event_may_not_be_recorded_twice_under_another_name(tmp_path):
    """Written to a different output path on purpose.

    The earlier form of this test reused one path and accepted either error, so
    `_write_new` refusing the filename satisfied it and the event-level scan it
    was named for could be — and was — deleted without the suite noticing. The
    scan is what protects an append-only record: a second bundle for one event
    is what `summarize_trials` afterwards fails on.
    """
    path, _count = usable_registry(tmp_path)
    trials = tmp_path / "trials"
    evaluate_observation_file(
        path, OBSERVATION, trials, trials / "first.json", datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    with pytest.raises(ValueError, match="already has an append-only hypothesis trial bundle"):
        evaluate_observation_file(
            path, OBSERVATION, trials, trials / "second.json",
            datetime(2026, 9, 30, 19, tzinfo=JST),
        )
    assert sorted(item.name for item in trials.glob("*.json")) == ["first.json"]


def test_an_existing_output_file_is_never_overwritten(tmp_path):
    """The other half of what one test used to claim: the writer refuses the
    filename even where the event-level scan has nothing to say."""
    path, _count = usable_registry(tmp_path)
    trials = tmp_path / "trials"
    output = trials / "event.json"
    evaluate_observation_file(
        path, OBSERVATION, trials, output, datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    before = output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="append-only output already exists"):
        _write_new(output, "{}\n")
    assert output.read_text(encoding="utf-8") == before


def test_no_trial_is_recorded_against_knowledge_the_rules_condemn(tmp_path):
    """The committed registry is seventeen-nineteenths invalid under the rules
    as they stand, and recording trials against it would be gathering evidence
    about hypotheses whose evidence the rules no longer support."""
    with pytest.raises(ValueError, match="source-validity"):
        evaluate_observation_file(
            REGISTRY, OBSERVATION, tmp_path / "trials", tmp_path / "trials/event.json",
            datetime(2026, 9, 30, 18, tzinfo=JST),
        )


def test_no_trial_is_recorded_against_knowledge_nobody_has_judged(tmp_path):
    """Unjudged is refused too. A definition nobody has checked under the
    current rules is the case this capability exists for."""
    path, _count = usable_registry(tmp_path)
    (path.parent / "source_validity.jsonl").unlink()
    with pytest.raises(ValueError, match="source-validity"):
        evaluate_observation_file(
            path, OBSERVATION, tmp_path / "trials", tmp_path / "trials/event.json",
            datetime(2026, 9, 30, 18, tzinfo=JST),
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
    path, count = usable_registry(tmp_path)
    trials = tmp_path / "trials"
    output = trials / "event.json"
    assert main([
        "evaluate-hypothesis-event",
        "--registry", str(path),
        "--observation", str(OBSERVATION),
        "--trials-dir", str(trials),
        "--recorded-at", "2026-09-30T18:00:00+09:00",
        "--output", str(output),
    ]) == 0
    summary = tmp_path / "status.json"
    assert main([
        "summarize-hypothesis-registry",
        "--registry", str(path),
        "--trials-dir", str(trials),
        "--evaluated-at", "2026-10-01T09:00:00+09:00",
        "--output", str(summary),
    ]) == 0
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert len(result["hypotheses"]) == count
    assert result["automatic_weight_change"] is False


# --- 打ち切り基準 -------------------------------------------------------------

def stop_rule(**changes):
    """Every term stated. The model has no defaults, on purpose."""
    from earnings_research.prospective_hypotheses.models import StopRule

    return StopRule(**{
        "stop_when_halves_reverse": True,
        "stop_below_reserved_effect_ratio": 0.5,
        "maximum_revisions": 2,
        **changes,
    })


def test_a_stop_rule_states_every_term_and_refuses_unknown_ones():
    """A term left out took whatever the code said that day, so the hash of a
    frozen registry depended on the code rather than on its own bytes. A
    misspelled term was accepted in silence as the default, leaving a rule that
    reads as tightened and is not."""
    from pydantic import ValidationError as _ValidationError

    from earnings_research.prospective_hypotheses.models import StopRule

    complete = {
        "stop_when_halves_reverse": True,
        "stop_below_reserved_effect_ratio": 0.5,
        "maximum_revisions": 2,
    }
    # Each term on its own: the earlier version omitted one and so pinned only
    # that one, leaving a default on either of the other two undetected.
    for missing in complete:
        with pytest.raises(_ValidationError):
            StopRule(**{key: value for key, value in complete.items() if key != missing})
    assert StopRule(**complete)
    with pytest.raises(_ValidationError):
        stop_rule(stop_when_halves_reversed=False)


def test_a_stop_rule_may_be_tightened_but_never_relaxed():
    """Otherwise a hypothesis is never wrong, only awaiting one more condition."""
    from earnings_research.prospective_hypotheses.models import StopRule

    frozen = stop_rule()
    assert stop_rule(maximum_revisions=1).at_least_as_strict_as(frozen)
    assert stop_rule(stop_below_reserved_effect_ratio=0.8).at_least_as_strict_as(frozen)
    assert not stop_rule(maximum_revisions=99).at_least_as_strict_as(frozen)
    assert not stop_rule(stop_below_reserved_effect_ratio=0.1).at_least_as_strict_as(frozen)
    assert not stop_rule(stop_when_halves_reverse=False).at_least_as_strict_as(frozen)


def stopping_definition(**changes):
    class _Rule:
        stop_rule = stop_rule(**changes)

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
    strict = plain.model_copy(update={"stop_rule": stop_rule(maximum_revisions=1)})
    loose = plain.model_copy(update={"stop_rule": stop_rule(maximum_revisions=9)})
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

    frozen = superseding(stop_rule(maximum_revisions=1), version=1)
    assert stop_rule_relaxations(frozen, superseding(stop_rule(maximum_revisions=0))) == []
    assert stop_rule_relaxations(frozen, superseding(stop_rule(maximum_revisions=9)))
    assert stop_rule_relaxations(frozen, superseding(None))


def _written(tmp_path, name, registry):
    path = tmp_path / name
    path.write_text(registry.model_dump_json(), encoding="utf-8")
    return path


def test_the_cli_refuses_a_successor_that_widens_its_stop_rule(tmp_path, capsys):
    """The check a version bump has to pass, reachable from CI."""
    from earnings_research.prospective_hypotheses.models import StopRule

    earlier = _written(tmp_path, "v1.json", superseding(stop_rule(maximum_revisions=1), version=1))
    widened = _written(tmp_path, "v2.json", superseding(stop_rule(maximum_revisions=9)))
    tightened = _written(tmp_path, "v2b.json", superseding(stop_rule(maximum_revisions=0)))
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

    earlier = _written(tmp_path, "v1.json", superseding(stop_rule(), version=1))
    dropped = _written(tmp_path, "v2.json", superseding(None))
    with pytest.raises(ValueError, match="drops the stop rule"):
        verify_stop_rules_only_tightened(earlier, dropped)


def test_a_registry_that_is_not_a_successor_is_refused(tmp_path):
    from earnings_research.prospective_hypotheses.models import StopRule
    from earnings_research.prospective_hypotheses.pipeline import verify_stop_rules_only_tightened

    same = superseding(stop_rule(), version=1)
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
        update={"stop_rule": stop_rule(maximum_revisions=1)}
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


# --- 停止規則が「効果」を見ていること -----------------------------------------

def _trial(definition, index, target, value, day):
    """One trial for a hypothesis, on a given day, in or out of the target."""
    from earnings_research.prospective_hypotheses.models import HypothesisTrial

    return HypothesisTrial(
        trial_id="T-%03d" % index,
        hypothesis_id=definition.hypothesis_id,
        hypothesis_version=definition.hypothesis_version,
        earnings_event_id="EE-%03d" % index,
        event_quarter="2026-Q%d" % (index % 4 + 1),
        phase=definition.phase,
        evaluation_horizon=definition.evaluation_horizon,
        cohort="target" if target else "non_target",
        observed_dimension=definition.dimension,
        observed_value=definition.target_value if target else "other",
        return_value=value,
        individual_outcome="success",
        outcome_observed_at=datetime(2026, day // 28 + 1, day % 28 + 1, 15, tzinfo=JST),
        observation_id="OBS-%03d" % index,
        observation_sha256="0" * 64,
        source_record_ids=["R-%03d" % index],
        recorded_at=datetime(2026, 12, 1, 12, tzinfo=JST),
        append_only=True,
    )


def halves(first_target, first_other, second_target, second_other):
    """Build two halves with the stated target and comparator returns."""
    from earnings_research.prospective_hypotheses.evaluator import _halves_reversed

    definition = registry().hypotheses[0]
    index = 0
    target, comparator = [], []
    # The frozen rule asks for thirty trials on each side of each half.
    for day, (inside, outside) in enumerate(
        [(first_target, first_other)] * 32 + [(second_target, second_other)] * 32
    ):
        for value, is_target in ((inside, True), (outside, False)):
            index += 1
            trial = _trial(definition, index, is_target, value, day)
            (target if is_target else comparator).append(trial)
    return _halves_reversed(definition, target, target + comparator)


def test_a_market_that_turned_does_not_count_as_the_effect_reversing():
    """The target group's raw returns flip whenever the market does. Reading
    them instead of the effect retires a hypothesis that held perfectly in both
    halves — and this is the condition that is on by default."""
    assert halves(-0.0525, -0.1025, 0.1525, 0.1025) is False


def test_an_effect_that_actually_decayed_is_caught_even_while_returns_stay_up():
    """The mirror failure: raw returns positive throughout, effect +5% to -5%."""
    assert halves(0.1525, 0.1025, 0.0525, 0.1025) is True


def test_a_difference_inside_the_frozen_materiality_band_is_not_a_reversal():
    assert halves(0.0002, 0.0, -0.0002, 0.0) is None


def test_too_few_trials_in_a_half_answers_nothing_rather_than_guessing():
    from earnings_research.prospective_hypotheses.evaluator import _halves_reversed

    definition = registry().hypotheses[0]
    assert _halves_reversed(definition, [], []) is None


def test_a_stopped_hypothesis_does_not_keep_reading_as_a_live_one():
    """status and stop_reason were computed independently, so a hypothesis
    could be supported and finished at the same time and the stop reason
    appeared nowhere a reader would look."""
    from earnings_research.prospective_hypotheses.evaluator import summarize_trials

    definition = registry().hypotheses[0].model_copy(deep=True)
    definition.hypothesis_version = 4
    definition.assessment_rule = definition.assessment_rule.model_copy(
        update={"stop_rule": stop_rule(maximum_revisions=1)}
    )
    one = registry().model_copy(deep=True)
    one.hypotheses = [definition]
    one.source_candidate_count = 1
    status = summarize_trials(one, [], datetime(2026, 10, 1, 12, tzinfo=JST)).hypotheses[0]
    assert status.status == "stopped"
    assert "revised 3 times" in status.stop_reason


def test_the_frozen_registry_hashes_to_a_value_recorded_outside_the_code():
    """Comparing the function against itself passes for any implementation.
    Salting canonical_hash passed all 873 tests; committed trial bundles carry
    this value and would have been invalidated in silence."""
    from earnings_research.prospective_hypotheses.evaluator import canonical_hash

    assert canonical_hash(registry()) == (
        "c6f05a282529c532d6d91ab01a2d769db876d9459b6b57552b8f8636b8252be9"
    )


def test_a_successor_cannot_drop_the_hypotheses_whose_rules_it_inherited():
    """Deleting a definition retires its stop rule, which is the largest
    relaxation available, and it was being reported as tightening."""
    from earnings_research.prospective_hypotheses.evaluator import stop_rule_relaxations
    from earnings_research.prospective_hypotheses.models import HypothesisRegistry

    previous = superseding(stop_rule(), version=1)
    replaced = previous.model_dump()
    replaced["registry_version"] = 2
    # A successor that keeps a hypothesis, but not the one that carried a rule.
    replaced["hypotheses"][0]["hypothesis_id"] = "LRH-SOMETHING-NEW"
    problems = stop_rule_relaxations(previous, HypothesisRegistry.model_validate(replaced))
    assert any("was dropped" in problem for problem in problems)


def test_an_unrelated_registry_is_not_a_successor():
    """Only the version numbers were compared, so a registry sharing no
    identifiers at all passed by having a larger number."""
    from earnings_research.prospective_hypotheses.evaluator import stop_rule_relaxations

    previous = superseding(stop_rule(), version=1)
    stranger = superseding(stop_rule(stop_when_halves_reverse=False), version=9)
    stranger.registry_id = "SOMETHING-ELSE"
    problems = stop_rule_relaxations(previous, stranger)
    assert any("is not a successor" in problem for problem in problems)


def test_a_status_and_a_stop_reason_cannot_disagree():
    """They were derived independently, so `supported` and a stop reason could
    ride together and a stopped hypothesis could carry none."""
    from earnings_research.prospective_hypotheses.models import HypothesisStatus

    fields = dict(
        hypothesis_id="LRH-X", hypothesis_version=1, phase="pre_event", priority="primary",
        prospective_trials=0, prospective_successes=0, prospective_failures=0,
        comparator_observations=0, target_mean_return=None, comparator_mean_return=None,
        prospective_effect=None, target_positive_rate=None, comparator_positive_rate=None,
        prospective_positive_rate_effect=None, distinct_event_quarters=0,
        last_evaluated_at=None, note="x",
    )
    with pytest.raises(ValidationError):
        HypothesisStatus(status="supported", stop_reason="halves reversed", **fields)
    with pytest.raises(ValidationError):
        HypothesisStatus(status="stopped", stop_reason=None, **fields)
    assert HypothesisStatus(status="stopped", stop_reason="halves reversed", **fields)


def test_a_condition_that_was_never_looked_at_says_so():
    """The reserved-effect condition has no counterpart in prospective trials
    and is never passed, so it can never fire. Reporting which conditions were
    evaluated is the difference between that and a condition that was checked
    and did not fire."""
    from earnings_research.prospective_hypotheses.evaluator import summarize_trials

    definition = registry().hypotheses[0].model_copy(deep=True)
    definition.assessment_rule = definition.assessment_rule.model_copy(
        update={"stop_rule": stop_rule()}
    )
    one = registry().model_copy(deep=True)
    one.hypotheses = [definition]
    one.source_candidate_count = 1
    status = summarize_trials(one, [], datetime(2026, 10, 1, 12, tzinfo=JST)).hypotheses[0]
    assert "revisions" in status.stop_conditions_evaluated
    assert "reserved_effect" not in status.stop_conditions_evaluated


def test_the_status_snapshot_matches_its_committed_schema(tmp_path):
    """Nothing validated this schema, so `stopped` and stop_reason were hand
    added to it with nothing detecting drift from the model."""
    from earnings_research.prospective_hypotheses.evaluator import summarize_trials

    schema = json.loads(
        (ROOT / "schemas/analysis/prospective_hypothesis_status.schema.json").read_text(
            encoding="utf-8"
        )
    )
    snapshot = summarize_trials(registry(), [], datetime(2026, 10, 1, 12, tzinfo=JST))
    jsonschema.validate(json.loads(snapshot.model_dump_json()), schema)
    for name in ("stopped", "supported", "rejected"):
        assert name in schema["$defs"]["HypothesisStatus"]["properties"]["status"]["enum"]


def test_the_trial_bundle_schema_accepts_what_the_pipeline_writes():
    from earnings_research.prospective_hypotheses.evaluator import evaluate_observation

    schema = json.loads(
        (ROOT / "schemas/analysis/prospective_hypothesis_trial_bundle.schema.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = evaluate_observation(registry(), observation(), datetime(2026, 10, 1, 12, tzinfo=JST))
    jsonschema.validate(json.loads(bundle.model_dump_json()), schema)
