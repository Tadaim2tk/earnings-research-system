"""Keep part of the record out of reach while a hypothesis is being formed.

Anything can be made to work on the data it was built from: drop the losing
cases, add a condition, drop again, and the past looks excellent. The defence
is not discipline, which fails quietly, but arithmetic — some of the record has
to be unavailable while the searching happens.

So the reserved period's statistics are not computed at all. It is not that
they are computed and then ignored; there is no number to be tempted by.
Reading them takes a deliberate second call naming a hypothesis that was frozen
before the reserved period was touched.

The split is by date rather than at random. Two earnings from the same quarter
are not independent draws, and a signal that decays — the usual fate of a
published one — looks fine under a random split and fails under a chronological
one. The chronological split is the honest test because it is the one the
future will run.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from earnings_research.statistics.cohort import MIN_REPORTABLE

# How much of the record is held back. A third leaves enough to explore with
# while keeping a reserve large enough to fail against.
DEFAULT_RESERVE = 1 / 3
# Both sides have to be large enough to say anything, or reserving simply
# destroys the record instead of protecting it. Reserving a third of eighteen
# leaves twelve to explore with and six in reserve, which is the first size
# where the reserved side clears MIN_REPORTABLE with anything to spare. Below
# that the reserve exists but can never return a number, which is worse than
# not reserving: it looks like a held-out test and behaves like nothing.
MIN_FOR_RESERVE = 18


class HoldoutViolation(RuntimeError):
    """Reserved records were about to be summarised during exploration."""


@dataclass(frozen=True)
class Split:
    """Which records may be explored, and which are being kept back."""

    cutoff: Optional[date]
    exploration: List[dict]
    reserved: List[dict]
    # Rows with no usable date. They stay in exploration, so their number is
    # reported: a large count means the cutoff governs less of the record than
    # the exploration total suggests.
    undated_count: int = 0
    reason: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "cutoff": self.cutoff.isoformat() if self.cutoff else None,
            "exploration_count": len(self.exploration),
            "reserved_count": len(self.reserved),
            "undated_count": self.undated_count,
            "no_reserve_reason": self.reason,
            "reserved_statistics": "not_computed",
            "note": (
                "No cutoff means nothing is reserved, either because the record "
                "is too short to divide or because no usable dates were found. "
                "Records on or after the cutoff are reserved. Their outcomes are "
                "not summarised here at all, so a hypothesis cannot be shaped "
                "against them. Evaluating one requires a definition frozen "
                "before the reserved period."
            ),
        }


def split_by_date(
    records: Sequence[dict],
    *,
    date_key: str = "date",
    reserve: float = DEFAULT_RESERVE,
) -> Split:
    """Reserve the most recent ``reserve`` share of the record.

    Records without a usable date stay in exploration: a missing date cannot be
    placed after the cutoff, and putting them in the reserve would let unknown
    rows leak into the part meant to stay clean.
    """
    if not 0 < reserve < 1:
        raise ValueError("reserve must sit between 0 and 1")
    dated: List[Tuple[date, dict]] = []
    undated: List[dict] = []
    for record in records:
        parsed = _as_date(record.get(date_key))
        (dated.append((parsed, record)) if parsed else undated.append(record))
    if len(dated) < MIN_FOR_RESERVE:
        # Too little to divide: reserving here would leave neither side able to
        # support a statistic, and the caller should see that nothing is held
        # back rather than a silently emptied exploration set.
        return Split(
            None,
            list(records),
            [],
            len(undated),
            "only %d dated records, below the %d needed to reserve a third"
            % (len(dated), MIN_FOR_RESERVE),
        )
    dated.sort(key=lambda item: item[0])
    cut_index = int(len(dated) * (1 - reserve))
    if cut_index >= len(dated):
        return Split(
            None,
            [record for _d, record in dated] + undated,
            [],
            len(undated),
            "the reserve share rounds to nothing at this size",
        )
    cutoff = dated[cut_index][0]
    exploration = [record for day, record in dated if day < cutoff] + undated
    reserved = [record for day, record in dated if day >= cutoff]
    # Dates repeat — a whole earnings season can land on one day — so the cut
    # index is not the cut. When the tie reaches back to the first date there is
    # nothing before the cutoff and every dated row is reserved, which would
    # leave the statistics running on the undated remainder alone while the
    # report still claimed a chronological split. Say instead that no split was
    # possible, and reserve nothing.
    if not any(day < cutoff for day, _record in dated):
        return Split(
            None,
            list(records),
            [],
            len(undated),
            "every dated record falls on or after %s, so there is no earlier "
            "period to explore" % cutoff.isoformat(),
        )
    if len(reserved) < MIN_REPORTABLE:
        return Split(
            None,
            list(records),
            [],
            len(undated),
            "a cutoff at %s would reserve only %d records, below the %d needed "
            "to report anything" % (cutoff.isoformat(), len(reserved), MIN_REPORTABLE),
        )
    return Split(cutoff, exploration, reserved, len(undated))


def evaluate_reserved(
    split: Split,
    frozen_at,
    summarise_with: Callable[[Sequence[dict]], object],
):
    """Read the reserved period, but only for a definition frozen before it.

    A definition frozen after the cutoff has already seen what it is about to
    be tested on, so the test would say nothing.
    """
    if split.cutoff is None:
        raise HoldoutViolation(
            "nothing is reserved, so there is nothing to confirm against"
            + (": %s" % split.reason if split.reason else "")
        )
    frozen_day = _as_date(frozen_at)
    if frozen_day is None:
        # Refusing beats guessing. An unreadable freeze date cannot be shown to
        # precede the reserved period, and the reserve is only worth anything
        # while that ordering is certain.
        raise HoldoutViolation(
            "the freeze date %r could not be read, so it cannot be shown to "
            "precede the reserved period" % (frozen_at,)
        )
    if frozen_day >= split.cutoff:
        raise HoldoutViolation(
            "the definition was frozen on %s, on or after the reserved period began on %s"
            % (frozen_day, split.cutoff)
        )
    return summarise_with(split.reserved)


def _as_date(value) -> Optional[date]:
    """Reduce whatever the record carries to a calendar day, or None.

    datetime is a subclass of date, so it has to be narrowed first: returning
    it unchanged makes every later ``day < cutoff`` a datetime-against-date
    comparison, which raises rather than misordering. A timezone is dropped
    rather than converted — the day an earnings release belongs to is the day
    it was filed in Tokyo, and re-basing it to UTC would move some releases a
    day earlier than the market that reacted to them.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
