"""Contracts for append-only post-event forecast validation and learning."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SourceRecordReference(BaseModel):
    record_type: Literal[
        "pre_event_baseline",
        "pre_event_hypothesis",
        "hypothesis_invalidation",
        "earnings_evaluation",
        "market_reaction_tracking",
    ]
    record_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at: Optional[datetime] = None
    declared_record_hash: Optional[str] = None


class HypothesisVerification(BaseModel):
    hypothesis_id: str
    hypothesis_text: str
    result: Literal["supported", "partially_supported", "rejected", "pending"]
    explanation: str
    supporting_findings: List[str] = Field(default_factory=list)
    contradicting_findings: List[str] = Field(default_factory=list)
    invalidation_condition_status: Literal[
        "triggered",
        "not_triggered",
        "not_recorded",
        "insufficient_evidence",
    ]
    invalidation_record_ids: List[str] = Field(default_factory=list)
    source_record_ids: List[str] = Field(min_length=2)


class NumericExpectationOutcome(BaseModel):
    metric_name: str
    expected_value: float
    actual_value: float
    normalized_unit: str
    difference: float
    difference_pct: Optional[float]
    result: Literal["above", "in_line", "below"]
    source_record_id: str


class CompanyGuidanceOutcome(BaseModel):
    metric_name: str
    pre_event_guidance: float
    announced_guidance: float
    revision_pct: Optional[float]
    revision: Literal["up", "unchanged", "down"]
    source_record_id: str


class MarketStageAssessment(BaseModel):
    stage: Literal[
        "immediate_post_announcement",
        "next_business_day",
        "fifth_business_day",
    ]
    status: Literal["complete", "pending", "not_comparable"]
    direction: Literal["positive", "negative", "muted", "pending", "not_comparable"]
    return_pct: Optional[float] = None
    observation_id: Optional[str] = None
    source_record_id: str

    @model_validator(mode="after")
    def validate_state(self):
        if self.status == "complete":
            if self.direction in {"pending", "not_comparable"} or self.return_pct is None:
                raise ValueError("complete market stage requires a comparable direction and return")
        elif self.return_pct is not None:
            raise ValueError("pending or non-comparable market stage cannot contain a return")
        if self.status == "pending" and self.direction != "pending":
            raise ValueError("pending market stage requires pending direction")
        if self.status == "not_comparable" and self.direction != "not_comparable":
            raise ValueError("non-comparable market stage requires non-comparable direction")
        return self


class ReasonAnalysis(BaseModel):
    supported_hypothesis_ids: List[str] = Field(default_factory=list)
    rejected_hypothesis_ids: List[str] = Field(default_factory=list)
    pending_hypothesis_ids: List[str] = Field(default_factory=list)
    above_expectation_metrics: List[str] = Field(default_factory=list)
    below_expectation_metrics: List[str] = Field(default_factory=list)
    guidance_revisions: List[str] = Field(default_factory=list)
    company_guidance_read_result: Literal[
        "supported",
        "contradicted",
        "mixed",
        "insufficient_evidence",
        "not_recorded",
    ]
    market_expectation_interpretation: Literal[
        "possible_higher_hurdle_than_recorded",
        "possible_lower_hurdle_than_recorded",
        "earnings_and_market_aligned",
        "insufficient_evidence",
        "not_comparable",
    ]
    reaction_transition: Literal[
        "same_direction",
        "changed_by_next_business_day",
        "reversed_by_fifth_business_day",
        "mixed",
        "pending",
        "not_comparable",
    ]
    triggered_invalidation_record_ids: List[str] = Field(default_factory=list)
    missing_or_blocked_reasons: List[str] = Field(default_factory=list)
    explanation: str


class LearningRecord(BaseModel):
    maintain_criteria: List[str] = Field(default_factory=list)
    weaken_candidates: List[str] = Field(default_factory=list)
    additional_indicators: List[str] = Field(default_factory=list)
    recurring_errors_to_prevent: List[str] = Field(default_factory=list)
    supported_but_not_generalized: List[str] = Field(default_factory=list)
    rejected_assumptions: List[str] = Field(default_factory=list)
    next_event_checks: List[str] = Field(default_factory=list)
    production_rules_modified: Literal[False] = False
    scoring_weights_modified: Literal[False] = False
    note: str = "観測結果と改善候補の記録であり、本番ルールへの自動反映ではありません。"


class PostEventLearningReview(BaseModel):
    schema_version: Literal["post_event_learning_review_v1"] = "post_event_learning_review_v1"
    review_id: str
    review_version: int = Field(ge=1)
    supersedes_review_id: Optional[str] = None
    earnings_event_id: str
    baseline_id: str
    evaluation_id: str
    tracking_id: str
    company_name: str
    ticker: str
    reviewed_at: datetime
    status: Literal["complete", "provisional", "blocked"]
    overall_forecast_result: Literal["success", "partial_success", "failure", "pending"]
    hypothesis_verifications: List[HypothesisVerification] = Field(default_factory=list)
    earnings_assessment: Literal["positive", "mixed", "negative", "in_line", "inconclusive"]
    numeric_expectation_outcomes: List[NumericExpectationOutcome] = Field(default_factory=list)
    company_guidance_outcomes: List[CompanyGuidanceOutcome] = Field(default_factory=list)
    market_stage_assessments: List[MarketStageAssessment] = Field(min_length=3, max_length=3)
    reason_analysis: ReasonAnalysis
    learning_record: LearningRecord
    source_records: List[SourceRecordReference] = Field(min_length=3)
    limitations: List[str] = Field(default_factory=list)
    baseline_modified: Literal[False] = False
    pre_event_hypotheses_modified: Literal[False] = False
    trade_decision_included: Literal[False] = False
    next_stage: Literal[
        "learning_record_ready",
        "awaiting_market_milestones",
        "comparison_blocked",
    ]

    @model_validator(mode="after")
    def validate_review(self):
        if (self.review_version == 1) != (self.supersedes_review_id is None):
            raise ValueError("only version 1 may omit supersedes_review_id")
        stages = [item.stage for item in self.market_stage_assessments]
        expected = {
            "immediate_post_announcement",
            "next_business_day",
            "fifth_business_day",
        }
        if set(stages) != expected or len(stages) != len(set(stages)):
            raise ValueError("market stages must contain each required stage exactly once")
        source_keys = [(item.record_type, item.record_id) for item in self.source_records]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("source record references must be unique")
        source_ids = {item.record_id for item in self.source_records}
        if len(source_ids) != len(self.source_records):
            raise ValueError("source record IDs must be globally unique")
        required_types = {
            "pre_event_baseline",
            "earnings_evaluation",
            "market_reaction_tracking",
        }
        if not required_types.issubset({item.record_type for item in self.source_records}):
            raise ValueError("baseline, earnings evaluation, and market reaction sources are required")
        if any(
            sum(item.record_type == record_type for item in self.source_records) != 1
            for record_type in required_types
        ):
            raise ValueError("each primary source type must occur exactly once")
        source_by_type = {
            item.record_type: item.record_id
            for item in self.source_records
            if item.record_type in required_types
        }
        if source_by_type != {
            "pre_event_baseline": self.baseline_id,
            "earnings_evaluation": self.evaluation_id,
            "market_reaction_tracking": self.tracking_id,
        }:
            raise ValueError("primary source record IDs must match the review identity")
        referenced_ids = {
            item.source_record_id for item in self.numeric_expectation_outcomes
        } | {
            item.source_record_id for item in self.company_guidance_outcomes
        } | {
            item.source_record_id for item in self.market_stage_assessments
        } | {
            record_id
            for item in self.hypothesis_verifications
            for record_id in item.source_record_ids
        }
        if not referenced_ids.issubset(source_ids):
            raise ValueError("all outcome references must resolve to source_records")
        source_types_by_id = {item.record_id: item.record_type for item in self.source_records}
        if any(item.source_record_id != self.evaluation_id for item in self.numeric_expectation_outcomes):
            raise ValueError("numeric outcomes must reference the earnings evaluation")
        if any(item.source_record_id != self.evaluation_id for item in self.company_guidance_outcomes):
            raise ValueError("guidance outcomes must reference the earnings evaluation")
        if any(item.source_record_id != self.tracking_id for item in self.market_stage_assessments):
            raise ValueError("market stages must reference market reaction tracking")
        for item in self.hypothesis_verifications:
            if source_types_by_id.get(item.hypothesis_id) != "pre_event_hypothesis":
                raise ValueError("hypothesis outcome must reference its pre-event source")
            if item.hypothesis_id not in item.source_record_ids or self.evaluation_id not in item.source_record_ids:
                raise ValueError("hypothesis outcome must cite its hypothesis and earnings evaluation")
            if any(
                source_types_by_id.get(record_id) != "hypothesis_invalidation"
                for record_id in item.invalidation_record_ids
            ):
                raise ValueError("invalidation IDs must reference append-only invalidation records")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("reviewed_at must include timezone")
        if any(item.recorded_at and item.recorded_at.tzinfo is None for item in self.source_records):
            raise ValueError("source recorded_at must include timezone")
        if any(item.recorded_at and item.recorded_at > self.reviewed_at for item in self.source_records):
            raise ValueError("review cannot use a source recorded in the future")
        stage_statuses = {item.status for item in self.market_stage_assessments}
        if self.status == "complete" and stage_statuses != {"complete"}:
            raise ValueError("complete review requires all market stages")
        if self.status == "provisional" and "pending" not in stage_statuses:
            raise ValueError("provisional review requires a pending market stage")
        if self.status == "blocked" and "not_comparable" not in stage_statuses:
            raise ValueError("blocked review requires a non-comparable market stage")
        expected_next_stage = {
            "complete": "learning_record_ready",
            "provisional": "awaiting_market_milestones",
            "blocked": "comparison_blocked",
        }[self.status]
        if self.next_stage != expected_next_stage:
            raise ValueError("next_stage must match review status")
        return self
