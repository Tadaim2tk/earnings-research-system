"""Build deterministic frozen definitions from legacy learning candidates."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from .models import (
    AssessmentRule,
    HistoricalEffect,
    HistoricalSample,
    HypothesisDefinition,
    HypothesisRegistry,
    PromotionReviewPolicy,
)


ASSESSMENT_MINIMUM = 30
PROMOTION_REVIEW_MINIMUM = 50


def _identifier(candidate_id: str) -> str:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:12].upper()
    return f"LRH-{digest}"


def _phase(dimension: str) -> str:
    return "post_event" if dimension == "reaction" else "pre_event"


def _direction(classification: str) -> str:
    return {
        "potentially_favorable": "higher_than_comparator",
        "potentially_unfavorable": "lower_than_comparator",
        "low_discrimination": "no_material_difference",
    }[classification]


def _priority(candidate: dict) -> str:
    effect = abs(candidate["mean_return_delta_vs_overall"])
    rate_effect = abs(candidate["positive_rate_delta_vs_overall"])
    if (
        candidate["classification"] != "low_discrimination"
        and candidate["effective_unit_count"] >= 20
        and (effect >= 0.02 or rate_effect >= 0.10)
    ):
        return "primary"
    return "secondary"


def _text(candidate: dict) -> str:
    direction = {
        "potentially_favorable": "平均リターンが比較群より高い",
        "potentially_unfavorable": "平均リターンが比較群より低い",
        "low_discrimination": "比較群との実質的な差が小さい",
    }[candidate["classification"]]
    return (
        f"{candidate['dimension']}={candidate['value']}に該当する新ERS決算群は、"
        f"{candidate['horizon'].upper()}で{direction}。"
    )


def build_registry(knowledge: dict, source_path: str, source_sha256: str, frozen_at: datetime):
    candidates = knowledge.get("learning", {}).get("candidates", [])
    if not candidates:
        raise ValueError("legacy research contains no learning candidates")
    if knowledge.get("record_mode") != "legacy_observational":
        raise ValueError("registry origin must be legacy observational research")
    if knowledge.get("analysis_scope", {}).get("prospective_records_included") != 0:
        raise ValueError("legacy candidate source must not contain prospective records")
    hypotheses = []
    for candidate in candidates:
        hypotheses.append(HypothesisDefinition(
            hypothesis_id=_identifier(candidate["candidate_id"]),
            hypothesis_version=1,
            origin="legacy_research",
            source_candidate_id=candidate["candidate_id"],
            hypothesis_text=_text(candidate),
            phase=_phase(candidate["dimension"]),
            priority=_priority(candidate),
            target_scope="new_ers_japanese_equity_earnings",
            dimension=candidate["dimension"],
            target_value=candidate["value"],
            expected_direction=_direction(candidate["classification"]),
            evaluation_horizon=candidate["horizon"].upper(),
            historical_sample_size=HistoricalSample(
                available_count=candidate["available_count"],
                effective_unit_count=candidate["effective_unit_count"],
                distinct_ticker_count=candidate["distinct_ticker_count"],
                distinct_context_snapshot_count=candidate["distinct_context_snapshot_count"],
            ),
            historical_effect=HistoricalEffect(
                mean_return_delta_vs_overall=candidate["mean_return_delta_vs_overall"],
                positive_rate_delta_vs_overall=candidate["positive_rate_delta_vs_overall"],
            ),
            historical_sample_grade=candidate["sample_grade"],
            frozen_at=frozen_at,
            assessment_rule=AssessmentRule(
                comparison_basis="target_vs_all_eligible_events",
                minimum_target_trials=ASSESSMENT_MINIMUM,
                minimum_comparator_trials=ASSESSMENT_MINIMUM,
                retained_effect_ratio=0.5,
                no_material_mean_delta=0.005,
                no_material_positive_rate_delta=0.05,
            ),
        ))
    return HypothesisRegistry(
        registry_id="ERS-PROSPECTIVE-HYPOTHESES-LEGACY-V1",
        registry_version=1,
        source_research_path=source_path,
        source_research_sha256=source_sha256,
        source_candidate_count=len(candidates),
        frozen_at=frozen_at,
        hypotheses=hypotheses,
        promotion_review_policy=PromotionReviewPolicy(
            automatic_promotion=False,
            minimum_target_trials=PROMOTION_REVIEW_MINIMUM,
            minimum_comparator_trials=PROMOTION_REVIEW_MINIMUM,
            minimum_distinct_event_quarters=2,
            minimum_consecutive_supported_evaluations=2,
            note="条件到達は別の統治レビュー候補になるだけで、weight・rank・売買ルールを自動変更しない。",
        ),
    )


def load_knowledge(path: Path):
    payload = path.read_bytes()
    return json.loads(payload), hashlib.sha256(payload).hexdigest()
