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

# The whole vocabulary, enumerated so an unrecognised word fails rather than
# landing in whichever branch happens to catch it. Only `approved` grants.
#
# `approved_candidate` is deliberately not approval: it means the terms and the
# capability fit, and a contract-and-cost decision is still open. A source can
# sit there indefinitely without unlocking anything.
STATUSES = frozenset({
    "approved",
    "approved_candidate",
    "pending_terms_review",
    "pending_per_site_review",
    "corroboration_only",
    "not_approved",
})

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


def test_every_status_is_one_the_review_defines():
    """Fail closed. A typo, a new word or a decorated one must not land in
    whichever branch happens to catch it."""
    for cells in candidate_rows():
        assert status_of(cells) in STATUSES, (cells[0], cells[1], status_of(cells))


def test_being_a_candidate_is_not_being_approved():
    """`approved_candidate` means the terms and the capability fit and a
    contract-and-cost decision is still open. It unlocks nothing.

    Stated as a property of the status rather than of today's table. Requiring
    a candidate row to exist would fail CI the moment the last one is promoted
    to `approved` — the outcome the document plans for — so the test would have
    blocked the very step it was written to protect.
    """
    assert "approved_candidate" not in APPROVED
    for cells in candidate_rows():
        if status_of(cells) == "approved_candidate":
            assert (cells[0].strip("` "), cells[1].strip("` ")) not in approved_uses()


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


def test_a_row_with_an_open_question_cannot_be_advanced():
    """`unknown` is the honest value, and a row carrying one has not been
    settled enough to be approved or even to be a candidate.

    An earlier version asserted every row had at least one `unknown`, which was
    true while nothing had been researched and became wrong the moment a source
    was. The property that survives that is the other direction: an open
    question blocks advancement, rather than every row being obliged to have one.
    """
    body = section()
    assert "unknown" in body and "推測で埋めない" in body
    for cells in candidate_rows():
        status = status_of(cells)
        if status in ("approved", "approved_candidate"):
            open_cells = [c for c in cells if "unknown" in c]
            assert not open_cells, (cells[0], cells[1], status, open_cells)


def test_the_review_states_what_it_did_not_do():
    body = section()
    for claim in ("契約", "account作成", "API接続", "scraping"):
        assert claim in body, claim


def test_no_disclosure_body_is_committed_to_this_public_repository():
    """The constraint discovered after the capture models were designed.

    This repository is public. The terms permit fetching and accumulating
    disclosures for one's own analysis and do not permit redistribution, so a
    body committed here is redistributed the moment it lands — a contract would
    not make it allowed.

    `ERS-ADR-0060` designed `data/evidence/` as a committed artifact before that
    was checked. What may be committed is the hash, the URL, the retrieval time
    and the status; the body belongs in a private store outside the repository.
    Committed hashes still prove that a later re-read returned the same text,
    which is what replay needs.
    """
    import json

    for ledger in CAPTURES.glob("*/bundles.jsonl"):
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            assert row.get("content") is None, (
                "%s carries a disclosure body; this repository is public"
                % ledger.relative_to(ROOT)
            )
            assert row.get("content_sha256") is not None or row.get(
                "capture_status"
            ) != "captured", ledger.relative_to(ROOT)


def test_the_review_records_where_the_body_may_and_may_not_live():
    """Written down because the separation has to be decided before the first
    fetch: a body published once cannot be unpublished."""
    body = section()
    for claim in ("public", "private store", "再配信"):
        assert claim in body, claim


def test_the_terms_that_drive_the_design_can_be_reproduced():
    """A licensing conclusion with no citation cannot be re-checked.

    These conclusions decide where a disclosure body may live, so an auditor —
    or the next person to promote a candidate — has to be able to read the same
    pages. Terms change; a conclusion with no retrieval date cannot be told
    apart from one that was true last year.
    """
    body = section()
    assert "### 参照した公開情報" in body
    start = body.index("### 参照した公開情報")
    end = body.index("\n### ", start + 1)
    citations = [line for line in body[start:end].splitlines() if line.startswith("| ")]
    # header, rule, and one row per source
    assert len(citations) >= 5, citations
    for line in citations[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert cells[1], line          # 参照
        assert "2026-" in cells[2], line   # 取得日
        assert cells[3], line          # 読み取ったこと


def test_promotion_is_gated_on_re_reading_those_pages():
    """Written into the document rather than left as a habit: the check above
    proves the citations exist, and this proves the document says they must be
    taken again before anything is promoted."""
    body = section()
    assert "取り直して差分を確認する" in body


def test_what_is_still_unknown_is_named_rather_than_left_blank():
    """One question decides whether the free path exists at all, and the
    document has to say which one it is."""
    body = section()
    assert "### 未確定のまま残っていること" in body
    assert "DisclosedTime" in body
    assert "予定は確認ではない" in body
