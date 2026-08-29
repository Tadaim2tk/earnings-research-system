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

from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_TIMING = "event_timing_provenance_v1"

JST = timezone(timedelta(hours=9))

# Where the announcement falls relative to the session it was made on.
TimingClass = Literal["pre_open", "intraday", "post_close", "non_trading_day", "unknown"]
TIMING_CLASSES = ("pre_open", "intraday", "post_close", "non_trading_day", "unknown")

# Tokyo's session. Written here rather than assumed at each call site, because
# the boundary between pre_open and intraday is the whole classification.
SESSION_OPEN = time(9, 0)
SESSION_CLOSE = time(15, 0)


class TradingCalendar(BaseModel):
    """The sessions, in order. Supplied rather than computed.

    Holidays are not derivable from a date, and a wrong calendar moves every
    entry by a session — which is the error this module exists to remove.
    """

    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(min_length=1)
    sessions: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_calendar(self):
        if self.sessions != sorted(self.sessions):
            raise ValueError("sessions must be in order")
        if len(self.sessions) != len(set(self.sessions)):
            raise ValueError("a session appears twice")
        return self

    def index_of(self, session: str) -> Optional[int]:
        try:
            return self.sessions.index(session)
        except ValueError:
            return None

    def after(self, session: str, offset: int) -> Optional[str]:
        base = self.index_of(session)
        if base is None or not 0 <= base + offset < len(self.sessions):
            return None
        return self.sessions[base + offset]

    def first_open_after(self, moment: datetime) -> Optional[str]:
        """The first session whose open is strictly after this instant.

        Where a position can first be opened, once the information exists. An
        announcement at 08:00 JST reaches that session's own open; one at 16:00
        reaches the next.

        Strictly after, not at-or-after. At exactly 09:00:00 the disclosure and
        the opening print are simultaneous, so that open is not a price the
        information could be acted on at. With `>=` such an event classified as
        `intraday` and still returned its own session — the same class that
        returns the next session at 12:00 — so one class answered two ways
        depending on the minute. Nothing tested the boundary; a mutation did.
        """
        local = moment.astimezone(JST)
        for session in self.sessions:
            opens = datetime.combine(
                datetime.strptime(session, "%Y-%m-%d").date(), SESSION_OPEN, tzinfo=JST
            )
            if opens > local:
                return session
        return None


def classify(announced_at: datetime, calendar: TradingCalendar) -> TimingClass:
    """Where this instant falls relative to the session it lands on."""
    local = announced_at.astimezone(JST)
    session = local.date().isoformat()
    if calendar.index_of(session) is None:
        return "non_trading_day"
    if local.time() < SESSION_OPEN:
        return "pre_open"
    if local.time() >= SESSION_CLOSE:
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
        return self


def decision_available_at(timing: EventTiming) -> Optional[datetime]:
    """When a person could first have known. The announcement itself."""
    return timing.announced_at


def first_tradeable_session(
    timing: EventTiming, calendar: TradingCalendar
) -> Optional[str]:
    """The first session an order could be filled in.

    This is what `i0+2` was standing in for, and why the substitution was
    fragile: from a post-close announcement the first fill is the next
    session's open, but from a pre-open one it is that same session's, and the
    two differ by a whole bar. An unknown timing yields no session rather than
    a default one.
    """
    if timing.announced_at is None:
        return None
    return calendar.first_open_after(timing.announced_at)


def session_index(timing: EventTiming, calendar: TradingCalendar) -> Optional[int]:
    """How far the first tradeable session sits from the event date.

    Reported so the legacy series can be read against it: a series that assumed
    a fixed offset is comparable only across events whose real offset matches.
    """
    session = first_tradeable_session(timing, calendar)
    if session is None:
        return None
    base = calendar.index_of(timing.event_date)
    target = calendar.index_of(session)
    if base is None or target is None:
        return None
    return target - base
