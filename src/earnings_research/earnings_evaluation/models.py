"""Structured output contracts for pre-event comparison and earnings evaluation."""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from earnings_research.document_analysis.models import SourceReference


class MetricComparison(BaseModel):
    metric_name: str
    expectation_type: Literal["market_consensus", "company_guidance"]
    expected_value: float
    actual_value: float
    normalized_unit: str
    difference: float
    difference_pct: Optional[float]
    result: Literal["above", "in_line", "below"]
    comparison_basis: str
    expectation_source: str
    calculation_origin: Literal["ers_calculated"] = "ers_calculated"
    formula: str = "(actual - expected) / abs(expected) * 100"
    source: SourceReference


class ProgressAssessment(BaseModel):
    metric_name: str
    cumulative_actual: float
    full_year_company_forecast: float
    progress_pct: Optional[float]
    interpretation: Literal["reference_only", "not_available"]
    note: str
    source: SourceReference


class GuidanceAssessment(BaseModel):
    metric_name: str
    pre_event_guidance: float
    announced_guidance: float
    revision_pct: Optional[float]
    revision: Literal["up", "unchanged", "down"]
    expectation_source: str
    calculation_origin: Literal["ers_calculated"] = "ers_calculated"
    source: SourceReference


class SegmentAssessment(BaseModel):
    segment: str
    revenue: Optional[float] = None
    profit: Optional[float] = None
    normalized_unit: str = "JPY"
    assessment: Literal["reported_positive", "reported_negative", "reported_mixed", "reported_only"]
    sources: List[SourceReference] = Field(default_factory=list)


class HypothesisAssessment(BaseModel):
    hypothesis_id: str
    hypothesis_text: str
    result: Literal["supported", "mixed", "invalidated", "pending"]
    explanation: str
    supporting_findings: List[str] = Field(default_factory=list)
    contradicting_findings: List[str] = Field(default_factory=list)


class EarningsEvaluation(BaseModel):
    schema_version: Literal["earnings_evaluation_v1"] = "earnings_evaluation_v1"
    evaluation_id: str
    earnings_event_id: str
    baseline_id: str
    analysis_id: str
    company_name: str
    ticker: str
    expectation_period_scope: Literal[
        "q1_cumulative", "half_year_cumulative", "nine_month_cumulative", "full_year"
    ]
    evaluated_at: datetime
    status: Literal["evaluated", "insufficient_data"]
    baseline_unit_multiplier: float
    metric_comparisons: List[MetricComparison] = Field(default_factory=list)
    guidance_assessments: List[GuidanceAssessment] = Field(default_factory=list)
    progress_assessments: List[ProgressAssessment] = Field(default_factory=list)
    segment_assessments: List[SegmentAssessment] = Field(default_factory=list)
    positive_factors: List[str] = Field(default_factory=list)
    negative_factors: List[str] = Field(default_factory=list)
    hypothesis_assessments: List[HypothesisAssessment] = Field(default_factory=list)
    assessment_dimensions: Dict[
        str, Literal["positive", "neutral", "negative", "not_available"]
    ] = Field(default_factory=dict)
    overall_assessment: Literal["positive", "mixed", "negative", "in_line", "inconclusive"]
    overall_explanation: str
    limitations: List[str] = Field(default_factory=list)
    next_stage: Literal["ready_for_market_reaction_tracking", "evaluation_not_available"]
    market_reaction_included: Literal[False] = False
    trade_decision_included: Literal[False] = False
