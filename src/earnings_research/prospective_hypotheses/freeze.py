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


def rule_freeze_violations(registries: Sequence, bundles: Sequence) -> List[str]:
    """Every definition whose rules moved after it began gathering evidence.

    Reads across registries rather than comparing two: a rule can be changed by
    freezing a third registry, and a pairwise check sees only the pair it was
    handed.

    A definition with no trials is skipped, and that is the boundary this whole
    module is about — not an exemption. Re-freezing before the first trial is
    how a rule is supposed to be changed.
    """
    problems: List[str] = []
    by_key: Dict[Key, Dict[str, List[str]]] = {}
    for registry in registries:
        for definition in registry.hypotheses:
            key = (definition.hypothesis_id, definition.hypothesis_version)
            where = "%s@v%d" % (registry.registry_id, registry.registry_version)
            by_key.setdefault(key, {}).setdefault(rule_digest(registry, definition), []).append(where)
    for key in sorted(by_key):
        digests = by_key[key]
        if len(digests) == 1:
            continue
        since = evaluation_started_at(key, bundles)
        if since is None:
            continue
        problems.append(
            "%s v%d began gathering evidence at %s, and its decision rules differ "
            "between %s; a rule that has to change needs a new hypothesis version, "
            "which starts from no trials"
            % (
                key[0],
                key[1],
                since.isoformat(),
                " and ".join(
                    "%s (%s)" % (", ".join(sorted(where)), digest[:12])
                    for digest, where in sorted(digests.items())
                ),
            )
        )
    return problems
