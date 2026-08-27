"""Append eligible event observations and derive reproducible hypothesis status."""

import hashlib
import json
from datetime import datetime
from statistics import fmean

from .models import (
    CompletedEventObservation,
    HypothesisEligibility,
    HypothesisRegistry,
    HypothesisStatus,
    HypothesisStatusSnapshot,
    HypothesisTrial,
    HypothesisTrialBundle,
    HypothesisTrialBundleV1,
)


def canonical_hash(model) -> str:
    payload = json.dumps(model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _feature(observation, definition):
    source = observation.post_event_features if definition.phase == "post_event" else observation.pre_event_features
    return getattr(source, definition.dimension)


def _individual_outcome(definition, cohort, value):
    if cohort != "target" or definition.expected_direction == "no_material_difference":
        return "not_applicable"
    if value == 0:
        return "neutral"
    favorable = value > 0 if definition.expected_direction == "higher_than_comparator" else value < 0
    return "success" if favorable else "failure"


def evaluate_observation(registry, observation, recorded_at, existing_trial_keys=None):
    if recorded_at.tzinfo is None:
        raise ValueError("trial recorded_at must include timezone")
    if recorded_at < observation.observed_through:
        raise ValueError("trial cannot be recorded before the staged event observation")
    existing_trial_keys = set(existing_trial_keys or ())
    returns = {item.horizon: item for item in observation.returns}
    observation_hash = canonical_hash(observation)
    trials = []
    eligibility = []
    for definition in registry.hypotheses:
        observed_value = _feature(observation, definition)
        if observed_value is None:
            reason = (
                "required_post_event_field_missing"
                if definition.phase == "post_event"
                else "required_pre_event_field_missing"
            )
            eligibility.append(HypothesisEligibility(
                hypothesis_id=definition.hypothesis_id,
                hypothesis_version=definition.hypothesis_version,
                evaluation_horizon=definition.evaluation_horizon,
                eligible_for_hypothesis=False,
                reason=reason,
            ))
            continue
        outcome = returns.get(definition.evaluation_horizon)
        if outcome is None:
            eligibility.append(HypothesisEligibility(
                hypothesis_id=definition.hypothesis_id,
                hypothesis_version=definition.hypothesis_version,
                evaluation_horizon=definition.evaluation_horizon,
                eligible_for_hypothesis=False,
                reason="horizon_not_matured",
            ))
            continue
        if outcome.status != "comparable":
            eligibility.append(HypothesisEligibility(
                hypothesis_id=definition.hypothesis_id,
                hypothesis_version=definition.hypothesis_version,
                evaluation_horizon=definition.evaluation_horizon,
                eligible_for_hypothesis=False,
                reason="horizon_not_comparable",
            ))
            continue
        trial_key = (
            definition.hypothesis_id,
            definition.hypothesis_version,
            observation.earnings_event_id,
            definition.evaluation_horizon,
        )
        if trial_key in existing_trial_keys:
            eligibility.append(HypothesisEligibility(
                hypothesis_id=definition.hypothesis_id,
                hypothesis_version=definition.hypothesis_version,
                evaluation_horizon=definition.evaluation_horizon,
                eligible_for_hypothesis=False,
                reason="trial_already_recorded",
            ))
            continue
        cohort = "target" if observed_value == definition.target_value else "non_target"
        raw_id = (
            f"{definition.hypothesis_id}|{definition.hypothesis_version}|"
            f"{observation.earnings_event_id}|{definition.evaluation_horizon}"
        )
        trial_id = "HPT-" + hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:20].upper()
        trials.append(HypothesisTrial(
            trial_id=trial_id,
            hypothesis_id=definition.hypothesis_id,
            hypothesis_version=definition.hypothesis_version,
            earnings_event_id=observation.earnings_event_id,
            event_quarter=observation.event_quarter,
            phase=definition.phase,
            evaluation_horizon=definition.evaluation_horizon,
            cohort=cohort,
            observed_dimension=definition.dimension,
            observed_value=observed_value,
            return_value=outcome.return_value,
            individual_outcome=_individual_outcome(definition, cohort, outcome.return_value),
            outcome_observed_at=outcome.observed_at,
            observation_id=observation.observation_id,
            observation_sha256=observation_hash,
            source_record_ids=list(dict.fromkeys(observation.source_record_ids + [outcome.source_record_id])),
            recorded_at=recorded_at,
        ))
        eligibility.append(HypothesisEligibility(
            hypothesis_id=definition.hypothesis_id,
            hypothesis_version=definition.hypothesis_version,
            evaluation_horizon=definition.evaluation_horizon,
            eligible_for_hypothesis=True,
            reason="eligible",
            appended_trial_id=trial_id,
        ))
    return HypothesisTrialBundle(
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        registry_sha256=canonical_hash(registry),
        observation_id=observation.observation_id,
        observation_sha256=observation_hash,
        observation_version=observation.observation_version,
        supersedes_observation_id=observation.supersedes_observation_id,
        observation_stage=observation.observation_stage,
        earnings_event_id=observation.earnings_event_id,
        company_name=observation.company_name,
        ticker=observation.ticker,
        event_quarter=observation.event_quarter,
        event_occurred_at=observation.event_occurred_at,
        observed_through=observation.observed_through,
        pre_event_features_sha256=canonical_hash(observation.pre_event_features),
        reaction=observation.post_event_features.reaction,
        return_snapshots=observation.returns,
        recorded_at=recorded_at,
        trials=trials,
        hypothesis_eligibility=eligibility,
    )


