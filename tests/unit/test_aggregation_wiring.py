"""The aggregation's own invariants, which the statistics tests do not reach.

Every one of these survived a mutation before it existed: deleting the
multiplicity call, disabling the by_ticker exclusion, or pooling every view
into one family all left the suite green.
"""

import csv
from datetime import date
from pathlib import Path

import pytest

from earnings_research.legacy_research.aggregation import _open_anchored
from earnings_research.statistics.holdout import split_by_date
from earnings_research.legacy_research.aggregation import (
    DESCRIPTIVE_VIEW,
    RETURN_FIELDS,
    build_aggregation,
)

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "data/historical_research/earnings_research_os/v1/source/records.csv"


def _all_rows():
    return list(csv.DictReader(RECORDS.open(encoding="utf-8-sig")))


def _explored_rows():
    """The rows the summary is actually built from, reserve already removed."""
    from earnings_research.legacy_research.aggregation import _open_anchored
    from earnings_research.statistics.holdout import split_by_date

    return split_by_date([_open_anchored(row) for row in _all_rows()]).exploration


@pytest.fixture(scope="module")
def summary():
    return build_aggregation(_all_rows(), [], "test")


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


def test_the_opening_anchor_measures_between_the_prices_it_declares():
    """This replaces a test that could not fail.

    It computed (f/o)(v/f) == v/o from the CSV and compared the answer with
    itself — an identity true of any three prices — while taking the summary
    fixture as an argument and never touching it. Gutting _open_anchored to
    `return dict(row)` left it green. The prices now come from the declaration
    table and the returns are checked against hand arithmetic on real rows.
    """
    from earnings_research.legacy_research.aggregation import _open_anchored
    from earnings_research.statistics.lookahead import prices_for

    rows = list(csv.DictReader(RECORDS.open(encoding="utf-8-sig")))
    checked = 0
    for row in rows:
        enriched = _open_anchored(row)
        for field in ("open_d1", "open_d5", "open_d20", "close_d5", "close_d20"):
            entry_field, exit_field = prices_for(field)
            try:
                entry, exit_ = float(row[entry_field]), float(row[exit_field])
            except (ValueError, KeyError):
                continue
            if entry <= 0 or exit_ <= 0:
                continue
            assert enriched[field] == pytest.approx((exit_ - entry) / entry), (field, row["code"])
            checked += 1
    assert checked > 800


def test_the_declared_prices_cover_every_reported_field():
    from earnings_research.legacy_research.aggregation import RETURN_FIELDS
    from earnings_research.statistics.lookahead import prices_for

    for field in RETURN_FIELDS:
        entry, exit_ = prices_for(field)
        assert entry != exit_, field
    with pytest.raises(KeyError):
        prices_for("ret_d60")


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
    # Against the rest of the record rather than against a base rate this
    # cohort helped set. It was 16% of the population, and comparing it with
    # itself included put the lift at 2.5077 against an assertion of 2.5.
    assert capture["base_rate"] < 0.05
    # Names, not rows: the comparison population is counted the same way.
    assert capture["lift"] > 3.4
    # Nominally 0.055 against the rest of the record — the binomial form,
    # which treated the base rate as known rather than estimated, said 0.025 —
    # and nowhere at all after the family is counted.
    assert 0.05 < capture["p_value"] < 0.06
    assert capture["p_value_adjusted"] > 0.5
    assert capture["distinguishable"] is False


def test_a_cohort_is_not_compared_against_a_base_rate_it_helped_set(summary):
    """Every cohort here is a subset, one of them of more than half the record."""
    from earnings_research.legacy_research.aggregation import _Population

    rows = _explored_rows()
    population = _Population(rows)
    whole = population.rate_excluding([], "open_d5", 0.10)
    biggest = max(
        (
            [row for row in rows if row.get("narrative") == label]
            for label in {row.get("narrative") for row in rows}
        ),
        key=len,
    )
    assert len(biggest) / len(rows) > 0.4
    assert population.rate_excluding(biggest, "open_d5", 0.10) != whole


def test_the_whole_record_has_nothing_outside_it_to_be_compared_with(summary):
    for capture in summary["overall"]["open_d5"]["tail_capture"]:
        assert capture["base_rate"] is None
        assert capture["lift"] is None
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
            "legacy_record_id": "ERSO-%s" % row["code"],
            "ticker": row["code"],
            "legacy_event_date": row["date"],
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


