"""Summarise a cohort of returns so the number can be acted on or dismissed.

A mean answers "what would holding all of them equally have returned", which is
a fair question. It does not answer "does this work", and the two are easy to
confuse: one stock limit-up for three days can carry a cohort of forty whose
other thirty-nine went nowhere, and the mean will look the same either way. The
win rate and the median answer the second question; the concentration figures
say how far apart the two answers are.

Every interval here is exact and distribution-free. Returns are fat-tailed, so
a normal interval understates the tails, and a bootstrap would put a seed
between the data and the answer. Clopper-Pearson covers the win rate and an
order statistic covers the median: neither assumes a shape, neither needs a
random number, and both reproduce exactly.
"""

from dataclasses import dataclass, replace
from math import comb, floor
from statistics import median as _median, quantiles
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Below this a cohort reports its size and nothing else. Statistics from a
# handful of observations read as precise while carrying none of the weight.
MIN_REPORTABLE = 5
TRIM_FRACTION = 0.1
CONFIDENCE = 0.95
# Concentration is reported, not thresholded. A cut-off would have to be
# guessed: for fat-tailed returns a single name routinely carries four to six
# observations' worth of the spread without the cohort being unsound. What
# matters is whether the conclusion survives that name leaving.


@dataclass(frozen=True)
class Interval:
    """A range that either does or does not contain zero."""

    low: Optional[float]
    high: Optional[float]

    def excludes_zero(self) -> bool:
        if self.low is None or self.high is None:
            return False
        return self.low > 0 or self.high < 0

    def as_dict(self) -> Dict[str, Optional[float]]:
        return {"low": self.low, "high": self.high}


@dataclass(frozen=True)
class CohortSummary:
    """What a group of outcomes supports, and what it does not."""

    n: int
    n_independent: int
    reportable: bool
    win_rate: Optional[float] = None
    win_rate_interval: Interval = Interval(None, None)
    median: Optional[float] = None
    median_interval: Interval = Interval(None, None)
    mean: Optional[float] = None
    trimmed_mean: Optional[float] = None
    q1: Optional[float] = None
    q3: Optional[float] = None
    best: Optional[float] = None
    worst: Optional[float] = None
    mean_without_best: Optional[float] = None
    concentration: Optional[float] = None
    sign_test_p: Optional[float] = None
    verdict: str = "insufficient"

    def as_dict(self) -> Dict[str, object]:
        return {
            "n": self.n,
            "n_independent": self.n_independent,
            "reportable": self.reportable,
            "win_rate": self.win_rate,
            "win_rate_interval": self.win_rate_interval.as_dict(),
            "median": self.median,
            "median_interval": self.median_interval.as_dict(),
            "mean": self.mean,
            "trimmed_mean": self.trimmed_mean,
            "q1": self.q1,
            "q3": self.q3,
            "best": self.best,
            "worst": self.worst,
            "mean_without_best": self.mean_without_best,
            "concentration": self.concentration,
            "sign_test_p": self.sign_test_p,
            "verdict": self.verdict,
        }


def summarise(
    values: Sequence[float],
    *,
    clusters: Optional[Sequence[object]] = None,
) -> CohortSummary:
    """Describe one cohort.

    ``clusters`` names what each observation belongs to, normally the ticker.
    Two earnings from the same company are not two independent tries, so the
    sign test counts distinct clusters rather than rows.
    """
    numbers = [float(value) for value in values]
    n = len(numbers)
    if clusters is not None and len(clusters) != n:
        raise ValueError("clusters must line up with values")
    independent = len(set(clusters)) if clusters is not None else n
    if n < MIN_REPORTABLE:
        return CohortSummary(n=n, n_independent=independent, reportable=False)

    ordered = sorted(numbers)
    wins = sum(1 for value in ordered if value > 0)
    mean = sum(ordered) / n
    quarters = quantiles(ordered, n=4)
    trim = floor(n * TRIM_FRACTION)
    trimmed = ordered[trim: n - trim] or ordered

    summary = CohortSummary(
        n=n,
        n_independent=independent,
        reportable=True,
        win_rate=wins / n,
        win_rate_interval=clopper_pearson(wins, n),
        median=_median(ordered),
        median_interval=median_interval(ordered),
        mean=mean,
        trimmed_mean=sum(trimmed) / len(trimmed),
        q1=quarters[0],
        q3=quarters[2],
        best=ordered[-1],
        worst=ordered[0],
        mean_without_best=sum(ordered[:-1]) / (n - 1),
        concentration=concentration(ordered),
        sign_test_p=sign_test(ordered, independent),
    )
    return replace(summary, verdict=_verdict(summary))


def concentration(ordered: Sequence[float]) -> Optional[float]:
    """How many observations' worth of the spread the largest one carries.

    One means the biggest mover pulls no harder than its turn. The ceiling is
    n/2, reached when a single name accounts for everything and the rest sit
    still, so the figure is read against the cohort size rather than against a
    fixed number.
    """
    n = len(ordered)
    if n < 2:
        return None
    mean = sum(ordered) / n
    spread = sum(abs(value - mean) for value in ordered)
    if spread == 0:
        return 1.0
    largest = max(abs(value - mean) for value in ordered)
    return round(largest / spread * n, 4)


