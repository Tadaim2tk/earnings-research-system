"""What may no longer change once a hypothesis has started gathering evidence.

Every path here runs against a synthetic registry rather than the committed
one, because the committed registry cannot reach any of them: all nineteen of
its hypotheses are invalid under the contamination rules, so none may record a
trial, so none has an evaluation start and none has rules to freeze.

The synthetic registry is not a loosened copy of production. It uses the
production contamination rules unchanged, and picks a pairing those rules
genuinely clear — a `rank` cohort scored on an opening-anchored return. If that
ever stops being true, `test_the_fixture_is_valid_under_the_production_rules`
fails rather than the rest of the file quietly testing an unreachable state.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from earnings_research.prospective_hypotheses.evaluator import summarize_trials
from earnings_research.prospective_hypotheses.freeze import (
    evaluation_started_at,
    rule_digest,
    rule_freeze_violations,
    started,
)
from earnings_research.prospective_hypotheses.models import (
    CompletedEventObservation,
    HypothesisRegistry,
)
from earnings_research.prospective_hypotheses.pipeline import (
    evaluate_observation_file,
    load_trial_bundles,
    verify_rule_freeze_files,
)
from earnings_research.prospective_hypotheses.source_validity import (
    VALID,
    Verdict,
    append_ledger,
    source_fields_digest,
)
from earnings_research.statistics import lookahead

ROOT = Path(__file__).resolve().parents[2]
OBSERVATION = ROOT / "data/samples/prospective_hypothesis_event_sample.json"
JST = timezone(timedelta(hours=9))
FROZEN_AT = datetime(2026, 9, 1, tzinfo=JST)

# The cohort and the return the synthetic hypothesis pairs. Chosen because the
# production rules clear it: `rank` is fixed after the previous close, and an
# opening-anchored return does not start there.
DIMENSION = "rank"
SOURCE_FIELD = "open_d5"


def stop_rule(**changes):
    return {
        "stop_when_halves_reverse": True,
        "stop_below_reserved_effect_ratio": 0.5,
        "maximum_revisions": 2,
        **changes,
    }


def promotion_policy(**changes):
    return {
        "automatic_promotion": False,
        "minimum_target_trials": 30,
        "minimum_comparator_trials": 60,
        "minimum_distinct_event_quarters": 3,
        "minimum_consecutive_supported_evaluations": 2,
        "note": "promotion is a human decision; these are the conditions for asking",
        **changes,
    }


def synthetic_registry(
    *, registry_version=1, hypothesis_version=1, stop=None, promotion=None
):
    """One hypothesis the contamination rules clear, frozen on its own terms."""
    definition = {
        "hypothesis_id": "SYN-RANK-D5",
        "hypothesis_version": hypothesis_version,
        "origin": "legacy_research",
        "source_candidate_id": "SYN-CANDIDATE-1",
        "hypothesis_text": "A-ranked events outperform the eligible cohort over five days.",
        "phase": "pre_event",
        "priority": "primary",
        "target_scope": "new_ers_japanese_equity_earnings",
        "dimension": DIMENSION,
        "target_value": "B+",
        "expected_direction": "higher_than_comparator",
        "evaluation_horizon": "D5",
        "historical_sample_size": {
            "available_count": 40,
            "effective_unit_count": 40,
            "distinct_ticker_count": 35,
            "distinct_context_snapshot_count": 12,
        },
        "historical_effect": {
            "mean_return_delta_vs_overall": 0.01,
            "positive_rate_delta_vs_overall": 0.05,
        },
        "historical_sample_grade": "limited",
        "frozen_at": FROZEN_AT.isoformat(),
        "assessment_rule": {
            "comparison_basis": "target_vs_all_eligible_events",
            "minimum_target_trials": 20,
            "minimum_comparator_trials": 40,
            "retained_effect_ratio": 0.5,
            "no_material_mean_delta": 0.002,
            "no_material_positive_rate_delta": 0.02,
            "stop_rule": stop or stop_rule(),
        },
    }
    return HypothesisRegistry.model_validate({
        "registry_id": "ERS-SYNTHETIC-FREEZE",
        "registry_version": registry_version,
        "source_research_path": "synthetic",
        "source_research_sha256": "0" * 64,
        "source_candidate_count": 1,
        "frozen_at": FROZEN_AT.isoformat(),
        "hypotheses": [definition],
        "promotion_review_policy": promotion or promotion_policy(),
    })


def freeze(directory, registry, *, clear=True):
    """Write a registry and a ledger that clears it, as a recording path needs."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("%s-v%d.json" % (registry.registry_id, registry.registry_version))
    path.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
    if clear:
        append_ledger(directory / "source_validity.jsonl", [
            Verdict(
                hypothesis_id=item.hypothesis_id,
                hypothesis_version=item.hypothesis_version,
                registry_id=registry.registry_id,
                registry_version=registry.registry_version,
                dimension=item.dimension,
                evaluation_horizon=item.evaluation_horizon,
                source_field=SOURCE_FIELD,
                verdict=VALID,
                reason=None,
                contamination_rules_sha256=lookahead.rules_digest(),
                source_fields_sha256=source_fields_digest(),
                evaluated_at=FROZEN_AT.isoformat(),
            )
            for item in registry.hypotheses
        ])
    return path


