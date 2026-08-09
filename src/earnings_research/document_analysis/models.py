"""Structured contracts for normalized earnings-document analysis."""

from datetime import datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field

Number = Union[int, float]


class SourceReference(BaseModel):
    source_url: str
    document_title: str
    page_number: Optional[int] = Field(default=None, ge=1)
    text_anchor: str
    acquired_at: datetime


class PeriodReference(BaseModel):
    fiscal_year: str
    scope: Literal[
        "quarter_only",
        "q1_cumulative",
        "half_year_cumulative",
        "nine_month_cumulative",
        "full_year",
        "point_in_time",
    ]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    comparison: Literal["current", "prior_corresponding", "company_forecast", "prior_year_end"]


class MetricValue(BaseModel):
    metric_name: str
    label: str
    value_kind: Literal["actual", "prior_actual", "company_forecast", "derived"]
    displayed_value: str
    displayed_unit: str
    normalized_value: Number
    normalized_unit: str
    period: PeriodReference
    origin: Literal["reported", "calculated"]
    confidence: Literal["table_explicit", "text_explicit", "calculated", "unclear"]
    source: SourceReference
    formula: Optional[str] = None
    input_metric_names: List[str] = Field(default_factory=list)


class CompanySpecificMetric(BaseModel):
    category: str
    name: str
    value: MetricValue


class NarrativeFinding(BaseModel):
    finding_type: Literal[
        "revenue_driver",
        "profit_driver",
        "positive_factor",
        "negative_factor",
        "forecast_change",
        "dividend_change",
        "business_environment",
        "outlook",
    ]
    subject: str
    statement: str
    status: Literal["positive", "negative", "mixed", "unchanged", "changed", "not_stated"]
    confidence: Literal["text_explicit", "unclear"]
    source: SourceReference


class ConsistencyCheck(BaseModel):
    check_type: str
    status: Literal["passed", "review_required", "not_applicable"]
    message: str
    related_metrics: List[str] = Field(default_factory=list)


class DocumentIdentity(BaseModel):
    company_name: str
    ticker: str
    accounting_period: str
    reporting_scope: str
    announcement_date: str
    document_type: Literal["earnings_release", "earnings_presentation"]
    document_title: str
    source_url: str
    source_sha256: str
    acquired_at: datetime
    page_count: int = Field(ge=0)


class EarningsDocumentAnalysis(BaseModel):
    schema_version: Literal["earnings_document_analysis_v1"] = "earnings_document_analysis_v1"
    analysis_id: str
    status: Literal["analyzed", "unparseable", "not_target"]
    document: DocumentIdentity
    financial_metrics: List[MetricValue] = Field(default_factory=list)
    company_specific_metrics: List[CompanySpecificMetric] = Field(default_factory=list)
    narrative_findings: List[NarrativeFinding] = Field(default_factory=list)
    consistency_checks: List[ConsistencyCheck] = Field(default_factory=list)
    unresolved_items: List[str] = Field(default_factory=list)
    next_stage: Literal["ready_for_pre_event_comparison", "analysis_not_available", "not_applicable"]
    raw_document_retained: Literal[False] = False
