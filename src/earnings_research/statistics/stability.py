"""Does the relationship hold in both halves, or only in one?

A cohort measured once over the whole record cannot say whether it found
something durable or something that worked for a while. Published signals
usually stop working: McLean and Pontiff tracked ninety-seven predictors and
found returns fell 26% out of sample and 58% after publication. A relationship
that only appears in one half is the shape that decay leaves behind, and it is
also the shape that a lucky stretch leaves behind.

Splitting the exploration set in two and asking whether both halves agree costs
nothing and separates those cases from a relationship that was present
throughout. It is a weaker test than the reserved period — both halves were
available while the hypothesis was formed — so it rules things out rather than
confirming them.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from earnings_research.statistics.cohort import MIN_REPORTABLE, CohortSummary, summarise
from earnings_research.statistics.holdout import _as_date


@dataclass(frozen=True)
class Stability:
    """Whether the two halves of the record tell the same story."""

    first: Optional[CohortSummary]
    second: Optional[CohortSummary]
    boundary: Optional[date]
    verdict: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "boundary": self.boundary.isoformat() if self.boundary else None,
            "first_half": self.first.as_dict() if self.first else None,
            "second_half": self.second.as_dict() if self.second else None,
            # Surfaced beside the verdict because it is the whole reason a sign
            # difference did or did not become a reversal.
            "halves_exclude_zero": [
                bool(self.first and self.first.median_interval.excludes_zero()),
                bool(self.second and self.second.median_interval.excludes_zero()),
            ],
            "verdict": self.verdict,
        }


def assess(
    records: Sequence[dict],
    value_of,
    *,
    date_key: str = "date",
    cluster_of=None,
) -> Stability:
    """Summarise each half of the record separately and compare their direction.

    ``value_of`` returns the outcome for a record, or None where it is missing.
    """
    dated: List[Tuple[date, dict]] = []
    for record in records:
        day = _as_date(record.get(date_key))
        if day is not None and value_of(record) is not None:
            dated.append((day, record))
    if len(dated) < MIN_REPORTABLE * 2:
        return Stability(None, None, None, "too_short")
    dated.sort(key=lambda item: item[0])
    middle = len(dated) // 2
    boundary = dated[middle][0]
    halves = []
    for part in (dated[:middle], dated[middle:]):
        values = [value_of(record) for _day, record in part]
        clusters = [cluster_of(record) for _day, record in part] if cluster_of else None
        halves.append(summarise(values, clusters=clusters))
    first, second = halves
    return Stability(first, second, boundary, _verdict(first, second))


def _verdict(first: CohortSummary, second: CohortSummary) -> str:
    """Name what the two halves support, keeping ``reversed`` expensive to earn.

    A bare sign difference is not evidence of a regime change. Split a record
    with no effect at all in two and the halves disagree about half the time,
    which is exactly what chance produces: over the 254 legacy records the
    permuted rate of sign disagreement was 0.514 against a null of 0.50
    (p = 0.508). Stopping on that would retire good hypotheses at a coin's
    pace, so a reversal has to be a reversal of two directions each of which
    the data can actually assert: both halves' 95% median intervals have to
    exclude zero and point opposite ways. Anything short of that is
    ``inconclusive`` — the halves failed to agree, and also failed to disagree.
    """
    if not (first.reportable and second.reportable):
        return "too_short"
    if first.median is None or second.median is None:
        return "too_short"
    if first.median == 0 or second.median == 0:
        # No direction to reverse. Reported separately from inconclusive because
        # an exact zero median is a property of the data, not of the evidence.
        return "flat"
    if (first.median > 0) != (second.median > 0):
        if first.median_interval.excludes_zero() and second.median_interval.excludes_zero():
            # Each half asserts a direction on its own, and they point apart.
            # Whatever the full-period figure says, it averages two regimes.
            return "reversed"
        return "inconclusive"
    # Same direction in both halves. Not a confirmation — both halves were in
    # view while the hypothesis was formed — but it survives the cheapest check.
    return "consistent"