def observation(index):
    payload = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    payload["earnings_event_id"] = "EE-SYNTHETIC-%03d" % index
    payload["observation_id"] = "OBS-SYNTHETIC-%03d" % index
    payload["event_quarter"] = "2026-Q%d" % (index % 4 + 1)
    return CompletedEventObservation.model_validate(payload)


def record(tmp_path, registry_path, index, recorded_at):
    """Put one trial into the append-only record, through the real path."""
    source = tmp_path / "observations"
    source.mkdir(parents=True, exist_ok=True)
    payload = source / ("obs-%03d.json" % index)
    payload.write_text(observation(index).model_dump_json(indent=2), encoding="utf-8")
    trials = tmp_path / "trials"
    return evaluate_observation_file(
        registry_path, payload, trials, trials / ("bundle-%03d.json" % index), recorded_at
    )


def key(registry):
    item = registry.hypotheses[0]
    return (item.hypothesis_id, item.hypothesis_version)


# --- the fixture answers to production, not the other way round -------------

def test_the_fixture_is_valid_under_the_production_rules():
    """The whole file rests on this pairing being one the rules actually clear.

    Asserted against `lookahead` itself rather than assumed, and with nothing
    monkeypatched: a fixture that reached `valid` by loosening the rules would
    be testing a system that does not exist. If a future rule condemns this
    pairing, this fails first and says so, instead of every path below
    exercising a state production can never enter.
    """
    assert lookahead.declares(DIMENSION)
    assert lookahead.contamination(DIMENSION, SOURCE_FIELD) is None
    assert lookahead.RETURN_ANCHOR[SOURCE_FIELD] not in lookahead.COHORT_SPAN[DIMENSION]


# --- 1. the first eligible trial fixes the start ----------------------------

def test_the_first_eligible_trial_sets_the_evaluation_start(tmp_path):
    registry = synthetic_registry()
    path = freeze(tmp_path / "registry", registry)
    assert evaluation_started_at(key(registry), []) is None
    at = datetime(2026, 10, 1, 9, tzinfo=JST)
    record(tmp_path, path, 1, at)
    bundles = load_trial_bundles(tmp_path / "trials")
    assert bundles, "the recording path refused a hypothesis the rules clear"
    assert evaluation_started_at(key(registry), bundles) == at
    assert started(key(registry), bundles)


# --- 2. later trials do not move it -----------------------------------------

def test_later_trials_do_not_move_the_start(tmp_path):
    """Otherwise the freeze would slide forward with every new event, and a rule
    changed today would always be a rule changed before the latest trial."""
    registry = synthetic_registry()
    path = freeze(tmp_path / "registry", registry)
    first = datetime(2026, 10, 1, 9, tzinfo=JST)
    record(tmp_path, path, 1, first)
    for index, day in ((2, 8), (3, 15)):
        record(tmp_path, path, index, datetime(2026, 10, day, 9, tzinfo=JST))
    bundles = load_trial_bundles(tmp_path / "trials")
    assert len(bundles) == 3
    assert evaluation_started_at(key(registry), bundles) == first


def test_the_start_is_the_earliest_trial_and_not_the_first_one_written(tmp_path):
    """Files are read in name order, so a bundle recorded earlier but written
    later would set the start to the wrong moment if the order were trusted."""
    registry = synthetic_registry()
    path = freeze(tmp_path / "registry", registry)
    record(tmp_path, path, 1, datetime(2026, 10, 20, 9, tzinfo=JST))
    record(tmp_path, path, 2, datetime(2026, 10, 3, 9, tzinfo=JST))
    bundles = load_trial_bundles(tmp_path / "trials")
    assert evaluation_started_at(key(registry), bundles) == datetime(2026, 10, 3, 9, tzinfo=JST)


# --- 3. after the start, neither rule may move ------------------------------

