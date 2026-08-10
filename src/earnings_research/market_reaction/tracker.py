"""Deterministic calculation of earnings-event market reaction milestones."""

from datetime import datetime
from typing import Dict, List, Optional

from earnings_research.earnings_evaluation.models import EarningsEvaluation
from earnings_research.market_reaction.models import (
    EventWindowReaction,
    MarketReactionObservationBundle,
    MarketReactionSummary,
    MarketReactionTracking,
    PriceObservation,
    ReactionMilestone,
)


MILESTONE_ROLES = (
    "pre_event_close",
    "immediate_post_announcement",
    "next_business_day_close",
    "fifth_business_day_close",
)


def track_market_reaction(
    bundle: MarketReactionObservationBundle,
    evaluation: EarningsEvaluation,
) -> MarketReactionTracking:
    """Create a reaction snapshot without retrieving or retaining raw price data."""
    _validate_identity(bundle, evaluation)
    observations = {item.role: item for item in bundle.observations}
    _validate_timing(bundle, observations)
    warnings = []
    comparable = bundle.corporate_action_status == "none_detected"
    if not comparable:
        warnings.append("価格窓内のcorporate actionが未解決のため、returnを計算しません。")

    pre_close = observations.get("pre_event_close")
    expected_dates = {
        "pre_event_close": bundle.pre_event_close_date,
        "immediate_post_announcement": _immediate_expected_date(bundle),
        "next_business_day_close": bundle.next_five_session_dates[0],
        "fifth_business_day_close": bundle.next_five_session_dates[4],
    }
    milestones = [
        _milestone(role, expected_dates[role], observations.get(role), pre_close, comparable)
        for role in MILESTONE_ROLES
    ]
    event_window = _event_window(bundle, observations, comparable)
    summary = _summarize(milestones, event_window)
    observed_required = all(item.status == "observed" for item in milestones)
    if not comparable:
        status = "not_comparable"
        next_stage = "manual_review_required"
        completed_at = None
    elif observed_required and event_window.status == "calculated":
        status = "complete"
        next_stage = "ready_for_post_event_validation"
        completed_at = bundle.recorded_at
    else:
        status = "tracking"
        next_stage = "awaiting_price_milestones"
        completed_at = None

    return MarketReactionTracking(
        tracking_id=bundle.tracking_id,
        earnings_event_id=bundle.earnings_event_id,
        evaluation_id=bundle.evaluation_id,
        company_name=bundle.company_name,
        ticker=bundle.ticker,
        currency=bundle.observations[0].currency,
        status=status,
        announcement_datetime=bundle.announcement_datetime,
        announcement_session=bundle.announcement_session,
        calendar_name=bundle.calendar_name,
        corporate_action_status=bundle.corporate_action_status,
        milestones=milestones,
        event_window_reaction=event_window,
        summary=summary,
        warnings=warnings,
        completed_at=completed_at,
        next_stage=next_stage,
    )


def _validate_identity(bundle, evaluation) -> None:
    if evaluation.status != "evaluated" or evaluation.next_stage != "ready_for_market_reaction_tracking":
        raise ValueError("earnings evaluation is not ready for market reaction tracking")
    pairs = (
        (bundle.evaluation_id, evaluation.evaluation_id, "evaluation_id"),
        (bundle.earnings_event_id, evaluation.earnings_event_id, "earnings_event_id"),
        (bundle.ticker, evaluation.ticker, "ticker"),
        (bundle.company_name, evaluation.company_name, "company_name"),
    )
    for observed, expected, label in pairs:
        if observed != expected:
            raise ValueError("%s does not match earnings evaluation" % label)
    if bundle.recorded_at < evaluation.evaluated_at:
        raise ValueError("market reaction bundle cannot predate earnings evaluation")


def _validate_timing(
    bundle: MarketReactionObservationBundle,
    observations: Dict[str, PriceObservation],
) -> None:
    pre_close = observations.get("pre_event_close")
    if pre_close:
        if pre_close.trading_date != bundle.pre_event_close_date:
            raise ValueError("pre-event close date does not match calendar input")
        if pre_close.price_datetime >= bundle.announcement_datetime:
            raise ValueError("pre-event close must be strictly before announcement")
    pre_announcement = observations.get("pre_announcement_reference")
    if bundle.announcement_session == "intraday":
        if pre_announcement is None:
            raise ValueError("intraday event requires pre-announcement reference")
        if not (pre_announcement.price_datetime < bundle.announcement_datetime):
            raise ValueError("pre-announcement reference must be strictly before announcement")
        if pre_announcement.trading_date != bundle.announcement_datetime.date():
            raise ValueError("intraday pre-announcement reference must be on announcement date")
    elif pre_announcement is not None:
        raise ValueError("pre-announcement reference is only valid for intraday events")

    immediate = observations.get("immediate_post_announcement")
    if immediate:
        if immediate.price_datetime <= bundle.announcement_datetime:
            raise ValueError("immediate reaction price must be after announcement")
        if immediate.trading_date != _immediate_expected_date(bundle):
            raise ValueError("immediate reaction date does not match announcement session")
        allowed = {
            "before_open": {"official_open", "manual_trade_price"},
            "intraday": {"minute_bar_close", "vwap_after_announcement", "manual_trade_price"},
            "after_close": {"official_open", "manual_trade_price"},
        }[bundle.announcement_session]
        if immediate.price_kind not in allowed:
            raise ValueError("immediate price kind does not match announcement session")
    next_close = observations.get("next_business_day_close")
    if next_close and next_close.trading_date != bundle.next_five_session_dates[0]:
        raise ValueError("next-business-day close does not match trading calendar")
    fifth_close = observations.get("fifth_business_day_close")
    if fifth_close and fifth_close.trading_date != bundle.next_five_session_dates[4]:
        raise ValueError("fifth-business-day close does not match trading calendar")


