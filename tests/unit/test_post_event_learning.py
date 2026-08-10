import csv
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from earnings_research.cli.__main__ import main
from earnings_research.earnings_evaluation.models import EarningsEvaluation
from earnings_research.market_reaction.models import MarketReactionTracking
from earnings_research.post_event_learning.models import PostEventLearningReview
from earnings_research.post_event_learning.pipeline import write_review
from earnings_research.post_event_learning.reviewer import build_post_event_review


def baseline():
    return {
        "baseline_id": "BASE-FICTIONAL-001",
        "earnings_event_id": "EVT-FICTIONAL-001",
        "baseline_status": "locked",
        "is_locked": "true",
        "uses_post_event_data": "false",
        "locked_at": "2027-05-09T18:00:00+09:00",
        "baseline_record_hash": "locked-hash-fixture",
        "recorded_at": "2027-05-09T18:05:00+09:00",
    }


def hypothesis_rows(results=("supported",), explicit_condition=False):
    rows = []
    for index, _ in enumerate(results, start=1):
        suffix = " 撤回条件: 売上が事前予想を下回ること。" if explicit_condition else ""
        rows.append({
            "hypothesis_id": f"HYP-FICTIONAL-{index:03d}",
            "earnings_event_id": "EVT-FICTIONAL-001",
            "parent_hypothesis_id": "",
            "hypothesis_type": "pre_event",
            "hypothesis_text": f"主要指標は改善する。{suffix}",
            "evidence": "架空の発表前資料",
            "confidence": "0.70",
            "status": "active",
            "created_by": "system_policy:test-fixture",
            "created_at": "2027-05-09T17:00:00+09:00",
            "invalidated_at": "",
            "invalidation_reason": "",
        })
    return rows


def evaluation(results=("supported",), overall="positive", with_metric=True):
    metric_comparisons = []
    if with_metric:
        metric_comparisons.append({
            "metric_name": "revenue",
            "expectation_type": "market_consensus",
            "expected_value": 100,
            "actual_value": 110 if overall == "positive" else 90,
            "normalized_unit": "JPY",
            "difference": 10 if overall == "positive" else -10,
            "difference_pct": 10 if overall == "positive" else -10,
            "result": "above" if overall == "positive" else "below",
            "comparison_basis": "full_year_actual_vs_pre_event_consensus",
            "expectation_source": "BASE-FICTIONAL-001:market_consensus_revenue",
            "source": source_reference(),
        })
    return EarningsEvaluation.model_validate({
        "evaluation_id": "EE-FICTIONAL-001",
        "earnings_event_id": "EVT-FICTIONAL-001",
        "baseline_id": "BASE-FICTIONAL-001",
        "analysis_id": "EDA-FICTIONAL-001",
        "company_name": "架空食品株式会社",
        "ticker": "9999",
        "expectation_period_scope": "full_year",
        "evaluated_at": "2027-05-10T17:00:00+09:00",
        "status": "evaluated",
        "baseline_unit_multiplier": 1_000_000,
        "metric_comparisons": metric_comparisons,
        "guidance_assessments": [{
            "metric_name": "operating_profit",
            "pre_event_guidance": 50,
            "announced_guidance": 55,
            "revision_pct": 10,
            "revision": "up",
            "expectation_source": "BASE-FICTIONAL-001:company_guidance_operating_income",
            "source": source_reference(),
        }],
        "hypothesis_assessments": [
            {
                "hypothesis_id": f"HYP-FICTIONAL-{index:03d}",
                "hypothesis_text": "主要指標は改善する。",
                "result": result,
                "explanation": f"架空fixtureの{result}判定",
                "supporting_findings": ["改善を確認"] if result == "supported" else [],
                "contradicting_findings": ["悪化を確認"] if result == "invalidated" else [],
            }
            for index, result in enumerate(results, start=1)
        ],
        "overall_assessment": overall,
        "overall_explanation": "架空の決算評価です。",
        "next_stage": "ready_for_market_reaction_tracking",
    })


def source_reference():
    return {
        "source_url": "https://example.invalid/fictional.pdf",
        "document_title": "架空決算資料",
        "page_number": 1,
        "text_anchor": "架空表",
        "acquired_at": "2027-05-10T16:30:00+09:00",
    }


