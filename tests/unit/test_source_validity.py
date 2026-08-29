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
    source_fields_digest,
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
        "registry_id": "ERS-X", "registry_version": 1,
        "evaluated_at": "2026-09-01T00:00:00+09:00",
        "contamination_rules_sha256": lookahead.rules_digest(),
        "source_fields_sha256": source_fields_digest(),
    }
    assert is_usable("ERS-X", 1, "LRH-X", 1, [row]) is usable


def test_knowledge_nobody_has_judged_may_not_gather_evidence_either():
    assert is_usable("ERS-X", 1, "LRH-X", 1, []) is False


def test_a_successor_freeze_is_not_cleared_by_its_predecessors_verdict():
    """The gate and the standing check must refuse the same things.

    A definition carried forward unchanged draws the same verdict, so keying on
    the definition alone looks harmless — but it means no verdict is ever
    recorded against the new freeze. Trials could then be recorded against
    knowledge that was never judged where it was frozen, while
    `verify-source-validity` refused the very same registry.
    """
    row = {
        "hypothesis_id": "LRH-X", "hypothesis_version": 1, "verdict": VALID,
        "registry_id": "ERS-X", "registry_version": 1,
        "evaluated_at": "2026-09-01T00:00:00+09:00",
        "contamination_rules_sha256": lookahead.rules_digest(),
        "source_fields_sha256": source_fields_digest(),
    }
    assert is_usable("ERS-X", 1, "LRH-X", 1, [row]) is True
    assert is_usable("ERS-X", 2, "LRH-X", 1, [row]) is False


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


# --- 実装監査が「生存した」と報告した変異を殺す ---------------------------------

def test_the_standard_covers_the_mapping_that_decides_which_pairing_is_judged(monkeypatch):
    """`source_field_for` reads knowledge.py's horizon mapping, so that mapping
    decides which pairing gets judged. Left outside the digests, changing d5
    from ret_d5 to open_d5 moved four verdicts while the rules digest sat
    still, and the re-scan never fired."""
    from earnings_research.legacy_research import knowledge

    ledger = read_ledger(LEDGER)
    assert unevaluated(registry(), ledger) == []
    monkeypatch.setitem(knowledge.HORIZONS, "d5", "open_d5")
    assert len(unevaluated(registry(), ledger)) == len(registry().hypotheses)