def _immediate_expected_date(bundle: MarketReactionObservationBundle):
    if bundle.announcement_session == "after_close":
        return bundle.next_five_session_dates[0]
    return bundle.announcement_datetime.date()


def _return_pct(price: float, reference: float) -> float:
    return round((price / reference - 1) * 100, 4)


def _milestone(
    role: str,
    expected_date,
    observation: Optional[PriceObservation],
    pre_close: Optional[PriceObservation],
    comparable: bool,
) -> ReactionMilestone:
    if observation is None:
        return ReactionMilestone(
            role=role,
            status="pending",
            expected_trading_date=expected_date,
            note="価格観測待ちです。",
        )
    if role == "pre_event_close":
        return ReactionMilestone(
            role=role,
            status="observed" if comparable else "not_comparable",
            expected_trading_date=expected_date,
            observation_id=observation.observation_id,
            price=observation.price,
            price_datetime=observation.price_datetime,
            source=observation.source,
            note="発表前のregular-session終値です。",
        )
    if not comparable or pre_close is None:
        return ReactionMilestone(
            role=role,
            status="not_comparable" if not comparable else "pending",
            expected_trading_date=expected_date,
            observation_id=observation.observation_id,
            price=observation.price,
            price_datetime=observation.price_datetime,
            source=observation.source,
            note="比較可能な発表前終値がありません。" if comparable else "corporate action確認待ちです。",
        )
    return ReactionMilestone(
        role=role,
        status="observed",
        expected_trading_date=expected_date,
        observation_id=observation.observation_id,
        price=observation.price,
        price_datetime=observation.price_datetime,
        source=observation.source,
        return_from_pre_event_close_pct=_return_pct(observation.price, pre_close.price),
        calculation_origin="ers_calculated",
        formula="(milestone_price / pre_event_close - 1) * 100",
        note="発表前終値を基準に計算しました。",
    )


def _event_window(bundle, observations, comparable) -> EventWindowReaction:
    reference_role = "pre_announcement_reference" if bundle.announcement_session == "intraday" else "pre_event_close"
    reference = observations.get(reference_role)
    immediate = observations.get("immediate_post_announcement")
    if not comparable:
        status = "not_comparable"
        note = "corporate action確認待ちのため計算しません。"
    elif reference is None or immediate is None:
        status = "pending"
        note = "発表直前または直後の価格観測待ちです。"
    else:
        return EventWindowReaction(
            status="calculated",
            reference_role=reference_role,
            reference_observation_id=reference.observation_id,
            immediate_observation_id=immediate.observation_id,
            return_pct=_return_pct(immediate.price, reference.price),
            calculation_origin="ers_calculated",
            formula="(immediate_price / event_window_reference - 1) * 100",
            note="発表sessionに対応する直前価格を基準に計算しました。",
        )
    return EventWindowReaction(status=status, reference_role=reference_role, note=note)


def _direction(value: Optional[float], status: str, tolerance: float = 0.5) -> str:
    if status == "not_comparable":
        return "not_comparable"
    if value is None:
        return "pending"
    if value > tolerance:
        return "positive"
    if value < -tolerance:
        return "negative"
    return "muted"


def _summarize(milestones, event_window) -> MarketReactionSummary:
    by_role = {item.role: item for item in milestones}
    immediate_direction = _direction(event_window.return_pct, event_window.status)
    next_item = by_role["next_business_day_close"]
    fifth_item = by_role["fifth_business_day_close"]
    next_direction = _direction(next_item.return_from_pre_event_close_pct, next_item.status)
    fifth_direction = _direction(fifth_item.return_from_pre_event_close_pct, fifth_item.status)
    if "not_comparable" in {immediate_direction, next_direction, fifth_direction}:
        path = "not_comparable"
        explanation = "corporate actionまたは基準価格の問題により比較を確定できません。"
    elif "pending" in {immediate_direction, next_direction, fifth_direction}:
        path = "pending"
        explanation = "必要な価格時点が揃うまで反応経路を確定しません。"
    elif immediate_direction == next_direction == fifth_direction == "muted":
        path = "muted"
        explanation = "各時点の反応は許容幅内です。"
    elif immediate_direction in {"positive", "negative"} and fifth_direction not in {immediate_direction, "muted"}:
        path = "reversed"
        explanation = "発表直後と5営業日後で反応方向が反転しました。"
    elif immediate_direction == fifth_direction and immediate_direction in {"positive", "negative"}:
        immediate_abs = abs(event_window.return_pct or 0)
        fifth_abs = abs(fifth_item.return_from_pre_event_close_pct or 0)
        path = "extended" if fifth_abs > immediate_abs else "sustained"
        explanation = "初期反応と5営業日後の方向が一致しています。"
    else:
        path = "mixed"
        explanation = "各時点の方向が一様ではありません。"
    return MarketReactionSummary(
        immediate_direction=immediate_direction,
        next_business_day_direction=next_direction,
        fifth_business_day_direction=fifth_direction,
        reaction_path=path,
        explanation=explanation,
    )
