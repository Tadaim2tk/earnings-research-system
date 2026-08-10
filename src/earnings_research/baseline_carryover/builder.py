"""Deterministic aggregation of prior review learning without promotion."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from datetime import datetime
from typing import Iterable, List, Tuple

from earnings_research.post_event_learning.models import PostEventLearningReview

from .models import (
    BaselineCarryoverContext,
    CarryoverItem,
    MarketEarningsDivergence,
    SourceReviewReference,
)

LEARNING_FIELDS = (
    "maintain_criteria",
    "weaken_candidates",
    "next_event_checks",
    "rejected_assumptions",
    "recurring_errors_to_prevent",
)
_DIVERGENCE_VALUES = {
    "possible_higher_hurdle_than_recorded",
    "possible_lower_hurdle_than_recorded",
}


def canonical_json_sha256(value) -> str:
    """Use the same canonical JSON representation as post_event_learning."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_baseline_carryover(
    reviews: Iterable[Tuple[PostEventLearningReview, str]],
    target_event_id: str,
    prepared_at: datetime,
) -> BaselineCarryoverContext:
    """Build reference-only context from validated, immutable review snapshots."""
    review_inputs = list(reviews)
    if not review_inputs:
        raise ValueError("at least one post-event learning review is required")
    if not target_event_id:
        raise ValueError("target_event_id must not be empty")
    if prepared_at.tzinfo is None:
        raise ValueError("prepared_at must include timezone")

    models = [item[0] for item in review_inputs]
    review_ids = [item.review_id for item in models]
    if len(review_ids) != len(set(review_ids)):
        raise ValueError("review_id must be unique")
    identities = {(item.company_name, item.ticker) for item in models}
    if len(identities) != 1:
        raise ValueError("reviews from different companies cannot be mixed")
    for review in models:
        if review.reviewed_at > prepared_at:
            raise ValueError("reviewed_at cannot be later than prepared_at")
        if any(source.recorded_at and source.recorded_at > prepared_at for source in review.source_records):
            raise ValueError("review source recorded_at cannot be later than prepared_at")

    fields = {field: _aggregate_learning(models, field) for field in LEARNING_FIELDS}
    return BaselineCarryoverContext(
        target_event_id=target_event_id,
        prepared_at=prepared_at,
        source_event_ids=list(dict.fromkeys(item.earnings_event_id for item in models)),
        source_reviews=[
            SourceReviewReference(
                review_id=review.review_id,
                earnings_event_id=review.earnings_event_id,
                reviewed_at=review.reviewed_at,
                content_sha256=digest,
            )
            for review, digest in review_inputs
        ],
        market_earnings_divergence_history=_aggregate_divergences(models),
        **fields,
    )


def _aggregate_learning(reviews: List[PostEventLearningReview], field: str) -> List[CarryoverItem]:
    observed = OrderedDict()
    for review in reviews:
        for text in getattr(review.learning_record, field):
            sources = observed.setdefault(text, [])
            if review.review_id not in sources:
                sources.append(review.review_id)
    return [
        CarryoverItem(text=text, occurrence_count=len(source_ids), source_review_ids=source_ids)
        for text, source_ids in observed.items()
    ]


def _aggregate_divergences(reviews: List[PostEventLearningReview]) -> List[MarketEarningsDivergence]:
    observed = OrderedDict()
    for review in reviews:
        interpretation = review.reason_analysis.market_expectation_interpretation
        if interpretation not in _DIVERGENCE_VALUES:
            continue
        key = (review.earnings_assessment, interpretation, review.reason_analysis.reaction_transition)
        source_reviews, source_events = observed.setdefault(key, ([], []))
        if review.review_id not in source_reviews:
            source_reviews.append(review.review_id)
        if review.earnings_event_id not in source_events:
            source_events.append(review.earnings_event_id)
    return [
        MarketEarningsDivergence(
            earnings_assessment=key[0],
            market_expectation_interpretation=key[1],
            reaction_transition=key[2],
            occurrence_count=len(source_reviews),
            source_review_ids=source_reviews,
            source_event_ids=source_events,
        )
        for key, (source_reviews, source_events) in observed.items()
    ]
