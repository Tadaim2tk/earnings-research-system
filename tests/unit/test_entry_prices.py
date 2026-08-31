"""The price an order is actually filled at.

The record carried five prices per event and none of them was one a trade goes
on. Measuring from the first session's open assumes buying into the gap;
measuring from its close assumes filling at the very print that decides the
reaction label. The fill is the next open after that — session i0+2, counting
the announcement day as i0 — and it was never recorded.
"""

import csv
import json
from pathlib import Path

import pytest

from earnings_research.legacy_research.entry_prices import (
    ENTRY_FIELD,
    accepted,
    attach,
    by_event,
    digest,
    disagreements,
    read,
)
from earnings_research.legacy_research.publishing import ENTRY_MANIFEST, ENTRY_PRICES, with_entry_prices
from earnings_research.statistics.lookahead import (
    COHORT_SPAN,
    COMPARISON_AXIS,
    DERIVED_FIELDS,
    RETURN_ANCHOR,
    contamination,
    prices_for,
)

EVENT5 = "entry_i0p2_open__exit_i0p5_close"
EVENT20 = "entry_i0p2_open__exit_i0p20_close"
PLUS5 = "entry_i0p2_open__exit_i0p7_close"
PLUS20 = "entry_i0p2_open__exit_i0p22_close"

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "data/historical_research/earnings_research_os/v1/source/records.csv"


def records():
    return list(csv.DictReader(RECORDS.read_text(encoding="utf-8").splitlines()))


def fetched():
    return read(ROOT / ENTRY_PRICES)


def test_the_fill_price_is_the_open_after_the_session_the_label_is_read_at():
    """Which is what makes it the only anchor no label reaches.

    A reaction cohort is settled at the first session's close. This price does
    not exist until the next open, so the split and the result share no bar —
    where scoring the same cohort from next_close means entering at the print
    that decides it.
    """
    for name in (EVENT5, EVENT20, PLUS5, PLUS20):
        assert prices_for(name)[0] == "i0p2_open", name
        for cohort in ("rank", "narrative", "judge", "surprise", "shodo", "reaction"):
            assert contamination(cohort, name) is None, (cohort, name)


def test_the_two_axes_share_an_entry_and_differ_only_in_what_moves():
    """The whole reason both exist.

    With only the exit-fixed pair, "the ranking orders at the fill price" and
    "the ranking orders over a three-session hold" are one observation. The
    entry is identical across all four series, so a difference within the
    exit-fixed pair is the entry and a difference within the holding-fixed pair
    is the duration.
    """
    assert prices_for(EVENT5) == ("i0p2_open", "d5_close")
    assert prices_for(EVENT20) == ("i0p2_open", "d20_close")
    assert prices_for(PLUS5) == ("i0p2_open", "i0p7_close")
    assert prices_for(PLUS20) == ("i0p2_open", "i0p22_close")

    # Within the entry axis every series ends at the same close, so a
    # difference along it is the entry and nothing else.
    exits = {prices_for(name)[1] for name in COMPARISON_AXIS["entry"]}
    assert exits == {"d5_close", "d20_close"}
    for horizon in exits:
        group = [n for n in COMPARISON_AXIS["entry"] if prices_for(n)[1] == horizon]
        assert len({prices_for(n)[0] for n in group}) == len(group) == 3

    # Within the duration axis every series starts at the same open, so a
    # difference along it is the hold and nothing else.
    assert {prices_for(name)[0] for name in COMPARISON_AXIS["duration"]} == {"i0p2_open"}
    assert len(COMPARISON_AXIS["duration"]) == 6

    # The axes cross, and the crossing point is a real series rather than an
    # ambiguity: the i0+2 entry into i0+5 is also the three-session hold. An
    # earlier form of this test forbade any overlap, which was a statement
    # about mixing them inside one table, not about a grid having a corner.
    shared = set(COMPARISON_AXIS["entry"]) & set(COMPARISON_AXIS["duration"])
    assert shared == {EVENT5}
    assert prices_for(EVENT5)[0] == "i0p2_open" and prices_for(EVENT5)[1] == "d5_close"


