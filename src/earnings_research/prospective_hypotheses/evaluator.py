"""Append eligible event observations and derive reproducible hypothesis status."""

import hashlib
import json
from datetime import datetime
from statistics import fmean

from earnings_research.statistics.stability import assess

from .models import (
    CompletedEventObservation,
    HypothesisRegistry,
    HypothesisStatus,
    HypothesisStatusSnapshot,
    HypothesisTrial,
    HypothesisTrialBundle,
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


def evaluate_observation(registry, observation, recorded_at):
    if recorded_at.tzinfo is None:
        raise ValueError("trial recorded_at must include timezone")
    if recorded_at < observation.completed_at:
        raise ValueError("trial cannot be recorded before the completed event observation")
    returns = {item.horizon: item for item in observation.returns}
    observation_hash = canonical_hash(observation)
    trials = []
    ineligible = {}
    for definition in registry.hypotheses:
        observed_value = _feature(observation, definition)
        if observed_value is None:
            ineligible[definition.hypothesis_id] = "required feature was not recorded"
            continue
        outcome = returns.get(definition.evaluation_horizon)
        if outcome is None:
            ineligible[definition.hypothesis_id] = "evaluation horizon has not matured"
            continue
        if outcome.status != "comparable":
            ineligible[definition.hypothesis_id] = "evaluation horizon is not comparable"
            continue
        cohort = "target" if observed_value == definition.target_value else "non_target"
        raw_id = f"{definition.hypothesis_id}|{definition.hypothesis_version}|{observation.earnings_event_id}"
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
    return HypothesisTrialBundle(
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        registry_sha256=canonical_hash(registry),
        observation_id=observation.observation_id,
        earnings_event_id=observation.earnings_event_id,
        recorded_at=recorded_at,
        trials=trials,
        ineligible_hypotheses=ineligible,
    )


def _rate(values):
    return sum(value > 0 for value in values) / len(values) if values else None


def _rounded(value):
    return None if value is None else round(value, 8)


def should_stop(definition, *, halves_reversed=None, reserved_effect_ratio=None, revisions=None):
    """Return why this hypothesis is finished, or None to keep it open.

    Every condition was fixed when the definition was frozen. Reaching one is
    not a setback to be worked around; it is the answer.
    """
    rule = definition.assessment_rule.stop_rule
    if rule is None:
        # Versions frozen before stop rules existed carry none, and one is not
        # applied to them after the fact. They simply have no stopping point
        # until a new version is frozen with one.
        return None
    if rule.stop_when_halves_reverse and halves_reversed:
        return "the effect reversed between the two halves of the record"
    if (
        reserved_effect_ratio is not None
        and reserved_effect_ratio < rule.stop_below_reserved_effect_ratio
    ):
        return (
            "the reserved period retained %.2f of the frozen effect, below the %.2f required"
            % (reserved_effect_ratio, rule.stop_below_reserved_effect_ratio)
        )
    if revisions is not None and revisions > rule.maximum_revisions:
        return (
            "revised %d times against a limit of %d; the question needs asking again, not patching"
            % (revisions, rule.maximum_revisions)
        )
    return None


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


def _halves_reversed(definition, target, comparator):
    """Whether the *effect* changed sign between the halves of the record.

    Reading the target group's raw returns instead answers a different
    question, and answers it wrongly in both directions. A market that fell and
    then rose flips those returns while the hypothesis holds perfectly in each
    half, so a regime change retires a good hypothesis; and an effect that
    genuinely decays from +5% to -5% keeps positive raw returns throughout, so
    the real decay is missed. For a hypothesis whose claim is that there is no
    material difference, the target group's raw sign says nothing at all.

    So each half is scored on what the hypothesis actually claims: the target
    group against its comparator. The reversal has to clear the definition's
    own materiality band on both sides, which keeps a hair either side of zero
    from counting as a change of direction.

    None wherever the question cannot be answered — too few trials in a half,
    or a difference too small to call. A stop rule reading None does not fire.
    """
    rule = definition.assessment_rule
    dated = sorted(
        ((trial.outcome_observed_at, trial) for trial in list(target) + list(comparator)),
        key=lambda item: item[0],
    )
    if len(dated) < 2:
        return None
    middle = len(dated) // 2
    deltas = []
    for part in (dated[:middle], dated[middle:]):
        rows = [trial for _when, trial in part]
        inside = [item.return_value for item in rows if item.cohort == "target"]
        outside = [item.return_value for item in rows]
        if len(inside) < rule.minimum_target_trials or len(outside) < rule.minimum_comparator_trials:
            return None
        deltas.append(fmean(inside) - fmean(outside))
    first, second = deltas
    band = rule.no_material_mean_delta
    if abs(first) <= band or abs(second) <= band:
        return None
    return (first > 0) != (second > 0)


def stop_rule_relaxations(previous, current):
    """Report every way a successor registry loosened what it inherited.

    Widening a condition is the obvious way. Dropping the hypothesis entirely
    is the larger one and was passing silently: a successor keeping one of
    nineteen definitions, or renaming every identifier so that nothing matched,
    was reported as having only tightened. So is comparing against an unrelated
    registry, which the version check alone cannot catch.
    """
    problems = []
    if previous.registry_id != current.registry_id:
        problems.append(
            "registry %s is not a successor of %s" % (current.registry_id, previous.registry_id)
        )
        return problems
    if previous.registry_version >= current.registry_version:
        problems.append("the superseded registry must carry an earlier registry_version")
    earlier = {item.hypothesis_id: item for item in previous.hypotheses}
    now = {item.hypothesis_id: item for item in current.hypotheses}
    for missing in sorted(set(earlier) - set(now)):
        problems.append("%s was dropped, which retires its stop rule with it" % missing)
    for item in current.hypotheses:
        before = earlier.get(item.hypothesis_id)
        if before is None:
            continue
        if item.hypothesis_version < before.hypothesis_version:
            problems.append(
                "%s went back from v%d to v%d"
                % (item.hypothesis_id, before.hypothesis_version, item.hypothesis_version)
            )
        was, current_rule = before.assessment_rule.stop_rule, item.assessment_rule.stop_rule
        if was is None:
            continue
        if current_rule is None:
            problems.append(
                "%s v%d drops the stop rule frozen in v%d"
                % (item.hypothesis_id, item.hypothesis_version, before.hypothesis_version)
            )
        elif not current_rule.at_least_as_strict_as(was):
            problems.append(
                "%s v%d relaxes the stop rule frozen in v%d"
                % (item.hypothesis_id, item.hypothesis_version, before.hypothesis_version)
            )
    return problems


def summarize_trials(registry, bundles, evaluated_at):
    trial_keys = set()
    registry_hash = canonical_hash(registry)
    definitions = {
        (item.hypothesis_id, item.hypothesis_version): item
        for item in registry.hypotheses
    }
    by_hypothesis = {item.hypothesis_id: [] for item in registry.hypotheses}
    for bundle in bundles:
        if (bundle.registry_id, bundle.registry_version) != (registry.registry_id, registry.registry_version):
            raise ValueError("trial bundle belongs to a different registry")
        if bundle.registry_sha256 != registry_hash:
            raise ValueError("trial bundle registry hash does not match the frozen definitions")
        for trial in bundle.trials:
            key = (trial.hypothesis_id, trial.hypothesis_version, trial.earnings_event_id)
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
        # The stop rule is read here rather than by a reviewer, because a
        # condition nobody evaluates is a condition nobody is bound by. Halves
        # are compared on the trials themselves; the reserved period belongs to
        # historical exploration and has no counterpart in prospective trials,
        # so that condition is left unevaluated rather than guessed at.
        stop_reason = should_stop(
            definition,
            halves_reversed=_halves_reversed(definition, target, comparator),
            revisions=definition.hypothesis_version - 1,
        )
        if stop_reason is not None:
            # A hypothesis that met its own abandonment condition is finished.
            # Leaving the status at supported let a stopped hypothesis keep
            # reading as a live one, and the stop reason appeared nowhere a
            # reader would look.
            status, note = "stopped", stop_reason
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
            stop_reason=stop_reason,
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
