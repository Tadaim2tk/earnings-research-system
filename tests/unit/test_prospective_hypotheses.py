import csv
import json
import shutil
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
    HypothesisTrialBundleV1,
)
from earnings_research.prospective_hypotheses.pipeline import (
    build_registry_file,
    evaluate_observation_file,
    load_trial_bundles,
    verify_registry_file,
)
from earnings_research.validation.validator import _calculate_baseline_record_hash, load_spec


ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "outputs/historical_research/research_knowledge.json"
REGISTRY = ROOT / "data/prospective_hypotheses/legacy_research_v1.json"
OBSERVATION = ROOT / "data/samples/prospective_hypothesis_event_sample.json"
SAMPLES = ROOT / "data/samples"
PROSPECTIVE_BASELINE_SAMPLES = SAMPLES / "prospective_baseline"
STAGED_D1 = ROOT / "data/samples/prospective_hypothesis_event_d1_sample.json"
STAGED_D5 = ROOT / "data/samples/prospective_hypothesis_event_d5_sample.json"
STAGED_D20 = ROOT / "data/samples/prospective_hypothesis_event_d20_sample.json"
JST = timezone(timedelta(hours=9))


def _read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path, fieldnames, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def authoritative_dataset(tmp_path):
    dataset = tmp_path / "authoritative-dataset"
    shutil.copytree(SAMPLES, dataset)

    baseline_path = dataset / "pre_earnings_baseline_sample.csv"
    _, baseline_rows = _read_csv(baseline_path)
    fixture_fields, fixture_rows = _read_csv(
        PROSPECTIVE_BASELINE_SAMPLES / "pre_earnings_baseline_sample.csv"
    )
    fixtures_by_id = {row["baseline_id"]: row for row in fixture_rows}
    existing_ids = {row["baseline_id"] for row in baseline_rows}
    normalized = []
    spec = load_spec("pre_earnings_baseline")
    for source in baseline_rows:
        if source["baseline_id"] in fixtures_by_id:
            normalized.append(dict(fixtures_by_id[source["baseline_id"]]))
            continue
        row = {field: source.get(field, "") for field in fixture_fields}
        row.update({
            "baseline_status": "locked",
            "lock_hash_algorithm": "sha256",
            "human_review_status": "approved",
            "reviewed_by": "test-reviewer",
            "reviewed_at": row["locked_at"],
            "recorded_at": row["locked_at"],
        })
        row["baseline_record_hash"] = _calculate_baseline_record_hash(row, spec)
        normalized.append(row)
    normalized.extend(row for row in fixture_rows if row["baseline_id"] not in existing_ids)
    _write_csv(baseline_path, fixture_fields, normalized)

    evidence_path = dataset / "evidence_sample.csv"
    _, evidence_rows = _read_csv(evidence_path)
    evidence_fields, fixture_evidence = _read_csv(
        PROSPECTIVE_BASELINE_SAMPLES / "evidence_sample.csv"
    )
    normalized_evidence = []
    for source in evidence_rows:
        row = {field: source.get(field, "") for field in evidence_fields}
        row.update({
            "evidence_status": "original",
            "content_hash_status": "not_recorded",
            "raw_storage_status": "metadata_only",
            "license_status": "not_applicable",
        })
        normalized_evidence.append(row)
    normalized_evidence.extend(fixture_evidence)
    _write_csv(evidence_path, evidence_fields, normalized_evidence)

    review_path = dataset / "post_earnings_review_sample.csv"
    review_fields, review_rows = _read_csv(review_path)
    for row in review_rows:
        if row["earnings_event_id"] not in {"EVT-ASTER-2026Q1", "EVT-MINATO-2026Q2"}:
            continue
        if row["earnings_event_id"] == "EVT-ASTER-2026Q1":
            row["baseline_id"] = "BASE-ASTER-003"
        row.update({
            "open_gap_pct": "1.0",
            "day1_return_pct": "3.0",
            "day5_return_pct": "6.0",
            "day20_return_pct": "11.0",
            "recorded_at": "2026-09-29T15:30:00+09:00",
        })
    _write_csv(review_path, review_fields, review_rows)
    return dataset


