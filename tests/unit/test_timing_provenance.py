"""When the information became available, and therefore when it could be acted on.

Every return series here counts sessions from the calendar date and reads
`i0+2`'s open as the fill. That holds only if the disclosure lands after
`i0`'s close, and the record cannot establish that — 26 of 245 events show
their move on `i0` itself. The calendar index is the wrong anchor; the
announcement instant is the right one.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from earnings_research.market_reaction.models import VerifiedTradingSession
from earnings_research.timing import (
    TIMING_CLASSES,
    EventTiming,
    TradingCalendar,
    classify,
    first_open_anchored_session,
    first_tradeable_session,
    open_anchored_index,
    session_index,
    verify_against,
)
from earnings_research.timing.models import JST, decision_available_at

# 2026-09-01 火 から。09-05 土 / 09-06 日 は非取引日として抜いてある。
# 大引けは 15:30 — 取引所が午後場を延長して以降の時刻で、この repository の
# 既存 fixture もこれを使う。定数で 15:00 と書いていたのが元の誤り。
DAYS = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
        "2026-09-07", "2026-09-08", "2026-09-09"]
CALENDAR = TradingCalendar(
    calendar_id="TSE-fixture",
    sessions=[
        VerifiedTradingSession(
            trading_date=date.fromisoformat(day),
            regular_open=datetime.fromisoformat(day + "T09:00:00+09:00"),
            regular_close=datetime.fromisoformat(day + "T15:30:00+09:00"),
        )
        for day in DAYS
    ],
)


def at(day, hour, minute=0):
    return datetime.fromisoformat("%sT%02d:%02d:00+09:00" % (day, hour, minute))


def timing(hour, minute=0, day="2026-09-01", **changes):
    moment = at(day, hour, minute)
    payload = {
        "event_id": "EV-1", "ticker": "1234", "event_date": day,
        "announced_at": moment, "announced_at_timezone": "Asia/Tokyo",
        "source": "fixture-disclosure",
        "source_observed_at": moment + timedelta(days=9),
        "timing_class": classify(moment, CALENDAR),
    }
    payload.update(changes)
    return EventTiming(**payload)


# --- classification reads the session's own hours ---------------------------

@pytest.mark.parametrize("hour,minute,expected", [
    (8, 0, "pre_open"), (8, 59, "pre_open"),
    (9, 0, "intraday"), (12, 0, "intraday"),
    # 15:00–15:29 is still the session. Written as a constant this was
    # `post_close`, and every disclosure in that half hour went to the wrong
    # cohort and the wrong reference window.
    (15, 0, "intraday"), (15, 29, "intraday"),
    (15, 30, "post_close"), (16, 30, "post_close"),
])
def test_where_the_announcement_falls_in_its_session(hour, minute, expected):
    assert classify(at("2026-09-01", hour, minute), CALENDAR) == expected


def test_the_close_comes_from_the_dated_calendar_and_not_from_a_constant():
    """Hours belong to a date for the same reason holidays do: they change, and
    a constant cannot say when. A session ending at 15:00 classifies 15:10 the
    other way, on the same code."""
    short = TradingCalendar(
        calendar_id="short-day",
        sessions=[VerifiedTradingSession(
            trading_date=date(2026, 9, 1),
            regular_open=at("2026-09-01", 9, 0),
            regular_close=at("2026-09-01", 15, 0),
        )],
    )
    moment = at("2026-09-01", 15, 10)
    assert classify(moment, CALENDAR) == "intraday"
    assert classify(moment, short) == "post_close"


def test_an_announcement_on_a_day_with_no_session_is_its_own_class():
    assert classify(at("2026-09-05", 10), CALENDAR) == "non_trading_day"


def test_a_calendar_entry_is_a_real_date_by_construction():
    """A list of strings accepted "2026-02-30" and failed later inside
    `strptime`; the session model refuses it at the boundary."""
    with pytest.raises(ValidationError):
        VerifiedTradingSession(
            trading_date="2026-02-30",
            regular_open=at("2026-09-01", 9), regular_close=at("2026-09-01", 15, 30),
        )
    with pytest.raises(ValidationError, match="in order"):
        TradingCalendar(calendar_id="x", sessions=list(reversed(CALENDAR.sessions))[:2])


# --- unknown is a state -----------------------------------------------------

def test_an_unknown_timing_carries_nothing_that_could_be_mistaken_for_one():
    unknown = EventTiming(
        event_id="EV-2", ticker="5678", event_date="2026-09-01", timing_class="unknown"
    )
    assert unknown.announced_at is None and unknown.source is None
    assert decision_available_at(unknown) is None
    assert first_tradeable_session(unknown, CALENDAR) is None
    assert first_open_anchored_session(unknown, CALENDAR) is None
    assert session_index(unknown, CALENDAR) is None
    with pytest.raises(ValidationError, match="carries no instant and no source"):
        EventTiming(
            event_id="EV-2", ticker="5678", event_date="2026-09-01",
            timing_class="unknown", announced_at=at("2026-09-01", 16),
        )
    assert "unknown" in TIMING_CLASSES


# --- provenance -------------------------------------------------------------

def test_a_classified_timing_has_to_say_where_it_came_from():
    with pytest.raises(ValidationError, match="has to say where it came from"):
        timing(16, source=None)
    with pytest.raises(ValidationError, match="when it was read"):
        timing(16, source_observed_at=None)
    with pytest.raises(ValidationError, match="has to say when"):
        timing(16, announced_at=None)


def test_a_source_read_before_the_announcement_cannot_confirm_it_happened():
    """A schedule read in advance is an expectation. Recorded as provenance it
    becomes confirmation that publication occurred at the scheduled instant."""
    with pytest.raises(ValidationError, match="cannot confirm that it occurred"):
        timing(16, source_observed_at=at("2026-09-01", 12))


def test_the_instant_has_to_fall_on_the_day_the_event_is_recorded_under():
    with pytest.raises(ValidationError, match="different day from event_date"):
        timing(16, announced_at=at("2026-09-02", 16))


def test_a_class_that_contradicts_its_own_instant_is_refused():
    """Nothing stopped a payload claiming `post_close` over an 08:00 instant.
    A consumer would cohort it one way while the derived entry behaved the
    other."""
    contradictory = timing(8, timing_class="post_close")
    assert not contradictory.agrees_with(CALENDAR)
    with pytest.raises(ValueError, match="recorded as post_close"):
        verify_against(contradictory, CALENDAR)
    verify_against(timing(8), CALENDAR)


# --- the two derived sessions are different questions ------------------------

@pytest.mark.parametrize("hour,minute,tradeable,open_anchored", [
    (8, 0, "2026-09-01", "2026-09-01"),
    (8, 59, "2026-09-01", "2026-09-01"),
    # Tradeable now — at the next print, at VWAP, at the close. Only the
    # opening print is behind.
    (9, 0, "2026-09-01", "2026-09-02"),
    (12, 0, "2026-09-01", "2026-09-02"),
    (15, 29, "2026-09-01", "2026-09-02"),
    (15, 30, "2026-09-02", "2026-09-02"),
    (18, 0, "2026-09-02", "2026-09-02"),
])
def test_being_tradeable_and_having_a_usable_open_are_not_the_same(
    hour, minute, tradeable, open_anchored
):
    """The two answers differ for every intraday event, by a whole bar.

    One function used to answer both under the name of the first. The
    repository's own intraday workflow records minute or VWAP prices on the
    announcement date, which is the behaviour that name promises.
    """
    item = timing(hour, minute)
    assert first_tradeable_session(item, CALENDAR) == date.fromisoformat(tradeable)
    assert first_open_anchored_session(item, CALENDAR) == date.fromisoformat(open_anchored)


def test_the_offsets_are_reported_for_both():
    intraday = timing(12)
    assert session_index(intraday, CALENDAR) == 0
    assert open_anchored_index(intraday, CALENDAR) == 1
    after = timing(18)
    assert session_index(after, CALENDAR) == 1
    assert open_anchored_index(after, CALENDAR) == 1


def test_an_announcement_over_a_closed_weekend_skips_to_the_next_session():
    friday_evening = timing(18, day="2026-09-04")
    assert first_tradeable_session(friday_evening, CALENDAR) == date(2026, 9, 7)
    assert session_index(friday_evening, CALENDAR) == 1


def test_the_same_calendar_offset_means_different_things_for_different_classes():
    """The finding this capability exists for.

    Two events on one date, one disclosed before the open and one after the
    close. A series reading `i0+2`'s open for both is one bar past the first
    usable open for one of them and two bars past for the other.
    """
    before, after = timing(8), timing(18)
    assert open_anchored_index(before, CALENDAR) != open_anchored_index(after, CALENDAR)


def test_an_instant_past_the_end_of_the_calendar_yields_no_session():
    late = timing(18, day="2026-09-09")
    assert first_tradeable_session(late, CALENDAR) is None
    assert first_open_anchored_session(late, CALENDAR) is None
