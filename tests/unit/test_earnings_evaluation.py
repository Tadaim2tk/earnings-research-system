import csv
import json
from pathlib import Path

import pytest

from earnings_research.cli.__main__ import main
from earnings_research.document_analysis.models import (
    CompanySpecificMetric,
    DocumentIdentity,
    EarningsDocumentAnalysis,
    MetricValue,
    NarrativeFinding,
    PeriodReference,
    SourceReference,
)
from earnings_research.earnings_evaluation import (
    evaluate_earnings,
    load_evaluation_context,
    load_evaluation_inputs,
)


def source(page=1):
    return SourceReference(
        source_url="https://example.com/earnings.pdf",
        document_title="架空食品 2027年3月期決算短信",
        page_number=page,
        text_anchor="経営成績",
        acquired_at="2027-05-10T15:00:00+09:00",
    )


def metric(name, label, value, kind="actual", scope="full_year", unit="JPY"):
    return MetricValue(
        metric_name=name,
        label=label,
        value_kind=kind,
        displayed_value=str(value),
        displayed_unit="百万円" if unit == "JPY" else "円",
        normalized_value=value,
        normalized_unit=unit,
        period=PeriodReference(
            fiscal_year="2027",
            scope=scope,
            comparison="company_forecast" if kind == "company_forecast" else "current",
        ),
        origin="reported",
        confidence="table_explicit",
        source=source(),
    )


def analysis(scope="full_year"):
    actuals = [
        metric("revenue", "売上高", 10_500_000_000, scope=scope),
        metric("operating_profit", "営業利益", 480_000_000, scope=scope),
        metric("earnings_per_share", "1株利益", 105, scope=scope, unit="JPY_per_share"),
    ]
    forecasts = [
        metric("revenue", "売上高", 11_000_000_000, "company_forecast"),
        metric("operating_profit", "営業利益", 520_000_000, "company_forecast"),
        metric("earnings_per_share", "1株利益", 110, "company_forecast", unit="JPY_per_share"),
    ]
    segment_loss = metric("segment_profit", "セグメント損失", -50_000_000, scope=scope)
    return EarningsDocumentAnalysis(
        analysis_id="EDA-FICTIONAL-20270510",
        status="analyzed",
        document=DocumentIdentity(
            company_name="架空食品株式会社",
            ticker="9999",
            accounting_period="2027年3月期",
            reporting_scope=scope,
            announcement_date="2027-05-10",
            document_type="earnings_release",
            document_title="架空食品 2027年3月期決算短信",
            source_url="https://example.com/earnings.pdf",
            source_sha256="a" * 64,
            acquired_at="2027-05-10T15:00:00+09:00",
            page_count=8,
        ),
        financial_metrics=actuals + forecasts,
        company_specific_metrics=[
            CompanySpecificMetric(category="新規事業", name="セグメント損失", value=segment_loss)
        ],
        narrative_findings=[
            NarrativeFinding(
                finding_type="positive_factor",
                subject="売上高",
                statement="新規取引が売上を押し上げました。",
                status="positive",
                confidence="text_explicit",
                source=source(3),
            ),
            NarrativeFinding(
                finding_type="negative_factor",
                subject="営業利益",
                statement="物流費の増加が利益を圧迫しました。",
                status="negative",
                confidence="text_explicit",
                source=source(3),
            ),
        ],
        next_stage="ready_for_pre_event_comparison",
    )


def baseline():
    return {
        "baseline_id": "BASE-FICTIONAL-001",
        "earnings_event_id": "EVT-FICTIONAL-2027FY",
        "locked_at": "2027-05-09T15:00:00+09:00",
        "market_consensus_revenue": "10000",
        "market_consensus_operating_income": "500",
        "market_consensus_eps": "100",
        "company_guidance_revenue": "10800",
        "company_guidance_operating_income": "500",
        "company_guidance_eps": "105",
    }


def test_full_year_expectations_guidance_and_eps_are_compared():
    result = evaluate_earnings(baseline(), [], analysis(), expected_ticker="9999")
    comparisons = {item.metric_name: item for item in result.metric_comparisons}
    assert comparisons["revenue"].difference_pct == 5.0
    assert comparisons["revenue"].result == "above"
    assert comparisons["operating_profit"].difference_pct == -4.0
    assert comparisons["earnings_per_share"].actual_value == 105
    assert comparisons["earnings_per_share"].expected_value == 100
    assert comparisons["revenue"].calculation_origin == "ers_calculated"
    assert comparisons["revenue"].expectation_source.endswith(":market_consensus_revenue")
    guidance = {item.metric_name: item for item in result.guidance_assessments}
    assert guidance["revenue"].revision == "up"
    assert guidance["operating_profit"].revision == "up"
    assert guidance["earnings_per_share"].revision == "up"
    assert result.market_reaction_included is False
    assert result.trade_decision_included is False


