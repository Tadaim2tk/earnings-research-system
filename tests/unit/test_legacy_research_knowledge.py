import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from earnings_research.cli.__main__ import main
from earnings_research.legacy_research.knowledge import (
    build_research_knowledge,
    verify_research_outputs,
    write_research_outputs,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "a" * 40
TSO_COMMIT = "b" * 40


def inputs(count=35):
    records = []
    contexts = []
    history = []
    for index in range(count):
        record_id = f"LEGACY-{index:03d}"
        ticker = "1000" if index in (0, 1) else str(1000 + index)
        rank = "A" if index % 3 == 0 else ("B" if index % 3 == 1 else "C")
        narrative = "整合" if index % 2 == 0 else "中立"
        judge = "監視" if index % 2 == 0 else "見送り"
        d1 = "0.03" if index % 4 in (0, 1) else "-0.02"
        d5 = "0.08" if rank == "A" else "-0.01"
        d20 = "" if index >= count - 4 else ("-0.04" if index % 5 == 0 else "0.06")
        raw = {
            "code": ticker,
            "date": f"2026-06-{(index % 28) + 1:02d}",
            "rank": rank,
            "narrative": narrative,
            "judge": judge,
            "reaction": "GU継続" if index % 2 == 0 else "GD反発",
            "ret_d1": d1,
            "ret_d5": d5,
            "ret_d20": d20,
            "rc1": "earnings_momentum" if index % 2 == 0 else "margin_pressure",
            "rc2": "",
            "rc3": "",
        }
        records.append({
            "legacy_record_id": record_id,
            "dataset_origin": "earnings-research-os",
            "record_mode": "legacy_observational",
            "raw_record": raw,
        })
        contexts.append({
            "legacy_record_id": record_id,
            "record_mode": "legacy_observational",
            "join_status": "ok",
            "tso_snapshot_id": f"MCTX-{index:03d}",
            "market_context": {
                "risk_on_score": str(55 if index % 2 == 0 else 45),
                "risk_off_score": str(45 if index % 2 == 0 else 55),
                "volatility_stress_score": str(40 + index),
                "dollar_strength_score": str(45 + index / 10),
            },
        })
        for field in ("rank", "narrative", "judge"):
            history.append({
                "legacy_record_id": record_id,
                "field_name": field,
                "first_seen_commit": "c" * 40,
                "last_changed_commit": "d" * 40 if index == 0 and field == "rank" else "c" * 40,
            })
    manifest = {
        "dataset_origin": "earnings-research-os",
        "record_mode": "legacy_observational",
        "source_row_count": count,
        "frozen_source_commit": SOURCE_COMMIT,
        "tso_source_commit": TSO_COMMIT,
    }
    return records, contexts, history, manifest


def test_horizons_report_available_missing_and_ticker_balanced_counts():
    knowledge = build_research_knowledge(*inputs())
    coverage = knowledge["coverage"]
    assert coverage["record_count"] == 35
    assert coverage["distinct_ticker_count"] == 34
    assert coverage["repeated_ticker_count"] == 1
    assert coverage["horizons"]["d1"]["available_count"] == 35
    assert coverage["horizons"]["d20"]["available_count"] == 31
    assert coverage["horizons"]["d20"]["missing_count"] == 4
    assert coverage["horizons"]["d20"]["distinct_ticker_count"] == 30
    assert coverage["horizons"]["d20"]["distinct_context_snapshot_count"] == 31
    assert coverage["horizons"]["d20"]["effective_unit_count"] == 30
    assert coverage["horizons"]["d20"]["sample_grade"] == "descriptive"
    assert coverage["horizons"]["d20"]["ticker_balanced_mean_return"] is not None


def test_small_combinations_stay_hypotheses_and_missing_is_not_a_loss():
    knowledge = build_research_knowledge(*inputs(12))
    rank_groups = knowledge["single_dimension_results"]["rank"]
    group_a = next(group for group in rank_groups if group["dimensions"]["rank"] == "A")
    assert group_a["summary"]["horizons"]["d5"]["sample_grade"] == "insufficient"
    d20 = knowledge["coverage"]["horizons"]["d20"]
    assert d20["available_count"] == 8
    assert d20["positive_count"] + d20["negative_count"] + d20["zero_count"] == 8
    assert knowledge["learning"]["weight_changes_generated"] == 0
    assert knowledge["learning"]["trading_rules_generated"] == 0


def test_reversals_exceptions_and_classification_changes_are_visible():
    knowledge = build_research_knowledge(*inputs())
    transitions = {
        item["transition"]: item["summary"]["record_count"]
        for item in knowledge["initial_to_d20_transitions"]["groups"]
    }
    assert transitions["positive_to_negative"] > 0
    assert transitions["negative_to_positive"] > 0
    assert transitions["unavailable"] == 4
    assert knowledge["exception_patterns"]["d5"]["high_rank_negative"]["summary"]["record_count"] == 0
    assert knowledge["exception_patterns"]["d5"]["low_rank_positive"]["summary"]["record_count"] == 0
    assert knowledge["classification_lineage"]["rank"]["changed_after_first_seen_count"] == 1
    assert knowledge["classification_lineage"]["narrative"]["changed_after_first_seen_count"] == 0


def test_prospective_or_unlinked_rows_cannot_enter_legacy_research():
    records, contexts, history, manifest = inputs()
    records[0]["record_mode"] = "prospective"
    with pytest.raises(ValueError, match="prospective or foreign"):
        build_research_knowledge(records, contexts, history, manifest)
    records[0]["record_mode"] = "legacy_observational"
    contexts[0]["join_status"] = "missing"
    with pytest.raises(ValueError, match="valid read-only TSO context"):
        build_research_knowledge(records, contexts, history, manifest)


def test_incomplete_classification_history_is_rejected():
    records, contexts, history, manifest = inputs()
    history.pop()
    with pytest.raises(ValueError, match="classification history"):
        build_research_knowledge(records, contexts, history, manifest)


def test_actual_254_record_outputs_are_reproducible_and_schema_valid(tmp_path):
    input_root = ROOT / "data/historical_research/earnings_research_os/v1"
    output = tmp_path / "research"
    result = write_research_outputs(input_root, output)
    assert result["record_count"] == 254
    assert result["d1_available"] == 245
    assert result["d5_available"] == 242
    assert result["d20_available"] == 139
    assert result["learning_candidate_count"] > 0
    assert verify_research_outputs(input_root, output)["output_count"] == 4
    knowledge = json.loads((output / "research_knowledge.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas/analysis/legacy_research_knowledge.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(knowledge, schema)
    assert knowledge["analysis_scope"]["prospective_records_included"] == 0
    assert knowledge["repeated_company_control"]["distinct_ticker_count"] == 251
    assert all(item["dimension"] != "event_month" for item in knowledge["learning"]["candidates"])
    assert {item["classification"] for item in knowledge["learning"]["candidates"]} == {
        "potentially_favorable", "potentially_unfavorable", "low_discrimination"
    }
    reaction_candidates = [item for item in knowledge["learning"]["candidates"] if item["dimension"] == "reaction"]
    assert reaction_candidates
    assert all(item["temporal_role"] == "post_event_reaction_path" for item in reaction_candidates)
    assert "正式なスコア・売買ルールではない" in (output / "weekly_research_digest.md").read_text(encoding="utf-8")
    report = (output / "research_report.md").read_text(encoding="utf-8")
    assert "## 高rank下落・低rank上昇" in report
    assert "## 初動からD20への反転" in report


def test_cli_generates_and_verifies_research_outputs(tmp_path):
    input_root = ROOT / "data/historical_research/earnings_research_os/v1"
    output = tmp_path / "research"
    assert main(["analyze-legacy-research", "--input-root", str(input_root), "--output-dir", str(output)]) == 0
    assert main(["verify-legacy-research", "--input-root", str(input_root), "--output-dir", str(output)]) == 0


def test_frozen_input_hash_mismatch_is_rejected(tmp_path):
    source = ROOT / "data/historical_research/earnings_research_os/v1"
    copied = tmp_path / "input"
    shutil.copytree(source, copied)
    with (copied / "legacy_records.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="input hash mismatch"):
        write_research_outputs(copied, tmp_path / "output")
