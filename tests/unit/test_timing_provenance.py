"""When the information became available, and therefore when it could be acted on.

Every return series here counts sessions from the calendar date and reads
`i0+2`'s open as the fill. That holds only if the disclosure lands after
`i0`'s close, and the record cannot establish that — 26 of 245 events show
their move on `i0` itself. The calendar index is the wrong anchor; the
announcement instant is the right one.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from earnings_research.timing import TIMING_CLASSES, EventTiming, TradingCalendar
from earnings_research.timing.models import (
    JST,
    classify,
    decision_available_at,
    first_tradeable_session,
    session_index,
)

# 2026-09-01 火 から。09-05 土 / 09-06 日 は非取引日として抜いてある。
CALENDAR = TradingCalendar(
    calendar_id="TSE-fixture",
    sessions=["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
              "2026-09-07", "2026-09-08", "2026-09-09"],
)


def timing(hour, minute=0, day="2026-09-01", **changes):
    payload = {
        "event_id": "EV-1", "ticker": "1234", "event_date": day,
        "announced_at": datetime.fromisoformat("%sT%02d:%02d:00+09:00" % (day, hour, minute)),
        "announced_at_timezone": "Asia/Tokyo",
        "source": "fixture-disclosure",
        "source_observed_at": datetime(2026, 9, 10, tzinfo=JST),
    }
    payload["timing_class"] = classify(payload["announced_at"], CALENDAR)
    payload.update(changes)
    return EventTiming(**payload)


# --- classification ---------------------------------------------------------

@pytest.mark.parametrize("hour,minute,expected", [
    (8, 0, "pre_open"), (8, 59, "pre_open"),
    (9, 0, "intraday"), (12, 0, "intraday"), (14, 59, "intraday"),
    (15, 0, "post_close"), (16, 30, "post_close"), (23, 59, "post_close"),
])
def test_where_the_announcement_falls_in_its_session(hour, minute, expected):
    assert classify(
        datetime.fromisoformat("2026-09-01T%02d:%02d:00+09:00" % (hour, minute)), CALENDAR
    ) == expected


def test_an_announcement_on_a_day_with_no_session_is_its_own_class():
    """Neither before nor during nor after a session that did not happen."""
    assert classify(datetime(2026, 9, 5, 10, tzinfo=JST), CALENDAR) == "non_trading_day"


# --- unknown is a state -----------------------------------------------------

def test_an_unknown_timing_carries_nothing_that_could_be_mistaken_for_one():
    """Never rounded to `post_close` because that is the common case. A guess
    here would put a made-up decision time under a return series with nothing
    to distinguish it from a measured one."""
    unknown = EventTiming(
        event_id="EV-2", ticker="5678", event_date="2026-09-01", timing_class="unknown"
    )
    assert unknown.announced_at is None and unknown.source is None
    assert decision_available_at(unknown) is None
    assert first_tradeable_session(unknown, CALENDAR) is None
    assert session_index(unknown, CALENDAR) is None
    with pytest.raises(ValidationError, match="carries no instant and no source"):
        EventTiming(
            event_id="EV-2", ticker="5678", event_date="2026-09-01",
            timing_class="unknown", announced_at=datetime(2026, 9, 1, 16, tzinfo=JST),
        )


def test_unknown_is_one_of_the_declared_classes_rather_than_an_absence():
    assert "unknown" in TIMING_CLASSES


# --- provenance is required ------------------------------------------------

def test_a_classified_timing_has_to_say_where_it_came_from():
    """An instant with no source is a number somebody typed, and the point of
    establishing these is that the return series stop resting on an assumption
    nobody measured."""
    with pytest.raises(ValidationError, match="has to say where it came from"):
        timing(16, source=None)
    with pytest.raises(ValidationError, match="when it was read"):
        timing(16, source_observed_at=None)
    with pytest.raises(ValidationError, match="has to say when"):
        timing(16, announced_at=None)


def test_the_instant_has_to_fall_on_the_day_the_event_is_recorded_under():
    with pytest.raises(ValidationError, match="different day from event_date"):
        timing(16, announced_at=datetime(2026, 9, 2, 16, tzinfo=JST))


# --- what follows from the instant ------------------------------------------

def test_a_post_close_announcement_is_first_tradeable_the_next_session():
    after = timing(16)
    assert after.timing_class == "post_close"
    assert first_tradeable_session(after, CALENDAR) == "2026-09-02"
    assert session_index(after, CALENDAR) == 1


def test_a_pre_open_announcement_is_tradeable_the_same_session():
    """The substitution `i0+2` was standing in for. From a pre-open
    announcement the first fill is that same session's open, a whole bar
    earlier than a post-close one — which is why a fixed offset cannot serve
    both."""
    before = timing(8)
    assert before.timing_class == "pre_open"
    assert first_tradeable_session(before, CALENDAR) == "2026-09-01"
    assert session_index(before, CALENDAR) == 0


def test_an_intraday_announcement_reaches_the_next_session(
):
    """Not the current one: its open has already passed."""
    during = timing(12)
    assert during.timing_class == "intraday"
    assert first_tradeable_session(during, CALENDAR) == "2026-09-02"
    assert session_index(during, CALENDAR) == 1


def test_an_announcement_over_a_closed_weekend_skips_to_the_next_session():
    """The calendar is supplied rather than computed: holidays are not
    derivable from a date, and a wrong calendar moves every entry by a session."""
    friday_evening = timing(16, day="2026-09-04")
    assert first_tradeable_session(friday_evening, CALENDAR) == "2026-09-07"
    assert session_index(friday_evening, CALENDAR) == 1


def test_the_same_calendar_offset_means_different_things_for_different_classes():
    """The finding this capability exists for, stated as a comparison.

    Two events on the same date, one disclosed before the open and one after
    the close. A series that reads `i0+2`'s open for both is reading one bar
    after the first fill for one of them and two bars after for the other.
    """
    before, after = timing(8), timing(16)
    assert session_index(before, CALENDAR) != session_index(after, CALENDAR)
    assert first_tradeable_session(before, CALENDAR) == "2026-09-01"
    assert first_tradeable_session(after, CALENDAR) == "2026-09-02"


# --- the calendar -----------------------------------------------------------

def test_a_calendar_out_of_order_or_with_a_repeat_is_refused():
    with pytest.raises(ValidationError, match="in order"):
        TradingCalendar(calendar_id="x", sessions=["2026-09-02", "2026-09-01"])
    with pytest.raises(ValidationError, match="appears twice"):
        TradingCalendar(calendar_id="x", sessions=["2026-09-01", "2026-09-01"])


def test_an_instant_past_the_end_of_the_calendar_yields_no_session():
    """Rather than the last one. A calendar that has not been extended cannot
    say where a later event first becomes tradeable."""
    late = timing(16, day="2026-09-09")
    assert first_tradeable_session(late, CALENDAR) is None
    assert session_index(late, CALENDAR) is None


@pytest.mark.parametrize("hour,minute,expected_class,expected_session", [
    (8, 59, "pre_open", "2026-09-01"),
    # The boundary. The disclosure and the opening print are simultaneous, so
    # that open is not a price this information could be acted on at.
    (9, 0, "intraday", "2026-09-02"),
    (9, 1, "intraday", "2026-09-02"),
    (12, 0, "intraday", "2026-09-02"),
    (14, 59, "intraday", "2026-09-02"),
    (15, 0, "post_close", "2026-09-02"),
])
def test_the_class_and_the_first_fill_agree_at_every_boundary(
    hour, minute, expected_class, expected_session
):
    """One class, one answer.

    At exactly 09:00 an `intraday` event used to return its own session while
    the same class returned the next session at 12:00 — one class answering two
    ways depending on the minute. Nothing covered the boundary; changing
    `>=` to `>` broke no test, which is how it was found.
    """
    item = timing(hour, minute)
    assert item.timing_class == expected_class
    assert first_tradeable_session(item, CALENDAR) == expected_session