def _rate(values):
    return sum(value > 0 for value in values) / len(values) if values else None


def _rounded(value):
    return None if value is None else round(value, 8)


def _status(definition, target, comparator):
    if not target and not comparator:
        return "active", "prospective observation is not recorded yet"
    rule = definition.assessment_rule
    if len(target) < rule.minimum_target_trials or len(comparator) < rule.minimum_comparator_trials:
        return "insufficient", "fixed minimum target/comparator trials have not both matured"
    mean_delta = fmean(item.return_value for item in target) - fmean(item.return_value for item in comparator)
    rate_delta = _rate([item.return_value for item in target]) - _rate([item.return_value for item in comparator])
    if definition.expected_direction == "no_material_difference":
        mean_ok = abs(mean_delta) <= rule.no_material_mean_delta
        rate_ok = abs(rate_delta) <= rule.no_material_positive_rate_delta
        if mean_ok and rate_ok:
            return "supported", "both frozen no-material-difference bounds are satisfied"
        if mean_ok or rate_ok:
            return "weakened", "only one frozen no-material-difference bound is satisfied"
        return "rejected", "prospective difference exceeds both frozen no-material-difference bounds"
    historical = definition.historical_effect.mean_return_delta_vs_overall
    same_direction = mean_delta > 0 if definition.expected_direction == "higher_than_comparator" else mean_delta < 0
    if not same_direction:
        return "rejected", "prospective mean effect has not retained the frozen direction"
    if abs(mean_delta) >= abs(historical) * rule.retained_effect_ratio:
        return "supported", "prospective mean effect retains the direction and required historical-effect ratio"
    return "weakened", "prospective mean effect retains direction but is below the frozen retained-effect ratio"


