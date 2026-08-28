"""The aggregation's own invariants, which the statistics tests do not reach.

Every one of these survived a mutation before it existed: deleting the
multiplicity call, disabling the by_ticker exclusion, or pooling every view
into one family all left the suite green.
"""

import csv
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


def test_a_cohort_that_reverses_between_halves_is_named(summary):
    """margin_pressure looked promising until the halves were separated."""
    stability = summary["by_reason_code"]["margin_pressure"]["open_d5"]["stability"]
    assert stability["verdict"] == "reversed"
    assert stability["first_half"]["median"] > 0 > stability["second_half"]["median"]


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
