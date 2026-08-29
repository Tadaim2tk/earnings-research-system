"""What may no longer change once a hypothesis has started gathering evidence.

A stop rule says when the hypothesis is finished. A promotion rule says when it
has earned a change to production. Both are easy to move once the numbers are
in, and moving either one mid-test turns a test into a search for the threshold
that makes the answer come out right.

So the moment evidence starts arriving they are fixed — not "may only be
tightened". Tightening is still a change made in sight of the result, and "the
bar went up and it still passed" is a different experiment from the one that
was registered. Nothing here can tell the two apart, and it should not try: a
rule that needs to change gets a new hypothesis version, which starts from no
trials at all.

Before the first trial there is nothing to fix. A definition that has observed
nothing cannot have been adjusted in response to what it observed, so the rules
may be changed and re-frozen freely. The boundary is the arrival of the first
trial, not the freeze of the registry.

When evaluation started is not written down. It is the moment the first trial
for that definition entered the append-only record, and that record is the only
thing that can say so. A field somebody maintains could be set to a later date,
and every rule before it would come unfrozen — a new way to be wrong that
buys nothing, since the answer is already derivable.
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from .models import canonical_hash

Key = Tuple[str, int]


def decision_rules(registry, definition) -> Dict[str, object]:
    """The frozen rules that decide this hypothesis's fate.

    Two of them, from two levels. The stop rule is the definition's own. The
    promotion policy is the registry's, and it counts: a hypothesis cannot be
    promoted on terms other than the ones that were registered, and those terms
    live one level up. Leaving it out would have let the bar for promotion move
    under a hypothesis already gathering evidence, with every per-hypothesis
    digest unchanged.
    """
    stop_rule = definition.assessment_rule.stop_rule
    return {
        "stop_rule": None if stop_rule is None else stop_rule.model_dump(mode="json"),
        "promotion_review_policy": registry.promotion_review_policy.model_dump(mode="json"),
    }


def rule_digest(registry, definition) -> str:
    """SHA-256 of those rules, so a change is a different value and not an opinion."""
    return hashlib.sha256(
        json.dumps(
            decision_rules(registry, definition),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def trials_for(key: Key, bundles: Sequence) -> List:
    """Every recorded trial for one frozen definition, across all bundles."""
    return [
        trial
        for bundle in bundles
        for trial in bundle.trials
        if (trial.hypothesis_id, trial.hypothesis_version) == key
    ]


def evaluation_started_at(key: Key, bundles: Sequence) -> Optional[datetime]:
    """When this definition began gathering evidence, derived from the record.

    The earliest moment a trial for it was appended, or None while it has none.
    Derived rather than stored: with a field, "started" and "has trials" could
    disagree, and the only way to notice would be to compute this anyway.

    `recorded_at` rather than `outcome_observed_at`: the question is when the
    definition began accumulating evidence, which is when a trial entered the
    record. An event can be observed long before anyone records a trial for it,
    and a rule changed in between was changed before any result was in hand.
    """
    trials = trials_for(key, bundles)
    if not trials:
        return None
    return min(trial.recorded_at for trial in trials)


def started(key: Key, bundles: Sequence) -> bool:
    return evaluation_started_at(key, bundles) is not None


def _bundle_registry(bundle, registries) -> Tuple[object, Optional[str]]:
    """The registry a bundle was recorded against, or why it cannot be found.

    Provenance, not inference. A bundle names the registry it was scored under
    and carries that registry's hash, so which rules were actually applied to a
    trial is recorded rather than reconstructed from timestamps.
    """
    for registry in registries:
        if (registry.registry_id, registry.registry_version) == (
            bundle.registry_id,
            bundle.registry_version,
        ):
            if canonical_hash(registry) != bundle.registry_sha256:
                return None, (
                    "a trial was recorded against %s@v%d, which no longer matches the "
                    "hash the bundle carries; the rules it was scored under cannot be "
                    "established" % (bundle.registry_id, bundle.registry_version)
                )
            return registry, None
    return None, (
        "a trial names registry %s@v%d, which is not among the registries being "
        "checked; the rules it was scored under cannot be established"
        % (bundle.registry_id, bundle.registry_version)
    )


def rule_freeze_violations(registries: Sequence, bundles: Sequence) -> List[str]:
    """Every definition whose rules moved after it began gathering evidence.

    The rule in effect is the one the earliest trial was actually scored under,
    read off that trial's own bundle. Comparing every registry that mentions the
    definition instead was wrong in a way that only appeared later: a rule
    changed and re-frozen *before* the first trial is permitted, but both
    registries stay on disk, so the first trial to arrive afterwards turned the
    earlier, legitimate edit into a violation — the documented path failing
    retroactively, in standing CI, long after the change it objected to.

    So a registry matters here only if it was frozen after the start, or if a
    trial was recorded against it. Two ways the rules can move, and both are
    reported:

      * trials for one definition scored under registries that disagree — the
        rules already differ across the evidence;
      * a registry defining it with different rules, frozen after the start —
        nothing has been recorded under it yet, and nothing should be.

    Reads across every registry rather than comparing two, because a rule can
    be changed by freezing a third.
    """
    problems: List[str] = []
    registry_of: Dict[int, object] = {}
    for bundle in bundles:
        registry, failure = _bundle_registry(bundle, registries)
        if failure is not None:
            if failure not in problems:
                problems.append(failure)
            continue
        registry_of[id(bundle)] = registry
    if problems:
        # Provenance could not be established for at least one trial, so no
        # statement about which rules were in effect would mean anything.
        return problems

    keys = sorted(
        {
            (definition.hypothesis_id, definition.hypothesis_version)
            for registry in registries
            for definition in registry.hypotheses
        }
    )
    for key in keys:
        since = evaluation_started_at(key, bundles)
        if since is None:
            continue
        scored = [
            (bundle, registry_of[id(bundle)])
            for bundle in bundles
            if any(
                (trial.hypothesis_id, trial.hypothesis_version) == key for trial in bundle.trials
            )
        ]
        first = min(scored, key=lambda pair: min(
            trial.recorded_at for trial in pair[0].trials
            if (trial.hypothesis_id, trial.hypothesis_version) == key
        ))[1]
        in_effect = _digest_for(first, key)
        for bundle, registry in scored:
            digest = _digest_for(registry, key)
            if digest != in_effect:
                problems.append(
                    "%s v%d has trials scored under two different rules: %s@v%d (%s) and "
                    "%s@v%d (%s)"
                    % (
                        key[0], key[1],
                        first.registry_id, first.registry_version, in_effect[:12],
                        registry.registry_id, registry.registry_version, digest[:12],
                    )
                )
                break
        for registry in registries:
            digest = _digest_for(registry, key)
            if digest is None or digest == in_effect:
                continue
            if registry.frozen_at <= since:
                # Frozen before evidence began. Changing the rules then is how
                # they are supposed to be changed, and this is that path.
                continue
            problems.append(
                "%s v%d began gathering evidence at %s, and %s@v%d was frozen afterwards "
                "with different decision rules (%s, was %s); a rule that has to change "
                "needs a new hypothesis version, which starts from no trials"
                % (
                    key[0], key[1], since.isoformat(),
                    registry.registry_id, registry.registry_version,
                    digest[:12], in_effect[:12],
                )
            )
    return problems


def _digest_for(registry, key: Key) -> Optional[str]:
    for definition in registry.hypotheses:
        if (definition.hypothesis_id, definition.hypothesis_version) == key:
            return rule_digest(registry, definition)
    return None