def test_a_missing_context_link_is_refused_rather_than_shifting_every_later_row():
    """Dropping one link slides all the rest onto their neighbour's context.

    Nothing objected: the linked count stayed right and the dominance tables
    merely moved by one, which is the shape of an error that survives review.
    The producer enforces a one-to-one join today, and that is exactly why this
    went unnoticed rather than a reason not to check it.
    """
    from earnings_research.legacy_research.aggregation import build_aggregation

    rows = _dated_rows(30)
    contexts = _context_for(rows, 90)[1:]
    with pytest.raises(ValueError, match="does not belong to legacy record"):
        build_aggregation(rows, contexts, "deadbeef")


def test_a_reordered_context_list_is_refused():
    from earnings_research.legacy_research.aggregation import build_aggregation

    rows = _dated_rows(30)
    contexts = _context_for(rows, 90)
    contexts[3], contexts[9] = contexts[9], contexts[3]
    with pytest.raises(ValueError, match="does not belong to legacy record"):
        build_aggregation(rows, contexts, "deadbeef")


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
    before = render_dashboard(rows, "2026-06-10 00:00")
    note_before = _note_insights(render_note(rows, date(2026, 6, 10)))
    for row in split.reserved:
        # Returns nothing like the explored period's, in every anchored field.
        row.update({"next_open": "100", "next_close": "180", "d5_close": "220", "d20_close": "260"})
        row["ret_d1"] = row["ret_d5"] = row["ret_d20"] = "0.8"
    after = render_dashboard(rows, "2026-06-10 00:00")
    note_after = _note_insights(render_note(rows, date(2026, 6, 10)))
    assert _statistics_section(after) == _statistics_section(before)
    assert note_after == note_before
    assert "+80.0%" not in _statistics_section(after)


def test_changing_the_explored_period_does_move_the_published_statistics():
    """The control: without this the test above passes on a dashboard of zeroes."""
    from earnings_research.legacy_research.publishing import render_dashboard
    from earnings_research.statistics.holdout import split_by_date

    rows = _dated_rows(30)
    split = split_by_date(rows)
    before = render_dashboard(rows, "2026-06-10 00:00")
    for row in split.exploration:
        row.update({"next_open": "100", "next_close": "180", "d5_close": "220", "d20_close": "260"})
    after = render_dashboard(rows, "2026-06-10 00:00")
    assert _statistics_section(after) != _statistics_section(before)


def test_the_reserved_rows_are_still_listed():
    from earnings_research.legacy_research.publishing import render_dashboard
    from earnings_research.statistics.holdout import split_by_date

    rows = _dated_rows(30)
    split = split_by_date(rows)
    published = render_dashboard(rows, "2026-06-10 00:00")
    listing = published[: published.index("## 仮説検証")]
    assert split.reserved[-1]["code"] in listing


# --- 公開物のテストが自分自身を検査していないこと -----------------------------

