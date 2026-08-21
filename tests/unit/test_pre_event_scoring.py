import csv
from decimal import Decimal
from pathlib import Path

import pytest

from earnings_research.scoring.pre_event import (
    ScoringError,
    component_names,
    coverage_gaps,
    definitions_for,
    derive_score,
    explain,
)
from earnings_research.validation.validator import load_spec, validate_dataset

ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = list(
    csv.DictReader(
        (ROOT / "data/samples/score_definition_sample.csv").open(encoding="utf-8-sig")
    )
)
BASELINES = list(
    csv.DictReader(
        (ROOT / "data/samples/pre_earnings_baseline_sample.csv").open(encoding="utf-8-sig")
    )
)
COMPONENTS = component_names(column.name for column in load_spec("pre_earnings_baseline").columns)


def in_force(scoring_version="ERS-SCORE-0.1"):
    return definitions_for(DEFINITIONS, scoring_version=scoring_version)


def test_every_baseline_component_carries_a_weight():
    assert coverage_gaps(COMPONENTS, in_force()) == []


def test_the_component_set_is_the_eighteen_scored_columns():
    assert len(COMPONENTS) == 18
    assert "pre_event_score" not in COMPONENTS


def test_a_partial_scoring_version_is_reported_as_unusable():
    partial = {name: row for name, row in in_force().items() if name.endswith("_penalty")}
    gaps = coverage_gaps(COMPONENTS, partial)
    assert gaps and "defines no weight for" in gaps[0]


def test_weights_that_do_not_sum_to_one_are_reported():
    tampered = {name: dict(row) for name, row in in_force().items()}
    tampered["liquidity_score"]["weight"] = "0.5"
    gaps = coverage_gaps(COMPONENTS, tampered)
    assert gaps == ["component weights sum to 1.42, not 1"]


@pytest.mark.parametrize("baseline", BASELINES, ids=[row["baseline_id"] for row in BASELINES])
def test_every_shipped_baseline_score_can_be_recomputed(baseline):
    assert Decimal(baseline["pre_event_score"]) == derive_score(baseline, in_force())


def test_a_penalty_pulls_the_score_down():
    """Penalties carry a negative weight, so direction lives in the data."""
    calm = dict(BASELINES[0], meme_overheat_penalty="0")
    overheated = dict(BASELINES[0], meme_overheat_penalty="100")
    assert derive_score(overheated, in_force()) < derive_score(calm, in_force())


def test_a_uniform_baseline_scores_that_value():
    """Signed weights summing to one keep the score on the component scale."""
    flat = {name: "60" for name in COMPONENTS}
    assert derive_score(flat, in_force()) == Decimal("60.0")


def test_explain_accounts_for_the_whole_score():
    rows = explain(BASELINES[0], in_force())
    assert len(rows) == 18
    assert sum(contribution for _n, _v, _w, contribution in rows).quantize(
        Decimal("0.1")
    ) == derive_score(BASELINES[0], in_force())


@pytest.mark.parametrize("value", ["", "  "])
def test_a_blank_component_under_human_review_is_not_filled_in(value):
    row = dict(BASELINES[0], liquidity_score=value)
    with pytest.raises(ScoringError, match="human_review"):
        derive_score(row, in_force())


def test_a_component_outside_its_declared_range_is_refused():
    row = dict(BASELINES[0], liquidity_score="140")
    with pytest.raises(ScoringError, match="outside its declared range"):
        derive_score(row, in_force())


def test_a_locked_baseline_whose_score_drifts_fails_validation(tmp_path):
    """The point of locking is that the number can be checked afterwards."""
    samples = tmp_path / "samples"
    samples.mkdir()
    source = ROOT / "data/samples"
    for path in source.glob("*.csv"):
        samples.joinpath(path.name).write_bytes(path.read_bytes())
    target = samples / "pre_earnings_baseline_sample.csv"
    rows = list(csv.DictReader(target.open(encoding="utf-8-sig")))
    fieldnames = list(rows[0].keys())
    rows[0]["pre_event_score"] = "99.9"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report = validate_dataset(samples)
    assert not report.ok
    assert any("does not match" in issue.message for issue in report.issues)
