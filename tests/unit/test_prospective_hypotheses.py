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
    _write_new,
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


def cleared_registry(tmp_path):
    """確定済みの全19件を、source-validity gate が通す形で置き直す。

    `usable_registry` は先頭3件だけを残すので、段階評価の観測が参照する仮説が
    落ちて別の理由で失敗する。段階評価の試験が確かめたいのは**正本との突合と
    版の連鎖**であって、gate ではない。gate 自体は
    `test_no_trial_is_recorded_against_knowledge_nobody_has_judged` が見ている。

    **gate を回避しているのではない。** 台帳を書いて通す形にしているだけで、
    台帳が無ければこの補助を使っても拒まれる。
    """
    from earnings_research.prospective_hypotheses.source_validity import (
        VALID, Verdict, append_ledger, source_fields_digest,
    )
    from earnings_research.statistics.lookahead import rules_digest

    base = HypothesisRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    directory = tmp_path / "cleared-registry"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "registry.json"
    path.write_text(base.model_dump_json(indent=2), encoding="utf-8")
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
        for item in base.hypotheses
    ])
    return path


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
        cleared_registry(tmp_path), OBSERVATION, trials, output, datetime(2026, 9, 30, 18, tzinfo=JST), authoritative_dataset, market_reactions["minato"]
    )
    with pytest.raises(ValueError, match="increment by one"):
        evaluate_observation_file(
            cleared_registry(tmp_path), OBSERVATION, trials, output, datetime(2026, 9, 30, 19, tzinfo=JST), authoritative_dataset, market_reactions["minato"]
        )
    other = json.loads(STAGED_D1.read_text(encoding="utf-8"))
    other_path = tmp_path / "other.json"
    other_path.write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FileExistsError, match="already"):
        evaluate_observation_file(
            cleared_registry(tmp_path), other_path, trials, output, datetime(2026, 9, 30, 19, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
        )
    replay = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    replay["observation_id"] = "HPO-FICTIONAL-REPLAY"
    replay["observation_version"] = 2
    replay["supersedes_observation_id"] = "HPO-FICTIONAL-2026-Q1"
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="horizon must advance"):
        evaluate_observation_file(
            cleared_registry(tmp_path), replay_path, trials, trials / "replay.json", datetime(2026, 10, 1, 18, tzinfo=JST), authoritative_dataset, market_reactions["minato"]
        )