def reaction(immediate="positive", next_day="positive", fifth="positive", corporate="none_detected"):
    status_for = lambda direction: "pending" if direction == "pending" else "not_comparable" if direction == "not_comparable" else "observed"
    return_for = lambda direction, value: None if direction in {"pending", "not_comparable"} else value
    event_status = "pending" if immediate == "pending" else "not_comparable" if immediate == "not_comparable" else "calculated"
    milestones = [
        {
            "role": "pre_event_close",
            "status": "not_comparable" if corporate != "none_detected" else "observed",
            "expected_trading_date": "2027-05-09",
            "observation_id": "PX-PRE",
            "price": 100,
            "price_datetime": "2027-05-09T15:30:00+09:00",
            "note": "架空の発表前終値",
        },
        {
            "role": "immediate_post_announcement",
            "status": status_for(immediate),
            "expected_trading_date": "2027-05-10",
            "observation_id": None if immediate == "pending" else "PX-IMMEDIATE",
            "return_from_pre_event_close_pct": return_for(immediate, 5 if immediate == "positive" else -5),
            "note": "架空の初動",
        },
        {
            "role": "next_business_day_close",
            "status": status_for(next_day),
            "expected_trading_date": "2027-05-11",
            "observation_id": None if next_day == "pending" else "PX-NEXT",
            "return_from_pre_event_close_pct": return_for(next_day, 4 if next_day == "positive" else -4),
            "note": "架空の翌営業日",
        },
        {
            "role": "fifth_business_day_close",
            "status": status_for(fifth),
            "expected_trading_date": "2027-05-17",
            "observation_id": None if fifth == "pending" else "PX-FIFTH",
            "return_from_pre_event_close_pct": return_for(fifth, 8 if fifth == "positive" else -8),
            "note": "架空の5営業日後",
        },
    ]
    path = "not_comparable" if corporate != "none_detected" else "pending" if "pending" in {immediate, next_day, fifth} else "reversed" if fifth != immediate else "sustained"
    if corporate != "none_detected":
        immediate = next_day = fifth = "not_comparable"
        event_status = "not_comparable"
        for item in milestones:
            item["status"] = "not_comparable"
            item["return_from_pre_event_close_pct"] = None
    return MarketReactionTracking.model_validate({
        "tracking_id": "MR-FICTIONAL-001",
        "earnings_event_id": "EVT-FICTIONAL-001",
        "evaluation_id": "EE-FICTIONAL-001",
        "company_name": "架空食品株式会社",
        "ticker": "9999",
        "currency": "JPY",
        "status": "not_comparable" if corporate != "none_detected" else "tracking" if path == "pending" else "complete",
        "announcement_datetime": "2027-05-10T15:00:00+09:00",
        "announcement_session": "intraday",
        "calendar_name": "架空取引日",
        "corporate_action_status": corporate,
        "milestones": milestones,
        "event_window_reaction": {
            "status": event_status,
            "reference_role": "pre_announcement_reference",
            "reference_observation_id": "PX-REFERENCE" if event_status == "calculated" else None,
            "immediate_observation_id": "PX-IMMEDIATE" if event_status == "calculated" else None,
            "return_pct": return_for(immediate, 5 if immediate == "positive" else -5),
            "note": "架空のevent window",
        },
        "summary": {
            "immediate_direction": immediate,
            "next_business_day_direction": next_day,
            "fifth_business_day_direction": fifth,
            "reaction_path": path,
            "explanation": "架空の市場反応",
        },
        "completed_at": None if path in {"pending", "not_comparable"} else "2027-05-17T17:00:00+09:00",
        "next_stage": "manual_review_required" if corporate != "none_detected" else "awaiting_price_milestones" if path == "pending" else "ready_for_post_event_validation",
    })


def build(results=("supported",), overall="positive", directions=("positive", "positive", "positive"), corporate="none_detected", with_metric=True, rows=None, previous=None):
    rows = rows or hypothesis_rows(results)
    ev = evaluation(results, overall, with_metric)
    for item, row in zip(ev.hypothesis_assessments, rows):
        if row["hypothesis_type"] == "pre_event":
            item.hypothesis_text = row["hypothesis_text"]
    return build_post_event_review(
        baseline(),
        rows,
        ev,
        reaction(*directions, corporate=corporate),
        datetime.fromisoformat("2027-05-17T18:00:00+09:00") if previous is None else datetime.fromisoformat("2027-05-17T19:00:00+09:00"),
        previous,
    )


def test_supported_hypothesis_good_earnings_and_rising_price_is_success():
    result = build()
    assert result.status == "complete"
    assert result.overall_forecast_result == "success"
    assert result.earnings_assessment == "positive"
    assert [item.direction for item in result.market_stage_assessments] == ["positive"] * 3
    assert result.reason_analysis.market_expectation_interpretation == "earnings_and_market_aligned"


