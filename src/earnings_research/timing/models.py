"""The announcement instant, and what follows from it.

Every return series in this repository counts sessions from `i0`, the calendar
session of the announcement date, and reads `i0+2`'s open as the price an order
fills at. That reading holds only if the disclosure lands after `i0`'s close.
`LEGACY_OS_INTEGRATION.md` says the record cannot establish it: there is no
announcement session, and `date` may be a before-open, intraday or after-close
event. Measured on the sessions themselves, 26 of 245 events show their move on
`i0` rather than in `i0+1`'s gap — evidence that the assumption is not uniform,
though a large move has other causes and this is not proof either way.

So the calendar index is the wrong anchor. What decides when a position can be
opened is the moment the information became available, and the session that
begins after it.

**`unknown` is a state, not a gap to fill.** An event whose announcement time
cannot be established stays `unknown`; it is never rounded to `post_close`
because that is the common case. Guessing here would put a made-up decision
time under a return series and there would be nothing to distinguish it from a
measured one — the same reason `undeclared` exists in the source-validity
ledger and `capture_status` in the evidence bundles.
"""

from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from earnings_research.market_reaction.models import VerifiedTradingSession

SCHEMA_TIMING = "event_timing_provenance_v1"

JST = timezone(timedelta(hours=9))

# Where the announcement falls relative to the session it was made on.
TimingClass = Literal["pre_open", "intraday", "post_close", "non_trading_day", "unknown"]
TIMING_CLASSES = ("pre_open", "intraday", "post_close", "non_trading_day", "unknown")

class TradingCalendar(BaseModel):
    """The sessions, in order, each with the hours it actually kept.

    Built on `VerifiedTradingSession` rather than on a list of dates and a pair
    of module constants. The constants were wrong: this wrote a 15:00 close
    while the repository's own verified fixtures use 15:30, which is the hour
    the exchange has kept since it extended the afternoon session. Every
    disclosure between 15:00 and 15:30 would have been filed as `post_close`
    and routed to the next session.

    Hours belong to a date for the same reason holidays do — they change, and a
    constant cannot say when. Using the existing model also means a calendar
    entry is a real date by construction, where a list of strings accepted
    "2026-02-30" and failed later inside `strptime`.
    """

    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(min_length=1)
    sessions: List[VerifiedTradingSession] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_calendar(self):
        dates = [item.trading_date for item in self.sessions]
        if dates != sorted(dates):
            raise ValueError("sessions must be in order")
        if len(dates) != len(set(dates)):
            raise ValueError("a session appears twice")
        return self

    def _dates(self) -> List[date]:
        return [item.trading_date for item in self.sessions]

    def session_on(self, day: date) -> Optional[VerifiedTradingSession]:
        for item in self.sessions:
            if item.trading_date == day:
                return item
        return None

    def index_of(self, day: date) -> Optional[int]:
        try:
            return self._dates().index(day)
        except ValueError:
            return None

    def first_open_after(self, moment: datetime) -> Optional[date]:
        """The first session whose open is strictly after this instant.

        Strictly after, not at-or-after. At exactly the opening bell the
        disclosure and the opening print are simultaneous, so that open is not
        a price the information could be acted on at. With `>=` such an event
        classified as `intraday` and still returned its own session — the same
        class that returns the next session an hour later — so one class
        answered two ways depending on the minute. Nothing tested the boundary;
        a mutation did.
        """
        for item in self.sessions:
            if item.regular_open > moment:
                return item.trading_date
        return None

    def session_in_progress_or_next(self, moment: datetime) -> Optional[date]:
        """The session a position could first be opened in.

        Not the same question as the one above. An intraday disclosure can be
        acted on immediately — at the next print, at VWAP, at the close — so
        the session it lands in is tradeable even though its opening price is
        already behind. Only the *opening print* is unavailable, and the
        repository's own intraday workflow records minute or VWAP prices on the
        announcement date for exactly that reason.
        """
        for item in self.sessions:
            if item.regular_close > moment:
                return item.trading_date
        return None


def classify(announced_at: datetime, calendar: TradingCalendar) -> TimingClass:
    """Where this instant falls relative to the session it lands on.

    Read off that date's own hours. A close written as a constant was wrong by
    thirty minutes for every contemporary event.
    """
    local = announced_at.astimezone(JST)
    session = calendar.session_on(local.date())
    if session is None:
        return "non_trading_day"
    if local < session.regular_open:
        return "pre_open"
    if local >= session.regular_close:
        return "post_close"
    return "intraday"