def test_cumulative_result_is_not_misrepresented_as_consensus_surprise():
    result = evaluate_earnings(baseline(), [], analysis("nine_month_cumulative"))
    assert result.metric_comparisons == []
    assert len(result.progress_assessments) == 3
    assert all(item.interpretation == "reference_only" for item in result.progress_assessments)
    assert any("実績期間nine_month_cumulativeが一致しない" in item for item in result.limitations)


def test_event_period_allows_same_period_quarterly_comparison():
    result = evaluate_earnings(
        baseline(),
        [],
        analysis("nine_month_cumulative"),
        expected_period_scope="nine_month_cumulative",
    )
    assert len(result.metric_comparisons) == 3
    assert result.expectation_period_scope == "nine_month_cumulative"


def test_guidance_and_actual_stay_separate():
    result = evaluate_earnings(baseline(), [], analysis())
    revenue_actual = next(item for item in result.metric_comparisons if item.metric_name == "revenue")
    revenue_guidance = next(item for item in result.guidance_assessments if item.metric_name == "revenue")
    assert revenue_actual.actual_value == 10_500_000_000
    assert revenue_guidance.announced_guidance == 11_000_000_000


def test_negative_segment_is_preserved():
    result = evaluate_earnings(baseline(), [], analysis())
    segment = result.segment_assessments[0]
    assert segment.profit == -50_000_000
    assert segment.assessment == "reported_negative"


def test_baseline_multiplier_is_explicit_and_configurable():
    small = baseline()
    small.update({
        "market_consensus_revenue": "10000000",
        "market_consensus_operating_income": "500000",
        "market_consensus_eps": "100",
        "company_guidance_revenue": "10800000",
        "company_guidance_operating_income": "500000",
        "company_guidance_eps": "105",
    })
    result = evaluate_earnings(small, [], analysis(), baseline_unit_multiplier=1000)
    assert result.baseline_unit_multiplier == 1000
    assert result.metric_comparisons[0].expected_value == 10_000_000_000


def test_wrong_ticker_and_future_baseline_are_rejected():
    with pytest.raises(ValueError, match="ticker"):
        evaluate_earnings(baseline(), [], analysis(), expected_ticker="0000")
    late = baseline()
    late["locked_at"] = "2027-05-11T00:00:00+09:00"
    with pytest.raises(ValueError, match="locked after"):
        evaluate_earnings(late, [], analysis())


def test_hypothesis_without_clear_document_link_remains_pending():
    rows = [{
        "hypothesis_id": "HYP-001",
        "hypothesis_text": "海外拠点の稼働率が改善する。",
    }]
    result = evaluate_earnings(baseline(), rows, analysis())
    assert result.hypothesis_assessments[0].result == "pending"
    assert "推測せず未判定" in result.hypothesis_assessments[0].explanation


@pytest.mark.parametrize(
    ("status", "expected"),
    [("positive", "supported"), ("negative", "invalidated")],
)
def test_hypothesis_uses_only_directly_related_company_explanation(status, expected):
    actual = analysis()
    actual.narrative_findings = [NarrativeFinding(
        finding_type="positive_factor" if status == "positive" else "negative_factor",
        subject="Revenue growth",
        statement="Revenue growth was strong." if status == "positive" else "Revenue growth was weak.",
        status=status,
        confidence="text_explicit",
        source=source(3),
    )]
    rows = [{
        "hypothesis_id": "HYP-GROWTH",
        "hypothesis_text": "Revenue growth will improve.",
    }]
    result = evaluate_earnings(baseline(), rows, actual)
    assessment = result.hypothesis_assessments[0]
    assert assessment.result == expected
    assert assessment.supporting_findings or assessment.contradicting_findings


def test_unknown_actual_unit_is_not_compared():
    actual = analysis()
    revenue = next(item for item in actual.financial_metrics if item.metric_name == "revenue" and item.value_kind == "actual")
    revenue.normalized_unit = "unknown"
    result = evaluate_earnings(baseline(), [], actual)
    assert all(item.metric_name != "revenue" for item in result.metric_comparisons)
    assert any("実績単位" in item for item in result.limitations)


