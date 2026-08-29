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
    DERIVED_FIELDS,
    RETURN_ANCHOR,
    contamination,
    prices_for,
)

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
    assert prices_for("entry_d5") == ("entry_open", "d5_close")
    assert prices_for("entry_d20") == ("entry_open", "d20_close")
    for cohort in ("rank", "narrative", "judge", "surprise", "shodo", "reaction"):
        assert contamination(cohort, "entry_d5") is None, cohort
        assert contamination(cohort, "entry_d20") is None, cohort


def test_a_label_fixed_after_every_price_is_still_refused():
    """The environment labels are future-informed at every anchor, and the new
    one is not an exception. Their span is read off the anchor table, so adding
    a price extends it without anybody remembering to."""
    for cohort in ("dollar_environment", "volatility_environment"):
        assert "entry_open" in COHORT_SPAN[cohort]
        assert contamination(cohort, "entry_d5") is not None


def test_the_field_lists_come_from_the_declaration_and_not_from_a_copy():
    """Three lists in two files used to restate the anchor table. Adding a
    price left all three short: it was computed on every row and summarised
    nowhere."""
    from earnings_research.legacy_research.aggregation import RETURN_FIELDS

    assert set(RETURN_FIELDS) == set(RETURN_ANCHOR)
    assert set(DERIVED_FIELDS) == {f for f, a in RETURN_ANCHOR.items() if a != "prev_close"}
    assert "entry_d5" in DERIVED_FIELDS and "entry_d20" in DERIVED_FIELDS


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
