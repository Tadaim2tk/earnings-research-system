"""Deterministic forecast validation and append-only learning generation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from earnings_research.earnings_evaluation.models import EarningsEvaluation
from earnings_research.market_reaction.models import MarketReactionTracking

from .models import (
    CompanyGuidanceOutcome,
    HypothesisVerification,
    LearningRecord,
    MarketStageAssessment,
    NumericExpectationOutcome,
    PostEventLearningReview,
    ReasonAnalysis,
    SourceRecordReference,
)


def build_post_event_review(
    baseline: Dict[str, str],
    hypothesis_rows: List[Dict[str, str]],
    evaluation: EarningsEvaluation,
    reaction: MarketReactionTracking,
    reviewed_at: datetime,
    previous_review: Optional[PostEventLearningReview] = None,
) -> PostEventLearningReview:
    """Join immutable research snapshots without changing any source record."""
    _validate_identity_and_time(baseline, evaluation, reaction, reviewed_at, previous_review)
    selected, invalidations = _resolve_hypotheses(
        baseline, hypothesis_rows, evaluation.hypothesis_assessments
    )
    source_records = _source_records(baseline, selected, invalidations, evaluation, reaction)
    verifications = _hypothesis_verifications(
        selected, invalidations, evaluation.hypothesis_assessments, evaluation.evaluation_id
    )
    numeric = [
        NumericExpectationOutcome(
            metric_name=item.metric_name,
            expected_value=item.expected_value,
            actual_value=item.actual_value,
            normalized_unit=item.normalized_unit,
            difference=item.difference,
            difference_pct=item.difference_pct,
            result=item.result,
            source_record_id=evaluation.evaluation_id,
        )
        for item in evaluation.metric_comparisons
    ]
    guidance = [
        CompanyGuidanceOutcome(
            metric_name=item.metric_name,
            pre_event_guidance=item.pre_event_guidance,
            announced_guidance=item.announced_guidance,
            revision_pct=item.revision_pct,
            revision=item.revision,
            source_record_id=evaluation.evaluation_id,
        )
        for item in evaluation.guidance_assessments
    ]
    stages = _market_stages(reaction)
    status, next_stage = _review_state(stages)
    overall = _overall_forecast_result(verifications)
    reasons = _reason_analysis(verifications, numeric, guidance, stages, evaluation, reaction)
    learning = _learning_record(verifications, numeric, reasons, evaluation, reaction)
    version = 1 if previous_review is None else previous_review.review_version + 1
    supersedes = None if previous_review is None else previous_review.review_id
    digest = hashlib.sha256(
        f"{evaluation.earnings_event_id}|{evaluation.evaluation_id}|{reaction.tracking_id}|{version}".encode()
    ).hexdigest()[:16]
    limitations = list(dict.fromkeys([
        *evaluation.limitations,
        *reaction.warnings,
        *reasons.missing_or_blocked_reasons,
    ]))
    return PostEventLearningReview(
        review_id=f"PEL-{digest}",
        review_version=version,
        supersedes_review_id=supersedes,
        earnings_event_id=evaluation.earnings_event_id,
        baseline_id=evaluation.baseline_id,
        evaluation_id=evaluation.evaluation_id,
        tracking_id=reaction.tracking_id,
        company_name=evaluation.company_name,
        ticker=evaluation.ticker,
        reviewed_at=reviewed_at,
        status=status,
        overall_forecast_result=overall,
        hypothesis_verifications=verifications,
        earnings_assessment=evaluation.overall_assessment,
        numeric_expectation_outcomes=numeric,
        company_guidance_outcomes=guidance,
        market_stage_assessments=stages,
        reason_analysis=reasons,
        learning_record=learning,
        source_records=source_records,
        limitations=limitations,
        next_stage=next_stage,
    )


def _validate_identity_and_time(baseline, evaluation, reaction, reviewed_at, previous) -> None:
    if evaluation.status != "evaluated" or evaluation.next_stage != "ready_for_market_reaction_tracking":
        raise ValueError("earnings evaluation is not complete")
    if baseline.get("baseline_id") != evaluation.baseline_id:
        raise ValueError("baseline_id does not match earnings evaluation")
    if baseline.get("earnings_event_id") != evaluation.earnings_event_id:
        raise ValueError("baseline earnings_event_id does not match earnings evaluation")
    if baseline.get("is_locked", "").lower() != "true" or baseline.get("uses_post_event_data", "").lower() != "false":
        raise ValueError("post-event review requires an immutable pre-event baseline")
    if baseline.get("baseline_status") not in {None, "", "locked"}:
        raise ValueError("post-event review requires a locked baseline")
    try:
        locked_at = datetime.fromisoformat(baseline["locked_at"])
    except (KeyError, ValueError) as exc:
        raise ValueError("baseline locked_at must be a valid datetime") from exc
    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include timezone")
    if reviewed_at < evaluation.evaluated_at or reviewed_at < reaction.announcement_datetime:
        raise ValueError("post-event review cannot predate its source records")
    pairs = (
        (reaction.evaluation_id, evaluation.evaluation_id, "evaluation_id"),
        (reaction.earnings_event_id, evaluation.earnings_event_id, "earnings_event_id"),
        (reaction.company_name, evaluation.company_name, "company_name"),
        (reaction.ticker, evaluation.ticker, "ticker"),
    )
    for actual, expected, label in pairs:
        if actual != expected:
            raise ValueError(f"market reaction {label} does not match earnings evaluation")
    if locked_at > evaluation.evaluated_at:
        raise ValueError("baseline lock must predate earnings evaluation")
    if previous is not None:
        previous_pairs = (
            (previous.earnings_event_id, evaluation.earnings_event_id, "earnings_event_id"),
            (previous.baseline_id, evaluation.baseline_id, "baseline_id"),
            (previous.evaluation_id, evaluation.evaluation_id, "evaluation_id"),
            (previous.company_name, evaluation.company_name, "company_name"),
            (previous.ticker, evaluation.ticker, "ticker"),
        )
        for actual, expected, label in previous_pairs:
            if actual != expected:
                raise ValueError(f"previous review {label} does not match current sources")
        if reviewed_at <= previous.reviewed_at:
            raise ValueError("new review version must be recorded after the previous version")


def _resolve_hypotheses(baseline, rows, assessments):
    by_id = {row.get("hypothesis_id"): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("hypothesis_id must be unique")
    locked_at = datetime.fromisoformat(baseline["locked_at"])
    selected = []
    for assessment in assessments:
        row = by_id.get(assessment.hypothesis_id)
        if row is None:
            raise ValueError("evaluated hypothesis is missing from hypothesis log")
        if row.get("earnings_event_id") != baseline.get("earnings_event_id"):
            raise ValueError("hypothesis earnings_event_id does not match baseline")
        if row.get("hypothesis_type") != "pre_event":
            raise ValueError("evaluated hypothesis must reference a pre-event record")
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (KeyError, ValueError) as exc:
            raise ValueError("pre-event hypothesis created_at must be valid") from exc
        if created_at > locked_at:
            raise ValueError("post-event hypothesis cannot be presented as a pre-event forecast")
        if row.get("hypothesis_text") != assessment.hypothesis_text:
            raise ValueError("evaluated hypothesis text does not match the immutable source record")
        selected.append(row)
    selected_ids = {row["hypothesis_id"] for row in selected}
    invalidations = [
        row for row in rows
        if row.get("hypothesis_type") == "invalidation"
        and row.get("parent_hypothesis_id") in selected_ids
        and row.get("status") == "invalidated"
    ]
    for row in invalidations:
        if row.get("earnings_event_id") != baseline.get("earnings_event_id"):
            raise ValueError("hypothesis invalidation earnings_event_id does not match baseline")
        recorded_at = row.get("invalidated_at") or row.get("created_at")
        try:
            invalidated_at = datetime.fromisoformat(recorded_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("hypothesis invalidation timestamp must be valid") from exc
        if invalidated_at <= locked_at:
            raise ValueError("post-event invalidation must be recorded after baseline lock")
    return selected, invalidations


def _canonical_hash(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _source_records(baseline, hypotheses, invalidations, evaluation, reaction):
    records = [
        SourceRecordReference(
            record_type="pre_event_baseline",
            record_id=baseline["baseline_id"],
            content_sha256=_canonical_hash(baseline),
            recorded_at=datetime.fromisoformat(baseline["recorded_at"]) if baseline.get("recorded_at") else None,
            declared_record_hash=baseline.get("baseline_record_hash") or None,
        ),
        SourceRecordReference(
            record_type="earnings_evaluation",
            record_id=evaluation.evaluation_id,
            content_sha256=_canonical_hash(evaluation),
            recorded_at=evaluation.evaluated_at,
        ),
        SourceRecordReference(
            record_type="market_reaction_tracking",
            record_id=reaction.tracking_id,
            content_sha256=_canonical_hash(reaction),
            recorded_at=reaction.completed_at,
        ),
    ]
    for row in hypotheses:
        records.append(SourceRecordReference(
            record_type="pre_event_hypothesis",
            record_id=row["hypothesis_id"],
            content_sha256=_canonical_hash(row),
            recorded_at=datetime.fromisoformat(row["created_at"]),
        ))
    for row in invalidations:
        recorded_at = row.get("invalidated_at") or row.get("created_at")
        records.append(SourceRecordReference(
            record_type="hypothesis_invalidation",
            record_id=row["hypothesis_id"],
            content_sha256=_canonical_hash(row),
            recorded_at=datetime.fromisoformat(recorded_at) if recorded_at else None,
        ))
    return records


def _hypothesis_verifications(selected, invalidations, assessments, evaluation_id):
    rows = {row["hypothesis_id"]: row for row in selected}
    invalidations_by_parent: Dict[str, List[Dict[str, str]]] = {}
    for row in invalidations:
        invalidations_by_parent.setdefault(row["parent_hypothesis_id"], []).append(row)
    result_map = {
        "supported": "supported",
        "mixed": "partially_supported",
        "invalidated": "rejected",
        "pending": "pending",
    }
    output = []
    for item in assessments:
        row = rows[item.hypothesis_id]
        children = invalidations_by_parent.get(item.hypothesis_id, [])
        child_ids = [child["hypothesis_id"] for child in children]
        if children:
            condition_status = "triggered"
        elif item.result == "invalidated":
            condition_status = "insufficient_evidence"
        elif _has_explicit_invalidation_condition(row["hypothesis_text"]):
            condition_status = "not_triggered"
        else:
            condition_status = "not_recorded"
        references = list(dict.fromkeys([item.hypothesis_id, *child_ids, evaluation_id]))
        output.append(HypothesisVerification(
            hypothesis_id=item.hypothesis_id,
            hypothesis_text=row["hypothesis_text"],
            result=result_map[item.result],
            explanation=item.explanation,
            supporting_findings=item.supporting_findings,
            contradicting_findings=item.contradicting_findings,
            invalidation_condition_status=condition_status,
            invalidation_record_ids=child_ids,
            source_record_ids=references,
        ))
    return output


def _has_explicit_invalidation_condition(text: str) -> bool:
    lowered = text.lower()
    return "撤回条件:" in text or "撤回条件：" in text or "invalidation condition:" in lowered


def _market_stages(reaction):
    milestones = {item.role: item for item in reaction.milestones}
    definitions = (
        (
            "immediate_post_announcement",
            reaction.event_window_reaction.status,
            reaction.summary.immediate_direction,
            reaction.event_window_reaction.return_pct,
            reaction.event_window_reaction.immediate_observation_id,
        ),
        (
            "next_business_day",
            milestones["next_business_day_close"].status,
            reaction.summary.next_business_day_direction,
            milestones["next_business_day_close"].return_from_pre_event_close_pct,
            milestones["next_business_day_close"].observation_id,
        ),
        (
            "fifth_business_day",
            milestones["fifth_business_day_close"].status,
            reaction.summary.fifth_business_day_direction,
            milestones["fifth_business_day_close"].return_from_pre_event_close_pct,
            milestones["fifth_business_day_close"].observation_id,
        ),
    )
    state_map = {"calculated": "complete", "observed": "complete", "pending": "pending", "not_comparable": "not_comparable"}
    return [
        MarketStageAssessment(
            stage=stage,
            status=state_map[status],
            direction=direction,
            return_pct=value,
            observation_id=observation_id,
            source_record_id=reaction.tracking_id,
        )
        for stage, status, direction, value, observation_id in definitions
    ]


def _review_state(stages):
    statuses = {item.status for item in stages}
    if "not_comparable" in statuses:
        return "blocked", "comparison_blocked"
    if "pending" in statuses:
        return "provisional", "awaiting_market_milestones"
    return "complete", "learning_record_ready"


def _overall_forecast_result(verifications):
    results = [item.result for item in verifications]
    if not results or set(results) == {"pending"}:
        return "pending"
    if set(results) == {"supported"}:
        return "success"
    if set(results) == {"rejected"}:
        return "failure"
    return "partial_success"


def _reason_analysis(verifications, numeric, guidance, stages, evaluation, reaction):
    supported = [item.hypothesis_id for item in verifications if item.result == "supported"]
    rejected = [item.hypothesis_id for item in verifications if item.result == "rejected"]
    pending = [item.hypothesis_id for item in verifications if item.result == "pending"]
    above = [item.metric_name for item in numeric if item.result == "above"]
    below = [item.metric_name for item in numeric if item.result == "below"]
    guidance_revisions = [f"{item.metric_name}:{item.revision}" for item in guidance]
    immediate = stages[0]
    earnings = _earnings_direction(evaluation)
    if immediate.status == "not_comparable":
        expectation = "not_comparable"
    elif immediate.status != "complete" or earnings == "inconclusive" or immediate.direction == "muted":
        expectation = "insufficient_evidence"
    elif earnings == "positive" and immediate.direction == "negative":
        expectation = "possible_higher_hurdle_than_recorded"
    elif earnings == "negative" and immediate.direction == "positive":
        expectation = "possible_lower_hurdle_than_recorded"
    else:
        expectation = "earnings_and_market_aligned"
    if reaction.summary.reaction_path == "reversed":
        transition = "reversed_by_fifth_business_day"
    elif immediate.status == "not_comparable":
        transition = "not_comparable"
    elif any(item.status == "pending" for item in stages):
        transition = "pending"
    elif stages[1].direction != immediate.direction and stages[1].direction not in {"muted", "pending"}:
        transition = "changed_by_next_business_day"
    elif len({item.direction for item in stages}) == 1:
        transition = "same_direction"
    else:
        transition = "mixed"
    missing = []
    for item in stages:
        if item.status == "pending":
            missing.append(f"{item.stage}: 価格観測待ち")
        elif item.status == "not_comparable":
            missing.append(f"{item.stage}: corporate actionまたは基準価格により比較不能")
    if not numeric:
        missing.append("数値予想との比較結果がありません。")
    if pending:
        missing.append("一部の事前仮説は証拠不足で未判定です。")
    triggered = [record_id for item in verifications for record_id in item.invalidation_record_ids]
    return ReasonAnalysis(
        supported_hypothesis_ids=supported,
        rejected_hypothesis_ids=rejected,
        pending_hypothesis_ids=pending,
        above_expectation_metrics=above,
        below_expectation_metrics=below,
        guidance_revisions=guidance_revisions,
        company_guidance_read_result=_company_guidance_read(verifications),
        market_expectation_interpretation=expectation,
        reaction_transition=transition,
        triggered_invalidation_record_ids=triggered,
        missing_or_blocked_reasons=missing,
        explanation="事前仮説、決算評価、市場反応を分離したまま照合し、確認できない理由は推測していません。",
    )


def _company_guidance_read(verifications):
    explicit = [
        item for item in verifications
        if "会社予想:" in item.hypothesis_text
        or "会社予想：" in item.hypothesis_text
        or "company guidance:" in item.hypothesis_text.lower()
    ]
    if not explicit:
        return "not_recorded"
    results = {item.result for item in explicit}
    if results == {"supported"}:
        return "supported"
    if results == {"rejected"}:
        return "contradicted"
    if results == {"pending"}:
        return "insufficient_evidence"
    return "mixed"


def _earnings_direction(evaluation):
    if evaluation.overall_assessment == "positive":
        return "positive"
    if evaluation.overall_assessment == "negative":
        return "negative"
    return "inconclusive"


def _learning_record(verifications, numeric, reasons, evaluation, reaction):
    maintain = [item.hypothesis_text for item in verifications if item.result == "supported"]
    weaken = [item.hypothesis_text for item in verifications if item.result in {"partially_supported", "rejected"}]
    additional = [item.hypothesis_text for item in verifications if item.result == "pending"]
    if not numeric:
        additional.append("比較対象となる数値予想")
    errors = []
    if reasons.market_expectation_interpretation in {
        "possible_higher_hurdle_than_recorded",
        "possible_lower_hurdle_than_recorded",
    }:
        errors.append("決算の良否と市場期待の高さを同一視しない。")
    if reasons.reaction_transition in {"changed_by_next_business_day", "reversed_by_fifth_business_day"}:
        errors.append("発表直後だけで反応を確定せず、翌営業日と5営業日後を分けて確認する。")
    if reaction.corporate_action_status != "none_detected":
        errors.append("corporate action未解決時に推測returnを作らない。")
    next_checks = list(additional)
    next_checks.extend(
        f"{name}の予想値と実績値"
        for name in sorted(set(reasons.below_expectation_metrics + reasons.above_expectation_metrics))
    )
    next_checks.extend(reasons.missing_or_blocked_reasons)
    next_checks.extend(f"会社予想の{item.metric_name}変更を再確認" for item in evaluation.guidance_assessments)
    return LearningRecord(
        maintain_criteria=list(dict.fromkeys(maintain)),
        weaken_candidates=list(dict.fromkeys(weaken)),
        additional_indicators=list(dict.fromkeys(additional)),
        recurring_errors_to_prevent=list(dict.fromkeys(errors)),
        supported_but_not_generalized=list(dict.fromkeys(maintain)),
        rejected_assumptions=[item.hypothesis_text for item in verifications if item.result == "rejected"],
        next_event_checks=list(dict.fromkeys(next_checks)),
    )
