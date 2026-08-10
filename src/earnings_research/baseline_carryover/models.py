"""Contracts for human-readable baseline carryover context."""

from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, Field, model_validator


class SourceReviewReference(BaseModel):
    review_id: str = Field(min_length=1)
    earnings_event_id: str = Field(min_length=1)
    reviewed_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CarryoverItem(BaseModel):
    text: str = Field(min_length=1)
    occurrence_count: int = Field(ge=1)
    source_review_ids: List[str] = Field(min_length=1)


class MarketEarningsDivergence(BaseModel):
    earnings_assessment: Literal["positive", "mixed", "negative", "in_line", "inconclusive"]
    market_expectation_interpretation: Literal[
        "possible_higher_hurdle_than_recorded",
        "possible_lower_hurdle_than_recorded",
    ]
    reaction_transition: Literal[
        "same_direction",
        "changed_by_next_business_day",
        "reversed_by_fifth_business_day",
        "mixed",
        "pending",
        "not_comparable",
    ]
    occurrence_count: int = Field(ge=1)
    source_review_ids: List[str] = Field(min_length=1)
    source_event_ids: List[str] = Field(min_length=1)


class BaselineCarryoverContext(BaseModel):
    schema_version: Literal["baseline_carryover_context_v1"] = "baseline_carryover_context_v1"
    target_event_id: str = Field(min_length=1)
    prepared_at: datetime
    source_event_ids: List[str] = Field(min_length=1)
    source_reviews: List[SourceReviewReference] = Field(min_length=1)
    maintain_criteria: List[CarryoverItem] = Field(default_factory=list)
    weaken_candidates: List[CarryoverItem] = Field(default_factory=list)
    next_event_checks: List[CarryoverItem] = Field(default_factory=list)
    rejected_assumptions: List[CarryoverItem] = Field(default_factory=list)
    recurring_errors_to_prevent: List[CarryoverItem] = Field(default_factory=list)
    market_earnings_divergence_history: List[MarketEarningsDivergence] = Field(default_factory=list)
    production_rules_modified: Literal[False] = False
    scoring_weights_modified: Literal[False] = False
    trade_decision_included: Literal[False] = False

    @model_validator(mode="after")
    def validate_context(self):
        if self.prepared_at.tzinfo is None:
            raise ValueError("prepared_at must include timezone")
        review_ids = [item.review_id for item in self.source_reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("source review IDs must be unique")
        if any(item.reviewed_at.tzinfo is None for item in self.source_reviews):
            raise ValueError("source reviewed_at must include timezone")
        if any(item.reviewed_at > self.prepared_at for item in self.source_reviews):
            raise ValueError("source review cannot be later than prepared_at")
        if self.source_event_ids != list(dict.fromkeys(item.earnings_event_id for item in self.source_reviews)):
            raise ValueError("source_event_ids must match source reviews in input order")
        known_reviews = set(review_ids)
        for collection in (
            self.maintain_criteria,
            self.weaken_candidates,
            self.next_event_checks,
            self.rejected_assumptions,
            self.recurring_errors_to_prevent,
        ):
            for item in collection:
                if item.occurrence_count != len(item.source_review_ids):
                    raise ValueError("occurrence_count must equal distinct source review count")
                if len(item.source_review_ids) != len(set(item.source_review_ids)):
                    raise ValueError("carryover source review IDs must be unique")
                if not set(item.source_review_ids).issubset(known_reviews):
                    raise ValueError("carryover source review ID is unknown")
        return self