def test_the_digest_does_not_depend_on_how_the_process_hashed_its_sets():
    """Dropping the sort inside the spans made the digest vary with
    PYTHONHASHSEED — three values across four seeds — so two machines would
    disagree about whether the standard had moved."""
    import subprocess
    import sys

    digests = set()
    for seed in ("0", "1", "2", "3", "7"):
        result = subprocess.run(
            [sys.executable, "-c",
             "from earnings_research.statistics.lookahead import rules_digest;print(rules_digest())"],
            capture_output=True, text=True, check=True,
            env={"PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        )
        digests.add(result.stdout.strip())
    assert len(digests) == 1, digests


def test_the_digest_ignores_the_order_the_span_members_were_written():
    """The only genuinely non-deterministic ordering in the rules."""
    before = lookahead.rules_digest()
    original = dict(lookahead.COHORT_SPAN)
    try:
        lookahead.COHORT_SPAN["reaction"] = frozenset(reversed(sorted(original["reaction"])))
        assert lookahead.rules_digest() == before
        lookahead.COHORT_SPAN["reaction"] = frozenset({"prev_close"})
        assert lookahead.rules_digest() != before
    finally:
        lookahead.COHORT_SPAN.clear()
        lookahead.COHORT_SPAN.update(original)


def test_a_verdict_stamped_in_another_timezone_does_not_win_by_its_digits():
    """Compared as strings, +00:00 loses to an earlier +09:00 and the ledger
    reports the superseded answer."""
    later = {
        "hypothesis_id": "LRH-X", "hypothesis_version": 1, "verdict": INVALID,
        "evaluated_at": "2026-09-01T00:00:00+00:00",
        "contamination_rules_sha256": lookahead.rules_digest(),
        "source_fields_sha256": source_fields_digest(),
    }
    earlier = {**later, "verdict": VALID, "evaluated_at": "2026-09-01T08:00:00+09:00"}
    assert earlier["evaluated_at"] > later["evaluated_at"]  # as text
    assert effective_status([earlier, later])[("LRH-X", 1)]["verdict"] == INVALID


def test_two_freezes_sharing_a_hypothesis_id_each_keep_their_own_rate():
    """Bucketing on the hypothesis alone dropped one of them, which is the case
    the per-freeze rate exists to show."""
    rows = []
    for index, (registry_version, verdict) in enumerate(((1, INVALID), (2, VALID))):
        rows.append({
            "hypothesis_id": "LRH-SAME", "hypothesis_version": 1, "verdict": verdict,
            "registry_id": "ERS-X", "registry_version": registry_version,
            "evaluated_at": "2026-09-0%dT00:00:00+09:00" % (index + 1),
            "contamination_rules_sha256": lookahead.rules_digest(),
            "source_fields_sha256": source_fields_digest(),
        })
    from earnings_research.prospective_hypotheses.source_validity import rates as compute

    class _One:
        registry_id = "ERS-X"
        registry_version = 1
        hypotheses = []

    buckets = compute(_One(), rows)["by_registry"]
    assert set(buckets) == {"ERS-X@v1", "ERS-X@v2"}
    assert buckets["ERS-X@v1"]["invalidation_rate"] == 1.0
    assert buckets["ERS-X@v2"]["invalidation_rate"] == 0.0


def test_the_headline_rate_counts_what_it_says_it_counts():
    """Swapping the numerator to undeclared, or the denominator to the frozen
    count, or faking any of the three counts, all passed: the earlier test
    computed its expectation from the function's own output."""
    ledger = read_ledger(LEDGER)
    numbers = rates(registry(), ledger)
    current = effective_status(ledger)
    invalid = sum(1 for row in current.values() if row["verdict"] == INVALID)
    undeclared = sum(1 for row in current.values() if row["verdict"] == UNDECLARED)
    assert numbers["frozen_count"] == len(registry().hypotheses)
    assert numbers["judged_count"] == len(current)
    assert numbers["invalid_count"] == invalid
    assert numbers["undeclared_count"] == undeclared
    assert numbers["retroactive_invalidation_rate"] == pytest.approx(invalid / len(current))


def test_re_judging_is_keyed_to_the_standard_and_not_to_the_hypothesis(tmp_path):
    """Deduplicating on the hypothesis alone meant the re-scan fired once and
    then never again, however far the rules moved."""
    path = tmp_path / "source_validity.jsonl"
    assert evaluate_source_validity_file(REGISTRY, path, datetime(2026, 9, 1, tzinfo=JST))[
        "appended"
    ] == len(registry().hypotheses)
    original = dict(lookahead.COHORT_SPAN)
    try:
        lookahead.COHORT_SPAN["some_new_cohort"] = frozenset({"prev_close"})
        again = evaluate_source_validity_file(REGISTRY, path, datetime(2026, 9, 2, tzinfo=JST))
        assert again["appended"] == len(registry().hypotheses)
    finally:
        lookahead.COHORT_SPAN.clear()
        lookahead.COHORT_SPAN.update(original)
    assert len(read_ledger(path)) == 2 * len(registry().hypotheses)


def test_a_status_snapshot_is_refused_over_knowledge_the_rules_condemn(tmp_path):
    """The other half of the gate. Four ways of disabling it — removing it,
    firing only when every hypothesis is condemned, summarising the usable ones
    quietly, and reading a different ledger — all passed."""
    from earnings_research.prospective_hypotheses.pipeline import summarize_trials_file

    with pytest.raises(ValueError, match="source-validity"):
        summarize_trials_file(
            REGISTRY, tmp_path / "trials", tmp_path / "status.json",
            datetime(2026, 10, 1, tzinfo=JST),
        )


def test_the_workflow_runs_the_gate():
    """Deleting the step from checks.yml passed the whole suite."""
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8"))
    commands = " ".join(step.get("run", "") for step in workflow["jobs"]["checks"]["steps"])
    assert "verify-source-validity" in commands
    assert "--ledger data/prospective_hypotheses/source_validity.jsonl" in commands


def test_the_valid_verdict_is_reachable_and_distinct(monkeypatch):
    """No frozen hypothesis is valid today, so without a synthetic case the
    valid side of the boundary is never exercised at all — and `declares`
    reading the wrong table would go unnoticed."""
    monkeypatch.setitem(lookahead.COHORT_SPAN, "reaction", frozenset({"next_close"}))
    verdicts = {item.hypothesis_id: item for item in judge(registry(), "2026-09-01T00:00:00+09:00")}
    reaction = [item for item in verdicts.values() if item.dimension == "reaction"]
    assert reaction
    assert all(item.verdict == VALID for item in reaction), [item.verdict for item in reaction]
    assert all(item.reason is None for item in reaction)


def test_a_successor_registry_is_unjudged_however_much_it_inherits():
    """Re-freezing carries the definitions forward; it does not carry the
    verdicts forward. Keyed on the definition, a successor registry read as
    fully judged the moment it was created, `evaluate-source-validity` appended
    nothing for it, and its per-freeze rate had no bucket to be counted in."""
    committed = registry()
    ledger = read_ledger(LEDGER)
    assert unevaluated(committed, ledger) == []
    successor = committed.model_copy(update={"registry_version": committed.registry_version + 1})
    assert len(unevaluated(successor, ledger)) == len(successor.hypotheses)
    assert "%s@v%d" % (successor.registry_id, successor.registry_version) not in rates(
        successor, ledger
    )["by_registry"]


def test_every_registry_in_the_repository_has_been_judged():
    """Named by directory rather than by filename.

    The CI step this mirrors used to verify one hard-coded path, so a second
    registry could be committed, never judged under the current standard, and
    merge with the step still green — the standing check silently not covering
    the newly frozen knowledge it exists for.
    """
    directory = ROOT / "data/prospective_hypotheses"
    registries = [
        path
        for path in sorted(directory.glob("*.json"))
        if {"registry_id", "hypotheses"} <= set(json.loads(path.read_text(encoding="utf-8")))
    ]
    assert registries, "no registry found in %s" % directory
    for path in registries:
        assert verify_source_validity_file(path, LEDGER)["status"] == "judged", path