class EventTiming(BaseModel):
    """When one event's information became available, and where that came from.

    The provenance is not decoration. An announcement time with no source is a
    number somebody typed, and the whole point of establishing these is that
    the return series stop resting on an assumption nobody measured.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["event_timing_provenance_v1"] = SCHEMA_TIMING
    event_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    event_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    timing_class: TimingClass
    announced_at: Optional[datetime] = None
    announced_at_timezone: Optional[str] = None
    source: Optional[str] = Field(default=None, min_length=1)
    source_url: Optional[str] = None
    source_observed_at: Optional[datetime] = None
    evidence_bundle_id: Optional[str] = None
    note: Optional[str] = None

    @model_validator(mode="after")
    def validate_timing(self):
        if self.timing_class == "unknown":
            # Nothing is carried on an unknown, so a later reader cannot mistake
            # a leftover value for a determination. The absence is the record.
            if self.announced_at is not None or self.source is not None:
                raise ValueError(
                    "an unknown timing carries no instant and no source; "
                    "if either is known, the class is not unknown"
                )
            return self
        if self.announced_at is None:
            raise ValueError("a classified timing has to say when")
        if self.announced_at.tzinfo is None:
            raise ValueError("announced_at must include timezone")
        if not self.source:
            raise ValueError(
                "a classified timing has to say where it came from; an instant "
                "with no source is a number somebody typed"
            )
        if self.source_observed_at is None:
            raise ValueError("a source has to say when it was read")
        if self.source_observed_at.tzinfo is None:
            raise ValueError("source_observed_at must include timezone")
        if self.announced_at.astimezone(JST).date().isoformat() != self.event_date:
            raise ValueError("announced_at falls on a different day from event_date")
        if self.source_observed_at < self.announced_at:
            # A schedule read before the event is not confirmation that the
            # event happened. Recorded the other way round, an expectation
            # becomes provenance for an occurrence.
            raise ValueError(
                "source_observed_at precedes announced_at; a source read before "
                "the announcement cannot confirm that it occurred"
            )
        return self

    def agrees_with(self, calendar: "TradingCalendar") -> bool:
        """Whether the recorded class is the one this instant actually falls in.

        Not enforced by the model, because a timing is built without a calendar
        and the calendar is what decides. Checked wherever both are in hand —
        `verify_against` below — because a payload claiming `post_close` over an
        08:00 instant would let a consumer cohort it one way while the derived
        entry behaves the other.
        """
        if self.timing_class == "unknown" or self.announced_at is None:
            return self.timing_class == "unknown"
        return classify(self.announced_at, calendar) == self.timing_class


def decision_available_at(timing: EventTiming) -> Optional[datetime]:
    """When a person could first have known. The announcement itself."""
    return timing.announced_at


def first_tradeable_session(
    timing: EventTiming, calendar: TradingCalendar
) -> Optional[date]:
    """The session a position could first be opened in.

    For a disclosure before the open, that session. For one during it, **that
    same session** — the information can be acted on at the next print, at
    VWAP, or at the close, which is what the intraday workflow already records.
    For one after the close, the next session.

    An earlier version returned the next session for intraday too, because it
    was really answering the question below and had been given this name. The
    two differ by a whole bar for every intraday event.
    """
    if timing.announced_at is None:
        return None
    return calendar.session_in_progress_or_next(timing.announced_at.astimezone(JST))


def first_open_anchored_session(
    timing: EventTiming, calendar: TradingCalendar
) -> Optional[date]:
    """The first session whose *opening print* can serve as an entry price.

    What `i0+2` was standing in for. For an intraday disclosure this is the
    next session even though the current one is tradeable, because that
    session's open has already happened.
    """
    if timing.announced_at is None:
        return None
    return calendar.first_open_after(timing.announced_at.astimezone(JST))


def session_index(timing: EventTiming, calendar: TradingCalendar) -> Optional[int]:
    """How far the first tradeable session sits from the event date."""
    return _offset(timing, calendar, first_tradeable_session(timing, calendar))


def open_anchored_index(timing: EventTiming, calendar: TradingCalendar) -> Optional[int]:
    """The same, for the first usable opening print.

    Reported beside `session_index` so a legacy series built on a fixed offset
    can be read against the offset each event actually had.
    """
    return _offset(timing, calendar, first_open_anchored_session(timing, calendar))


def _offset(
    timing: EventTiming, calendar: TradingCalendar, session: Optional[date]
) -> Optional[int]:
    if session is None:
        return None
    base = calendar.index_of(date.fromisoformat(timing.event_date))
    target = calendar.index_of(session)
    if base is None or target is None:
        return None
    return target - base


def verify_against(timing: EventTiming, calendar: TradingCalendar) -> None:
    """Refuse a timing whose recorded class contradicts its own instant."""
    if not timing.agrees_with(calendar):
        raise ValueError(
            "%s is recorded as %s but %s falls in %s"
            % (
                timing.event_id,
                timing.timing_class,
                timing.announced_at.isoformat() if timing.announced_at else "no instant",
                classify(timing.announced_at, calendar) if timing.announced_at else "unknown",
            )
        )