def test_every_series_is_named_by_the_sessions_it_spans():
    """And by nothing else.

    An earlier draft called these `decision_d1_close__entry_d2_open__…`, which
    asserts that the disclosure lands after i0's close and that i0+1 is the
    first reacting session. The record cannot support that — there is no
    announcement session, and `date` may be a before-open, intraday or
    after-close event — so the names say which sessions the prices come from
    and leave the interpretation to the ADR that owns it.

    `d5` alone was the other half of the problem: a five-session hold from the
    previous close, four from the first open, three from i0+2, all in one table.
    """
    for name in (EVENT5, EVENT20, PLUS5, PLUS20):
        assert name.startswith("entry_i0p") and "__exit_i0p" in name, name
        assert "decision_" not in name, name
    # The offsets are in the name, so the hold length is readable from it.
    assert prices_for(PLUS5)[1] == "i0p7_close"
    assert prices_for(EVENT5)[1] == "d5_close"


def test_a_label_fixed_after_every_price_is_still_refused():
    """The environment labels are future-informed at every anchor, and the new
    one is not an exception. Their span is read off the anchor table, so adding
    a price extends it without anybody remembering to."""
    for cohort in ("dollar_environment", "volatility_environment"):
        assert "i0p2_open" in COHORT_SPAN[cohort]
        assert contamination(cohort, EVENT5) is not None
        assert contamination(cohort, PLUS20) is not None


def test_the_field_lists_come_from_the_declaration_and_not_from_a_copy():
    """Three lists in two files used to restate the anchor table. Adding a
    price left all three short: it was computed on every row and summarised
    nowhere."""
    from earnings_research.legacy_research.aggregation import RETURN_FIELDS

    assert set(RETURN_FIELDS) == set(RETURN_ANCHOR)
    assert set(DERIVED_FIELDS) == {f for f, a in RETURN_ANCHOR.items() if a != "prev_close"}
    for name in (EVENT5, EVENT20, PLUS5, PLUS20):
        assert name in DERIVED_FIELDS, name


def test_the_fetch_reproduces_every_price_the_record_already_holds():
    """The check the fetch had to pass before anything rested on it.

    Same provider, same ticker convention, same session indexing as the retired
    pipeline, or the five known prices would not line up — and if they do not,
    the entry price it produced from the same series cannot be trusted either.
    """
    rows, source = fetched(), records()
    problems = disagreements(rows, source, accepted(ROOT / ENTRY_MANIFEST))
    assert problems == []
    checked = sum(
        1 for row in rows if row.get("status") == "ok"
        for value in row.get("derived", {}).values() if value is not None
    )
    assert checked > 1000, checked


def test_the_two_measured_disagreements_are_named_rather_than_tolerated():
    """A relative tolerance would be a rule nobody chose. These two are listed
    with their values, so a third fails instead of joining them."""
    manifest = json.loads((ROOT / ENTRY_MANIFEST).read_text(encoding="utf-8"))
    listed = manifest["accepted_discrepancies"]
    assert len(listed) == 2
    for item in listed:
        assert item["field"] == "next_open"
        assert abs(item["record"] - item["fetched"]) / item["record"] < 0.002
    # Without the allowlist the same check fails, which is what makes it a check.
    assert disagreements(fetched(), records()) != []