def test_zero_consensus_does_not_crash_or_invent_percentage():
    zero = baseline()
    zero["market_consensus_operating_income"] = "0"
    result = evaluate_earnings(zero, [], analysis())
    operating = next(item for item in result.metric_comparisons if item.metric_name == "operating_profit")
    assert operating.difference_pct is None
    assert operating.result == "in_line"


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_cli_runs_locked_baseline_to_evaluation(tmp_path):
    base = baseline()
    base.update({"baseline_status": "locked", "is_locked": "true", "uses_post_event_data": "false"})
    baseline_path = tmp_path / "baselines.csv"
    hypotheses_path = tmp_path / "hypotheses.csv"
    events_path = tmp_path / "events.csv"
    companies_path = tmp_path / "companies.csv"
    analysis_path = tmp_path / "analysis.json"
    output_path = tmp_path / "evaluation.json"
    write_csv(baseline_path, [base])
    write_csv(hypotheses_path, [{
        "hypothesis_id": "HYP-001",
        "earnings_event_id": base["earnings_event_id"],
        "hypothesis_type": "pre_event",
        "hypothesis_text": "利益率が改善する。",
        "status": "active",
        "created_at": "2027-05-09T14:00:00+09:00",
    }])
    write_csv(events_path, [{
        "earnings_event_id": base["earnings_event_id"],
        "company_id": "CMP-FICTIONAL",
        "quarter": "FY",
        "announcement_date": "2027-05-10",
    }])
    write_csv(companies_path, [{
        "company_id": "CMP-FICTIONAL",
        "ticker": "9999",
        "company_name": "架空食品株式会社",
    }])
    analysis_path.write_text(analysis().model_dump_json(indent=2), encoding="utf-8")
    exit_code = main([
        "evaluate-earnings",
        "--baseline", str(baseline_path),
        "--baseline-id", base["baseline_id"],
        "--hypotheses", str(hypotheses_path),
        "--events", str(events_path),
        "--companies", str(companies_path),
        "--analysis", str(analysis_path),
        "--evaluated-at", "2027-05-10T16:00:00+09:00",
        "--output", str(output_path),
    ])
    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["baseline_id"] == base["baseline_id"]
    assert payload["ticker"] == "9999"
    assert payload["next_stage"] == "ready_for_market_reaction_tracking"


def test_context_rejects_company_name_mismatch(tmp_path):
    base = baseline()
    events_path = tmp_path / "events.csv"
    companies_path = tmp_path / "companies.csv"
    write_csv(events_path, [{
        "earnings_event_id": base["earnings_event_id"],
        "company_id": "CMP-FICTIONAL",
        "quarter": "FY",
        "announcement_date": "2027-05-10",
    }])
    write_csv(companies_path, [{
        "company_id": "CMP-FICTIONAL",
        "ticker": "9999",
        "company_name": "別会社株式会社",
    }])
    with pytest.raises(ValueError, match="company name"):
        load_evaluation_context(events_path, companies_path, base, analysis())


def test_loader_rejects_unlocked_or_post_event_baseline(tmp_path):
    base = baseline()
    base.update({"baseline_status": "draft", "is_locked": "false", "uses_post_event_data": "false"})
    baseline_path = tmp_path / "baselines.csv"
    hypothesis_path = tmp_path / "hypotheses.csv"
    analysis_path = tmp_path / "analysis.json"
    write_csv(baseline_path, [base])
    write_csv(hypothesis_path, [{"hypothesis_id": "x", "earnings_event_id": "other"}])
    analysis_path.write_text(analysis().model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="locked baseline"):
        load_evaluation_inputs(baseline_path, hypothesis_path, analysis_path, base["baseline_id"])


def test_loader_excludes_hypotheses_created_after_lock(tmp_path):
    base = baseline()
    base.update({"baseline_status": "locked", "is_locked": "true", "uses_post_event_data": "false"})
    baseline_path = tmp_path / "baselines.csv"
    hypothesis_path = tmp_path / "hypotheses.csv"
    analysis_path = tmp_path / "analysis.json"
    write_csv(baseline_path, [base])
    write_csv(hypothesis_path, [{
        "hypothesis_id": "HYP-LATE",
        "earnings_event_id": base["earnings_event_id"],
        "hypothesis_type": "pre_event",
        "hypothesis_text": "発表後に追加された仮説",
        "status": "active",
        "created_at": "2027-05-10T16:00:00+09:00",
    }])
    analysis_path.write_text(analysis().model_dump_json(), encoding="utf-8")
    _, hypotheses, _ = load_evaluation_inputs(
        baseline_path, hypothesis_path, analysis_path, base["baseline_id"]
    )
    assert hypotheses == []


def test_iceco_actual_remains_nine_month_cumulative():
    root = Path(__file__).parents[2]
    payload = json.loads((root / "data/research/iceco/EDA-7698-20250212.json").read_text(encoding="utf-8"))
    iceco = EarningsDocumentAnalysis.model_validate(payload)
    result = evaluate_earnings(
        {
            **baseline(),
            "baseline_id": "BASE-ICECO-HISTORICAL-TEST",
            "earnings_event_id": "EVT-ICECO-20250212-TEST",
            "locked_at": "2025-02-11T15:00:00+09:00",
        },
        [],
        iceco,
        expected_ticker="7698",
    )
    assert result.metric_comparisons == []
    assert all(item.interpretation == "reference_only" for item in result.progress_assessments)
    assert result.company_name == "株式会社アイスコ"
