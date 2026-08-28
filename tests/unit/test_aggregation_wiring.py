"""The aggregation's own invariants, which the statistics tests do not reach.

Every one of these survived a mutation before it existed: deleting the
multiplicity call, disabling the by_ticker exclusion, or pooling every view
into one family all left the suite green.
"""

import csv
from datetime import date
from pathlib import Path

import pytest

from earnings_research.legacy_research.aggregation import (
    DESCRIPTIVE_VIEW,
    build_aggregation,
)

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "data/historical_research/earnings_research_os/v1/source/records.csv"


@pytest.fixture(scope="module")
def summary():
    rows = list(csv.DictReader(RECORDS.open(encoding="utf-8-sig")))
    return build_aggregation(rows, [], "test")


def test_a_gap_cohort_withholds_the_returns_that_contain_the_gap(summary):
    cohort = summary["by_shodo"]["GU"]
    for field in ("gap", "ret_d1", "ret_d5", "ret_d20"):
        assert "withheld" in cohort[field], field
    for field in ("open_d1", "open_d5", "open_d20"):
        assert "withheld" not in cohort[field], field


def test_a_reaction_cohort_withholds_the_opening_anchor_too(summary):
    cohort = summary["by_reaction"]["GD反発"]
    for field in ("ret_d5", "open_d5", "open_d20"):
        assert "withheld" in cohort[field], field
    for field in ("close_d5", "close_d20"):
        assert "withheld" not in cohort[field], field


def test_the_gap_cohorts_reverse_once_measured_from_the_open(summary):
    """The finding this guard exists for, pinned against the real records."""
    up = summary["by_shodo"]["GU"]
    down = summary["by_shodo"]["GD"]
    assert up["ret_d5"]["withheld"]
    assert up["open_d5"]["win_rate"] < 0.5 < down["open_d5"]["win_rate"]
    assert up["open_d5"]["median"] < 0 < down["open_d5"]["median"]


def test_the_opening_anchor_is_arithmetically_consistent(summary):
    rows = list(csv.DictReader(RECORDS.open(encoding="utf-8-sig")))
    checked = 0
    for row in rows:
        try:
            opening, first, fifth = (
                float(row["next_open"]), float(row["next_close"]), float(row["d5_close"])
            )
        except (ValueError, KeyError):
            continue
        if not opening or not first:
            continue
        open_d1, close_d5 = (first - opening) / opening, (fifth - first) / first
        open_d5 = (fifth - opening) / opening
        assert (1 + open_d1) * (1 + close_d5) == pytest.approx(1 + open_d5)
        checked += 1
    assert checked > 200


def test_a_per_ticker_breakdown_carries_no_test(summary):
    """It answers what a company did, not whether something predicts."""
    for metrics in summary[DESCRIPTIVE_VIEW].values():
        for stats in metrics.values():
            if not isinstance(stats, dict):
                continue
            assert stats.get("sign_test_p") is None
            for tail in stats.get("tail_capture") or []:
                assert tail.get("p_value") is None


def test_every_cohort_view_is_corrected_and_says_so(summary):
    families = summary["multiplicity"]["families"]
    assert summary["multiplicity"]["scope"] == "per_view"
    assert families[DESCRIPTIVE_VIEW]["corrected"] is False
    corrected = {name for name, item in families.items() if item["corrected"]}
    assert {"by_shodo", "by_rank", "by_narrative", "by_reaction", "by_reason_code"} <= corrected


def test_a_view_nested_under_market_context_is_not_skipped(summary):
    """It sits outside the top-level by_ keys and was missed entirely."""
    assert "market_context.by_relative_dominance" in summary["multiplicity"]["families"]


def test_each_view_is_its_own_family(summary):
    """Pooling them would spend one question's power on another."""
    families = summary["multiplicity"]["families"]
    counts = {name: item["comparisons"] for name, item in families.items() if item["corrected"]}
    assert len(set(counts.values())) > 1


def test_nothing_in_the_reason_codes_survives_correction(summary):
    """Nineteen nominally significant, none of them after the family is counted."""
    raw = adjusted = 0
    for metrics in summary["by_reason_code"].values():
        for stats in metrics.values():
            if not isinstance(stats, dict):
                continue
            for key, seen in (("sign_test_p", "sign_test_p_adjusted"),):
                if (stats.get(key) or 1) < 0.05:
                    raw += 1
                if (stats.get(seen) or 1) < 0.05:
                    adjusted += 1
            for tail in stats.get("tail_capture") or []:
                if (tail.get("p_value") or 1) < 0.05:
                    raw += 1
                if (tail.get("p_value_adjusted") or 1) < 0.05:
                    adjusted += 1
    assert raw > 0
    assert adjusted == 0


def test_the_tail_capture_of_a_reason_code_matches_the_records(summary):
    capture = summary["by_reason_code"]["margin_pressure"]["open_d5"]["tail_capture"][0]
    # Measured on the exploration set only; the reserved third is not in view.
    assert (capture["hits"], capture["n"]) == (4, 26)
    assert capture["lift"] > 2.5
    assert capture["p_value_adjusted"] == 1.0
    assert capture["distinguishable"] is False


