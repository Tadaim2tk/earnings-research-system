"""Contracts for frozen hypotheses, event observations, trials, and derived status."""

import hashlib
import json
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


def canonical_hash(model) -> str:
    """The identity of a frozen model, independent of how it was written out.

    Lives here rather than beside its first caller because two modules need it
    and one of them derives when a hypothesis started gathering evidence, which
    the other imports. A second implementation of this would be a second answer
    to "is this the registry that trial was recorded against".
    """
    payload = json.dumps(
        model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


Dimension = Literal[
    "rank",
    "narrative",
    "judge",
    "reaction",
    "risk_balance",
    "volatility_environment",
    "dollar_environment",
]
Horizon = Literal["D1", "D5", "D20"]
Phase = Literal["pre_event", "post_event"]
ExpectedDirection = Literal["higher_than_comparator", "lower_than_comparator", "no_material_difference"]

def _versioned_stage_schema_rules(return_field):
    version_rule = {
        "if": {
            "properties": {"observation_version": {"const": 1}},
            "required": ["observation_version"],
        },
        "then": {
            "properties": {"supersedes_observation_id": {"type": "null"}},
        },
        "else": {
            "properties": {"supersedes_observation_id": {"type": "string", "minLength": 1}},
            "required": ["supersedes_observation_id"],
        },
    }
    stage_rules = []
    horizon_order = ("D1", "D5", "D20")
    for index, stage in enumerate(horizon_order):
        allowed = list(horizon_order[: index + 1])
        stage_rules.append({
            "if": {
                "properties": {"observation_stage": {"const": stage}},
                "required": ["observation_stage"],
            },
            "then": {
                "properties": {
                    return_field: {
                        "contains": {
                            "properties": {"horizon": {"const": stage}},
                            "required": ["horizon"],
                        },
                        "minContains": 1,
                        "items": {
                            "properties": {"horizon": {"enum": allowed}},
                            "required": ["horizon"],
                        },
                    }
                }
            },
        })
    uniqueness_rules = [
        {
            "properties": {
                return_field: {
                    "contains": {
                        "properties": {"horizon": {"const": horizon}},
                        "required": ["horizon"],
                    },
                    "minContains": 0,
                    "maxContains": 1,
                }
            }
        }
        for horizon in horizon_order
    ]
    return {"allOf": [version_rule, *stage_rules, *uniqueness_rules]}


VERSIONED_OBSERVATION_SCHEMA_RULE = _versioned_stage_schema_rules("returns")
VERSIONED_BUNDLE_SCHEMA_RULE = _versioned_stage_schema_rules("return_snapshots")


class HistoricalSample(BaseModel):
    available_count: int = Field(ge=0)
    effective_unit_count: int = Field(ge=0)
    distinct_ticker_count: int = Field(ge=0)
    distinct_context_snapshot_count: int = Field(ge=0)


class HistoricalEffect(BaseModel):
    mean_return_delta_vs_overall: float
    positive_rate_delta_vs_overall: float


class StopRule(BaseModel):
    """When to abandon the hypothesis, decided before any result is seen.

    Without this, a hypothesis is never wrong — it is only ever awaiting more
    data or one more condition. The conditions are frozen with the definition
    precisely because they are easy to relax once the numbers are in.

    There used to be an `at_least_as_strict_as` here, permitting a successor to
    tighten what it inherited. It is gone. Tightening is still a change made in
    sight of the result, and a test whose bar moved partway through is not the
    test that was registered — whether the bar went up or down. Once trials
    exist the rule is fixed outright; changing it means a new hypothesis
    version, from no trials. `freeze.py` is where that is enforced.
    """

    # No defaults, and no unknown keys. With defaults, a frozen registry that
    # omitted a term took whatever the code said that day, so its hash depended
    # on the code rather than on its own bytes; and a misspelled
    # stop_when_halves_reversed was accepted in silence as the default, leaving
    # a rule that reads as tightened and is not. The committed JSON schema has
    # required all three from the start.
    model_config = ConfigDict(extra="forbid")

    # A relationship present in one half of the record and reversed in the
    # other is what decay and luck both look like.
    stop_when_halves_reverse: bool
    # Below this share of the frozen historical effect, on data reserved before
    # the definition existed, the hypothesis is finished rather than weakened.
    stop_below_reserved_effect_ratio: float = Field(gt=0, le=1)
    # Revisions are how a dead hypothesis stays alive. After this many the
    # question has to be asked again from scratch, not patched.
    maximum_revisions: int = Field(ge=0)


class AssessmentRule(BaseModel):
    comparison_basis: Literal["target_vs_all_eligible_events"]
    minimum_target_trials: int = Field(ge=1)
    minimum_comparator_trials: int = Field(ge=1)
    retained_effect_ratio: float = Field(gt=0, le=1)
    no_material_mean_delta: float = Field(ge=0)
    no_material_positive_rate_delta: float = Field(ge=0)
    # Optional so that registries frozen before stop rules existed keep their
    # hash. A frozen definition is not rewritten to carry a field it never had;
    # the conditions attach to the next version instead. Where a version does
    # carry one it is serialised and hashed like any other term, so the
    # conditions are as frozen as the rest of the definition.
    stop_rule: Optional[StopRule] = None

    @model_serializer(mode="wrap")
    def _omit_absent_stop_rule(self, handler):
        payload = handler(self)
        if self.stop_rule is None:
            payload.pop("stop_rule", None)
        return payload


class HypothesisDefinition(BaseModel):
    hypothesis_id: str
    hypothesis_version: int = Field(ge=1)
    origin: Literal["legacy_research"]
    source_candidate_id: str
    hypothesis_text: str
    phase: Phase
    priority: Literal["primary", "secondary"]
    target_scope: Literal["new_ers_japanese_equity_earnings"]
    dimension: Dimension
    target_value: str
    expected_direction: ExpectedDirection
    evaluation_horizon: Horizon
    historical_sample_size: HistoricalSample
    historical_effect: HistoricalEffect
    historical_sample_grade: Literal["insufficient", "limited", "descriptive"]
    frozen_at: datetime
    definition_status: Literal["active"] = "active"
    assessment_rule: AssessmentRule
    automatic_weight_change: Literal[False] = False
    automatic_rank_rule_change: Literal[False] = False
    automatic_trading_rule_change: Literal[False] = False

    @model_validator(mode="after")
    def validate_definition(self):
        if self.frozen_at.tzinfo is None:
            raise ValueError("frozen_at must include timezone")
        expected_phase = "post_event" if self.dimension == "reaction" else "pre_event"
        if self.phase != expected_phase:
            raise ValueError("reaction is post-event; all other registry dimensions are pre-event")
        direction_by_effect = {
            "higher_than_comparator": self.historical_effect.mean_return_delta_vs_overall > 0,
            "lower_than_comparator": self.historical_effect.mean_return_delta_vs_overall < 0,
            "no_material_difference": (
                abs(self.historical_effect.mean_return_delta_vs_overall)
                <= self.assessment_rule.no_material_mean_delta
                and abs(self.historical_effect.positive_rate_delta_vs_overall)
                <= self.assessment_rule.no_material_positive_rate_delta
            ),
        }
        if not direction_by_effect[self.expected_direction]:
            raise ValueError("expected direction must agree with the frozen historical effect")
        return self


class PromotionReviewPolicy(BaseModel):
    automatic_promotion: Literal[False] = False
    minimum_target_trials: int = Field(ge=1)
    minimum_comparator_trials: int = Field(ge=1)
    minimum_distinct_event_quarters: int = Field(ge=1)
    minimum_consecutive_supported_evaluations: int = Field(ge=1)
    note: str


class HypothesisRegistry(BaseModel):
    schema_version: Literal["prospective_hypothesis_registry_v1"] = "prospective_hypothesis_registry_v1"
    registry_id: str
    registry_version: int = Field(ge=1)
    source_research_path: str
    source_research_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_candidate_count: int = Field(ge=1)
    frozen_at: datetime
    hypotheses: List[HypothesisDefinition] = Field(min_length=1)
    promotion_review_policy: PromotionReviewPolicy

    @model_validator(mode="after")
    def validate_registry(self):
        if self.frozen_at.tzinfo is None:
            raise ValueError("frozen_at must include timezone")
        if self.source_candidate_count != len(self.hypotheses):
            raise ValueError("every source candidate must map to exactly one hypothesis")
        keys = [(item.hypothesis_id, item.hypothesis_version) for item in self.hypotheses]
        if len(keys) != len(set(keys)):
            raise ValueError("hypothesis identity/version must be unique")
        source_ids = [item.source_candidate_id for item in self.hypotheses]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source candidates must map one-to-one")
        if any(item.frozen_at != self.frozen_at for item in self.hypotheses):
            raise ValueError("all definitions must share the registry freeze timestamp")
        return self

class PreEventFeatures(BaseModel):
    captured_at: datetime
    baseline_id: str
    baseline_version: int = Field(ge=1)
    baseline_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locked_at: datetime
    rank: Optional[str] = None
    narrative: Optional[str] = None
    judge: Optional[str] = None
    risk_balance: Optional[str] = None
    volatility_environment: Optional[str] = None
    dollar_environment: Optional[str] = None

    @model_validator(mode="after")
    def validate_pre_event_features(self):
        if self.captured_at.tzinfo is None or self.locked_at.tzinfo is None:
            raise ValueError("pre-event feature timestamps must include timezone")
        if self.captured_at > self.locked_at:
            raise ValueError("pre-event features must be captured by baseline lock")
        return self


class PostEventFeatures(BaseModel):
    captured_at: datetime
    reaction: Optional[str] = None
    reaction_source_record_id: str


class HorizonReturn(BaseModel):
    horizon: Horizon
    status: Literal["comparable", "not_comparable"]
    return_value: Optional[float] = None
    observed_at: datetime
    source_record_id: str

    @model_validator(mode="after")
    def validate_return(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("return observed_at must include timezone")
        if (self.status == "comparable") != (self.return_value is not None):
            raise ValueError("only comparable returns may contain a value")
        return self


class CompletedEventObservation(BaseModel):
    model_config = ConfigDict(json_schema_extra=VERSIONED_OBSERVATION_SCHEMA_RULE)

    schema_version: Literal["prospective_hypothesis_event_observation_v2"] = "prospective_hypothesis_event_observation_v2"
    observation_id: str
    observation_version: int = Field(ge=1)
    supersedes_observation_id: Optional[str] = None
    observation_stage: Horizon
    earnings_event_id: str
    company_name: str
    ticker: str
    event_quarter: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    event_occurred_at: datetime
    observed_through: datetime
    pre_event_features: PreEventFeatures
    post_event_features: PostEventFeatures
    returns: List[HorizonReturn]
    source_record_ids: List[str] = Field(min_length=1)
    prospective_record: Literal[True] = True
    production_rules_modified: Literal[False] = False
    scoring_weights_modified: Literal[False] = False
    trade_decision_included: Literal[False] = False

    @model_validator(mode="after")
    def validate_observation(self):
        timestamps = [
            self.event_occurred_at,
            self.observed_through,
            self.pre_event_features.captured_at,
            self.post_event_features.captured_at,
        ]
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("event observation timestamps must include timezone")
        if self.pre_event_features.captured_at > self.event_occurred_at:
            raise ValueError("pre-event features must be frozen before the event occurs")
        if self.pre_event_features.locked_at > self.event_occurred_at:
            raise ValueError("pre-event baseline must be locked before the event occurs")
        if self.post_event_features.captured_at < self.event_occurred_at:
            raise ValueError("post-event features cannot be captured before the event")
        if (self.observation_version == 1) != (self.supersedes_observation_id is None):
            raise ValueError("only observation version 1 may omit supersedes_observation_id")
        if self.observed_through < self.post_event_features.captured_at:
            raise ValueError("observed_through cannot precede post-event features")
        horizons = [item.horizon for item in self.returns]
        if len(horizons) != len(set(horizons)):
            raise ValueError("return horizons must be unique")
        if any(item.observed_at < self.event_occurred_at for item in self.returns):
            raise ValueError("returns cannot be observed before the event")
        if any(item.observed_at > self.observed_through for item in self.returns):
            raise ValueError("observed_through cannot precede a return observation")
        horizon_order = {"D1": 1, "D5": 2, "D20": 3}
        if self.observation_stage not in horizons:
            raise ValueError("observation stage requires its matured horizon return")
        if any(horizon_order[item.horizon] > horizon_order[self.observation_stage] for item in self.returns):
            raise ValueError("observation cannot contain a return beyond its stage")
        if len(self.source_record_ids) != len(set(self.source_record_ids)):
            raise ValueError("source_record_ids must be unique")
        return self


EligibilityReason = Literal[
    "eligible",
    "required_pre_event_field_missing",
    "required_post_event_field_missing",
    "horizon_not_matured",
    "horizon_not_comparable",
    "trial_already_recorded",
]


class HypothesisEligibility(BaseModel):
    hypothesis_id: str
    hypothesis_version: int = Field(ge=1)
    evaluation_horizon: Horizon
    eligible_for_hypothesis: bool
    reason: EligibilityReason
    appended_trial_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_eligibility(self):
        if self.eligible_for_hypothesis != (self.reason == "eligible"):
            raise ValueError("eligibility flag must match reason")
        if self.eligible_for_hypothesis != (self.appended_trial_id is not None):
            raise ValueError("eligible hypothesis requires one appended trial ID")
        return self


class HypothesisTrial(BaseModel):
    trial_id: str
    hypothesis_id: str
    hypothesis_version: int = Field(ge=1)
    earnings_event_id: str
    event_quarter: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    phase: Phase
    evaluation_horizon: Horizon
    cohort: Literal["target", "non_target"]
    observed_dimension: Dimension
    observed_value: str
    return_value: float
    individual_outcome: Literal["success", "failure", "neutral", "not_applicable"]
    outcome_observed_at: datetime
    observation_id: str
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_ids: List[str]
    recorded_at: datetime
    append_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_trial(self):
        if self.outcome_observed_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("trial timestamps must include timezone")
        if self.recorded_at < self.outcome_observed_at:
            raise ValueError("trial cannot be recorded before its outcome")
        if len(self.source_record_ids) != len(set(self.source_record_ids)):
            raise ValueError("trial source_record_ids must be unique")
        return self


class HypothesisTrialBundleV1(BaseModel):
    schema_version: Literal["prospective_hypothesis_trial_bundle_v1"] = "prospective_hypothesis_trial_bundle_v1"
    registry_id: str
    registry_version: int
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_id: str
    earnings_event_id: str
    recorded_at: datetime
    trials: List[HypothesisTrial]
    ineligible_hypotheses: Dict[str, str]
    weight_changes_generated: Literal[0] = 0
    rank_rule_changes_generated: Literal[0] = 0
    trading_rules_generated: Literal[0] = 0

    @model_validator(mode="after")
    def validate_bundle(self):
        if self.recorded_at.tzinfo is None:
            raise ValueError("bundle recorded_at must include timezone")
        trial_ids = [item.trial_id for item in self.trials]
        if len(trial_ids) != len(set(trial_ids)):
            raise ValueError("trial IDs must be unique")
        if any(item.earnings_event_id != self.earnings_event_id for item in self.trials):
            raise ValueError("all trials must belong to the bundle event")
        if any(item.observation_id != self.observation_id for item in self.trials):
            raise ValueError("all trials must reference the bundle observation")
        if any(item.recorded_at != self.recorded_at for item in self.trials):
            raise ValueError("all trials must share the bundle recorded_at")
        return self


class HypothesisTrialBundle(BaseModel):
    model_config = ConfigDict(json_schema_extra=VERSIONED_BUNDLE_SCHEMA_RULE)

    schema_version: Literal["prospective_hypothesis_trial_bundle_v2"] = "prospective_hypothesis_trial_bundle_v2"
    registry_id: str
    registry_version: int
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_id: str
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_version: int = Field(ge=1)
    supersedes_observation_id: Optional[str] = None
    observation_stage: Horizon
    earnings_event_id: str
    company_name: str
    ticker: str
    event_quarter: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    event_occurred_at: datetime
    observed_through: datetime
    pre_event_features_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reaction: Optional[str] = None
    return_snapshots: List[HorizonReturn]
    recorded_at: datetime
    trials: List[HypothesisTrial]
    hypothesis_eligibility: List[HypothesisEligibility]
    weight_changes_generated: Literal[0] = 0
    rank_rule_changes_generated: Literal[0] = 0
    trading_rules_generated: Literal[0] = 0

    @model_validator(mode="after")
    def validate_bundle(self):
        if self.recorded_at.tzinfo is None:
            raise ValueError("bundle recorded_at must include timezone")
        if self.event_occurred_at.tzinfo is None or self.observed_through.tzinfo is None:
            raise ValueError("bundle event timestamps must include timezone")
        if self.recorded_at < self.observed_through:
            raise ValueError("bundle cannot be recorded before observed_through")
        if (self.observation_version == 1) != (self.supersedes_observation_id is None):
            raise ValueError("only bundle observation version 1 may omit supersedes_observation_id")
        trial_ids = [item.trial_id for item in self.trials]
        if len(trial_ids) != len(set(trial_ids)):
            raise ValueError("trial IDs must be unique")
        if any(item.earnings_event_id != self.earnings_event_id for item in self.trials):
            raise ValueError("all trials must belong to the bundle event")
        if any(item.observation_id != self.observation_id for item in self.trials):
            raise ValueError("all trials must reference the bundle observation")
        if any(item.observation_sha256 != self.observation_sha256 for item in self.trials):
            raise ValueError("all trials must match the bundle observation hash")
        if any(item.recorded_at != self.recorded_at for item in self.trials):
            raise ValueError("all trials must share the bundle recorded_at")
        horizons = [item.horizon for item in self.return_snapshots]
        if len(horizons) != len(set(horizons)):
            raise ValueError("bundle return snapshots must have unique horizons")
        horizon_order = {"D1": 1, "D5": 2, "D20": 3}
        if self.observation_stage not in horizons:
            raise ValueError("bundle observation stage requires its matured horizon return")
        if any(horizon_order[item.horizon] > horizon_order[self.observation_stage] for item in self.return_snapshots):
            raise ValueError("bundle cannot contain a return beyond its observation stage")
        eligibility_keys = [
            (item.hypothesis_id, item.hypothesis_version)
            for item in self.hypothesis_eligibility
        ]
        if len(eligibility_keys) != len(set(eligibility_keys)):
            raise ValueError("bundle must contain one eligibility result per hypothesis")
        eligible_trial_ids = {
            item.appended_trial_id
            for item in self.hypothesis_eligibility
            if item.eligible_for_hypothesis
        }
        if eligible_trial_ids != set(trial_ids):
            raise ValueError("eligible hypothesis results must resolve exactly to appended trials")
        return self


class HypothesisStatus(BaseModel):
    hypothesis_id: str
    hypothesis_version: int
    phase: Phase
    priority: Literal["primary", "secondary"]
    status: Literal["active", "insufficient", "supported", "weakened", "rejected", "stopped"]
    prospective_trials: int = Field(ge=0)
    prospective_successes: int = Field(ge=0)
    prospective_failures: int = Field(ge=0)
    comparator_observations: int = Field(ge=0)
    target_mean_return: Optional[float]
    comparator_mean_return: Optional[float]
    prospective_effect: Optional[float]
    target_positive_rate: Optional[float]
    comparator_positive_rate: Optional[float]
    prospective_positive_rate_effect: Optional[float]
    distinct_event_quarters: int = Field(ge=0)
    last_evaluated_at: Optional[datetime]
    # When this definition began gathering evidence, and so when its stop and
    # promotion rules stopped being changeable. Reported here because a reader
    # deciding whether a rule may still move needs it, but it is derived from
    # the trials on every snapshot and never read back in — a stored copy could
    # be edited to a later date and unfreeze the rules behind it.
    evaluation_started_at: Optional[datetime] = None
    production_review_eligible: Literal[False] = False
    # Why this hypothesis is finished under its own frozen stop rule, or None
    # while it stays open. Versions carrying no stop rule are always None.
    stop_reason: Optional[str] = None
    # Which of the frozen conditions the evaluation was actually able to look
    # at. A condition with no data behind it never fires, and without this the
    # difference between "checked and did not fire" and "never checked" is
    # invisible: the reserved-effect condition has no counterpart in
    # prospective trials and has never been evaluated once.
    stop_conditions_evaluated: List[str] = Field(default_factory=list)
    note: str


    @model_validator(mode="after")
    def validate_status(self):
        if (self.stop_reason is not None) != (self.status == "stopped"):
            raise ValueError("a stopped hypothesis carries its reason, and only a stopped one")
        return self


class HypothesisStatusSnapshot(BaseModel):
    schema_version: Literal["prospective_hypothesis_status_v1"] = "prospective_hypothesis_status_v1"
    registry_id: str
    registry_version: int
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    source_trial_bundle_count: int = Field(ge=0)
    source_trial_bundle_sha256: List[str]
    hypotheses: List[HypothesisStatus]
    automatic_weight_change: Literal[False] = False
    automatic_rank_rule_change: Literal[False] = False
    automatic_trading_rule_change: Literal[False] = False

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must include timezone")
        if self.source_trial_bundle_count != len(self.source_trial_bundle_sha256):
            raise ValueError("source trial bundle count must match its hash list")
        if len(self.source_trial_bundle_sha256) != len(set(self.source_trial_bundle_sha256)):
            raise ValueError("source trial bundle hashes must be unique")
        if any(len(value) != 64 for value in self.source_trial_bundle_sha256):
            raise ValueError("source trial bundle hashes must be SHA-256 values")
        keys = [(item.hypothesis_id, item.hypothesis_version) for item in self.hypotheses]
        if len(keys) != len(set(keys)):
            raise ValueError("status snapshot hypotheses must be unique")
        return self
