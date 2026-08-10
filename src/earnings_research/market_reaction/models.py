"""Contracts for source-neutral market reaction observations and results."""

from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


ObservationRole = Literal[
    "pre_event_close",
    "pre_announcement_reference",
    "immediate_post_announcement",
    "next_business_day_close",
    "fifth_business_day_close",
]


class PriceSourceReference(BaseModel):
    source_name: str = Field(min_length=1)
    source_url_or_identifier: str = Field(min_length=1)
    source_checked_at: datetime
    recorded_by: str
    terms_status: Literal["approved", "system_policy", "manual_fallback"]
    terms_basis: str = Field(min_length=1)


class VerifiedTradingSession(BaseModel):
    trading_date: date
    regular_open: datetime
    regular_close: datetime

    @model_validator(mode="after")
    def validate_session(self):
        if self.trading_date.weekday() >= 5:
            raise ValueError("verified trading session cannot be Saturday or Sunday")
        for value in (self.regular_open, self.regular_close):
            if value.tzinfo is None or value.utcoffset() != timedelta(hours=9):
                raise ValueError("trading session times must use Asia/Tokyo offset")
            if value.date() != self.trading_date:
                raise ValueError("trading session times must match trading_date")
        if self.regular_open >= self.regular_close:
            raise ValueError("regular_open must be before regular_close")
        return self


class PriceObservation(BaseModel):
    observation_id: str
    role: ObservationRole
    price: float = Field(gt=0)
    currency: str
    price_datetime: datetime
    trading_date: date
    price_kind: Literal[
        "official_close",
        "official_open",
        "minute_bar_close",
        "vwap_after_announcement",
        "manual_trade_price",
    ]
    selection_rule: str = Field(min_length=1)
    bar_interval_minutes: Optional[int] = Field(default=None, gt=0)
    vwap_window: Optional[str] = None
    is_unadjusted: Literal[True] = True
    source: PriceSourceReference
    raw_data_retained: Literal[False] = False

    @model_validator(mode="after")
    def validate_role_kind(self):
        if self.price_datetime.tzinfo is None:
            raise ValueError("price_datetime must include timezone")
        if self.price_datetime.utcoffset() != timedelta(hours=9):
            raise ValueError("price_datetime must use Asia/Tokyo offset")
        if self.source.source_checked_at.tzinfo is None:
            raise ValueError("source_checked_at must include timezone")
        if self.price_datetime.date() != self.trading_date:
            raise ValueError("trading_date must match price_datetime date")
        if self.source.source_checked_at < self.price_datetime:
            raise ValueError("source_checked_at must not be before price_datetime")
        if self.role in {"pre_event_close", "next_business_day_close", "fifth_business_day_close"}:
            if self.price_kind != "official_close":
                raise ValueError("close milestone requires official_close")
        if self.role == "pre_announcement_reference":
            if self.price_kind not in {"minute_bar_close", "manual_trade_price"}:
                raise ValueError("pre-announcement reference requires minute bar or manual trade price")
        if self.price_kind == "minute_bar_close" and self.bar_interval_minutes is None:
            raise ValueError("minute_bar_close requires bar_interval_minutes")
        if self.price_kind != "minute_bar_close" and self.bar_interval_minutes is not None:
            raise ValueError("bar_interval_minutes is only valid for minute_bar_close")
        if self.price_kind == "vwap_after_announcement" and not self.vwap_window:
            raise ValueError("vwap_after_announcement requires vwap_window")
        if self.price_kind != "vwap_after_announcement" and self.vwap_window is not None:
            raise ValueError("vwap_window is only valid for vwap_after_announcement")
        return self