def test_the_reserved_period_is_declared_but_not_summarised(summary):
    holdout = summary["holdout"]
    assert holdout["reserved_count"] > 0
    assert holdout["reserved_statistics"] == "not_computed"
    assert summary["record_count"] + holdout["reserved_count"] == summary[
        "record_count_including_reserved"
    ]


def test_a_sign_flip_the_record_cannot_support_is_not_reported_as_a_reversal(summary):
    """margin_pressure, the case this rule exists for.

    Its halves do sit either side of zero, which is what the earlier rule called
    a reversal and what was reported as one. Only the first half can actually
    assert a direction; the second half's median interval spans zero, so it is
    not claiming the opposite, it is claiming nothing. Over these records the
    permuted rate of sign disagreement is 0.514 against a null of 0.50
    (p = 0.508) — the flip is what an absent effect looks like, not evidence
    against the hypothesis. Calling it a reversal retires hypotheses at a
    coin's pace.
    """
    stability = summary["by_reason_code"]["margin_pressure"]["open_d5"]["stability"]
    assert stability["first_half"]["median"] > 0 > stability["second_half"]["median"]
    assert stability["halves_exclude_zero"] == [True, False]
    assert stability["verdict"] == "inconclusive"


def test_no_cohort_stays_directional_after_the_correction_dismisses_it(summary):
    """Otherwise the correction is decorative: it records a number nobody uses."""
    for view, groups in summary.items():
        if not view.startswith("by_") or not isinstance(groups, dict):
            continue
        for label, metrics in groups.items():
            for field, stats in metrics.items():
                if not isinstance(stats, dict) or stats.get("verdict") != "directional":
                    continue
                adjusted = stats.get("sign_test_p_adjusted")
                assert adjusted is not None and adjusted < 0.05, (view, label, field)


def test_a_descriptive_view_carries_no_directional_verdict(summary):
    """Its p-values are removed, so a verdict resting on one must go too."""
    for metrics in summary[DESCRIPTIVE_VIEW].values():
        for stats in metrics.values():
            if isinstance(stats, dict):
                assert stats.get("verdict") != "directional"


def cohort(p_value, verdict="directional"):
    return {
        "mean": 0.02,
        "median": 0.02,
        "mean_without_best": 0.015,
        "sign_test_p": p_value,
        "verdict": verdict,
        "tail_capture": [],
    }


def test_the_correction_takes_back_a_verdict_it_dismisses():
    """Raw p under five percent, adjusted p over it: the label has to move."""
    from earnings_research.legacy_research.aggregation import _multiplicity

    summary = {
        "by_rank": {
            "A": {"open_d5": cohort(0.02)},
            **{
                "R%d" % index: {"open_d5": cohort(0.4 + index * 0.01, "no_signal")}
                for index in range(30)
            },
        }
    }
    _multiplicity(summary)
    dismissed = summary["by_rank"]["A"]["open_d5"]
    assert dismissed["sign_test_p"] == 0.02
    assert dismissed["sign_test_p_adjusted"] >= 0.05
    assert dismissed["verdict"] == "no_signal"


def test_a_verdict_the_correction_upholds_is_left_alone():
    from earnings_research.legacy_research.aggregation import _multiplicity

    summary = {"by_rank": {"A": {"open_d5": cohort(0.0001)}}}
    _multiplicity(summary)
    upheld = summary["by_rank"]["A"]["open_d5"]
    assert upheld["sign_test_p_adjusted"] < 0.05
    assert upheld["verdict"] == "directional"


def test_a_tail_driven_cohort_keeps_its_label_whatever_the_p_value():
    """It is a statement about shape, not about significance."""
    from earnings_research.legacy_research.aggregation import _multiplicity

    tail = cohort(0.0001)
    tail["median"] = -0.01  # mean and median now disagree
    summary = {"by_rank": {"A": {"open_d5": tail}}}
    _multiplicity(summary)
    assert summary["by_rank"]["A"]["open_d5"]["verdict"] == "tail_driven"