def validate_bundle_history(bundles):
    observation_ids = [bundle.observation_id for bundle in bundles]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("staged observation IDs must be globally unique")
    by_event = {}
    for bundle in bundles:
        if isinstance(bundle, HypothesisTrialBundle):
            by_event.setdefault(bundle.earnings_event_id, []).append(bundle)
    stage_order = {"D1": 1, "D5": 2, "D20": 3}
    for event_bundles in by_event.values():
        ordered = sorted(event_bundles, key=lambda item: item.observation_version)
        versions = [item.observation_version for item in ordered]
        if versions != list(range(1, len(ordered) + 1)):
            raise ValueError("staged observation versions must be contiguous per event")
        first = ordered[0]
        if first.supersedes_observation_id is not None:
            raise ValueError("first staged observation cannot supersede another observation")
        for previous, current in zip(ordered, ordered[1:]):
            if current.supersedes_observation_id != previous.observation_id:
                raise ValueError("staged observation predecessor chain is broken")
            identity = (current.company_name, current.ticker, current.event_quarter, current.event_occurred_at)
            prior_identity = (previous.company_name, previous.ticker, previous.event_quarter, previous.event_occurred_at)
            if identity != prior_identity:
                raise ValueError("staged observation changed event identity")
            if current.pre_event_features_sha256 != previous.pre_event_features_sha256:
                raise ValueError("staged observation changed frozen pre-event features")
            if previous.reaction is not None and current.reaction != previous.reaction:
                raise ValueError("staged observation changed an already recorded reaction")
            if stage_order[current.observation_stage] <= stage_order[previous.observation_stage]:
                raise ValueError("staged observation horizon did not advance")
            if current.observed_through <= previous.observed_through:
                raise ValueError("staged observation time did not advance")
            current_returns = {item.horizon: item for item in current.return_snapshots}
            for old_return in previous.return_snapshots:
                present = current_returns.get(old_return.horizon)
                if present is None or present.model_dump(mode="json") != old_return.model_dump(mode="json"):
                    raise ValueError("staged observation changed a matured return")