def test_d1_d5_d20_stages_append_only_new_horizons(tmp_path, authoritative_dataset, market_reactions):
    trials = tmp_path / "trials"
    d1 = evaluate_observation_file(
        cleared_registry(tmp_path), STAGED_D1, trials, trials / "01-d1.json", datetime(2026, 9, 1, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
    )
    assert d1.trials == []
    d5 = evaluate_observation_file(
        cleared_registry(tmp_path), STAGED_D5, trials, trials / "02-d5.json", datetime(2026, 9, 7, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
    )
    assert d5.trials
    assert {item.evaluation_horizon for item in d5.trials} == {"D5"}
    d20 = evaluate_observation_file(
        cleared_registry(tmp_path), STAGED_D20, trials, trials / "03-d20.json", datetime(2026, 9, 30, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
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
            cleared_registry(tmp_path), STAGED_D1, trials, trials / "01-d1.json", datetime(2026, 9, 1, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"]
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
                cleared_registry(tmp_path),
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
    # **「未成熟」はここでは出ない。** v2 は「まだ値が無い」(`horizon_not_matured`)
    # と「値はあるが比較できない」(`horizon_not_comparable`) を分けた。旧実装は
    # 自由文の辞書 `ineligible_hypotheses` で両方を「evaluation horizon has not
    # matured」と書いていて、母数外の理由を機械で集計できなかった。この試験は
    # D20 を `not_comparable` に置いているので、後者だけが立つ。前者は
    # `test_a_horizon_with_no_value_yet_is_not_matured_rather_than_not_comparable`
    # が見る。**旧検査を消したのではなく、2つに割った。**


def test_a_horizon_with_no_value_yet_is_not_matured_rather_than_not_comparable():
    """値がまだ無いことを「比較できない」と書かない。

    旧実装は両方を同じ自由文にしていた。区別が要るのは、**片方は待てば埋まり、
    もう片方は待っても埋まらない**からである。混ぜると、いつ再評価すべきかが
    記録から読めなくなる。
    """
    # D5段階の観測は D20 をまだ持たない。**空にするのではなく、実際に
    # まだ来ていない段階を使う**——モデルは「その段階に必要な期間」を要求する
    # ので、D20段階から D20 を抜くと観測自体が不正になる。
    bundle = evaluate_observation(
        registry(),
        CompletedEventObservation.model_validate_json(STAGED_D5.read_text(encoding="utf-8")),
        datetime(2026, 9, 30, 18, tzinfo=JST),
    )
    d20 = [item for item in bundle.hypothesis_eligibility if item.evaluation_horizon == "D20"]
    assert d20
    assert any(item.reason == "horizon_not_matured" for item in d20)
    assert not any(item.reason == "horizon_not_comparable" for item in d20)


def test_the_same_event_may_not_be_recorded_twice_under_another_name(tmp_path, authoritative_dataset, market_reactions):
    """Written to a different output path on purpose.

    The earlier form of this test reused one path and accepted either error, so
    `_write_new` refusing the filename satisfied it and the event-level scan it
    was named for could be — and was — deleted without the suite noticing. The
    scan is what protects an append-only record: a second bundle for one event
    is what `summarize_trials` afterwards fails on.

    **段階評価の導入で、その走査は版の連鎖へ移った。** D1 → D5 → D20 は同じ
    イベントに複数の bundle を持つことが目的なので、イベント名だけで2本目を
    拒む走査は使えない。代わりに `_validate_observation_chain` が「次の版で
    なければ拒む」を強制する。**保護は緩んでいない**——同じ観測をもう一度
    書けば、いまも拒まれる。移った先を確かめるため、メッセージを固定する。
    どちらのエラーでも通る書き方には戻さない（それがこの試験の由来である）。
    """
    path, _count = usable_registry(tmp_path)
    trials = tmp_path / "trials"
    evaluate_observation_file(
        path, OBSERVATION, trials, trials / "first.json", datetime(2026, 9, 30, 18, tzinfo=JST),
        authoritative_dataset, market_reactions["minato"],
    )
    with pytest.raises(ValueError, match="staged observation version must increment by one"):
        evaluate_observation_file(
            path, OBSERVATION, trials, trials / "second.json",
            datetime(2026, 9, 30, 19, tzinfo=JST),
        authoritative_dataset, market_reactions["minato"],
    )
    assert sorted(item.name for item in trials.glob("*.json")) == ["first.json"]


def test_an_existing_output_file_is_never_overwritten(tmp_path, authoritative_dataset, market_reactions):
    """The other half of what one test used to claim: the writer refuses the
    filename even where the event-level scan has nothing to say."""
    path, _count = usable_registry(tmp_path)
    trials = tmp_path / "trials"
    output = trials / "event.json"
    evaluate_observation_file(
        path, OBSERVATION, trials, output, datetime(2026, 9, 30, 18, tzinfo=JST),
        authoritative_dataset, market_reactions["minato"],
    )
    before = output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="append-only output already exists"):
        _write_new(output, "{}\n")
    assert output.read_text(encoding="utf-8") == before


def test_no_trial_is_recorded_against_knowledge_the_rules_condemn(tmp_path, authoritative_dataset, market_reactions):
    """The committed registry is seventeen-nineteenths invalid under the rules
    as they stand, and recording trials against it would be gathering evidence
    about hypotheses whose evidence the rules no longer support."""
    with pytest.raises(ValueError, match="source-validity"):
        evaluate_observation_file(
            REGISTRY, OBSERVATION, tmp_path / "trials", tmp_path / "trials/event.json",
            datetime(2026, 9, 30, 18, tzinfo=JST),
        authoritative_dataset, market_reactions["minato"],
    )


def test_no_trial_is_recorded_against_knowledge_nobody_has_judged(tmp_path, authoritative_dataset, market_reactions):
    """Unjudged is refused too. A definition nobody has checked under the
    current rules is the case this capability exists for."""
    path, _count = usable_registry(tmp_path)
    (path.parent / "source_validity.jsonl").unlink()
    with pytest.raises(ValueError, match="source-validity"):
        evaluate_observation_file(
            path, OBSERVATION, tmp_path / "trials", tmp_path / "trials/event.json",
            datetime(2026, 9, 30, 18, tzinfo=JST),
        authoritative_dataset, market_reactions["minato"],
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
            cleared_registry(tmp_path),
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
            cleared_registry(tmp_path),
            STAGED_D1,
            trials,
            trials / "tampered.json",
            datetime(2026, 9, 1, 18, tzinfo=JST),
            changed_dataset,
            market_reactions["aster"]
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
            cleared_registry(tmp_path),
            STAGED_D1,
            tmp_path / "incomplete-trials",
            tmp_path / "incomplete.json",
                datetime(2026, 9, 1, 18, tzinfo=JST),
                incomplete,
                market_reactions["aster"]
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
            cleared_registry(tmp_path),
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
            cleared_registry(tmp_path),
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
        cleared_registry(tmp_path),
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
    path, count = usable_registry(tmp_path)
    trials = tmp_path / "trials"
    output = trials / "event.json"
    summary = tmp_path / "status.json"
    assert main([
        "evaluate-hypothesis-event",
        "--registry", str(path),
        "--observation", str(OBSERVATION),
        "--dataset", str(authoritative_dataset),
        "--market-reaction", str(market_reactions["minato"]),
        "--trials-dir", str(trials),
        "--recorded-at", "2026-09-30T18:00:00+09:00",
        # 段階評価では、追記と全trialからのstatus再計算を一度に行う。
        # 分けると、追記だけ済んで status が古いままの状態が作れてしまう。
        "--evaluated-at", "2026-09-30T18:05:00+09:00",
        "--output", str(output),
        "--status-output", str(summary),
    ]) == 0
    # 追記した status をそのまま読む。段階評価の CLI が `--status-output` に
    # 書くので、集計を別に走らせ直さない。**別に走らせると、追記時の status と
    # 後から作った status のどちらが正かが曖昧になる。**
    # `summarize-hypothesis-registry` は独立した集計として残っており、
    # `--status-output` は取らない（そちらは `--output` に書く）。
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


def test_a_stop_rule_carries_no_notion_of_being_strict_enough():
    """`at_least_as_strict_as` is gone, and nothing may put it back.

    It licensed changing a rule partway through, on the argument that a
    stricter bar is a safe one. It is not: "the bar went up and it still
    passed" is a different experiment from the one registered, and this
    comparison cannot tell that apart from a bar moved to fit the answer. Once
    trials exist a rule is fixed outright — see tests/unit/test_freeze.py.
    """
    assert not hasattr(stop_rule(), "at_least_as_strict_as")


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


def superseding(stop_rule, version=2, bump=1):
    """A successor registry carrying one hypothesis.

    `bump` is how far the hypothesis version moves, because that is now the
    thing under test: a changed rule is permitted only where the version moved
    with it.
    """
    from earnings_research.prospective_hypotheses.models import HypothesisRegistry

    base = registry()
    definition = base.hypotheses[0].model_copy(deep=True)
    definition.hypothesis_version += bump
    definition.assessment_rule = definition.assessment_rule.model_copy(
        update={"stop_rule": stop_rule}
    )
    payload = base.model_dump()
    payload["registry_version"] = version
    payload["hypotheses"] = [definition.model_dump()]
    payload["source_candidate_count"] = 1
    return HypothesisRegistry.model_validate(payload)


def test_a_successor_may_not_drop_the_stop_rule_it_inherited():
    """Not a question about freezing, which is why it is decided here.

    A hypothesis with no abandonment condition can never be wrong, whether or
    not it has started gathering evidence, so this holds unconditionally and
    needs no trial record to decide.
    """
    from earnings_research.prospective_hypotheses.evaluator import successor_registry_problems

    frozen = superseding(stop_rule(maximum_revisions=1), version=1)
    assert successor_registry_problems(frozen, superseding(None))
    assert successor_registry_problems(frozen, superseding(stop_rule(maximum_revisions=1))) == []


def test_whether_a_rule_changed_is_not_decided_from_two_files(tmp_path):
    """Deliberately deferred, and it was briefly decided here by mistake.

    This function sees two registries and no trials, so it cannot tell a change
    made before any evidence arrived — permitted, and how a rule is meant to be
    corrected — from one made after. Deciding it here made the permitted path
    impossible to merge: CI runs this on every registry change and rejected the
    pre-start edit that `verify-rule-freeze` explicitly allows.

    Both directions are listed so that restoring either verdict fails.
    """
    from earnings_research.prospective_hypotheses.evaluator import successor_registry_problems

    frozen = superseding(stop_rule(maximum_revisions=1), version=1)
    for changed in (stop_rule(maximum_revisions=9), stop_rule(maximum_revisions=0)):
        assert successor_registry_problems(frozen, superseding(changed)) == []
        assert successor_registry_problems(frozen, superseding(changed, bump=2)) == []


def _written(tmp_path, name, registry):
    path = tmp_path / name
    path.write_text(registry.model_dump_json(), encoding="utf-8")
    return path


def test_the_cli_refuses_a_successor_that_drops_a_rule_and_permits_one_that_changes_it(
    tmp_path, capsys
):
    """The check a version bump has to pass, reachable from CI.

    The permitted case is in here on purpose: a rule change has to exit 0 from
    this command, because CI runs it on every registry change and a pre-start
    correction would otherwise be unmergeable.
    """
    earlier = _written(tmp_path, "v1.json", superseding(stop_rule(maximum_revisions=1), version=1))
    dropped = _written(tmp_path, "v2.json", superseding(None))
    changed = _written(tmp_path, "v2b.json", superseding(stop_rule(maximum_revisions=9)))
    assert main([
        "verify-successor-registry",
        "--previous-registry", str(earlier),
        "--registry", str(dropped),
    ]) == 1
    assert "drops the stop rule" in capsys.readouterr().err
    assert main([
        "verify-successor-registry",
        "--previous-registry", str(earlier),
        "--registry", str(changed),
    ]) == 0


def test_a_successor_may_not_quietly_drop_an_inherited_stop_rule(tmp_path):
    from earnings_research.prospective_hypotheses.models import StopRule
    from earnings_research.prospective_hypotheses.pipeline import verify_successor_registry

    earlier = _written(tmp_path, "v1.json", superseding(stop_rule(), version=1))
    dropped = _written(tmp_path, "v2.json", superseding(None))
    with pytest.raises(ValueError, match="drops the stop rule"):
        verify_successor_registry(earlier, dropped)


def test_a_registry_that_is_not_a_successor_is_refused(tmp_path):
    from earnings_research.prospective_hypotheses.models import StopRule
    from earnings_research.prospective_hypotheses.pipeline import verify_successor_registry

    same = superseding(stop_rule(), version=1)
    with pytest.raises(ValueError, match="earlier registry_version"):
        verify_successor_registry(
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
    from earnings_research.prospective_hypotheses.evaluator import successor_registry_problems
    from earnings_research.prospective_hypotheses.models import HypothesisRegistry

    previous = superseding(stop_rule(), version=1)
    replaced = previous.model_dump()
    replaced["registry_version"] = 2
    # A successor that keeps a hypothesis, but not the one that carried a rule.
    replaced["hypotheses"][0]["hypothesis_id"] = "LRH-SOMETHING-NEW"
    problems = successor_registry_problems(previous, HypothesisRegistry.model_validate(replaced))
    assert any("was dropped" in problem for problem in problems)


def test_an_unrelated_registry_is_not_a_successor():
    """Only the version numbers were compared, so a registry sharing no
    identifiers at all passed by having a larger number."""
    from earnings_research.prospective_hypotheses.evaluator import successor_registry_problems

    previous = superseding(stop_rule(), version=1)
    stranger = superseding(stop_rule(stop_when_halves_reverse=False), version=9)
    stranger.registry_id = "SOMETHING-ELSE"
    problems = successor_registry_problems(previous, stranger)
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


# --- 起点をまたいで比べない -------------------------------------------------

def test_a_reaction_is_not_labelled_when_the_two_numbers_share_no_basis(market_reactions):
    """**場中発表で符号が反転する。**

    `event_window_reaction` は発表直前価格を起点にすることがあり、翌営業日は
    前日終値起点である。例: 前日終値100、発表直前120、直後126、翌日終値110。
    直後は「発表直前から+5%」、翌日は「前日終値から+10%」となり、**急落した
    のに `GU継続` と付く**。起点が違うなら判定しない。
    """
    from earnings_research.market_reaction.models import MarketReactionTracking
    from earnings_research.prospective_hypotheses import pipeline as P
    tracking = MarketReactionTracking.model_validate_json(
        market_reactions["aster"].read_text(encoding="utf-8")
    )
    assert tracking.event_window_reaction.reference_role == P.REACTION_REFERENCE_ROLE
    labelled = P._reaction_label(tracking)
    assert labelled is not None

    shifted = tracking.model_copy(deep=True)
    shifted.event_window_reaction.reference_role = "pre_announcement_reference"
    assert P._reaction_label(shifted) is None, "起点が違えば判定しない"


def test_a_d20_return_measured_from_another_price_is_refused(
    tmp_path, authoritative_dataset, market_reactions
):
    """**イベントが宣言した起点と食い違う値を受け入れない。**

    起点を選び直すだけで仮説の判定が変わる。ただし「どの起点が正しいか」は
    実装が決めることではない——`docs/RETURN_BASE_PRICE_POLICY.md` が発表
    セッションごとに承認しており、`earnings_event.return_base_price_policy` が
    イベント単位でそれを記録する。最初の実装は `previous_close` を無条件に
    要求し、**決算の大半を占める `after_close`（承認済みは `next_open`）を
    塞いでいた。**
    """
    # イベントは `next_open` を宣言している（after_close の承認済み方針）。
    # そこに `vwap_after_announcement` を書けば食い違う。
    review_path = authoritative_dataset / "post_earnings_review_sample.csv"
    fields, rows = _read_csv(review_path)
    for row in rows:
        if row.get("day20_return_pct", "").strip():
            row["return_reference_price_type"] = "vwap_after_announcement"
    _write_csv(review_path, fields, rows)
    with pytest.raises(ValueError, match="but the event declares next_open"):
        evaluate_observation_file(
            cleared_registry(tmp_path), STAGED_D20, tmp_path / "basis-trials",
            tmp_path / "basis.json", datetime(2026, 10, 1, 18, tzinfo=JST),
            authoritative_dataset, market_reactions["aster"],
        )


def test_a_d20_return_written_too_soon_is_refused(
    tmp_path, authoritative_dataset, market_reactions
):
    """**`recorded_at` は「この review を書いた時刻」であって「20営業日目」では
    ない。** 発表直後に書かれた review でも `day20_return_pct` を埋められ、それが
    訂正できない trial になって status を動かす。

    取引カレンダーを持ち込まないので下限だけを見る——20営業日は暦で26日を
    下回らない。**「経った証明」ではなく「明らかに早すぎるものを弾く」検査**。
    """
    from earnings_research.prospective_hypotheses import pipeline as P
    assert P.MIN_D20_ELAPSED.days == 26
    payload = json.loads(STAGED_D20.read_text(encoding="utf-8"))
    d20 = next(item for item in payload["returns"] if item["horizon"] == "D20")
    too_soon = "2026-08-20T15:30:00+09:00"
    d20["observed_at"] = too_soon
    path = tmp_path / "premature.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    review_path = authoritative_dataset / "post_earnings_review_sample.csv"
    fields, rows = _read_csv(review_path)
    for row in rows:
        if row.get("day20_return_pct", "").strip():
            row["recorded_at"] = too_soon
    _write_csv(review_path, fields, rows)

    with pytest.raises(ValueError, match="twenty sessions cannot have elapsed"):
        evaluate_observation_file(
            cleared_registry(tmp_path), path, tmp_path / "soon-trials",
            tmp_path / "soon.json", datetime(2026, 10, 1, 18, tzinfo=JST),
            authoritative_dataset, market_reactions["aster"],
        )


def test_an_event_already_carrying_a_reaction_can_still_be_extended(
    tmp_path, authoritative_dataset, market_reactions
):
    """**規則を厳しくした結果、既存のイベントが育てられなくなることを避ける。**

    場中発表の反応は起点が揃わないので今後は導出しない。しかし旧実装の下で
    書かれた D1 bundle には値が入っている。追記の連鎖は「確定した反応を変え
    ない」ことを要求するので、導出できないことを理由に `None` を強いると、
    **そのイベントは二度と D5・D20 へ育てられない。** 記録済みの値をそのまま
    受け入れる。
    """
    from earnings_research.prospective_hypotheses import pipeline as P
    from earnings_research.market_reaction.models import MarketReactionTracking

    tracking = MarketReactionTracking.model_validate_json(
        market_reactions["aster"].read_text(encoding="utf-8")
    )
    recorded = P._reaction_label(tracking)
    assert recorded is not None

    trials = tmp_path / "compat-trials"
    registry = cleared_registry(tmp_path)
    P.evaluate_observation_file(
        registry, STAGED_D1, trials, trials / "d1.json",
        datetime(2026, 9, 1, 18, tzinfo=JST), authoritative_dataset, market_reactions["aster"],
    )
    assert P._recorded_reaction(P.load_trial_bundles(trials), 
                                CompletedEventObservation.model_validate_json(
                                    STAGED_D1.read_text(encoding="utf-8"))) == recorded

    # 起点が揃わなくなった後でも、記録済みの反応を保ったまま D5 を追記できる。
    shifted = json.loads(market_reactions["aster"].read_text(encoding="utf-8"))
    shifted["event_window_reaction"]["reference_role"] = "pre_announcement_reference"
    shifted_path = tmp_path / "shifted-reaction.json"
    shifted_path.write_text(json.dumps(shifted, ensure_ascii=False), encoding="utf-8")
    assert P._reaction_label(MarketReactionTracking.model_validate(shifted)) is None

    P.evaluate_observation_file(
        registry, STAGED_D5, trials, trials / "d5.json",
        datetime(2026, 9, 8, 18, tzinfo=JST), authoritative_dataset, shifted_path,
    )
    assert (trials / "d5.json").exists()