def _dated_rows(count, start_day=1):
    return [
        {
            "code": "%04d" % (index + 1000),
            "date": "2026-0%d-%02d" % (1 + index // 28, 1 + index % 28),
            "prev_close": "100", "next_open": "101", "next_close": "102",
            "d5_close": "103", "d20_close": "104",
            "gap": "0.01", "ret_d1": "0.02", "ret_d5": "0.03", "ret_d20": "0.04",
            "shodo": "GU", "reaction": "GU継続", "rank": "B", "narrative": "増収増益",
        }
        for index in range(count)
    ]


def _context_for(rows, risk_on):
    return [
        {
            "legacy_record_id": row["code"],
            "join_status": "ok",
            "market_context": {"risk_on_score": str(risk_on), "risk_off_score": "10"},
        }
        for row in rows
    ]


def test_a_row_keeps_its_own_market_context_across_the_reserve_split():
    """The split reorders rows; a positional re-pairing hands them the wrong one."""
    from earnings_research.legacy_research.aggregation import build_aggregation

    rows = _dated_rows(30)
    contexts = _context_for(rows, 90)
    # Reversed on the way in, so any position-based pairing survives only if it
    # tracks the row rather than the index.
    summary = build_aggregation(list(reversed(rows)), list(reversed(contexts)), "deadbeef")
    assert summary["market_context"]["linked_count"] == summary["record_count"]
    assert set(summary["market_context"]["by_relative_dominance"]) == {"risk_on_dominant"}


def test_a_missing_context_link_does_not_shift_every_later_row():
    """One unlinked row hands its successors the wrong context under a re-zip."""
    from earnings_research.legacy_research.aggregation import build_aggregation

    rows = _dated_rows(30)
    contexts = _context_for(rows, 90)
    for item in contexts[15:]:
        item["market_context"] = {"risk_on_score": "10", "risk_off_score": "90"}
    # The unlinked row carries an unmistakable return. Correctly paired it
    # belongs to no context group at all; re-zipped it takes the next row's
    # context and shows up as that group's best name.
    rows[0]["next_close"] = "199"
    contexts[0] = None
    summary = build_aggregation(rows, contexts, "deadbeef")
    groups = summary["market_context"]["by_relative_dominance"]
    assert summary["record_count"] == 20
    assert summary["market_context"]["linked_count"] == 19
    assert groups["risk_on_dominant"]["open_d1"]["best"] < 0.9
    assert groups["risk_off_dominant"]["open_d1"]["best"] < 0.9


def test_fewer_context_views_than_rows_does_not_borrow_a_neighbour_s_context():
    from earnings_research.legacy_research.aggregation import build_aggregation

    rows = _dated_rows(30)
    summary = build_aggregation(rows, _context_for(rows[:10], 90), "deadbeef")
    assert summary["market_context"]["linked_count"] <= 10


# --- 公開物の統計が留保期間を見ていないこと -----------------------------------

def _statistics_section(text):
    """Everything the dashboard states as a finding, without the row listing."""
    return text[text.index("## 仮説検証"):]


def _note_insights(text):
    """The note's automatically derived remarks, without the weekly listing."""
    return text[text.index("## 今週時点の検証メモ"):]


def test_the_published_statistics_cannot_see_the_reserved_period():
    """The reserve is only a reserve if what gets published never reads it.

    Reserved rows still appear in the listing — they are records, and hiding
    them would be a different kind of dishonesty — so the guarantee has to be
    that changing them cannot move a single published figure.
    """
    from earnings_research.legacy_research.publishing import render_dashboard, render_note
    from earnings_research.statistics.holdout import split_by_date

    rows = _dated_rows(30)
    split = split_by_date(rows)
    assert split.reserved, "the sample must actually reserve something"
    before = render_dashboard(rows, "2026-06-10 00:00", statistics_rows=split.exploration)
    note_before = _note_insights(render_note(rows, date(2026, 6, 10), statistics_rows=split.exploration))
    for row in split.reserved:
        # Returns nothing like the explored period's, in every anchored field.
        row.update({"next_open": "100", "next_close": "180", "d5_close": "220", "d20_close": "260"})
        row["ret_d1"] = row["ret_d5"] = row["ret_d20"] = "0.8"
    after = render_dashboard(rows, "2026-06-10 00:00", statistics_rows=split.exploration)
    note_after = _note_insights(render_note(rows, date(2026, 6, 10), statistics_rows=split.exploration))
    assert _statistics_section(after) == _statistics_section(before)
    assert note_after == note_before
    assert "+80.0%" not in _statistics_section(after)


def test_changing_the_explored_period_does_move_the_published_statistics():
    """The control: without this the test above passes on a dashboard of zeroes."""
    from earnings_research.legacy_research.publishing import render_dashboard
    from earnings_research.statistics.holdout import split_by_date

    rows = _dated_rows(30)
    split = split_by_date(rows)
    before = render_dashboard(rows, "2026-06-10 00:00", statistics_rows=split.exploration)
    for row in split.exploration:
        row.update({"next_open": "100", "next_close": "180", "d5_close": "220", "d20_close": "260"})
    after = render_dashboard(rows, "2026-06-10 00:00", statistics_rows=split.exploration)
    assert _statistics_section(after) != _statistics_section(before)


def test_the_reserved_rows_are_still_listed():
    from earnings_research.legacy_research.publishing import render_dashboard
    from earnings_research.statistics.holdout import split_by_date

    rows = _dated_rows(30)
    split = split_by_date(rows)
    published = render_dashboard(rows, "2026-06-10 00:00", statistics_rows=split.exploration)
    listing = published[: published.index("## 仮説検証")]
    assert split.reserved[-1]["code"] in listing
