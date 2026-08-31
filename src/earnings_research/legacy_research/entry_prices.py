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

SCHEMA_VERSION = "legacy_event_sessions_v1"
ENTRY_FIELD = "i0p2_open"

# Which session each price column comes from, counting the announcement day as
# i0. Written as offsets rather than as five named fetches, because the first
# pass stored named prices and adding one series meant fetching all 254 events
# again — a research question shaped by what was convenient to store.
PRICE_OFFSETS = {
    "i0p2_open": (2, "open"),
    "i0p3_close": (3, "close"),
    "i0p4_close": (4, "close"),
    "i0p7_close": (7, "close"),
    "i0p12_close": (12, "close"),
    "i0p22_close": (22, "close"),
}

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


def by_event(rows) -> Dict[Key, Dict[str, float]]:
    """Every price column each event can supply, read off its sessions.

    A row with no sessions is kept in the file rather than dropped, so the
    count of events with no fill price stays visible instead of being inferred
    from a gap between two totals. An event whose window ends before an offset
    simply has no value at that offset — a twenty-session hold from the fill
    runs past the record's end for the most recent events, and that is an
    absence, not a zero.
    """
    prices: Dict[Key, Dict[str, float]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        sessions = {item["offset"]: item for item in row.get("sessions", [])}
        values = {}
        for name, (offset, which) in PRICE_OFFSETS.items():
            session = sessions.get(offset)
            if session and session.get(which) is not None:
                values[name] = float(session[which])
        if values:
            prices[(row["code"], row["event_date"])] = values
    return prices


def attach(records, prices: Dict[Key, Dict[str, float]]) -> List[dict]:
    """Put the fetched prices on each record, as columns like the others.

    The aggregation reads prices off the row by the name the declaration table
    gives, so once these keys are there a new series needs no special case
    anywhere downstream. Every key is always present — empty where there is no
    price — because a missing key raises where a missing price should simply
    produce no return.
    """
    out = []
    for record in records:
        merged = dict(record)
        found = prices.get((record.get("code"), record.get("date")), {})
        for name in PRICE_OFFSETS:
            value = found.get(name)
            merged[name] = "" if value is None else value
        out.append(merged)
    return out


def accepted(manifest_path: Path) -> Dict[tuple, tuple]:
    """Disagreements already measured, named, and signed off — with their values.

    Two of 1146 known price points came back different: both `next_open`, both
    under 0.15%, neither feeding the entry anchor. Listing them keeps the check
    strict, so a third fails instead of joining them under a tolerance nobody
    chose.

    Keyed to the exact pair of numbers, not just to the row and the column.
    Keyed on `(code, date, field)` alone, those two cells were exempt for
    whatever value ever appeared there — so a re-fetch that read the wrong
    ticker would sail past on the two cells most likely to show it.
    """
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {
        (item["code"], item["event_date"], item["field"]): (item["record"], item["fetched"])
        for item in payload.get("accepted_discrepancies", [])
    }


def uncovered(rows, records) -> List[str]:
    """Events in the record that the fetched file says nothing about.

    Not the same as an event with no price. A row recorded as `no_session` is
    covered — the file states that the session is absent, and the count of
    those stays visible. An event the file omits entirely is different: the
    aggregation would give it an empty price and publish a smaller denominator
    as though the observation had simply not occurred.

    That is how a truncated file with a regenerated digest used to pass. The
    digest proves the bytes are the ones recorded; only this proves they are
    about the same events.
    """
    fetched = {(row.get("code"), row.get("event_date")) for row in rows}
    return [
        "%s %s is in the record but not in the fetched prices"
        % (item.get("code"), item.get("date"))
        for item in records
        if (item.get("code"), item.get("date")) not in fetched
    ]


def disagreements(rows, records, allowed=None) -> List[str]:
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
            signed_off = (allowed or {}).get((row["code"], row["event_date"], name))
            if signed_off and (
                abs(float(held) - signed_off[0]) < 1e-9
                and abs(float(fetched) - signed_off[1]) < 1e-9
            ):
                continue
            if abs(float(held) - round(float(fetched), 1)) > 0.6:
                problems.append(
                    "%s %s %s: record has %s, the fetch derived %.1f"
                    % (row["code"], row["event_date"], name, held, fetched)
                )
    return problems
