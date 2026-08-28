from datetime import date, datetime, timedelta, timezone

import pytest

from earnings_research.statistics.holdout import (
    MIN_FOR_RESERVE,
    HoldoutViolation,
    evaluate_reserved,
    split_by_date,
)
from earnings_research.statistics.stability import assess

JST = timezone(timedelta(hours=9))


def records(count, start=date(2026, 1, 1), value=0.01):
    return [
        {"date": (start + timedelta(days=index)).isoformat(), "code": "A%d" % index, "v": value}
        for index in range(count)
    ]


def test_the_recent_third_is_held_back():
    split = split_by_date(records(30))
    assert len(split.reserved) == 10
    assert len(split.exploration) == 20
    assert split.cutoff == date(2026, 1, 21)


def test_the_reserved_records_are_the_later_ones():
    split = split_by_date(records(30))
    assert max(r["date"] for r in split.exploration) < min(r["date"] for r in split.reserved)


@pytest.mark.parametrize("count", [0, 1, MIN_FOR_RESERVE - 1])
def test_too_short_a_record_reserves_nothing_rather_than_emptying_itself(count):
    split = split_by_date(records(count))
    assert split.cutoff is None
    assert len(split.exploration) == count
    assert split.reserved == []


def test_a_record_with_no_usable_date_stays_in_exploration():
    """Undated rows cannot be placed after a cutoff, so they never leak in."""
    rows = records(20) + [{"date": "", "code": "X"}, {"date": "not-a-date", "code": "Y"}]
    split = split_by_date(rows)
    assert {"X", "Y"} <= {row["code"] for row in split.exploration}
    assert all(row["date"] for row in split.reserved)


@pytest.mark.parametrize("reserve", [0, 1, -0.5, 1.5])
def test_an_impossible_reserve_is_refused(reserve):
    with pytest.raises(ValueError, match="between 0 and 1"):
        split_by_date(records(30), reserve=reserve)


def test_the_reserved_period_answers_only_to_a_definition_frozen_before_it():
    split = split_by_date(records(30))
    before = datetime(2026, 1, 10, tzinfo=JST)
    assert evaluate_reserved(split, before, len) == 10


@pytest.mark.parametrize("day", [date(2026, 1, 21), date(2026, 2, 1)])
def test_a_definition_frozen_after_the_cutoff_has_already_seen_the_answer(day):
    split = split_by_date(records(30))
    with pytest.raises(HoldoutViolation, match="frozen"):
        evaluate_reserved(split, day, len)


def test_nothing_reserved_means_nothing_to_confirm_against():
    split = split_by_date(records(3))
    with pytest.raises(HoldoutViolation, match="nothing is reserved"):
        evaluate_reserved(split, date(2020, 1, 1), len)


# --- 前半後半の一致 -----------------------------------------------------------

def dated(values, start=date(2026, 1, 1)):
    return [
        {"date": (start + timedelta(days=index)).isoformat(), "code": "A%d" % index, "v": value}
        for index, value in enumerate(values)
    ]


def value_of(row):
    return row.get("v")


def test_a_relationship_present_throughout_is_consistent():
    result = assess(dated([0.02] * 20), value_of)
    assert result.verdict == "consistent"
    assert result.first.median > 0 and result.second.median > 0


def test_a_relationship_that_only_worked_early_is_named():
    """Decay and luck both leave this shape."""
    result = assess(dated([0.05] * 10 + [-0.05] * 10), value_of)
    assert result.verdict == "reversed"
    assert result.first.median > 0 > result.second.median


def test_the_halves_are_split_by_date_not_by_position():
    shuffled = dated([0.05] * 10 + [-0.05] * 10)
    result = assess(list(reversed(shuffled)), value_of)
    assert result.verdict == "reversed"
    assert result.boundary == date(2026, 1, 11)


@pytest.mark.parametrize("count", [0, 4, 9])
def test_too_few_observations_to_split_says_so(count):
    assert assess(dated([0.01] * count), value_of).verdict == "too_short"


def test_rows_without_an_outcome_are_not_counted():
    rows = dated([0.02] * 20) + [{"date": "2026-03-01", "code": "Z", "v": None}]
    assert assess(rows, value_of).first.n + assess(rows, value_of).second.n == 20


def test_repeated_names_are_carried_into_each_half():
    rows = dated([0.02] * 20)
    for row in rows:
        row["code"] = "SAME"
    result = assess(rows, value_of, cluster_of=lambda row: row["code"])
    assert result.first.n_independent == 1
