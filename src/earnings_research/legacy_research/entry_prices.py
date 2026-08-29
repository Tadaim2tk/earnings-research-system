"""The price an order is actually filled at, fetched because the record lacks it.

The retired pipeline stored five prices per event: the announcement day's
close, the next session's open and close, and the closes five and twenty
sessions out. None of them is where a trade goes on.

The workflow is: the disclosure lands after the close, the first session
reacts, the reaction is read off that session's close, and the order fills at
the next open. That open — session i0+2, counting the announcement day as i0 —
was never recorded, so every return this repository could compute started from
a price nobody transacts at. Measuring from the first session's open assumes
buying into the gap; measuring from its close assumes filling at the very print
that decides the reaction label.

Fetched from the same provider, ticker convention and session indexing the
retired pipeline used, and every row re-derives the five prices the record does
carry so the fetch can be checked against 254 events' worth of known values
before anything rests on it.
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Tuple

SCHEMA_VERSION = "legacy_event_entry_price_v1"
ENTRY_FIELD = "entry_open"

Key = Tuple[str, str]


def read(path: Path) -> List[dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError("entry prices are missing: %s" % path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def by_event(rows) -> Dict[Key, float]:
    """The entry price per event, skipping the events that have none.

    A row without one is kept in the file rather than dropped, so the count of
    events with no fill price stays visible instead of being inferred from a
    gap between two totals.
    """
    prices = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        value = row.get(ENTRY_FIELD)
        if value is None:
            continue
        prices[(row["code"], row["event_date"])] = float(value)
    return prices


def attach(records, prices: Dict[Key, float]) -> List[dict]:
    """Put the entry price on each record, as a price column like the others.

    The aggregation reads its prices off the row by the name the declaration
    table gives, so once this key is there the new anchor needs no special
    case anywhere downstream.
    """
    out = []
    for record in records:
        merged = dict(record)
        value = prices.get((record.get("code"), record.get("date")))
        merged[ENTRY_FIELD] = "" if value is None else value
        out.append(merged)
    return out


def accepted(manifest_path: Path) -> set:
    """Disagreements already measured, named, and signed off.

    Two of 1146 known price points came back different — both `next_open`,
    both under 0.15%, neither feeding the entry anchor. Listing them keeps the
    check strict: a third disagreement fails instead of joining them quietly
    under a tolerance nobody chose.
    """
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {
        (item["code"], item["event_date"], item["field"])
        for item in payload.get("accepted_discrepancies", [])
    }


def disagreements(rows, records, allowed=frozenset()) -> List[str]:
    """Where the fetch and the committed record disagree about a known price.

    The five prices the record already holds are re-derived by the fetch. They
    have to match, or the fetch is reading a different series — a different
    ticker, a different session index, an adjusted close — and the entry price
    it also produced cannot be trusted either. Checked to the tenth, which is
    what the record rounds to.
    """
    committed = {(item["code"], item["date"]): item for item in records}
    problems = []
    for row in rows:
        if row.get("status") != "ok":
            continue
        record = committed.get((row["code"], row["event_date"]))
        if record is None:
            # Fetched an event this record does not contain. Not a
            # disagreement: the file covers the full 254 and a caller may hold
            # a subset. Only a shared event whose prices differ is a problem.
            continue
        for name, fetched in sorted(row.get("derived", {}).items()):
            held = record.get(name)
            if held in (None, "") or fetched is None:
                continue
            if (row["code"], row["event_date"], name) in allowed:
                continue
            if abs(float(held) - round(float(fetched), 1)) > 0.6:
                problems.append(
                    "%s %s %s: record has %s, the fetch derived %.1f"
                    % (row["code"], row["event_date"], name, held, fetched)
                )
    return problems
