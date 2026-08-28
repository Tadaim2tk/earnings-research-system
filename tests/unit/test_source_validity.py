"""The standing re-examination of frozen knowledge.

A hypothesis is frozen so nobody can change what it claims. Whether its
evidence still holds is a separate question, and the answer moves: the
contamination rules grew twice in one change, and each time knowledge frozen
earlier stopped being supportable without anything saying so.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from earnings_research.prospective_hypotheses.models import HypothesisRegistry
from earnings_research.prospective_hypotheses.pipeline import (
    evaluate_source_validity_file,
    verify_source_validity_file,
)
from earnings_research.prospective_hypotheses.source_validity import (
    INVALID,
    UNDECLARED,
    VALID,
    append_ledger,
    effective_status,
    is_usable,
    judge,
    rates,
    read_ledger,
    source_field_for,
    unevaluated,
)
from earnings_research.statistics import lookahead

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "data/prospective_hypotheses/legacy_research_v1.json"
LEDGER = ROOT / "data/prospective_hypotheses/source_validity.jsonl"
JST = timezone(timedelta(hours=9))

# What the historical analysis measured each horizon with, written out rather
# than imported: if knowledge.py's mapping changes, the pairing being judged
# changes with it, and the verdicts would move without anyone deciding to move
# them.
SOURCE_FIELDS = {"D1": "ret_d1", "D5": "ret_d5", "D20": "ret_d20"}


def registry():
    return HypothesisRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))


def test_the_horizon_is_judged_on_the_return_the_analysis_used():
    for horizon, field in SOURCE_FIELDS.items():
        assert source_field_for(horizon) == field
    with pytest.raises(KeyError):
        source_field_for("D60")


def test_the_rules_have_a_name_that_moves_when_they_do(monkeypatch):
    """Without one, a verdict recorded today cannot be told apart from one
    recorded before a rule existed — and that difference is the whole point."""
    before = lookahead.rules_digest()
    assert lookahead.rules_digest() == before
    monkeypatch.setitem(lookahead.COHORT_SPAN, "some_new_cohort", frozenset({"prev_close"}))
    assert lookahead.rules_digest() != before
    monkeypatch.delitem(lookahead.COHORT_SPAN, "some_new_cohort")
    assert lookahead.rules_digest() == before


def test_the_name_does_not_depend_on_the_order_the_rules_were_written():
    """A reordering is not a change of standard, and would otherwise unjudge
    every hypothesis in the registry."""
    before = lookahead.rules_digest()
    original = dict(lookahead.COHORT_SPAN)
    try:
        lookahead.COHORT_SPAN.clear()
        lookahead.COHORT_SPAN.update(dict(reversed(list(original.items()))))
        assert lookahead.rules_digest() == before
    finally:
        lookahead.COHORT_SPAN.clear()
        lookahead.COHORT_SPAN.update(original)


def test_a_cohort_the_rules_do_not_cover_is_not_reported_as_sound(monkeypatch):
    """`contamination` passes an undeclared cohort on purpose, but "checked and
    sound" and "not covered" are different findings and a ledger that records
    them as one number hides the second.

    Every dimension in the committed registry is declared now, so the case is
    made by taking one back out — which is also what a rule being removed would
    look like.
    """
    monkeypatch.delitem(lookahead.COHORT_SPAN, "reaction")
    verdicts = judge(registry(), "2026-09-01T00:00:00+09:00")
    kinds = {item.verdict for item in verdicts}
    assert UNDECLARED in kinds
    for item in verdicts:
        if item.verdict == UNDECLARED:
            assert not lookahead.declares(item.dimension)
            assert "not declared" in item.reason
        if item.verdict == VALID:
            assert lookahead.declares(item.dimension)


def test_every_dimension_the_registry_uses_is_covered_by_the_rules():
    """An undeclared cohort in the committed registry means the rules have a
    gap on knowledge that is already frozen — which is how dollar_environment
    sat as `undeclared` while its labels turned on data from after the event."""
    for item in registry().hypotheses:
        assert lookahead.declares(item.dimension), item.dimension


def test_the_committed_verdicts_are_the_ones_the_rules_produce_today():
    """Derived, not asserted at a remembered number: an audit put the count at
    eight before rank, judge and the reason codes entered the rules, and the
    check has to answer with what the rules say now rather than what somebody
    expected."""
    ledger = read_ledger(LEDGER)
    assert ledger, "the committed ledger is missing"
    current = effective_status(ledger)
    expected = {}
    for item in registry().hypotheses:
        field = SOURCE_FIELDS[item.evaluation_horizon]
        reason = lookahead.contamination(item.dimension, field)
        expected[(item.hypothesis_id, item.hypothesis_version)] = (
            INVALID if reason else (VALID if lookahead.declares(item.dimension) else UNDECLARED)
        )
    assert {key: row["verdict"] for key, row in current.items()} == expected


def test_a_change_of_standard_leaves_the_frozen_knowledge_unjudged(monkeypatch):
    """This is the situation the capability exists for: the rules move, and
    knowledge frozen under the old ones is neither valid nor invalid until
    somebody looks again."""
    ledger = read_ledger(LEDGER)
    assert unevaluated(registry(), ledger) == []
    monkeypatch.setitem(lookahead.COHORT_SPAN, "dollar_environment", frozenset({"prev_close"}))
    assert len(unevaluated(registry(), ledger)) == len(registry().hypotheses)


def test_the_ledger_keeps_the_old_verdict_when_the_standard_moves(tmp_path):
    """A history, not a current-state file. Rewriting it would erase the only
    evidence of when the standard moved."""
    path = tmp_path / "source_validity.jsonl"
    append_ledger(path, judge(registry(), "2026-09-01T00:00:00+09:00"))
    first = read_ledger(path)
    original = dict(lookahead.COHORT_SPAN)
    try:
        lookahead.COHORT_SPAN["dollar_environment"] = frozenset({"prev_close"})
        append_ledger(path, judge(registry(), "2026-09-02T00:00:00+09:00"))
        second = read_ledger(path)
        assert len(second) == 2 * len(first)
        assert second[: len(first)] == first
        moved = effective_status(second)
        assert all(row["verdict"] == INVALID for row in moved.values())
    finally:
        lookahead.COHORT_SPAN.clear()
        lookahead.COHORT_SPAN.update(original)
    # And the earlier judgement is still readable, under its own digest.
    digests = {row["contamination_rules_sha256"] for row in read_ledger(path)}
    assert len(digests) == 2


def test_the_effective_status_is_the_latest_word_under_the_current_rules(tmp_path):
    path = tmp_path / "source_validity.jsonl"
    early = judge(registry(), "2026-09-01T00:00:00+09:00")
    append_ledger(path, early)
    append_ledger(path, judge(registry(), "2026-09-05T00:00:00+09:00"))
    current = effective_status(read_ledger(path))
    assert len(current) == len(registry().hypotheses)
    assert {row["evaluated_at"] for row in current.values()} == {"2026-09-05T00:00:00+09:00"}


@pytest.mark.parametrize("verdict,usable", [(VALID, True), (UNDECLARED, False), (INVALID, False)])
def test_only_knowledge_the_rules_affirmatively_clear_may_gather_evidence(verdict, usable):
    """`undeclared` is not permission. Letting it through treated "we have not
    looked" as "go ahead", and two hypotheses passed the gate on it whose
    labels were afterwards measured to depend on data from seventy days after
    the event they describe."""
    row = {
        "hypothesis_id": "LRH-X", "hypothesis_version": 1, "verdict": verdict,
        "evaluated_at": "2026-09-01T00:00:00+09:00",
        "contamination_rules_sha256": lookahead.rules_digest(),
    }
    assert is_usable("LRH-X", 1, [row]) is usable


def test_knowledge_nobody_has_judged_may_not_gather_evidence_either():
    assert is_usable("LRH-X", 1, []) is False


def test_the_two_rates_answer_different_questions():
    """One of them can be improved by never adding a rule again."""
    numbers = rates(registry(), read_ledger(LEDGER))
    assert numbers["frozen_count"] == len(registry().hypotheses)
    assert numbers["judged_count"] == numbers["frozen_count"]
    assert 0 <= numbers["retroactive_invalidation_rate"] <= 1
    per_registry = numbers["by_registry"]
    assert per_registry, "the per-freeze rate is what shows a later registry repeating the mistake"
    for counts in per_registry.values():
        assert counts["frozen"] > 0
        assert counts["invalidation_rate"] == pytest.approx(counts["invalid"] / counts["frozen"])


def test_re_evaluating_without_a_change_of_standard_appends_nothing(tmp_path):
    path = tmp_path / "source_validity.jsonl"
    first = evaluate_source_validity_file(REGISTRY, path, datetime(2026, 9, 1, tzinfo=JST))
    second = evaluate_source_validity_file(REGISTRY, path, datetime(2026, 9, 2, tzinfo=JST))
    assert first["appended"] == len(registry().hypotheses)
    assert second["appended"] == 0
    assert second["already_judged"] == len(registry().hypotheses)


def test_verification_refuses_a_registry_the_current_rules_have_not_seen(tmp_path):
    empty = tmp_path / "source_validity.jsonl"
    with pytest.raises(ValueError, match="no source-validity verdict"):
        verify_source_validity_file(REGISTRY, empty)
    evaluate_source_validity_file(REGISTRY, empty, datetime(2026, 9, 1, tzinfo=JST))
    assert verify_source_validity_file(REGISTRY, empty)["status"] == "judged"


def test_the_committed_ledger_matches_its_schema():
    schema = json.loads(
        (ROOT / "schemas/analysis/prospective_hypothesis_source_validity.schema.json").read_text(
            encoding="utf-8"
        )
    )
    rows = read_ledger(LEDGER)
    assert rows
    for row in rows:
        jsonschema.validate(row, schema)


def test_the_committed_ledger_is_judged_under_the_rules_as_they_stand():
    """The check CI runs, stated here so a rule added without re-running the
    command fails the suite as well."""
    assert verify_source_validity_file(REGISTRY, LEDGER)["status"] == "judged"