def test_rejected_hypothesis_bad_earnings_and_falling_price_is_failure():
    result = build(("invalidated",), "negative", ("negative", "negative", "negative"))
    assert result.overall_forecast_result == "failure"
    assert result.earnings_assessment == "negative"
    assert result.reason_analysis.rejected_hypothesis_ids == ["HYP-FICTIONAL-001"]


@pytest.mark.parametrize(
    ("overall", "direction", "expected"),
    [
        ("positive", "negative", "possible_higher_hurdle_than_recorded"),
        ("negative", "positive", "possible_lower_hurdle_than_recorded"),
    ],
)
def test_earnings_quality_and_market_direction_remain_separate(overall, direction, expected):
    result = build(("supported",), overall, (direction, direction, direction))
    assert result.earnings_assessment == overall
    assert result.market_stage_assessments[0].direction == direction
    assert result.reason_analysis.market_expectation_interpretation == expected


def test_partial_hypotheses_are_not_flattened_to_success_or_failure():
    result = build(("supported", "mixed", "pending"), rows=hypothesis_rows(("supported", "mixed", "pending")))
    assert result.overall_forecast_result == "partial_success"
    assert result.reason_analysis.supported_hypothesis_ids == ["HYP-FICTIONAL-001"]
    assert result.reason_analysis.pending_hypothesis_ids == ["HYP-FICTIONAL-003"]


def test_initial_and_fifth_day_reversal_is_recorded():
    result = build(directions=("positive", "positive", "negative"))
    assert result.reason_analysis.reaction_transition == "reversed_by_fifth_business_day"
    assert any("5営業日後" in item for item in result.learning_record.recurring_errors_to_prevent)


def test_explicit_invalidation_condition_without_record_is_not_triggered():
    rows = hypothesis_rows(("supported",), explicit_condition=True)
    result = build(rows=rows)
    assert result.hypothesis_verifications[0].invalidation_condition_status == "not_triggered"


def test_append_only_invalidation_is_traced_without_changing_parent():
    rows = hypothesis_rows(("invalidated",), explicit_condition=True)
    original = deepcopy(rows[0])
    rows.append({
        "hypothesis_id": "HYP-FICTIONAL-INVALIDATION",
        "earnings_event_id": "EVT-FICTIONAL-001",
        "parent_hypothesis_id": "HYP-FICTIONAL-001",
        "hypothesis_type": "invalidation",
        "hypothesis_text": "撤回条件が発動した。",
        "evidence": "架空の決算結果",
        "confidence": "0.90",
        "status": "invalidated",
        "created_by": "system_policy:test-fixture",
        "created_at": "2027-05-10T17:10:00+09:00",
        "invalidated_at": "2027-05-10T17:10:00+09:00",
        "invalidation_reason": "売上が事前予想を下回った。",
    })
    result = build(("invalidated",), "negative", ("negative", "negative", "negative"), rows=rows)
    assert rows[0] == original
    assert result.hypothesis_verifications[0].invalidation_condition_status == "triggered"
    assert result.reason_analysis.triggered_invalidation_record_ids == ["HYP-FICTIONAL-INVALIDATION"]


@pytest.mark.parametrize(
    "directions",
    [
        ("positive", "positive", "pending"),
        ("positive", "pending", "pending"),
        ("pending", "pending", "pending"),
    ],
)
def test_incomplete_market_data_produces_provisional_review(directions):
    result = build(directions=directions)
    assert result.status == "provisional"
    assert result.next_stage == "awaiting_market_milestones"
    assert result.overall_forecast_result == "success"


def test_pending_hypothesis_and_missing_kpi_are_not_failures():
    result = build(("pending",), with_metric=False)
    assert result.overall_forecast_result == "pending"
    assert result.numeric_expectation_outcomes == []
    assert "数値予想との比較結果がありません。" in result.reason_analysis.missing_or_blocked_reasons


def test_no_hypothesis_is_pending_instead_of_failure():
    result = build((), rows=[])
    assert result.overall_forecast_result == "pending"
    assert result.hypothesis_verifications == []


def test_company_guidance_read_is_only_judged_when_explicitly_recorded():
    rows = hypothesis_rows(("supported",))
    rows[0]["hypothesis_text"] = "会社予想: 通期予想は上方修正される。"
    result = build(rows=rows)
    assert result.reason_analysis.company_guidance_read_result == "supported"


def test_unlabeled_company_guidance_read_is_not_invented():
    result = build()
    assert result.reason_analysis.company_guidance_read_result == "not_recorded"