def _verdict(summary: CohortSummary) -> str:
    """Name what the numbers support, so a table can be read at a glance.

    `tail_driven` is not a claim that the cohort is wrong. It says the average
    and the typical member disagree, so whichever one gets quoted decides the
    conclusion.
    """
    mean = summary.mean
    median = summary.median
    if mean is None or median is None:
        return "no_signal"
    # The average and the middle pointing opposite ways, or the average
    # changing sign when the single largest name leaves, both mean the headline
    # rests on the tail rather than on the group.
    opposed = median != 0 and (median > 0) != (mean > 0)
    without_best = summary.mean_without_best
    flips = (
        without_best is not None
        and mean != 0
        and without_best != 0
        and (mean > 0) != (without_best > 0)
    )
    if opposed or flips:
        return "tail_driven"
    if summary.sign_test_p is not None and summary.sign_test_p < 0.05:
        return "directional"
    return "no_signal"


def sign_test(values: Sequence[float], n_independent: Optional[int] = None) -> Optional[float]:
    """Two-sided exact binomial probability of this many winners by chance.

    Ties at exactly zero carry no direction and are dropped, the usual
    treatment, which keeps a cohort of flat outcomes from looking decisive.
    """
    directional = [value for value in values if value != 0]
    observed = len(directional)
    if observed == 0:
        return None
    n = observed
    if n_independent is not None:
        # Repeated names inflate the count. Scaling down keeps the test from
        # claiming more evidence than the number of distinct bets supports.
        n = min(observed, max(1, n_independent))
    wins = round(sum(1 for value in directional if value > 0) * n / observed)
    return _binomial_two_sided(wins, n)


def _binomial_two_sided(successes: int, n: int) -> float:
    probabilities = [comb(n, k) * 0.5 ** n for k in range(n + 1)]
    observed = probabilities[successes]
    return round(min(1.0, sum(p for p in probabilities if p <= observed * (1 + 1e-9))), 6)


def clopper_pearson(successes: int, n: int, confidence: float = CONFIDENCE) -> Interval:
    """Exact interval for a proportion, found by inverting the binomial test."""
    if n == 0:
        return Interval(None, None)
    alpha = 1 - confidence
    low = 0.0
    high = 1.0
    if successes > 0:
        low = _invert(lambda p: _upper_tail(successes, n, p), alpha / 2, rising=True)
    if successes < n:
        high = _invert(lambda p: _lower_tail(successes, n, p), alpha / 2, rising=False)
    return Interval(round(low, 6), round(high, 6))


def _upper_tail(successes: int, n: int, p: float) -> float:
    return sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(successes, n + 1))


def _lower_tail(successes: int, n: int, p: float) -> float:
    return sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(0, successes + 1))


def _invert(tail: Callable[[float], float], target: float, *, rising: bool) -> float:
    """Bisect for the proportion at which the binomial tail reaches ``target``."""
    low, high = 0.0, 1.0
    for _step in range(80):
        middle = (low + high) / 2
        if (tail(middle) < target) == rising:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def median_interval(ordered: Sequence[float], confidence: float = CONFIDENCE) -> Interval:
    """Distribution-free interval built from order statistics.

    The rank whose cumulative binomial probability first passes the tail gives
    a bound that holds for any continuous distribution, which matters because
    returns are nothing like normal.
    """
    n = len(ordered)
    if n < MIN_REPORTABLE:
        return Interval(None, None)
    alpha = 1 - confidence
    cumulative = 0.0
    lower_rank = None
    for k in range(n):
        cumulative += comb(n, k) * 0.5 ** n
        if cumulative > alpha / 2:
            lower_rank = k
            break
    if lower_rank is None:
        return Interval(None, None)
    upper_rank = n - 1 - lower_rank
    if lower_rank > upper_rank:
        return Interval(None, None)
    return Interval(ordered[lower_rank], ordered[upper_rank])


def adjust_for_multiplicity(
    p_values: Dict[str, Optional[float]]
) -> Dict[str, Optional[float]]:
    """Benjamini-Hochberg across one family of comparisons.

    A report that shows thirty cohorts will show one or two under p<0.05 with
    nothing behind them. Presenting each in isolation invites reading whichever
    happened to clear the line, so the family is corrected together.
    """
    named: List[Tuple[str, float]] = [
        (name, value) for name, value in p_values.items() if value is not None
    ]
    adjusted: Dict[str, Optional[float]] = {name: None for name in p_values}
    if not named:
        return adjusted
    named.sort(key=lambda item: item[1])
    total = len(named)
    running = 1.0
    for index in range(total - 1, -1, -1):
        name, value = named[index]
        running = min(running, value * total / (index + 1), 1.0)
        adjusted[name] = round(running, 6)
    return adjusted
