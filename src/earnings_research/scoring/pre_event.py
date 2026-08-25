"""Derive a pre-event score from its declared scoring version.

A baseline records both a headline ``pre_event_score`` and the
``scoring_version`` that supposedly produced it. Until this module existed the
two were unrelated: the shipped version defined weights for five of eighteen
components, summing to 0.12, so the headline number could not be recomputed by
anyone. Locking a number nobody can reproduce gives the appearance of a
commitment without the substance of one.

Weights are signed. A component that counts against the score carries a
negative weight, which keeps the direction in the data instead of in a
convention someone has to remember.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

WEIGHT_SUM_TOLERANCE = Decimal("0.000001")
SCORE_QUANTUM = Decimal("0.1")
# At least half the declared weight must survive exclusion. Renormalising by a
# small remainder scales the survivors up without bound: dropping the positive
# components and keeping the penalties turned the worst possible row into 100.
MIN_SURVIVING_WEIGHT = Decimal("0.5")
SCORE_MIN = Decimal("0")
SCORE_MAX = Decimal("100")


class ScoringError(ValueError):
    """The recorded score cannot be reproduced from its scoring version."""


def component_names(columns: Iterable[str]) -> List[str]:
    """Return the baseline columns that feed the composite score."""
    return [
        name
        for name in columns
        if (name.endswith("_score") or name.endswith("_penalty"))
        and name not in ("pre_event_score", "post_event_score")
    ]


def definitions_for(
    definitions: Sequence[Dict[str, str]],
    *,
    scoring_version: str,
    score_name: str = "pre_event_score",
    as_of: Optional[date] = None,
) -> Dict[str, Dict[str, str]]:
    """Return the components in force for one scoring version."""
    selected = {}
    for row in definitions:
        if row.get("scoring_version") != scoring_version or row.get("score_name") != score_name:
            continue
        if as_of is not None and not _in_force(row, as_of):
            continue
        selected[str(row.get("component_name", ""))] = row
    return selected


def coverage_gaps(
    components: Sequence[str],
    definitions: Dict[str, Dict[str, str]],
) -> List[str]:
    """Return the reasons this scoring version cannot produce a score."""
    gaps = []
    missing = [name for name in components if name not in definitions]
    if missing:
        gaps.append("scoring version defines no weight for %s" % ", ".join(sorted(missing)))
    extra = [name for name in definitions if name not in components]
    if extra:
        gaps.append("scoring version weights unknown components %s" % ", ".join(sorted(extra)))
    if not missing and not extra:
        total = sum(_decimal(row.get("weight"), "weight") for row in definitions.values())
        if abs(total - Decimal("1")) > WEIGHT_SUM_TOLERANCE:
            gaps.append("component weights sum to %s, not 1" % _plain(total))
    return gaps


def derive_score(
    row: Dict[str, str],
    definitions: Dict[str, Dict[str, str]],
) -> Decimal:
    """Return the composite score implied by the components and their weights."""
    contributions, weight_total = _contributions(row, definitions)
    if weight_total < MIN_SURVIVING_WEIGHT:
        raise ScoringError(
            "only %s of the declared weight survives exclusion, too little to rescale"
            % _plain(weight_total)
        )
    total = sum(value * weight for _name, value, weight in contributions)
    score = (total / weight_total).quantize(SCORE_QUANTUM)
    if not SCORE_MIN <= score <= SCORE_MAX:
        # Signed weights summing to one bound the average, not the range: with
        # penalties the composite can land outside the scale its components use,
        # and such a row cannot be recorded in a column that stops at 100.
        raise ScoringError(
            "scoring version puts the composite at %s, outside the %s to %s component scale"
            % (_plain(score), _plain(SCORE_MIN), _plain(SCORE_MAX))
        )
    return score


def matches_recorded(recorded: str, derived: Decimal) -> bool:
    """Exact equality: the derived value is already at the recorded precision.

    A tolerance here is not rounding headroom, it is undetectable drift. The
    legacy CSV shape carries no lock hash, so anything the comparison forgives
    is unrecoverable.
    """
    try:
        return Decimal(str(recorded).strip()) == derived
    except (InvalidOperation, ValueError, AttributeError):
        return False


def explain(row: Dict[str, str], definitions: Dict[str, Dict[str, str]]) -> List[Tuple[str, Decimal, Decimal, Decimal]]:
    """Return (component, value, weight, contribution) for auditing a score."""
    contributions, _total = _contributions(row, definitions)
    return [(name, value, weight, value * weight) for name, value, weight in contributions]


def _contributions(
    row: Dict[str, str],
    definitions: Dict[str, Dict[str, str]],
) -> Tuple[List[Tuple[str, Decimal, Decimal]], Decimal]:
    contributions = []
    weight_total = Decimal("0")
    for name, definition in sorted(definitions.items()):
        weight = _decimal(definition.get("weight"), "weight")
        raw = str(row.get(name, "")).strip()
        if raw == "":
            value = _missing_value(name, definition)
            if value is None:
                continue  # exclude_with_note drops the component and its weight
        else:
            value = _decimal(raw, name)
            _require_in_range(name, value, definition)
        contributions.append((name, value, weight))
        weight_total += weight
    return contributions, weight_total


def _missing_value(name: str, definition: Dict[str, str]) -> Optional[Decimal]:
    policy = definition.get("missing_value_policy")
    if policy == "neutral":
        low = _decimal(definition.get("min_value"), "min_value")
        high = _decimal(definition.get("max_value"), "max_value")
        return (low + high) / 2
    if policy == "exclude_with_note":
        return None
    # `require` and `human_review` both mean a machine must not fill the blank.
    raise ScoringError("component %s is blank and its policy is %s" % (name, policy))


def _require_in_range(name: str, value: Decimal, definition: Dict[str, str]) -> None:
    low = _decimal(definition.get("min_value"), "min_value")
    high = _decimal(definition.get("max_value"), "max_value")
    if not low <= value <= high:
        raise ScoringError("component %s is outside its declared range" % name)


def _in_force(row: Dict[str, str], as_of: date) -> bool:
    started = str(row.get("effective_from", "")).strip()
    ended = str(row.get("effective_to", "")).strip()
    if started and date.fromisoformat(started) > as_of:
        return False
    if ended and date.fromisoformat(ended) < as_of:
        return False
    return True


def _decimal(value, field: str) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise ScoringError("%s is not a number" % field) from exc


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text
