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
    if not (first.reportable and second.reportable):
        return "too_short"
    if first.median is None or second.median is None:
        return "too_short"
    if first.median == 0 or second.median == 0:
        return "flat"
    if (first.median > 0) != (second.median > 0):
        # Present in one half and reversed in the other. Whatever the full-period
        # figure says, it is an average of two different regimes.
        return "reversed"
    # Same direction in both halves. Not a confirmation — both halves were in
    # view while the hypothesis was formed — but it survives the cheapest check.
    return "consistent"