def test_the_committed_prices_match_the_digest_recorded_for_them():
    manifest = json.loads((ROOT / ENTRY_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["sha256"] == digest(ROOT / ENTRY_PRICES)
    assert manifest["event_count"] == len(records())


def test_events_with_no_session_are_kept_rather_than_dropped():
    """Eight of them, and seven are a malformed ticker rather than a market
    holiday — five real companies carrying a trailing zero. Keeping the rows
    means that count stays visible instead of being inferred from a gap between
    two totals."""
    rows = fetched()
    assert len(rows) == len(records())
    unpriced = [row for row in rows if row.get("status") != "ok"]
    assert len(unpriced) == 8
    assert len(by_event(rows)) == len(rows) - len(unpriced)


def test_a_record_without_a_fill_price_gets_the_key_anyway():
    """Absent as an empty value, not as a missing key: the aggregation reads
    prices by name and a missing key would raise where a missing price should
    simply produce no return."""
    merged = attach([{"code": "9999", "date": "2026-06-10"}], {})
    assert merged[0][ENTRY_FIELD] == ""


def test_a_missing_fetch_is_refused_rather_than_read_as_thin_data(tmp_path):
    """Without the file every entry-anchored return is None, which reads in the
    published tables as "not enough records" — the same words a genuinely small
    cohort gets. A missing fetch would look like a finding about the data."""
    with pytest.raises(FileNotFoundError):
        with_entry_prices(records(), tmp_path / "absent.jsonl", ROOT / ENTRY_MANIFEST)


def test_prices_that_do_not_match_their_digest_are_refused(tmp_path):
    prices = tmp_path / "prices.jsonl"
    prices.write_text((ROOT / ENTRY_PRICES).read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="do not match the digest"):
        with_entry_prices(records(), prices, ROOT / ENTRY_MANIFEST)


def test_a_price_file_that_omits_an_event_is_refused(tmp_path):
    """A digest proves the bytes are the ones recorded. Only coverage proves
    they are about the same events.

    A truncated file with a regenerated digest used to pass: `disagreements`
    iterates the fetched rows, so an omitted event has nothing to disagree
    with, and `attach` gave it an empty price. The published tables then showed
    a smaller denominator as though the observation had not occurred.
    """
    from earnings_research.legacy_research.entry_prices import uncovered

    rows, source = fetched(), records()
    assert uncovered(rows, source) == []
    assert len(uncovered(rows[:-5], source)) == 5

    prices = tmp_path / "sessions.jsonl"
    prices.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows[:-5]),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    payload = json.loads((ROOT / ENTRY_MANIFEST).read_text(encoding="utf-8"))
    payload["sha256"] = digest(prices)
    manifest.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    # The manifest still claims 254, so this trips the manifest-versus-file
    # check first — the one that used to compare the manifest against the
    # record, which it makes no claim about.
    with pytest.raises(ValueError, match="manifest records 254 events and the file holds 249"):
        with_entry_prices(source, prices, manifest)
    # With the count corrected too, the coverage check is what stands between a
    # trimmed file and five silently smaller denominators.
    payload["event_count"] = 249
    manifest.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="in the record but not in the fetched prices"):
        with_entry_prices(source, prices, manifest)


def test_an_event_recorded_as_having_no_session_still_counts_as_covered():
    """Different from an omission. The file states the session is absent, and
    the count of those stays visible; an omitted event says nothing at all."""
    from earnings_research.legacy_research.entry_prices import uncovered

    rows = fetched()
    unpriced = [row for row in rows if row.get("status") != "ok"]
    assert unpriced
    assert uncovered(rows, records()) == []


def test_a_signed_off_discrepancy_only_excuses_the_values_that_were_reviewed(tmp_path):
    """Keyed on the row and column alone, those two cells were exempt for
    whatever value ever appeared there — so a re-fetch reading the wrong ticker
    would sail past on the two cells most likely to reveal it."""
    from earnings_research.legacy_research.entry_prices import accepted

    allowed = accepted(ROOT / ENTRY_MANIFEST)
    assert set(allowed) == {("5609", "2026-07-29", "next_open"), ("8316", "2026-07-31", "next_open")}
    assert allowed[("5609", "2026-07-29", "next_open")] == (936.0, 935.0)

    rows = [row for row in fetched() if row["code"] == "5609" and row["event_date"] == "2026-07-29"]
    assert rows and disagreements(rows, records(), allowed) == []
    wrong = json.loads(json.dumps(rows[0]))
    wrong["derived"]["next_open"] = 500.0
    assert disagreements([wrong], records(), allowed) != []
