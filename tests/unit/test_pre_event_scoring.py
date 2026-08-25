import csv
from decimal import Decimal
from pathlib import Path

import pytest

from earnings_research.scoring.pre_event import (
    MIN_SURVIVING_WEIGHT,
    ScoringError,
    component_names,
    coverage_gaps,
    definitions_for,
    derive_score,
    explain,
    matches_recorded,
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


def redefine(component, **changes):
    """Return the in-force definitions with one component's policy changed."""
    definitions = {name: dict(row) for name, row in in_force().items()}
    definitions[component].update(changes)
    return definitions


@pytest.mark.parametrize(
    "low,high,expected", [("0", "100", "50"), ("10", "90", "50"), ("0", "40", "20")]
)
def test_a_neutral_component_takes_its_declared_midpoint(low, high, expected):
    """The midpoint comes from the definition, not from a hardcoded 50."""
    definitions = redefine(
        "liquidity_score", missing_value_policy="neutral", min_value=low, max_value=high
    )
    blank = dict(BASELINES[0], liquidity_score="")
    filled = dict(BASELINES[0], liquidity_score=expected)
    assert derive_score(blank, definitions) == derive_score(filled, definitions)


def test_an_excluded_component_drops_its_weight_too():
    """Excluding is not scoring the component as zero."""
    definitions = redefine("liquidity_score", missing_value_policy="exclude_with_note")
    excluded = derive_score(dict(BASELINES[0], liquidity_score=""), definitions)
    as_zero = derive_score(dict(BASELINES[0], liquidity_score="0"), definitions)
    recorded = derive_score(BASELINES[0], in_force())
    assert excluded != as_zero
    assert excluded != recorded


def test_dropping_most_of_the_weight_is_refused_rather_than_rescaled():
    """Renormalising by a small remainder scales the survivors without bound."""
    definitions = {name: dict(row) for name, row in in_force().items()}
    positives = [name for name, row in definitions.items() if Decimal(row["weight"]) > 0]
    for name in positives:
        definitions[name]["missing_value_policy"] = "exclude_with_note"
    worst = dict(BASELINES[0], **{name: "" for name in positives})
    for name in definitions:
        if name.endswith("_penalty"):
            worst[name] = "100"
    with pytest.raises(ScoringError, match="survives exclusion"):
        derive_score(worst, definitions)


def test_the_surviving_weight_floor_is_half():
    assert MIN_SURVIVING_WEIGHT == Decimal("0.5")


def test_a_composite_outside_the_component_scale_is_refused():
    """Signed weights summing to one bound the average, not the range."""
    extreme = {name: ("0" if name.endswith("_penalty") else "100") for name in COMPONENTS}
    with pytest.raises(ScoringError, match="outside the 0 to 100 component scale"):
        derive_score(extreme, in_force())


@pytest.mark.parametrize("recorded,ok", [("58.0", True), ("58", True), ("58.00", True), ("58.05", False), ("57.95", False), ("", False), ("abc", False)])
def test_the_recorded_score_must_equal_the_derived_one_exactly(recorded, ok):
    """A tolerance here is undetectable drift, not rounding headroom."""
    assert matches_recorded(recorded, Decimal("58.0")) is ok


def test_a_component_outside_its_declared_range_is_refused():
    row = dict(BASELINES[0], liquidity_score="140")
    with pytest.raises(ScoringError, match="outside its declared range"):
        derive_score(row, in_force())


def dataset_with_score(tmp_path, baseline_id, score, name="samples"):
    """Copy the samples with one baseline's score replaced."""
    samples = tmp_path / name
    samples.mkdir()
    for path in (ROOT / "data/samples").glob("*.csv"):
        samples.joinpath(path.name).write_bytes(path.read_bytes())
    target = samples / "pre_earnings_baseline_sample.csv"
    rows = list(csv.DictReader(target.open(encoding="utf-8-sig")))
    fieldnames = list(rows[0].keys())
    for row in rows:
        if row["baseline_id"] == baseline_id:
            row["pre_event_score"] = score
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return samples


def test_a_draft_score_is_not_held_to_the_scoring_version(tmp_path):
    """A draft is still being worked out; only a lock is a commitment.

    The shipped baselines are all locked, so the draft is made here rather than
    letting the case go untested.
    """
    samples = tmp_path / "draft"
    samples.mkdir()
    for path in (ROOT / "data/samples").glob("*.csv"):
        samples.joinpath(path.name).write_bytes(path.read_bytes())
    target = samples / "pre_earnings_baseline_sample.csv"
    rows = list(csv.DictReader(target.open(encoding="utf-8-sig")))
    fieldnames = list(rows[0].keys())
    unlocked = {
        "pre_event_score": "99.9",
        "is_locked": "false",
        "locked_at": "",
        "baseline_record_hash": "",
        "lock_hash_algorithm": "",
        "baseline_status": "draft",
        "human_review_status": "pending",
        "reviewed_by": "",
        "reviewed_at": "",
        "supersedes_baseline_id": "",
        "supersession_reason": "",
    }
    # The shipped file uses the legacy shape, which carries only some of these.
    rows[0].update({k: v for k, v in unlocked.items() if k in fieldnames})
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report = validate_dataset(samples)
    assert not any("does not match" in issue.message for issue in report.issues)
    # And the same wrong score is caught once the row claims to be locked.
    locked_report = validate_dataset(
        dataset_with_score(tmp_path, rows[1]["baseline_id"], "99.9", name="locked")
    )
    assert any("does not match" in issue.message for issue in locked_report.issues)


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
