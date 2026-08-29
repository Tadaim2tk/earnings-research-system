"""The source review, made binding rather than decorative.

A rule written in a document and checked by nobody is the failure this project
keeps finding in its own work: `at_least_as_strict_as` was dead code, the
reserved period leaked into published figures, the contamination table was
corrected in one renderer and not the other. So the review's own conclusion —
that nothing may be fetched from a candidate still under terms review — is
asserted here against the two things that would contradict it: the table, and
the capture directory.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/PRICE_DATA_SOURCE_REVIEW.md"
CAPTURES = ROOT / "data/evidence"

SECTION = "## Evidence / Population 取得元レビュー"

# Approval is affirmative and nothing else counts. Listing the *unresolved*
# statuses instead let a decorated one slip past: `pending_candidate_terms_review
# （上表から）` did not match the list, so the review read as having an approved
# source and the check that depends on it skipped itself entirely. Same shape as
# `is_usable`, which passes only an affirmative `valid` — an unrecognised status
# is not permission.
APPROVED = frozenset({"approved"})


def section() -> str:
    text = REVIEW.read_text(encoding="utf-8")
    assert SECTION in text, "the evidence section is missing from the review"
    start = text.index(SECTION)
    end = text.index("\n## ", start + 1)
    return text[start:end]


def candidate_rows():
    """The candidate table's rows, which is where a status lives.

    Scoped to the `### 候補` block rather than to every table in the section:
    the criteria table above it also starts its rows with a backtick, and a
    first version of this read both and reported a criterion as a candidate
    with no status.

    Read out of the document rather than duplicated into the test: a copy here
    would be a second place to update, and the one that goes stale is always
    the copy.
    """
    body = section()
    start = body.index("### 候補")
    end = body.index("\n### ", start + 1)
    rows = []
    for line in body[start:end].splitlines():
        if not line.startswith("| `"):
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_every_evidence_candidate_carries_a_review_status():
    rows = candidate_rows()
    assert rows, "the candidate table has no rows"
    for cells in rows:
        assert cells[-1].strip("` "), cells[0]


def test_an_unrecognised_status_is_not_taken_for_approval():
    """Fail closed. A status nobody has defined — a typo, a new word, a
    decorated one — must not be read as permission to fetch."""
    for cells in candidate_rows():
        status = cells[-1].strip("` ").split("（")[0].strip()
        assert status in APPROVED or "pending" in status, (cells[0], status)


def test_nothing_is_captured_while_every_candidate_is_still_under_review():
    """The rule the review states, checked against the directory it governs.

    Written down, this is a sentence. Checked, it is the thing that stops a
    capture adapter from being wired to a source whose terms nobody read —
    which is exactly how the yfinance prices were fetched before anyone noticed
    the repository forbade it.
    """
    approved = [
        cells for cells in candidate_rows()
        if cells[-1].strip("` ").split("（")[0].strip() in APPROVED
    ]
    captures = sorted(CAPTURES.glob("*/population.json"))
    if not approved:
        assert not captures, (
            "evidence was captured while every candidate is still under terms review: %s"
            % [str(p.parent.name) for p in captures]
        )


def test_no_cell_in_the_evidence_table_was_guessed_at():
    """`unknown` is the honest value and the table says so.

    The review's own boundary is public information only — no contracts, no
    accounts, no API calls, no scraping. A cell that could not be established
    that way has to read `unknown` rather than a plausible-sounding answer,
    for the same reason `undeclared`, `capture_status` and `timing_class`
    exist elsewhere in this system.
    """
    body = section()
    assert "unknown" in body
    assert "推測で埋めない" in body
    # Every candidate row still has at least one open question today.
    for cells in candidate_rows():
        assert any("unknown" in cell for cell in cells), cells[0]


def test_the_review_states_what_it_did_not_do():
    """The methodology, carried from the price table above it. Without it a
    reader cannot tell a checked cell from an assumed one."""
    body = section()
    for claim in ("契約", "account作成", "API接続", "scraping"):
        assert claim in body, claim
