"""One definition of a cohort label, where there used to be three.

The importer folded the sign characters that are the same mark typed on a
different keyboard, `knowledge.py` mapped the missing markers and left the
signs alone, and the aggregation — the one that produces the published tables —
did neither. The tables a reader actually reads used the weakest of the three.
"""

import csv
import json
from pathlib import Path

from earnings_research.legacy_research.aggregation import build_aggregation
from earnings_research.legacy_research.importer import _surprise
from earnings_research.legacy_research.knowledge import _label as frozen_label
from earnings_research.legacy_research.labels import (
    MISSING_LABELS,
    cohort_label,
    fold_signs,
    frozen_cohort_label,
)

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "data/historical_research/earnings_research_os/v1/source/records.csv"
CONTEXT = ROOT / "data/historical_research/earnings_research_os/v1/legacy_context_view.jsonl"


def records():
    return list(csv.DictReader(RECORDS.read_text(encoding="utf-8").splitlines()))


def test_the_same_mark_typed_differently_is_one_label():
    """Full-width plus from a Japanese IME, en dash and non-breaking hyphen
    from a paste. The writer meant one thing each time."""
    assert cohort_label("＋1") == "+1"
    assert cohort_label("＋2") == "+2"
    assert cohort_label("–1") == "-1"
    assert cohort_label("‑1") == "-1"
    assert cohort_label(" +1 ") == "+1"


def test_the_em_dash_stays_a_missing_marker():
    """It is a blank, not a minus. Folding it to a hyphen would turn "nobody
    wrote one down" into an unparseable level."""
    assert "—" in MISSING_LABELS
    assert cohort_label("—") == "not_recorded"
    assert cohort_label("…") == "not_recorded"
    assert cohort_label("") == "not_recorded"
    assert fold_signs("—") == "—"


def test_the_published_tables_group_on_the_canonical_label():
    """The defect, stated against the real committed record.

    Grouping on the raw cell put `‑1` in a cohort of one, beside a `-1` cohort
    it belonged to. Six of 254 records were split this way, all in `surprise`,
    whose smallest real level holds six.
    """
    rows = records()
    contexts = [json.loads(line) for line in CONTEXT.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = build_aggregation(rows, contexts, "x")
    levels = set(summary["by_surprise"])
    assert levels <= {"+2", "+1", "0", "-1", "-2", "not_recorded"}, levels
    for stray in ("‑1", "–1", "＋1", "＋2", "—", "…"):
        assert stray not in levels


def test_no_record_is_lost_by_the_grouping():
    """Every exploration record lands in exactly one level of every view."""
    rows = records()
    contexts = [json.loads(line) for line in CONTEXT.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = build_aggregation(rows, contexts, "x")
    for view in ("by_surprise", "by_rank", "by_shodo", "by_narrative", "by_judge", "by_reaction"):
        counted = sum(cell["record_count"] for cell in summary[view].values())
        assert counted == summary["record_count"], (view, counted)


def test_the_importer_and_the_tables_now_fold_the_same_way():
    """They did not, and the importer was the one that was right."""
    for raw in ("＋1", "＋2", "–1", "‑1", "+1", "-2", "0"):
        assert _surprise(raw) == cohort_label(raw)


def test_the_frozen_path_is_deliberately_left_unfolded():
    """`research_knowledge.json` is hash-bound to the frozen registry, so
    folding here would move that hash and unfreeze nineteen definitions. The
    divergence is a decision, and this pins it so it cannot drift into an
    accident in either direction."""
    assert frozen_label("＋1") == "＋1"
    assert frozen_cohort_label("＋1") == "＋1"
    assert frozen_label("—") == "not_recorded"
    assert cohort_label("＋1") != frozen_cohort_label("＋1")
