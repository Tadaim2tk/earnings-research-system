"""Deterministic comparison of locked expectations and reported results."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from earnings_research.document_analysis.models import EarningsDocumentAnalysis, MetricValue

from .models import (
    EarningsEvaluation,
    GuidanceAssessment,
    HypothesisAssessment,
    MetricComparison,
    ProgressAssessment,
    SegmentAssessment,
)

METRIC_FIELDS = {
    "revenue": ("market_consensus_revenue", "company_guidance_revenue", "JPY"),
    "operating_profit": ("market_consensus_operating_income", "company_guidance_operating_income", "JPY"),
    "earnings_per_share": ("market_consensus_eps", "company_guidance_eps", "JPY_per_share"),
}
POSITIVE_WORDS = {"increase", "improve", "growth", "strong", "favorable", "positive", "上昇", "改善", "成長", "好調", "増加", "需要"}
NEGATIVE_WORDS = {"decrease", "decline", "weak", "loss", "negative", "down", "低下", "悪化", "減少", "弱い", "損失", "コスト"}
QUARTER_SCOPES = {
    "Q1": "q1_cumulative",
    "Q2": "half_year_cumulative",
    "Q3": "nine_month_cumulative",
    "Q4": "full_year",
    "FY": "full_year",
}


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_evaluation_inputs(
    baseline_path: Path,
    hypothesis_path: Path,
    analysis_path: Path,
    baseline_id: str,
) -> Tuple[Dict[str, str], List[Dict[str, str]], EarningsDocumentAnalysis]:
    matches = [row for row in _read_csv(baseline_path) if row.get("baseline_id") == baseline_id]
    if len(matches) != 1:
        raise ValueError("baseline_id must resolve to exactly one row")
    baseline = matches[0]
    if baseline.get("baseline_status") not in ("", "locked") or baseline.get("is_locked", "").lower() != "true":
        raise ValueError("earnings evaluation requires a locked baseline")
    if baseline.get("uses_post_event_data", "").lower() != "false":
        raise ValueError("earnings evaluation rejects baselines containing post-event data")
    try:
        locked_at = datetime.fromisoformat(baseline["locked_at"])
    except (KeyError, ValueError) as exc:
        raise ValueError("baseline locked_at is required and must be a valid datetime") from exc
    hypotheses = []
    for row in _read_csv(hypothesis_path):
        if (
            row.get("earnings_event_id") != baseline["earnings_event_id"]
            or row.get("hypothesis_type") != "pre_event"
            or row.get("status") not in {"active", "pending"}
        ):
            continue
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (KeyError, ValueError) as exc:
            raise ValueError("pre-event hypothesis created_at is required and must be valid") from exc
        if created_at <= locked_at:
            hypotheses.append(row)
    analysis = EarningsDocumentAnalysis.model_validate_json(analysis_path.read_text(encoding="utf-8"))
    if analysis.status != "analyzed" or analysis.next_stage != "ready_for_pre_event_comparison":
        raise ValueError("document analysis is not ready for pre-event comparison")
    return baseline, hypotheses, analysis


def load_evaluation_context(
    event_path: Path,
    company_path: Path,
    baseline: Dict[str, str],
    analysis: EarningsDocumentAnalysis,
) -> Tuple[str, str]:
    """Derive the pre-locked comparison period and ticker from dataset truth."""
    event_matches = [
        row for row in _read_csv(event_path)
        if row.get("earnings_event_id") == baseline.get("earnings_event_id")
    ]
    if len(event_matches) != 1:
        raise ValueError("earnings_event_id must resolve to exactly one event row")
    event = event_matches[0]
    company_matches = [
        row for row in _read_csv(company_path)
        if row.get("company_id") == event.get("company_id")
    ]
    if len(company_matches) != 1:
        raise ValueError("event company_id must resolve to exactly one company row")
    company = company_matches[0]
    try:
        scope = QUARTER_SCOPES[event["quarter"]]
    except KeyError as exc:
        raise ValueError("event quarter does not define a comparison period") from exc
    if company.get("ticker") != analysis.document.ticker:
        raise ValueError("event company ticker does not match analysis ticker")
    if company.get("company_name") != analysis.document.company_name:
        raise ValueError("event company name does not match analysis company name")
    if event.get("announcement_date") != analysis.document.announcement_date:
        raise ValueError("event announcement date does not match analysis announcement date")
    return scope, company["ticker"]


def _number(value: str, multiplier: float) -> Optional[float]:
    if value is None or value.strip() == "":
        return None
    return float(value) * multiplier


def _pct_change(actual: float, expected: float) -> Optional[float]:
    if expected == 0:
        return None
    return (actual - expected) / abs(expected) * 100


def _band(value: Optional[float], tolerance_pct: float) -> str:
    if value is None or abs(value) <= tolerance_pct:
        return "in_line"
    return "above" if value > 0 else "below"


def _metrics(analysis: EarningsDocumentAnalysis, kind: str) -> Dict[str, MetricValue]:
    return {
        item.metric_name: item
        for item in analysis.financial_metrics
        if item.value_kind == kind and item.period.comparison in {"current", "company_forecast"}
    }


def _words(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[A-Za-z]+|[\u3040-\u30ff\u3400-\u9fff]{2,}", text)}


def _direction(text: str) -> int:
    words = _words(text)
    pos = sum(word in text.lower() or word in words for word in POSITIVE_WORDS)
    neg = sum(word in text.lower() or word in words for word in NEGATIVE_WORDS)
    return 1 if pos > neg else -1 if neg > pos else 0


def _hypotheses(rows: Iterable[Dict[str, str]], analysis: EarningsDocumentAnalysis) -> List[HypothesisAssessment]:
    findings = [(item.statement, 1 if item.status == "positive" else -1 if item.status == "negative" else 0) for item in analysis.narrative_findings]
    output = []
    for row in rows:
        text = row["hypothesis_text"]
        terms = _words(text) - {"the", "and", "may", "with", "because", "even", "if"}
        related = [(statement, direction) for statement, direction in findings if terms & _words(statement)]
        expected_direction = _direction(text)
        supporting = [statement for statement, direction in related if expected_direction and direction == expected_direction]
        contradicting = [statement for statement, direction in related if expected_direction and direction == -expected_direction]
        direction_total = sum(direction for _, direction in related)
        observed_direction = 1 if direction_total > 0 else -1 if direction_total < 0 else 0
        if not related or expected_direction == 0:
            result, explanation = "pending", "会社資料との対応を一意に確認できないため、推測せず未判定として残しました。"
        elif supporting and not contradicting and observed_direction == expected_direction:
            result, explanation = "supported", "数値結果と会社説明が事前仮説の方向に一致しました。"
        elif contradicting and not supporting and expected_direction and observed_direction == -expected_direction:
            result, explanation = "invalidated", "数値結果または会社説明が事前仮説と反対の方向を示しました。"
        else:
            result, explanation = "mixed", "一致する材料と未確認または反対の材料が混在しています。"
        output.append(HypothesisAssessment(
            hypothesis_id=row["hypothesis_id"], hypothesis_text=text, result=result,
            explanation=explanation, supporting_findings=supporting, contradicting_findings=contradicting,
        ))
    return output


def _dimension(values: List[int]) -> Tuple[str, Optional[int]]:
    if not values:
        return "not_available", None
    total = sum(values)
    if total > 0:
        return "positive", 1
    if total < 0:
        return "negative", -1
    return "neutral", 0


def evaluate_earnings(
    baseline: Dict[str, str],
    hypotheses: List[Dict[str, str]],
    analysis: EarningsDocumentAnalysis,
    evaluated_at: Optional[datetime] = None,
    baseline_unit_multiplier: float = 1_000_000,
    tolerance_pct: float = 1.0,
    expected_ticker: Optional[str] = None,
    expected_period_scope: str = "full_year",
) -> EarningsEvaluation:
    if baseline_unit_multiplier <= 0:
        raise ValueError("baseline_unit_multiplier must be positive")
    if expected_ticker and analysis.document.ticker != expected_ticker:
        raise ValueError("analysis ticker does not match expected ticker")
    if expected_period_scope not in set(QUARTER_SCOPES.values()):
        raise ValueError("expected_period_scope is unsupported")
    locked_at = datetime.fromisoformat(baseline["locked_at"])
    announcement_date = datetime.fromisoformat(analysis.document.announcement_date).date()
    if locked_at.date() > announcement_date:
        raise ValueError("baseline was locked after the analyzed announcement date")
    actuals, forecasts = _metrics(analysis, "actual"), _metrics(analysis, "company_forecast")
    comparisons: List[MetricComparison] = []
    guidance: List[GuidanceAssessment] = []
    progress: List[ProgressAssessment] = []
    limitations = ["事前予想CSVに金額単位がないため、指定された換算倍率を記録して比較しています。"]
    for metric_name, (consensus_field, guidance_field, expected_unit) in METRIC_FIELDS.items():
        actual = actuals.get(metric_name)
        if actual is not None and actual.normalized_unit != expected_unit:
            limitations.append(f"{metric_name}: 実績単位が{expected_unit}ではないため比較から除外しました。")
            actual = None
        value_multiplier = 1 if metric_name == "earnings_per_share" else baseline_unit_multiplier
        consensus = _number(baseline.get(consensus_field, ""), value_multiplier)
        if actual is not None and consensus is not None and actual.period.scope == expected_period_scope:
            pct = _pct_change(float(actual.normalized_value), consensus)
            comparisons.append(MetricComparison(
                metric_name=metric_name, expectation_type="market_consensus", expected_value=consensus,
                actual_value=float(actual.normalized_value), normalized_unit=actual.normalized_unit,
                difference=float(actual.normalized_value) - consensus, difference_pct=pct,
                result=_band(pct, tolerance_pct), comparison_basis=f"{expected_period_scope}_actual_vs_pre_event_consensus",
                expectation_source=f"{baseline['baseline_id']}:{consensus_field}", source=actual.source,
            ))
        elif actual is not None and consensus is not None:
            limitations.append(
                f"{metric_name}: eventから導出した予想期間{expected_period_scope}と実績期間{actual.period.scope}が一致しないため比較から除外しました。"
            )
        announced = forecasts.get(metric_name)
        if announced is not None and (
            announced.period.scope != "full_year" or announced.normalized_unit != expected_unit
        ):
            limitations.append(f"{metric_name}: 通期会社予想の期間または単位が一致しないため比較から除外しました。")
            announced = None
        previous = _number(baseline.get(guidance_field, ""), value_multiplier)
        if announced is not None and previous is not None:
            pct = _pct_change(float(announced.normalized_value), previous)
            guidance.append(GuidanceAssessment(
                metric_name=metric_name, pre_event_guidance=previous, announced_guidance=float(announced.normalized_value),
                revision_pct=pct, revision="unchanged" if _band(pct, tolerance_pct) == "in_line" else "up" if pct and pct > 0 else "down",
                expectation_source=f"{baseline['baseline_id']}:{guidance_field}",
                source=announced.source,
            ))
        if actual is not None and announced is not None:
            pct = None if float(announced.normalized_value) == 0 else float(actual.normalized_value) / abs(float(announced.normalized_value)) * 100
            progress.append(ProgressAssessment(
                metric_name=metric_name, cumulative_actual=float(actual.normalized_value),
                full_year_company_forecast=float(announced.normalized_value), progress_pct=pct,
                interpretation="reference_only", note="季節性を考慮せず強弱を断定しない参考値です。", source=actual.source,
            ))
    segments = []
    grouped: Dict[str, List] = {}
    for item in analysis.company_specific_metrics:
        grouped.setdefault(item.category, []).append(item.value)
    for name, values in grouped.items():
        revenue = next((float(v.normalized_value) for v in values if v.metric_name == "segment_revenue"), None)
        profit = next((float(v.normalized_value) for v in values if v.metric_name == "segment_profit"), None)
        assessment = "reported_only" if profit is None else "reported_positive" if profit > 0 else "reported_negative" if profit < 0 else "reported_mixed"
        segments.append(SegmentAssessment(segment=name, revenue=revenue, profit=profit, assessment=assessment, sources=[v.source for v in values]))
    positive = [item.statement for item in analysis.narrative_findings if item.status == "positive"]
    negative = [item.statement for item in analysis.narrative_findings if item.status == "negative"]
    hypothesis_results = _hypotheses(hypotheses, analysis)
    dimension_inputs = {
        "market_expectation": [
            1 if item.result == "above" else -1 if item.result == "below" else 0
            for item in comparisons
        ],
        "company_guidance": [
            1 if item.revision == "up" else -1 if item.revision == "down" else 0
            for item in guidance
        ],
        "company_explanation": [1] * len(positive) + [-1] * len(negative),
        "pre_event_hypotheses": [
            1 if item.result == "supported" else -1 if item.result == "invalidated" else 0
            for item in hypothesis_results
            if item.result != "pending"
        ],
    }
    dimensions = {}
    dimension_signals = []
    for name, values in dimension_inputs.items():
        label, signal = _dimension(values)
        dimensions[name] = label
        if signal is not None:
            dimension_signals.append(signal)
    if not dimension_signals:
        overall, explanation, status = "inconclusive", "比較可能な材料が不足しています。", "insufficient_data"
    elif sum(dimension_signals) > 0:
        overall, explanation, status = "positive", "事前期待、会社予想、定性要因、仮説を総合すると肯定的です。", "evaluated"
    elif sum(dimension_signals) < 0:
        overall, explanation, status = "negative", "事前期待、会社予想、定性要因、仮説を総合すると否定的です。", "evaluated"
    elif any(signal != 0 for signal in dimension_signals):
        overall, explanation, status = "mixed", "肯定材料と否定材料が拮抗しています。", "evaluated"
    else:
        overall, explanation, status = "in_line", "確認できた材料は事前期待の範囲内です。", "evaluated"
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    digest = hashlib.sha256(f"{baseline['baseline_id']}|{analysis.analysis_id}".encode()).hexdigest()[:16]
    return EarningsEvaluation(
        evaluation_id=f"EE-{digest}", earnings_event_id=baseline["earnings_event_id"], baseline_id=baseline["baseline_id"],
        analysis_id=analysis.analysis_id, company_name=analysis.document.company_name,
        ticker=analysis.document.ticker, expectation_period_scope=expected_period_scope,
        evaluated_at=evaluated_at, status=status,
        baseline_unit_multiplier=baseline_unit_multiplier, metric_comparisons=comparisons,
        guidance_assessments=guidance, progress_assessments=progress, segment_assessments=segments,
        positive_factors=positive, negative_factors=negative, hypothesis_assessments=hypothesis_results,
        assessment_dimensions=dimensions,
        overall_assessment=overall, overall_explanation=explanation, limitations=list(dict.fromkeys(limitations)),
        next_stage="ready_for_market_reaction_tracking" if status == "evaluated" else "evaluation_not_available",
    )


def write_evaluation(result: EarningsEvaluation, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