class MarketReactionObservationBundle(BaseModel):
    schema_version: Literal["market_reaction_observations_v1"] = "market_reaction_observations_v1"
    tracking_id: str
    earnings_event_id: str
    evaluation_id: str
    company_name: str
    ticker: str
    announcement_datetime: datetime
    announcement_session: Literal["before_open", "intraday", "after_close"]
    market_timezone: Literal["Asia/Tokyo"] = "Asia/Tokyo"
    calendar_name: str
    calendar_source: PriceSourceReference
    verified_sessions: List[VerifiedTradingSession] = Field(min_length=6, max_length=7)
    pre_event_close_date: date
    next_five_session_dates: List[date] = Field(min_length=5, max_length=5)
    corporate_action_status: Literal["none_detected", "present", "unknown"]
    observations: List[PriceObservation] = Field(min_length=1)
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_bundle(self):
        if self.announcement_datetime.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("bundle datetimes must include timezone")
        if self.announcement_datetime.utcoffset() != timedelta(hours=9):
            raise ValueError("announcement_datetime must use Asia/Tokyo offset")
        if self.next_five_session_dates != sorted(set(self.next_five_session_dates)):
            raise ValueError("next_five_session_dates must contain five unique ascending dates")
        if self.next_five_session_dates[0] <= self.announcement_datetime.date():
            raise ValueError("next business-day sessions must be after announcement date")
        session_dates = [item.trading_date for item in self.verified_sessions]
        if session_dates != sorted(set(session_dates)):
            raise ValueError("verified_sessions must contain unique ascending dates")
        required_dates = {
            self.pre_event_close_date,
            self.announcement_datetime.date(),
            *self.next_five_session_dates,
        }
        if set(session_dates) != required_dates:
            raise ValueError("verified_sessions must exactly cover the event price window")
        roles = [item.role for item in self.observations]
        if len(roles) != len(set(roles)):
            raise ValueError("observation roles must be unique")
        ids = [item.observation_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation_id must be unique")
        currencies = {item.currency for item in self.observations}
        if len(currencies) != 1:
            raise ValueError("all price observations must use one currency")
        if any(item.source.source_checked_at > self.recorded_at for item in self.observations):
            raise ValueError("recorded_at must not be before source_checked_at")
        if self.calendar_source.source_checked_at > self.recorded_at:
            raise ValueError("recorded_at must not be before calendar source check")
        return self


class ReactionMilestone(BaseModel):
    role: Literal[
        "pre_event_close",
        "immediate_post_announcement",
        "next_business_day_close",
        "fifth_business_day_close",
    ]
    status: Literal["observed", "pending", "not_comparable"]
    expected_trading_date: date
    observation_id: Optional[str] = None
    price: Optional[float] = None
    price_datetime: Optional[datetime] = None
    source: Optional[PriceSourceReference] = None
    return_from_pre_event_close_pct: Optional[float] = None
    calculation_origin: Optional[Literal["ers_calculated"]] = None
    formula: Optional[str] = None
    note: str


class EventWindowReaction(BaseModel):
    status: Literal["calculated", "pending", "not_comparable"]
    reference_role: Literal["pre_event_close", "pre_announcement_reference"]
    reference_observation_id: Optional[str] = None
    immediate_observation_id: Optional[str] = None
    return_pct: Optional[float] = None
    calculation_origin: Optional[Literal["ers_calculated"]] = None
    formula: Optional[str] = None
    note: str


class MarketReactionSummary(BaseModel):
    immediate_direction: Literal["positive", "negative", "muted", "pending", "not_comparable"]
    next_business_day_direction: Literal["positive", "negative", "muted", "pending", "not_comparable"]
    fifth_business_day_direction: Literal["positive", "negative", "muted", "pending", "not_comparable"]
    reaction_path: Literal["extended", "sustained", "reversed", "muted", "mixed", "pending", "not_comparable"]
    explanation: str


class MarketReactionTracking(BaseModel):
    schema_version: Literal["market_reaction_tracking_v1"] = "market_reaction_tracking_v1"
    tracking_id: str
    earnings_event_id: str
    evaluation_id: str
    company_name: str
    ticker: str
    currency: str
    status: Literal["complete", "tracking", "not_comparable"]
    announcement_datetime: datetime
    announcement_session: Literal["before_open", "intraday", "after_close"]
    calendar_name: str
    corporate_action_status: Literal["none_detected", "present", "unknown"]
    milestones: List[ReactionMilestone]
    event_window_reaction: EventWindowReaction
    summary: MarketReactionSummary
    warnings: List[str] = Field(default_factory=list)
    completed_at: Optional[datetime] = None
    raw_price_data_retained: Literal[False] = False
    trade_decision_included: Literal[False] = False
    next_stage: Literal["ready_for_post_event_validation", "awaiting_price_milestones", "manual_review_required"]
