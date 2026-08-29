"""The source review, made binding rather than decorative.

A rule written in a document and checked by nobody is the failure this project
keeps finding in its own work: `at_least_as_strict_as` was dead code, the
reserved period leaked into published figures, the contamination table was
corrected in one renderer and not the other. So the review's own conclusion —
that nothing may be fetched from a candidate still under terms review — is
asserted here against the two things that would contradict it: the table, and
the capture directory.
"""

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

# The same source can be permitted for one use and not another: reading a
# roster and permanently storing a document body are different licences. A
# single bit per source would let approval of one carry the other.
USES = ("population_discovery", "evidence_capture", "timing_provenance")


def section() -> str:
    text = REVIEW.read_text(encoding="utf-8")
    assert SECTION in text, "the evidence section is missing from the review"
    start = text.index(SECTION)
    end = text.index("\n## ", start + 1)
    return text[start:end]


def candidate_rows():
    """The candidate table's rows, which is where a status lives.

    Scoped to the `### 候補` block rather than to every table in the section:
    the criteria and use tables above it also start their rows with a backtick,
    and a first version of this read all of them and reported a criterion as a
    candidate with no status.
    """
    body = section()
    start = body.index("### 候補")
    rows = []
    for line in body[start:].splitlines():
        if not line.startswith("| `"):
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def status_of(cells) -> str:
    return cells[-1].strip("` ").split("（")[0].strip()


def approved_uses() -> set:
    """The `(source, use)` pairs that carry an affirmative approval."""
    return {
        (cells[0].strip("` "), cells[1].strip("` "))
        for cells in candidate_rows()
        if status_of(cells) in APPROVED
    }


def committed_captures():
    """Every capture artifact, by either of the two files that make one.

    Discovering by `population.json` alone was the hole: `append_bundles()`
    creates a ledger and its parent directory on its own, so a change adding
    only `bundles.jsonl` — captured third-party text, no manifest — was invisible
    to the gate. An orphan ledger is a capture too.
    """
    return sorted(
        list(CAPTURES.glob("*/population.json")) + list(CAPTURES.glob("*/bundles.jsonl"))
    )


def test_every_candidate_names_a_source_a_use_and_a_status():
    rows = candidate_rows()
    assert rows, "the candidate table has no rows"
    for cells in rows:
        assert cells[0].strip("` "), cells
        assert cells[1].strip("` ") in USES, (cells[0], cells[1])
        assert status_of(cells), cells[0]


def test_an_unrecognised_status_is_not_taken_for_approval():
    """Fail closed. A status nobody has defined — a typo, a new word, a
    decorated one — must not be read as permission to fetch."""
    for cells in candidate_rows():
        status = status_of(cells)
        assert status in APPROVED or "pending" in status, (cells[0], cells[1], status)


def test_every_use_is_reviewed_separately_for_every_source():
    """Reading a roster and permanently storing a document body are different
    licences. One row per source would let approval of the first carry the
    second."""
    pairs = [(cells[0].strip("` "), cells[1].strip("` ")) for cells in candidate_rows()]
    assert len(pairs) == len(set(pairs)), "a (source, use) pair is listed twice"
    sources = {source for source, _ in pairs}
    assert len(sources) < len(pairs), "no source is reviewed for more than one use"


def test_nothing_is_captured_while_no_use_is_approved_for_capture():
    """The rule the review states, checked against the directory it governs.

    Keyed to `evidence_capture` specifically. Approval of a population source
    is not approval to store document bodies, and an earlier version of this
    check disabled itself as soon as *any* candidate was approved.
    """
    permitted = {source for source, use in approved_uses() if use == "evidence_capture"}
    captures = committed_captures()
    if not permitted:
        assert not captures, (
            "evidence was captured while no source is approved for evidence_capture: %s"
            % [str(p.relative_to(ROOT)) for p in captures]
        )


def test_no_cell_in_the_evidence_table_was_guessed_at():
    """`unknown` is the honest value and the table says so.

    The review's own boundary is public information only — no contracts, no
    accounts, no API calls, no scraping. A cell that could not be established
    that way has to read `unknown` rather than a plausible-sounding answer.
    """
    body = section()
    assert "unknown" in body
    assert "推測で埋めない" in body
    for cells in candidate_rows():
        assert any("unknown" in cell for cell in cells), (cells[0], cells[1])


def test_the_review_states_what_it_did_not_do():
    body = section()
    for claim in ("契約", "account作成", "API接続", "scraping"):
        assert claim in body, claim