def _varied_rows(count=40):
    """A fixture with spread, several cohorts, and repeated companies.

    The one the renderers were tested through had thirty identical rows, so the
    win rate was 100% and the median equalled the mean by construction: a
    renderer printing only the mean and one printing all three were
    indistinguishable, and every narrative cell was empty because the label did
    not match any real one.
    """
    ranks = ("A", "B+", "B", "C+", "C")
    narratives = ("整合", "中立", "衝突")
    judges = ("即買い候補", "押し目待ち", "監視", "見送り")
    rows = []
    for index in range(count):
        drift = (index % 7 - 3) / 100
        opening = 100 + index % 5
        rows.append({
            # Two appearances each, so names and rows differ.
            "code": "%04d" % (1000 + index // 2),
            "name": "架空%02d" % index,
            "date": "2026-%02d-%02d" % (6 + index // 28, index % 28 + 1),
            "prev_close": "100",
            "next_open": "%.2f" % opening,
            "next_close": "%.2f" % (opening * (1 + drift)),
            "d5_close": "%.2f" % (opening * (1 + drift * 2)),
            "d20_close": "%.2f" % (opening * (1 + drift * 3)),
            "gap": "%.4f" % ((opening - 100) / 100),
            "ret_d1": "%.4f" % (drift + 0.02),
            "ret_d5": "%.4f" % (drift * 2 + 0.02),
            "ret_d20": "%.4f" % (drift * 3 + 0.02),
            "shodo": ("GU", "フラット", "GD")[index % 3],
            "reaction": ("GU継続", "GU失速", "GD反発", "GD継続")[index % 4],
            "rank": ranks[index % 5],
            "narrative": narratives[index % 3],
            "judge": judges[index % 4],
            "surprise": ("+2", "+1", "0", "-1", "-2")[index % 5],
            "rc1": ("margin_pressure", "guidance_cut", "")[index % 3],
        })
    return rows


def _dashboard(rows=None):
    from earnings_research.legacy_research.aggregation import _open_anchored
    from earnings_research.legacy_research.publishing import render_dashboard
    from earnings_research.statistics.holdout import split_by_date

    prepared = [_open_anchored(row) for row in (rows or _varied_rows())]
    return render_dashboard(prepared, "2026-09-01 00:00")


def test_every_published_cell_carries_the_win_rate_and_the_middle():
    """Printing the mean alone is the defect this whole change exists to fix,
    and reverting the renderer to it passed the entire suite. The interval is
    part of the cell now: forty-nine published figures each had an exact one
    computed and thrown away, so a cohort of eleven read as precisely as a
    cohort of eighty."""
    import re

    body = _statistics_section(_dashboard())
    cells = [
        cell.strip()
        for line in body.splitlines()
        if line.startswith("|") and "---" not in line
        for cell in line.strip("|").split("|")[1:]
    ]
    figures = [cell for cell in cells if "%" in cell]
    assert figures, "the fixture produced no numbers at all"
    for cell in figures:
        assert re.fullmatch(
            r"\d+% \[\d+〜\d+%\] / [+-]\d+\.\d% / [+-]\d+\.\d% \(n=\d+(, \d+社)?(, 引分\d+)?\)†?",
            cell,
        ), cell


def test_a_handful_of_records_prints_its_size_instead_of_a_number():
    rows = [row for row in _varied_rows() if row["rank"] != "C"][:20]
    rows += [dict(row, rank="C") for row in _varied_rows()[:2]]
    body = _statistics_section(_dashboard(rows))
    assert "(件数不足)" in body


def test_the_published_tables_are_anchored_at_prices_a_trade_could_have_used():
    """Reverting any one table's anchor restored the circular figures the prose
    warns about, and passed the suite.

    The first version of this test read the column headings, so changing every
    anchor while leaving the headings alone still passed — the same shape of
    defect it was written to catch. It compares figures now.
    """
    from earnings_research.legacy_research.aggregation import _open_anchored
    from earnings_research.legacy_research.publishing import _anchored, _avg
    from earnings_research.statistics.holdout import split_by_date

    rows = [_open_anchored(row) for row in _varied_rows(60)]
    explored = split_by_date(rows).exploration
    body = _statistics_section(_dashboard(_varied_rows(60)))
    checks = (
        ("rank", "A", "open_d1", "ret_d1"),
        ("rank", "A", "open_d20", "ret_d20"),
        ("narrative", "整合", "open_d20", "ret_d20"),
        ("judge", "監視", "open_d20", "ret_d20"),
        ("shodo", "GU", "open_d5", "ret_d5"),
        ("reaction", "GU継続", "close_d5", "ret_d5"),
    )
    for column, label, sound_field, stale_field in checks:
        match = lambda row, column=column, label=label: row.get(column) == label
        sound = _anchored(explored, match, sound_field)
        stale = _avg(explored, match, stale_field)
        assert sound != stale, (column, label)
        assert sound in body, (column, label, sound)
        assert stale not in body, (column, label, stale)


def test_the_scope_of_the_statistics_is_stated_beside_them():
    body = _statistics_section(_dashboard(_varied_rows(60)))
    assert "統計は探索対象" in body


def test_the_note_states_its_scope_inside_the_part_it_asks_to_be_published():
    """It was stated above the line the note tells the reader to copy from, so
    the published article carried the figures and left their scope behind."""
    from earnings_research.legacy_research.aggregation import _open_anchored
    from earnings_research.legacy_research.publishing import render_note
    from earnings_research.statistics.holdout import split_by_date

    rows = [_open_anchored(row) for row in _varied_rows(60)]
    text = render_note(rows, date(2026, 9, 1))
    published = text[text.index("本文ここから"):]
    assert "## 今週時点の検証メモ" in published
    assert "統計は探索対象" in published


def test_the_base_rate_never_reads_the_reserved_period():
    """The renderers have a test for this leak; the base rate did not, and
    including the reserve moved a nominal p-value across 0.05.

    The first version of this built the population twice from the explored set
    itself, so it held for any implementation. It goes through the whole
    aggregation now, which is the path that decides what gets published.
    """
    from earnings_research.legacy_research.aggregation import build_aggregation

    rows = _all_rows()
    before = build_aggregation(rows, [], "test")
    reserved = split_by_date([_open_anchored(row) for row in rows]).reserved
    reserved_ids = {(row["code"], row["date"]) for row in reserved}
    poisoned = [
        dict(row, next_open="100", next_close="900", d5_close="900", d20_close="900")
        if (row["code"], row["date"]) in reserved_ids
        else row
        for row in rows
    ]
    after = build_aggregation(poisoned, [], "test")
    for view in ("by_shodo", "by_rank", "by_reason_code"):
        for label, metrics in before[view].items():
            for field, stats in metrics.items():
                if not isinstance(stats, dict) or "tail_capture" not in stats:
                    continue
                mine = after[view][label][field]["tail_capture"]
                theirs = stats["tail_capture"]
                assert [item["base_rate"] for item in mine] == [
                    item["base_rate"] for item in theirs
                ], (view, label, field)


def test_the_dashboard_says_what_survived_the_correction():
    """The sentence this whole change exists to produce, in the place people
    read. The words for correction, p-value, interval and verdict occurred zero
    times across all three published files, so every table heading phrased as a
    question read as though the figures beneath it were the answer."""
    body = _statistics_section(_dashboard(_varied_rows(80)))
    first = body.splitlines()[2]
    assert "Benjamini-Hochberg" in first
    assert "件の比較" in first
    assert "0件" in first or "残った" in first


def test_a_tail_driven_cohort_is_marked_where_it_is_published():
    """Twenty-seven of the forty-nine published cells had a mean and a middle
    pointing opposite ways and said nothing about it."""
    from earnings_research.legacy_research.publishing import _avg

    rows = [{"code": "%04d" % index, "v": 0.0001} for index in range(20)]
    rows[0]["v"] = 5.0
    assert _avg(rows, lambda _row: True, "v").endswith("†")
    assert not _avg([dict(row, v=0.01) for row in rows], lambda _row: True, "v").endswith("†")


def test_the_note_does_not_publish_a_pairing_the_summary_withholds():
    """The narrative insight was measured from the previous close — the anchor
    the JSON withholds for that cohort — inside the block the reader is told to
    copy and publish."""
    from earnings_research.legacy_research.aggregation import _open_anchored
    from earnings_research.legacy_research.publishing import _anchored, _avg, render_note
    from earnings_research.statistics.holdout import split_by_date
    from earnings_research.statistics.lookahead import contamination

    assert contamination("narrative", "ret_d1") is not None
    rows = [_open_anchored(row) for row in _varied_rows(60)]
    text = render_note(rows, date(2026, 9, 1))
    published = text[text.index("本文ここから"):]
    insights = [line for line in published.splitlines() if line.startswith("・ナラティブ")]
    assert insights
    # The figure itself, not the label beside it: relabelling without changing
    # the anchor would leave the withheld number published under an honest
    # heading.
    explored = split_by_date(rows).exploration
    for line in insights:
        label = line.split("「")[1].split("」")[0]
        match = lambda row, label=label: row.get("narrative") == label
        sound = _anchored(explored, match, "open_d1")
        stale = _avg(explored, match, "ret_d1")
        assert sound != stale, label
        assert line.endswith(sound), (line, sound)


def test_a_cell_with_flat_outcomes_says_so_rather_than_shrinking_its_denominator():
    """The win rate's denominator is the decided count, not n. Printing n alone
    made one-in-four-out-of-six read as one in four."""
    from earnings_research.legacy_research.publishing import _avg

    rows = [{"code": "A%d" % index, "v": 0.0} for index in range(4)]
    rows += [{"code": "B%d" % index, "v": 0.01} for index in range(2)]
    cell = _avg(rows, lambda _row: True, "v")
    assert "引分4" in cell
    assert "100%" in cell


# --- 補正の網羅が実際に効いていること -----------------------------------------

def test_the_headline_row_is_corrected_like_every_cohort(summary):
    """`overall` entered no family, which left the report's headline as the one
    place a raw p-value could still be quoted — and close_d20 was quoting one at
    0.025 while a cohort with a smaller raw p-value was buried at 0.95."""
    assert "overall" in summary["multiplicity"]["families"]
    assert summary["multiplicity"]["families"]["overall"]["comparisons"] > 0
    for field in RETURN_FIELDS:
        stats = summary["overall"][field]
        if stats.get("sign_test_p") is not None:
            assert "sign_test_p_adjusted" in stats, field
            assert stats["verdict"] != "directional" or stats["sign_test_p_adjusted"] < 0.05


def test_both_halves_of_the_stability_split_are_counted_as_comparisons(summary):
    """They published their own sign tests and their own verdicts outside the
    declared count, which was short by one per half."""
    halves = corrected = 0
    for view, groups in summary.items():
        if not view.startswith("by_") or view == DESCRIPTIVE_VIEW:
            continue
        for metrics in groups.values():
            for stats in metrics.values():
                if not isinstance(stats, dict):
                    continue
                for name in ("first_half", "second_half"):
                    part = (stats.get("stability") or {}).get(name)
                    if isinstance(part, dict) and part.get("sign_test_p") is not None:
                        halves += 1
                        corrected += "sign_test_p_adjusted" in part
    assert halves > 100
    assert corrected == halves


def test_a_tail_claim_the_correction_dismisses_is_withdrawn():
    """distinguishable is the figure this measure tells the reader to read, and
    it was the one the correction never touched."""
    from earnings_research.legacy_research.aggregation import _multiplicity

    cell = {
        "mean": 0.02, "median": 0.02, "trimmed_mean": 0.02, "sign_test_p": None,
        "stability": None,
        "tail_capture": [{"p_value": 0.01, "distinguishable": True, "direction": "above"}],
    }
    summary = {"by_thing": {"a": {"open_d1": cell}}}
    summary["by_thing"].update(
        {"c%d" % index: {"open_d1": dict(cell, tail_capture=[{"p_value": 0.9}])}
         for index in range(40)}
    )
    _multiplicity(summary)
    assert cell["tail_capture"][0]["p_value_adjusted"] > 0.05
    assert cell["tail_capture"][0]["distinguishable"] is False
    assert cell["tail_capture"][0]["direction"] is None


def test_the_reason_code_view_is_guarded_like_every_other_cohort(summary):
    """It calls _metrics itself and carries the largest family in the summary,
    and it was passing no cohort key at all, so the guard never ran."""
    for label, metrics in summary["by_reason_code"].items():
        for field in ("gap", "ret_d1", "ret_d5", "ret_d20"):
            assert "withheld" in metrics[field], (label, field)
        for field in ("open_d1", "open_d5", "close_d5"):
            assert "withheld" not in metrics[field], (label, field)


def test_the_judgement_views_exist_and_are_counted(summary):
    """They were published in the dashboard with no view here, so they were
    guarded by nothing and counted in no family."""
    for view in ("by_judge", "by_surprise"):
        assert view in summary
        assert summary["multiplicity"]["families"][view]["comparisons"] > 0
        for label, metrics in summary[view].items():
            for field in ("gap", "ret_d1", "ret_d20"):
                assert "withheld" in metrics[field], (view, label, field)


def test_the_published_count_is_names_where_names_repeat():
    """The aggregation counted names from the start; the renderer beside it
    counted rows, so one company's five earnings published as a cohort of five
    with a perfect record."""
    from earnings_research.legacy_research.publishing import _avg

    rows = [{"code": "9999", "date": "2026-0%d-01" % (m + 1), "v": 0.10} for m in range(5)]
    cell = _avg(rows, lambda _row: True, "v")
    assert "5社" not in cell
    assert "1社" in cell


def test_an_exit_price_of_zero_is_dropped_rather_than_read_as_a_total_loss():
    """The aggregation drops the row; the renderer treated it as -100% and
    published the two side by side."""
    from earnings_research.legacy_research.aggregation import _open_anchored
    from earnings_research.legacy_research.publishing import _anchored

    rows = [
        {"code": "A%d" % index, "next_open": "100", "next_close": "0", "d5_close": "0"}
        for index in range(6)
    ]
    assert _anchored(rows, lambda _row: True, "open_d1") == "-"
    assert _open_anchored(rows[0])["open_d1"] is None


def test_a_price_that_is_not_a_number_is_dropped_at_the_gate():
    """"nan" parses, passes `if not opening`, is counted as available, costs
    the win rate a silent point and poisons the mean."""
    from earnings_research.legacy_research.aggregation import _number, _open_anchored

    assert _number("nan") is None
    assert _number("inf") is None
    assert _number("-inf") is None
    assert _open_anchored({"next_open": "nan", "next_close": "110"})["open_d1"] is None


def test_a_missing_opening_price_does_not_take_the_closing_anchors_with_it():
    """close_d5 never touches next_open, and those are the only fields a
    reaction cohort has left once the contaminated ones are withheld."""
    from earnings_research.legacy_research.aggregation import _open_anchored

    enriched = _open_anchored(
        {"next_open": "", "next_close": "110", "d5_close": "121", "d20_close": "130"}
    )
    assert enriched["open_d1"] is None
    assert enriched["close_d5"] == pytest.approx(0.1)
    assert enriched["close_d20"] == pytest.approx(0.181818, abs=1e-5)