@pytest.fixture
def market_reactions(tmp_path):
    def write_tracking(name, tracking_id, event_id, company_name, ticker, announcement):
        path = tmp_path / f"{name}-market-reaction.json"
        payload = {
            "schema_version": "market_reaction_tracking_v1",
            "tracking_id": tracking_id,
            "earnings_event_id": event_id,
            "evaluation_id": f"EVAL-{name.upper()}-HYP",
            "company_name": company_name,
            "ticker": ticker,
            "currency": "JPY",
            "status": "complete",
            "announcement_datetime": announcement,
            "announcement_session": "after_close",
            "calendar_name": "verified-test-calendar",
            "corporate_action_status": "none_detected",
            "milestones": [
                {"role": "pre_event_close", "status": "observed", "expected_trading_date": "2026-08-07", "note": "verified"},
                {"role": "immediate_post_announcement", "status": "observed", "expected_trading_date": "2026-08-08", "return_from_pre_event_close_pct": 1.0, "note": "verified"},
                {"role": "next_business_day_close", "status": "observed", "expected_trading_date": "2026-09-01", "price_datetime": "2026-09-01T15:30:00+09:00", "return_from_pre_event_close_pct": 3.0, "note": "verified"},
                {"role": "fifth_business_day_close", "status": "observed", "expected_trading_date": "2026-09-07", "price_datetime": "2026-09-07T15:30:00+09:00", "return_from_pre_event_close_pct": 6.0, "note": "verified"},
            ],
            "event_window_reaction": {
                "status": "calculated",
                "reference_role": "pre_event_close",
                "return_pct": 1.0,
                "calculation_origin": "ers_calculated",
                "formula": "verified",
                "note": "verified",
            },
            "summary": {
                "immediate_direction": "positive",
                "next_business_day_direction": "positive",
                "fifth_business_day_direction": "positive",
                "reaction_path": "extended",
                "explanation": "verified",
            },
            "warnings": [],
            "completed_at": "2026-09-07T15:30:00+09:00",
            "raw_price_data_retained": False,
            "trade_decision_included": False,
            "next_stage": "ready_for_post_event_validation",
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    return {
        "aster": write_tracking(
            "aster", "MRT-ASTER-HYP", "EVT-ASTER-2026Q1", "Aster Cloud Works", "ASTR",
            "2026-08-08T15:30:00+09:00",
        ),
        "minato": write_tracking(
            "minato", "MRT-MINATO-HYP", "EVT-MINATO-2026Q2", "Minato Legacy Retail", "MNTO",
            "2026-08-12T15:00:00+09:00",
        ),
    }


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
    payload["pre_event_features"]["locked_at"] = "2026-08-31T16:30:00+09:00"
    with pytest.raises(ValidationError, match="before the event"):
        CompletedEventObservation.model_validate(payload)
    payload = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    payload["pre_event_features"]["locked_at"] = "2026-08-31T16:00:00+09:00"
    with pytest.raises(ValidationError, match="baseline must be locked before"):
        CompletedEventObservation.model_validate(payload)


def test_completed_event_creates_target_and_overall_comparison_trials():
    bundle = evaluate_observation(
        registry(), observation(), datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    assert len(bundle.trials) == 14
    assert sum(item.reason == "required_pre_event_field_missing" for item in bundle.hypothesis_eligibility) == 5
    assert {item.phase for item in bundle.trials} == {"pre_event", "post_event"}
    assert all(item.evaluation_horizon in {"D5", "D20"} for item in bundle.trials)
    gu_d5 = next(
        item for item in bundle.trials
        if item.observed_dimension == "reaction" and item.observed_value == "GU継続"
        and item.evaluation_horizon == "D5" and item.cohort == "target"
    )
    assert gu_d5.individual_outcome == "success"


def test_missing_or_noncomparable_horizon_is_not_counted_as_failure():
    payload = json.loads(STAGED_D5.read_text(encoding="utf-8"))
    bundle = evaluate_observation(
        registry(),
        CompletedEventObservation.model_validate(payload),
        datetime(2026, 9, 7, 18, tzinfo=JST),
    )
    assert all(item.evaluation_horizon == "D5" for item in bundle.trials)
    assert any(item.reason == "horizon_not_matured" for item in bundle.hypothesis_eligibility)
    judge_results = [
        item for item in bundle.hypothesis_eligibility
        if next(h for h in registry().hypotheses if h.hypothesis_id == item.hypothesis_id).dimension == "judge"
    ]
    assert judge_results
    assert all(item.eligible_for_hypothesis is False for item in judge_results)
    assert all(item.reason == "required_pre_event_field_missing" for item in judge_results)


def test_append_only_writer_rejects_existing_output_and_same_stage_replay(tmp_path, authoritative_dataset, market_reactions):
    trials = tmp_path / "trials"
    output = trials / "event-d20.json"
    evaluate_observation_file(
        REGISTRY, OBSERVATION, trials, output, datetime(2026, 9, 30, 18, tzinfo=JST), authoritative_dataset, market_reactions["minato"]
    )
    with pytest.raises(ValueError, match="increment by one"):
        evaluate_observation_file(
            REGISTRY, OBSERVATION, trials, output, datetime(2026, 9, 30, 19, tzinfo=JST), authoritative_dataset, market_reactions["minato"]
        )
    other = json.loads(STAGED_D1.read_text(encoding="utf-8"))
    other_path = tmp_path / "other.json"
    other_path.write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FileExistsError, match="already"):
        evaluate_observation_file(
            REGISTRY, other_path, trials, output, datetime(2026, 9, 30, 19, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
        )
    replay = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    replay["observation_id"] = "HPO-FICTIONAL-REPLAY"
    replay["observation_version"] = 2
    replay["supersedes_observation_id"] = "HPO-FICTIONAL-2026-Q1"
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="horizon must advance"):
        evaluate_observation_file(
            REGISTRY, replay_path, trials, trials / "replay.json", datetime(2026, 10, 1, 18, tzinfo=JST), authoritative_dataset, market_reactions["minato"]
        )


def test_d1_d5_d20_stages_append_only_new_horizons(tmp_path, authoritative_dataset, market_reactions):
    trials = tmp_path / "trials"
    d1 = evaluate_observation_file(
        REGISTRY, STAGED_D1, trials, trials / "01-d1.json", datetime(2026, 9, 1, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
    )
    assert d1.trials == []
    d5 = evaluate_observation_file(
        REGISTRY, STAGED_D5, trials, trials / "02-d5.json", datetime(2026, 9, 7, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
    )
    assert d5.trials
    assert {item.evaluation_horizon for item in d5.trials} == {"D5"}
    d20 = evaluate_observation_file(
        REGISTRY, STAGED_D20, trials, trials / "03-d20.json", datetime(2026, 9, 30, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
    )
    assert d20.trials
    assert {item.evaluation_horizon for item in d20.trials} == {"D20"}
    assert any(item.reason == "trial_already_recorded" for item in d20.hypothesis_eligibility)
    snapshot = summarize_trials(
        registry(), [d1, d5, d20], datetime(2026, 10, 1, 9, tzinfo=JST)
    )
    assert snapshot.source_trial_bundle_count == 3
    assert sum(item.comparator_observations for item in snapshot.hypotheses) == len(d5.trials) + len(d20.trials)
    duplicated = d20.model_copy(deep=True)
    duplicated.trials.append(d5.trials[0])
    with pytest.raises(ValueError, match="duplicate append-only"):
        summarize_trials(
            registry(), [d1, d5, duplicated], datetime(2026, 10, 1, 10, tzinfo=JST)
        )


def test_staged_observation_cannot_rewrite_pre_event_or_matured_return(tmp_path, authoritative_dataset, market_reactions):
    for field, expected in (("pre_event", "frozen pre-event"), ("return", "authoritative source")):
        trials = tmp_path / field
        evaluate_observation_file(
            REGISTRY, STAGED_D1, trials, trials / "01-d1.json", datetime(2026, 9, 1, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
        )
        changed = json.loads(STAGED_D5.read_text(encoding="utf-8"))
        if field == "pre_event":
            changed["pre_event_features"]["captured_at"] = "2026-08-07T20:59:00+09:00"
        else:
            changed["returns"][0]["return_value"] = -0.25
        changed_path = tmp_path / f"changed-{field}.json"
        changed_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match=expected):
            evaluate_observation_file(
                REGISTRY,
                changed_path,
                trials,
                trials / "02-d5.json",
                datetime(2026, 9, 7, 18, tzinfo=JST),
                authoritative_dataset,
                market_reactions["aster"],
            )


def test_not_comparable_horizon_is_structured_and_not_a_failure():
    payload = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    d20 = next(item for item in payload["returns"] if item["horizon"] == "D20")
    d20["status"] = "not_comparable"
    d20["return_value"] = None
    bundle = evaluate_observation(
        registry(),
        CompletedEventObservation.model_validate(payload),
        datetime(2026, 9, 30, 18, tzinfo=JST),
    )
    assert all(item.evaluation_horizon == "D5" for item in bundle.trials)
    d20_results = [
        item for item in bundle.hypothesis_eligibility
        if item.evaluation_horizon == "D20"
    ]
    assert d20_results
    assert all(item.eligible_for_hypothesis is False for item in d20_results)
    assert any(item.reason == "horizon_not_comparable" for item in d20_results)
    assert all(
        item.reason in {"horizon_not_comparable", "required_pre_event_field_missing"}
        for item in d20_results
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
    first = evaluate_observation(
        registry(), observation(), datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    second = first.model_copy(deep=True)
    second.observation_id = "HPO-FICTIONAL-DUPLICATE"
    second.observation_version = 2
    second.supersedes_observation_id = first.observation_id
    second.observation_stage = "D20"
    with pytest.raises(ValueError, match="horizon did not advance"):
        summarize_trials(registry(), [first, second], datetime(2026, 10, 1, 12, tzinfo=JST))


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
    changed_eligibility = bundle.model_copy(deep=True)
    eligible = next(item for item in changed_eligibility.hypothesis_eligibility if item.eligible_for_hypothesis)
    other = next(
        item for item in changed_eligibility.hypothesis_eligibility
        if item.eligible_for_hypothesis and item.hypothesis_id != eligible.hypothesis_id
    )
    eligible.appended_trial_id, other.appended_trial_id = other.appended_trial_id, eligible.appended_trial_id
    with pytest.raises(ValueError, match="different hypothesis trial"):
        summarize_trials(registry(), [changed_eligibility], datetime(2026, 10, 1, 12, tzinfo=JST))


def test_status_recomputation_cannot_predate_appended_trials():
    bundle = evaluate_observation(
        registry(), observation(), datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    with pytest.raises(ValueError, match="before its source trial"):
        summarize_trials(registry(), [bundle], datetime(2026, 9, 30, 17, 59, tzinfo=JST))


def test_contract_schemas_accept_committed_registry_and_sample():
    pairs = [
        ("prospective_hypothesis_registry.schema.json", json.loads(REGISTRY.read_text(encoding="utf-8"))),
        ("prospective_hypothesis_event_observation.schema.json", json.loads(OBSERVATION.read_text(encoding="utf-8"))),
        ("prospective_hypothesis_event_observation.schema.json", json.loads(STAGED_D1.read_text(encoding="utf-8"))),
        ("prospective_hypothesis_event_observation.schema.json", json.loads(STAGED_D5.read_text(encoding="utf-8"))),
        ("prospective_hypothesis_event_observation.schema.json", json.loads(STAGED_D20.read_text(encoding="utf-8"))),
    ]
    for schema_name, instance in pairs:
        schema = json.loads((ROOT / "schemas/analysis" / schema_name).read_text(encoding="utf-8"))
        jsonschema.validate(instance, schema)


def test_json_schema_rejects_v2_observation_without_predecessor():
    schema = json.loads(
        (ROOT / "schemas/analysis/prospective_hypothesis_event_observation.schema.json")
        .read_text(encoding="utf-8")
    )
    payload = json.loads(STAGED_D5.read_text(encoding="utf-8"))
    payload["supersedes_observation_id"] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
    payload.pop("supersedes_observation_id")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_json_schema_rejects_missing_stage_return_and_future_horizon():
    schema = json.loads(
        (ROOT / "schemas/analysis/prospective_hypothesis_event_observation.schema.json")
        .read_text(encoding="utf-8")
    )
    payload = json.loads(STAGED_D20.read_text(encoding="utf-8"))
    payload["returns"] = [item for item in payload["returns"] if item["horizon"] == "D1"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
    payload = json.loads(STAGED_D5.read_text(encoding="utf-8"))
    duplicate = dict(payload["returns"][0])
    duplicate["source_record_id"] = "MRT-DUPLICATE-D1"
    payload["returns"].append(duplicate)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
    payload = json.loads(STAGED_D1.read_text(encoding="utf-8"))
    payload["returns"].append(
        next(item for item in json.loads(STAGED_D5.read_text(encoding="utf-8"))["returns"] if item["horizon"] == "D5")
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_append_rejects_unresolved_or_tampered_authoritative_baseline(tmp_path, authoritative_dataset, market_reactions):
    trials = tmp_path / "trials"
    payload = json.loads(STAGED_D1.read_text(encoding="utf-8"))
    payload["pre_event_features"]["baseline_id"] = "BASE-NOT-FOUND"
    payload["source_record_ids"][0] = "BASE-NOT-FOUND"
    observation_path = tmp_path / "missing-baseline.json"
    observation_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="resolve to exactly one"):
        evaluate_observation_file(
            REGISTRY,
            observation_path,
            trials,
            trials / "missing.json",
            datetime(2026, 9, 1, 18, tzinfo=JST),
            authoritative_dataset,
            market_reactions["aster"],
        )
    changed_dataset = tmp_path / "tampered-dataset"
    shutil.copytree(authoritative_dataset, changed_dataset)
    changed_baseline = changed_dataset / "pre_earnings_baseline_sample.csv"
    baseline_rows = list(csv.DictReader(changed_baseline.open(encoding="utf-8")))
    baseline_rows[2]["baseline_record_hash"] = "0" * 64
    with changed_baseline.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=baseline_rows[0].keys())
        writer.writeheader()
        writer.writerows(baseline_rows)
    with pytest.raises(ValueError, match="authoritative dataset validation failed"):
        evaluate_observation_file(
            REGISTRY,
            STAGED_D1,
            trials,
            trials / "tampered.json",
            datetime(2026, 9, 1, 18, tzinfo=JST),
            changed_dataset,
            market_reactions["aster"],
        )


def test_append_requires_complete_dataset_and_current_baseline_tail(tmp_path, authoritative_dataset, market_reactions):
    incomplete = tmp_path / "incomplete-dataset"
    incomplete.mkdir()
    shutil.copy2(
        authoritative_dataset / "pre_earnings_baseline_sample.csv",
        incomplete / "pre_earnings_baseline_sample.csv",
    )
    with pytest.raises(ValueError, match="authoritative dataset validation failed"):
        evaluate_observation_file(
            REGISTRY,
            STAGED_D1,
            tmp_path / "incomplete-trials",
            tmp_path / "incomplete.json",
                datetime(2026, 9, 1, 18, tzinfo=JST),
                incomplete,
                market_reactions["aster"],
        )

    payload = json.loads(STAGED_D1.read_text(encoding="utf-8"))
    _, baseline_rows = _read_csv(authoritative_dataset / "pre_earnings_baseline_sample.csv")
    superseded = next(row for row in baseline_rows if row["baseline_id"] == "BASE-ASTER-001")
    payload["pre_event_features"].update({
        "baseline_id": superseded["baseline_id"],
        "baseline_version": 1,
        "baseline_record_hash": superseded["baseline_record_hash"],
        "captured_at": superseded["as_of_datetime"],
        "locked_at": superseded["locked_at"],
    })
    payload["source_record_ids"][0] = superseded["baseline_id"]
    superseded_observation = tmp_path / "superseded-observation.json"
    superseded_observation.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="current prospective baseline tail"):
        evaluate_observation_file(
            REGISTRY,
            superseded_observation,
            tmp_path / "superseded-trials",
            tmp_path / "superseded.json",
            datetime(2026, 9, 1, 18, tzinfo=JST),
            authoritative_dataset,
            market_reactions["aster"],
        )


@pytest.mark.parametrize(
    "field", ["reaction", "return_value", "observed_at", "source_record_id", "d20_return_value"]
)
def test_append_rejects_tampered_post_event_outcomes(
    tmp_path, authoritative_dataset, market_reactions, field
):
    source = STAGED_D20 if field == "d20_return_value" else STAGED_D5
    payload = json.loads(source.read_text(encoding="utf-8"))
    if field == "reaction":
        payload["post_event_features"]["reaction"] = "GU失速"
        expected = "reaction does not match"
    elif field == "return_value":
        payload["returns"][0][field] = 0.99
        expected = "return does not match"
    elif field == "observed_at":
        payload["returns"][0][field] = "2026-09-02T15:30:00+09:00"
        expected = "observed_at does not match"
    elif field == "d20_return_value":
        next(item for item in payload["returns"] if item["horizon"] == "D20")["return_value"] = 0.99
        expected = "D20 return does not match"
    else:
        payload["returns"][0][field] = "MRT-FABRICATED"
        expected = "must reference market reaction tracking_id"
    path = tmp_path / f"tampered-{field}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        evaluate_observation_file(
            REGISTRY,
            path,
            tmp_path / f"trials-{field}",
            tmp_path / f"trial-{field}.json",
            datetime(2026, 9, 7, 18, tzinfo=JST),
            authoritative_dataset,
            market_reactions["aster"],
        )


def test_v1_trial_bundle_remains_readable_and_counted(tmp_path, authoritative_dataset, market_reactions):
    generated = evaluate_observation(
        registry(), observation(), datetime(2026, 9, 30, 18, tzinfo=JST)
    )
    legacy = HypothesisTrialBundleV1(
        registry_id=generated.registry_id,
        registry_version=generated.registry_version,
        registry_sha256=generated.registry_sha256,
        observation_id=generated.observation_id,
        earnings_event_id=generated.earnings_event_id,
        recorded_at=generated.recorded_at,
        trials=generated.trials,
        ineligible_hypotheses={},
    )
    trials = tmp_path / "trials"
    trials.mkdir()
    (trials / "legacy-v1.json").write_text(
        json.dumps(legacy.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = load_trial_bundles(trials)
    snapshot = summarize_trials(
        registry(), loaded, datetime(2026, 10, 1, 9, tzinfo=JST)
    )
    assert snapshot.source_trial_bundle_count == 1
    assert sum(item.comparator_observations for item in snapshot.hypotheses) == 14
    evaluate_observation_file(
        REGISTRY,
        STAGED_D1,
        trials,
        trials / "staged-d1.json",
        datetime(2026, 10, 1, 18, tzinfo=JST),
        authoritative_dataset,
        market_reactions["aster"],
    )
    assert len(load_trial_bundles(trials)) == 2
    v1_schema = json.loads(
        (ROOT / "schemas/analysis/prospective_hypothesis_trial_bundle_v1.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.validate(legacy.model_dump(mode="json"), v1_schema)


def test_cli_verifies_registry_and_builds_append_only_outputs(tmp_path, authoritative_dataset, market_reactions):
    assert main([
        "verify-hypothesis-registry", "--knowledge", str(KNOWLEDGE), "--registry", str(REGISTRY)
    ]) == 0
    trials = tmp_path / "trials"
    output = trials / "event.json"
    summary = tmp_path / "status.json"
    assert main([
        "evaluate-hypothesis-event",
        "--registry", str(REGISTRY),
        "--observation", str(OBSERVATION),
        "--dataset", str(authoritative_dataset),
        "--market-reaction", str(market_reactions["minato"]),
        "--trials-dir", str(trials),
        "--recorded-at", "2026-09-30T18:00:00+09:00",
        "--evaluated-at", "2026-10-01T09:00:00+09:00",
        "--output", str(output),
        "--status-output", str(summary),
    ]) == 0
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert len(result["hypotheses"]) == 19
    assert result["automatic_weight_change"] is False