@pytest.mark.parametrize("changed", [
    pytest.param({"stop": stop_rule(maximum_revisions=9)}, id="stop-rule-loosened"),
    pytest.param({"stop": stop_rule(maximum_revisions=0)}, id="stop-rule-tightened"),
    pytest.param({"promotion": promotion_policy(minimum_target_trials=5)}, id="promotion-loosened"),
    pytest.param({"promotion": promotion_policy(minimum_target_trials=99)}, id="promotion-tightened"),
])
def test_a_rule_may_not_change_once_evidence_has_started_arriving(tmp_path, changed):
    """Tightened cases are in this list deliberately. A bar raised partway
    through is still a bar moved in sight of the result."""
    registry = synthetic_registry()
    path = freeze(tmp_path / "registry", registry)
    record(tmp_path, path, 1, datetime(2026, 10, 1, 9, tzinfo=JST))
    bundles = load_trial_bundles(tmp_path / "trials")
    successor = synthetic_registry(registry_version=2, **changed)
    assert rule_digest(successor, successor.hypotheses[0]) != rule_digest(
        registry, registry.hypotheses[0]
    )
    problems = rule_freeze_violations([registry, successor], bundles)
    assert problems, changed
    assert "began gathering evidence" in problems[0]


def test_the_cli_refuses_a_rule_changed_after_the_start(tmp_path):
    directory = tmp_path / "registry"
    registry = synthetic_registry()
    path = freeze(directory, registry)
    record(tmp_path, path, 1, datetime(2026, 10, 1, 9, tzinfo=JST))
    assert verify_rule_freeze_files(directory, tmp_path / "trials")["status"] == "rules_frozen"
    freeze(directory, synthetic_registry(registry_version=2, stop=stop_rule(maximum_revisions=9)),
           clear=False)
    with pytest.raises(ValueError, match="began gathering evidence"):
        verify_rule_freeze_files(directory, tmp_path / "trials")


# --- 4. a new version starts from nothing -----------------------------------

def test_a_new_version_starts_from_no_trials_and_no_start(tmp_path):
    """The way a rule is supposed to change. The old version keeps its trials
    and its rule; the new one has neither."""
    registry = synthetic_registry()
    path = freeze(tmp_path / "registry", registry)
    record(tmp_path, path, 1, datetime(2026, 10, 1, 9, tzinfo=JST))
    bundles = load_trial_bundles(tmp_path / "trials")
    successor = synthetic_registry(
        registry_version=2, hypothesis_version=2, stop=stop_rule(maximum_revisions=9)
    )
    assert rule_freeze_violations([registry, successor], bundles) == []
    assert evaluation_started_at(key(successor), bundles) is None
    snapshot = summarize_trials(successor, [], datetime(2026, 11, 1, tzinfo=JST))
    fresh = snapshot.hypotheses[0]
    assert fresh.hypothesis_version == 2
    assert fresh.prospective_trials == 0
    assert fresh.evaluation_started_at is None


def test_the_status_snapshot_reports_the_start_it_derived(tmp_path):
    """Reported so a reader can see whether the rules are still movable, and
    derived on every snapshot so it cannot disagree with the trials."""
    registry = synthetic_registry()
    path = freeze(tmp_path / "registry", registry)
    at = datetime(2026, 10, 1, 9, tzinfo=JST)
    record(tmp_path, path, 1, at)
    bundles = load_trial_bundles(tmp_path / "trials")
    snapshot = summarize_trials(registry, bundles, datetime(2026, 11, 1, tzinfo=JST))
    assert snapshot.hypotheses[0].evaluation_started_at == at


# --- 5. before the start, the rules are still free --------------------------

def test_a_rule_may_be_changed_and_re_frozen_before_the_first_trial(tmp_path):
    """The boundary, from the other side.

    A definition that has observed nothing cannot have been adjusted in
    response to what it observed. Refusing here would make the first freeze
    final and force a version bump to fix a typo in a threshold, which is not
    what freezing is for.
    """
    directory = tmp_path / "registry"
    registry = synthetic_registry()
    freeze(directory, registry)
    successor = synthetic_registry(registry_version=2, stop=stop_rule(maximum_revisions=9))
    freeze(directory, successor, clear=False)
    assert rule_freeze_violations([registry, successor], []) == []
    assert verify_rule_freeze_files(directory, tmp_path / "trials")["status"] == "rules_frozen"


def test_the_same_change_is_refused_once_one_trial_exists(tmp_path):
    """The two halves of the boundary, in one test, differing only in whether a
    trial was recorded in between."""
    directory = tmp_path / "registry"
    registry = synthetic_registry()
    path = freeze(directory, registry)
    successor = synthetic_registry(registry_version=2, stop=stop_rule(maximum_revisions=9))
    assert rule_freeze_violations([registry, successor], []) == []
    record(tmp_path, path, 1, datetime(2026, 10, 1, 9, tzinfo=JST))
    bundles = load_trial_bundles(tmp_path / "trials")
    assert rule_freeze_violations([registry, successor], bundles)