@pytest.mark.parametrize("corporate", ["present", "unknown"])
def test_unresolved_corporate_action_blocks_market_comparison_without_failing_hypothesis(corporate):
    result = build(corporate=corporate)
    assert result.status == "blocked"
    assert result.overall_forecast_result == "success"
    assert all(item.return_pct is None for item in result.market_stage_assessments)
    assert result.reason_analysis.market_expectation_interpretation == "not_comparable"


def test_source_baseline_and_hypotheses_are_not_mutated():
    base = baseline()
    rows = hypothesis_rows(("supported",))
    base_before, rows_before = deepcopy(base), deepcopy(rows)
    result = build_post_event_review(
        base,
        rows,
        evaluation(),
        reaction(),
        datetime.fromisoformat("2027-05-17T18:00:00+09:00"),
    )
    assert base == base_before
    assert rows == rows_before
    assert result.baseline_modified is False
    assert result.pre_event_hypotheses_modified is False
    assert result.learning_record.production_rules_modified is False
    assert result.learning_record.scoring_weights_modified is False


def test_outcome_reference_cannot_point_to_the_wrong_source_type():
    payload = build().model_dump(mode="json")
    payload["market_stage_assessments"][0]["source_record_id"] = "EE-FICTIONAL-001"
    with pytest.raises(ValidationError, match="market stages"):
        PostEventLearningReview.model_validate(payload)


def test_future_source_record_cannot_leak_into_review():
    payload = build().model_dump(mode="json")
    payload["source_records"][0]["recorded_at"] = "2027-05-18T18:00:00+09:00"
    with pytest.raises(ValidationError, match="future"):
        PostEventLearningReview.model_validate(payload)


def test_post_event_hypothesis_cannot_be_recast_as_pre_event():
    rows = hypothesis_rows(("supported",))
    rows[0]["created_at"] = "2027-05-10T18:00:00+09:00"
    with pytest.raises(ValueError, match="post-event hypothesis"):
        build(rows=rows)


def test_hypothesis_text_rewrite_is_rejected():
    rows = hypothesis_rows(("supported",))
    ev = evaluation()
    ev.hypothesis_assessments[0].hypothesis_text = "後から有利に書き換えた仮説"
    with pytest.raises(ValueError, match="immutable source record"):
        build_post_event_review(
            baseline(), rows, ev, reaction(), datetime.fromisoformat("2027-05-17T18:00:00+09:00")
        )


def test_follow_up_snapshot_supersedes_without_overwriting_previous():
    first = build(directions=("positive", "positive", "pending"))
    second = build(previous=first)
    assert first.status == "provisional"
    assert second.status == "complete"
    assert second.review_version == 2
    assert second.supersedes_review_id == first.review_id
    assert first.market_stage_assessments[-1].status == "pending"


def test_writer_refuses_to_overwrite_existing_review(tmp_path):
    output = tmp_path / "review.json"
    output.write_text("ORIGINAL", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        write_review(build(), output)
    assert output.read_text(encoding="utf-8") == "ORIGINAL"


def test_cli_generates_append_only_learning_review(tmp_path):
    base_path = tmp_path / "baseline.csv"
    hypothesis_path = tmp_path / "hypotheses.csv"
    evaluation_path = tmp_path / "evaluation.json"
    reaction_path = tmp_path / "reaction.json"
    output_path = tmp_path / "review.json"
    write_csv(base_path, [baseline()])
    write_csv(hypothesis_path, hypothesis_rows(("supported",)))
    evaluation_path.write_text(evaluation().model_dump_json(indent=2), encoding="utf-8")
    reaction_path.write_text(reaction().model_dump_json(indent=2), encoding="utf-8")
    exit_code = main([
        "review-earnings-outcome",
        "--baseline", str(base_path),
        "--baseline-id", "BASE-FICTIONAL-001",
        "--hypotheses", str(hypothesis_path),
        "--evaluation", str(evaluation_path),
        "--market-reaction", str(reaction_path),
        "--reviewed-at", "2027-05-17T18:00:00+09:00",
        "--output", str(output_path),
    ])
    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["overall_forecast_result"] == "success"
    assert payload["learning_record"]["production_rules_modified"] is False


def test_fictional_repository_sample_matches_contract():
    root = Path(__file__).parents[2]
    sample = root / "data/samples/post_event_learning_review_sample.json"
    result = PostEventLearningReview.model_validate_json(sample.read_text(encoding="utf-8"))
    assert result.company_name == "架空学習株式会社"
    assert result.trade_decision_included is False


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