def summarize_trials(registry, bundles, evaluated_at):
    if evaluated_at.tzinfo is None:
        raise ValueError("status evaluated_at must include timezone")
    if any(evaluated_at < bundle.recorded_at for bundle in bundles):
        raise ValueError("status cannot be evaluated before its source trial bundles")
    validate_bundle_history(bundles)
    trial_keys = set()
    registry_hash = canonical_hash(registry)
    definitions = {
        (item.hypothesis_id, item.hypothesis_version): item
        for item in registry.hypotheses
    }
    by_hypothesis = {item.hypothesis_id: [] for item in registry.hypotheses}
    ordered_bundles = sorted(
        bundles,
        key=lambda item: (item.earnings_event_id, getattr(item, "observation_version", 0)),
    )
    for bundle in ordered_bundles:
        if (bundle.registry_id, bundle.registry_version) != (registry.registry_id, registry.registry_version):
            raise ValueError("trial bundle belongs to a different registry")
        if bundle.registry_sha256 != registry_hash:
            raise ValueError("trial bundle registry hash does not match the frozen definitions")
        returns_by_horizon = {}
        if isinstance(bundle, HypothesisTrialBundle):
            eligibility_keys = {
                (item.hypothesis_id, item.hypothesis_version)
                for item in bundle.hypothesis_eligibility
            }
            if eligibility_keys != set(definitions):
                raise ValueError("trial bundle eligibility does not cover the frozen registry exactly")
            returns_by_horizon = {item.horizon: item for item in bundle.return_snapshots}
            trials_by_id = {item.trial_id: item for item in bundle.trials}
            for result in bundle.hypothesis_eligibility:
                definition = definitions[(result.hypothesis_id, result.hypothesis_version)]
                if result.evaluation_horizon != definition.evaluation_horizon:
                    raise ValueError("eligibility horizon does not match the frozen hypothesis")
                if result.eligible_for_hypothesis:
                    trial = trials_by_id[result.appended_trial_id]
                    if (
                        trial.hypothesis_id,
                        trial.hypothesis_version,
                        trial.evaluation_horizon,
                    ) != (
                        result.hypothesis_id,
                        result.hypothesis_version,
                        result.evaluation_horizon,
                    ):
                        raise ValueError("eligibility result references a different hypothesis trial")
                elif result.reason == "required_pre_event_field_missing" and definition.phase != "pre_event":
                    raise ValueError("pre-event missing reason cannot describe a post-event hypothesis")
                elif result.reason == "required_post_event_field_missing" and definition.phase != "post_event":
                    raise ValueError("post-event missing reason cannot describe a pre-event hypothesis")
                elif result.reason == "horizon_not_matured" and result.evaluation_horizon in returns_by_horizon:
                    raise ValueError("matured horizon cannot be marked as not matured")
                elif result.reason == "horizon_not_comparable":
                    source_return = returns_by_horizon.get(result.evaluation_horizon)
                    if source_return is None or source_return.status != "not_comparable":
                        raise ValueError("not-comparable reason must match the staged return")
                elif result.reason == "trial_already_recorded":
                    prior_key = (
                        result.hypothesis_id,
                        result.hypothesis_version,
                        bundle.earnings_event_id,
                        result.evaluation_horizon,
                    )
                    if prior_key not in trial_keys:
                        raise ValueError("already-recorded reason requires an earlier append-only trial")
        for trial in bundle.trials:
            key = (
                trial.hypothesis_id,
                trial.hypothesis_version,
                trial.earnings_event_id,
                trial.evaluation_horizon,
            )
            if key in trial_keys:
                raise ValueError("duplicate append-only hypothesis trial")
            trial_keys.add(key)
            definition = definitions.get((trial.hypothesis_id, trial.hypothesis_version))
            if definition is None:
                raise ValueError("trial references an unknown hypothesis version")
            if (
                trial.phase != definition.phase
                or trial.evaluation_horizon != definition.evaluation_horizon
                or trial.observed_dimension != definition.dimension
            ):
                raise ValueError("trial contract does not match its frozen hypothesis definition")
            expected_cohort = "target" if trial.observed_value == definition.target_value else "non_target"
            if trial.cohort != expected_cohort:
                raise ValueError("trial cohort does not match the frozen target value")
            if trial.individual_outcome != _individual_outcome(definition, trial.cohort, trial.return_value):
                raise ValueError("trial individual outcome does not match the frozen direction")
            if not isinstance(bundle, HypothesisTrialBundleV1):
                source_return = returns_by_horizon.get(trial.evaluation_horizon)
                if (
                    source_return is None
                    or source_return.status != "comparable"
                    or source_return.return_value != trial.return_value
                    or source_return.observed_at != trial.outcome_observed_at
                    or source_return.source_record_id not in trial.source_record_ids
                ):
                    raise ValueError("trial outcome does not match its staged return snapshot")
            by_hypothesis.setdefault(trial.hypothesis_id, []).append(trial)
    statuses = []
    for definition in registry.hypotheses:
        items = by_hypothesis[definition.hypothesis_id]
        target = [item for item in items if item.cohort == "target"]
        # The frozen historical effect compared each target category with the
        # complete eligible cohort, including the target rows themselves.
        comparator = items
        target_values = [item.return_value for item in target]
        comparator_values = [item.return_value for item in comparator]
        target_mean = fmean(target_values) if target_values else None
        comparator_mean = fmean(comparator_values) if comparator_values else None
        target_rate = _rate(target_values)
        comparator_rate = _rate(comparator_values)
        status, note = _status(definition, target, comparator)
        statuses.append(HypothesisStatus(
            hypothesis_id=definition.hypothesis_id,
            hypothesis_version=definition.hypothesis_version,
            phase=definition.phase,
            priority=definition.priority,
            status=status,
            prospective_trials=len(target),
            prospective_successes=sum(item.individual_outcome == "success" for item in target),
            prospective_failures=sum(item.individual_outcome == "failure" for item in target),
            comparator_observations=len(comparator),
            target_mean_return=_rounded(target_mean),
            comparator_mean_return=_rounded(comparator_mean),
            prospective_effect=_rounded(target_mean - comparator_mean) if target and comparator else None,
            target_positive_rate=_rounded(target_rate),
            comparator_positive_rate=_rounded(comparator_rate),
            prospective_positive_rate_effect=_rounded(target_rate - comparator_rate) if target and comparator else None,
            distinct_event_quarters=len({item.event_quarter for item in items}),
            last_evaluated_at=max((item.recorded_at for item in items), default=None),
            production_review_eligible=False,
            note=note,
        ))
    return HypothesisStatusSnapshot(
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        registry_sha256=registry_hash,
        evaluated_at=evaluated_at,
        source_trial_bundle_count=len(bundles),
        source_trial_bundle_sha256=sorted(canonical_hash(bundle) for bundle in bundles),
        hypotheses=statuses,
    )
