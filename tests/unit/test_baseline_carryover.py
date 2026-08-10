import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from earnings_research.baseline_carryover.builder import canonical_json_sha256
from earnings_research.baseline_carryover.pipeline import prepare_files, write_carryover
from earnings_research.cli.__main__ import main


ROOT = Path(__file__).resolve().parents[2]
REVIEW_SAMPLE = ROOT / "data/samples/post_event_learning_review_sample.json"
SCHEMA = ROOT / "schemas/analysis/baseline_carryover_context.schema.json"
PREPARED_AT = datetime.fromisoformat("2027-06-01T09:00:00+09:00")


def review_data():
    return json.loads(REVIEW_SAMPLE.read_text(encoding="utf-8"))


def write_review(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_one_review_is_carried_with_source_and_canonical_hash():
    result = prepare_files([REVIEW_SAMPLE], "EVT-FICTIONAL-NEXT-001", PREPARED_AT)
    raw = review_data()
    assert result.target_event_id == "EVT-FICTIONAL-NEXT-001"
    assert result.source_event_ids == [raw["earnings_event_id"]]
    assert result.source_reviews[0].content_sha256 == canonical_json_sha256(raw)
    assert result.maintain_criteria[0].occurrence_count == 1
    assert result.maintain_criteria[0].source_review_ids == [raw["review_id"]]
    assert result.production_rules_modified is False
    assert result.scoring_weights_modified is False
    assert result.trade_decision_included is False


def test_multiple_reviews_count_occurrence_and_aggregate_divergence(tmp_path):
    first = review_data()
    first["reason_analysis"]["market_expectation_interpretation"] = "possible_higher_hurdle_than_recorded"
    second = deepcopy(first)
    second["review_id"] = "PEL-FICTIONAL-LEARNING-002"
    second["earnings_event_id"] = "EVT-FICTIONAL-LEARNING-002"
    second["reviewed_at"] = "2027-05-24T18:00:00+09:00"
    paths = [write_review(tmp_path, "one.json", first), write_review(tmp_path, "two.json", second)]
    result = prepare_files(paths, "EVT-FICTIONAL-NEXT-001", PREPARED_AT)
    assert result.source_event_ids == ["EVT-FICTIONAL-LEARNING-001", "EVT-FICTIONAL-LEARNING-002"]
    assert result.maintain_criteria[0].occurrence_count == 2
    assert result.market_earnings_divergence_history[0].occurrence_count == 2
    assert result.market_earnings_divergence_history[0].source_event_ids == result.source_event_ids


def test_reviewed_after_prepared_at_is_rejected():
    with pytest.raises(ValueError, match="reviewed_at"):
        prepare_files([REVIEW_SAMPLE], "EVT-FICTIONAL-NEXT-001", datetime.fromisoformat("2027-05-01T09:00:00+09:00"))


def test_existing_output_is_not_overwritten(tmp_path):
    result = prepare_files([REVIEW_SAMPLE], "EVT-FICTIONAL-NEXT-001", PREPARED_AT)
    output = tmp_path / "existing.json"
    output.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_carryover(result, output)
    assert output.read_text(encoding="utf-8") == "original"


def test_different_events_are_allowed_only_for_same_company_and_are_explicit(tmp_path):
    first = review_data()
    second = deepcopy(first)
    second["review_id"] = "PEL-FICTIONAL-LEARNING-002"
    second["earnings_event_id"] = "EVT-FICTIONAL-LEARNING-002"
    second["reviewed_at"] = "2027-05-24T18:00:00+09:00"
    paths = [write_review(tmp_path, "one.json", first), write_review(tmp_path, "two.json", second)]
    assert prepare_files(paths, "EVT-FICTIONAL-NEXT-001", PREPARED_AT).source_event_ids == [
        first["earnings_event_id"], second["earnings_event_id"]
    ]
    second["company_name"] = "別の架空会社"
    paths[1] = write_review(tmp_path, "other.json", second)
    with pytest.raises(ValueError, match="different companies"):
        prepare_files(paths, "EVT-FICTIONAL-NEXT-001", PREPARED_AT)


def test_empty_learning_record_stays_empty(tmp_path):
    data = review_data()
    for field in ("maintain_criteria", "weaken_candidates", "next_event_checks", "rejected_assumptions", "recurring_errors_to_prevent"):
        data["learning_record"][field] = []
    result = prepare_files([write_review(tmp_path, "empty.json", data)], "EVT-FICTIONAL-NEXT-001", PREPARED_AT)
    assert result.maintain_criteria == []
    assert result.weaken_candidates == []
    assert result.next_event_checks == []
    assert result.rejected_assumptions == []
    assert result.recurring_errors_to_prevent == []


@pytest.mark.parametrize("field", ["production_rules_modified", "scoring_weights_modified"])
def test_schema_rejects_true_governance_flags(field):
    instance = prepare_files([REVIEW_SAMPLE], "EVT-FICTIONAL-NEXT-001", PREPARED_AT).model_dump(mode="json")
    instance[field] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_cli_writes_append_only_context(tmp_path):
    output = tmp_path / "carryover.json"
    assert main([
        "prepare-baseline-carryover", "--review", str(REVIEW_SAMPLE),
        "--target-event-id", "EVT-FICTIONAL-NEXT-001", "--prepared-at",
        PREPARED_AT.isoformat(), "--output", str(output),
    ]) == 0
    assert output.exists()
