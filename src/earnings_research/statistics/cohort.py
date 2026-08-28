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
from math import comb, exp, floor, fsum, lgamma, log, log1p
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
    # Outcomes that went neither way. Held out of the win rate rather than
    # counted against it.
    ties: int = 0
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
    # The other end. Removing only the largest name catches a cohort carried by
    # one winner and misses the mirror image entirely: ninety-nine names at
    # -0.1% with one at -150% reports a mean sixteen times the typical member
    # and, with only the top removed, nothing objects.
    mean_without_worst: Optional[float] = None
    concentration: Optional[float] = None
    # Reported beside it because the figure alone is unreadable: 9.4 is 57% of
    # the ceiling at n=33 and 12% of it at n=163.
    concentration_ceiling: Optional[float] = None
    # What share of the reported mean comes from the observations the trim
    # removes. Above a half the headline is the tail's, not the group's.
    tail_share: Optional[float] = None
    tail_direction: Optional[str] = None
    sign_test_p: Optional[float] = None
    # Names that actually voted. Fewer than n_independent whenever a name's own
    # rows cancel, which is the denominator the p-value was computed on.
    n_directional: int = 0
    verdict: str = "insufficient"

    def as_dict(self) -> Dict[str, object]:
        return {
            "n": self.n,
            "n_independent": self.n_independent,
            "reportable": self.reportable,
            "ties": self.ties,
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
            "mean_without_worst": self.mean_without_worst,
            "concentration": self.concentration,
            "concentration_ceiling": self.concentration_ceiling,
            "tail_share": self.tail_share,
            "tail_direction": self.tail_direction,
            "sign_test_p": self.sign_test_p,
            "n_directional": self.n_directional,
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
    if any(value != value or value in (float("inf"), float("-inf")) for value in numbers):
        # An infinity makes every comparison below meaningless while the
        # summary still reads as a finding, and a NaN quietly unsorts the list
        # so the median and the interval stop being what they say they are.
        raise ValueError("a cohort cannot contain infinite or undefined returns")
    n = len(numbers)
    if clusters is not None and len(clusters) != n:
        raise ValueError("clusters must line up with values")
    independent = len(set(clusters)) if clusters is not None else n
    if n < MIN_REPORTABLE:
        return CohortSummary(n=n, n_independent=independent, reportable=False)

    ordered = sorted(numbers)
    p_value, votes = sign_test(numbers, clusters)
    # The intervals speak about a population, and repeated appearances of one
    # company are not repeated draws from it. Built on rows, their measured
    # coverage falls to 62% when eight earnings share a name; built on one
    # value per name they stay at the level they claim. The point estimates
    # above stay row-level, because those describe the sample rather than
    # infer from it.
    per_name = _by_cluster(numbers, clusters)
    # A flat outcome is not a loss. Counting it as one made a cohort of twenty
    # unchanged prices report a win rate of zero, which reads as twenty losses,
    # while the sign test beside it dropped the same rows as directionless. The
    # two now use one convention.
    ties = sum(1 for value in ordered if value == 0)
    decided = n - ties
    wins = sum(1 for value in ordered if value > 0)
    name_ties = sum(1 for value in per_name if value == 0)
    name_wins = sum(1 for value in per_name if value > 0)
    mean = sum(ordered) / n
    quarters = quantiles(ordered, n=4)
    # A tenth of nine rounds to nothing, so below ten the trimmed mean was the
    # mean under another name — exactly where one name carries a cohort most
    # easily, the protection switched itself off. At least one observation
    # comes off each end, which at n=5 leaves the middle three.
    trim = max(1, floor(n * TRIM_FRACTION))
    trimmed = ordered[trim: n - trim] or ordered
    trimmed_mean = sum(trimmed) / len(trimmed)
    without_best = sum(ordered[:-1]) / (n - 1)
    without_worst = sum(ordered[1:]) / (n - 1)

    summary = CohortSummary(
        n=n,
        n_independent=independent,
        reportable=True,
        ties=ties,
        win_rate=wins / decided if decided else None,
        win_rate_interval=(
            clopper_pearson(name_wins, len(per_name) - name_ties)
            if len(per_name) - name_ties
            else Interval(None, None)
        ),
        median=_median(ordered),
        median_interval=median_interval(per_name),
        mean=mean,
        trimmed_mean=trimmed_mean,
        q1=quarters[0],
        q3=quarters[2],
        best=ordered[-1],
        worst=ordered[0],
        mean_without_best=without_best,
        mean_without_worst=without_worst,
        concentration=concentration(ordered),
        concentration_ceiling=n / 2,
        tail_share=tail_share(mean, trimmed_mean),
        tail_direction=_tail_direction(mean, without_best, without_worst),
        # Ordered values would break the pairing with clusters.
        sign_test_p=p_value,
        n_directional=votes,
    )
    return replace(summary, verdict=_verdict(summary))


def concentration(ordered: Sequence[float]) -> Optional[float]:
    """How many observations' worth of the spread the largest one carries.

    One means the biggest mover pulls no harder than its turn.

    The ceiling is n/2, but it does not mean what it looks like it means.
    Deviations sum to zero, so the positive ones total exactly half the spread;
    any observation sitting alone on one side of the mean therefore carries
    that half by itself and reads n/2. That happens for a cohort carried
    entirely by one name, and equally for ninety-nine names at +1.00% with one
    at +1.01%. Both measure 50.0 at n=100. So this figure says how lopsided the
    spread is, not whether the result rests on one name — read it beside
    ``tail_share``, which answers the second question.
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


def tail_share(mean: Optional[float], trimmed_mean: Optional[float]) -> Optional[float]:
    """What fraction of the reported mean comes from the trimmed-off ends.

    Zero means the middle of the cohort accounts for the whole headline. One
    means the middle accounts for none of it. Above one the ends are not only
    carrying the mean, they are carrying it against the middle's direction.
    """
    if mean is None or trimmed_mean is None:
        return None
    if mean == 0:
        # The ends cancel the middle exactly. Nothing is left to attribute to
        # the group, so the headline is entirely the ends' doing.
        return 0.0 if trimmed_mean == 0 else 1.0
    return round(1 - trimmed_mean / mean, 4)


def _tail_direction(mean, without_best, without_worst) -> Optional[str]:
    """Which end is carrying the mean, so two opposite cases stay distinct.

    A cohort of losers lifted by one winner and a cohort of winners dragged by
    one loser both fail the same test, and the reader has to do opposite things
    about them.
    """
    if None in (mean, without_best, without_worst):
        return None
    if abs(mean - without_best) == abs(mean - without_worst):
        return None
    return "up" if abs(mean - without_best) > abs(mean - without_worst) else "down"


def _by_cluster(values, clusters):
    """One value per name: its own median, or the rows themselves if unnamed."""
    if clusters is None:
        return sorted(float(value) for value in values)
    grouped: Dict[object, List[float]] = {}
    for value, cluster in zip(values, clusters):
        grouped.setdefault(cluster, []).append(float(value))
    return sorted(_median(sorted(group)) for group in grouped.values())


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def verdict_for(
    mean: Optional[float],
    median: Optional[float],
    mean_without_best: Optional[float],
    p_value: Optional[float],
    *,
    trimmed_mean: Optional[float],
    mean_without_worst: Optional[float],
) -> str:
    """Name what the numbers support, so a table can be read at a glance.

    `tail_driven` is not a claim that the cohort is wrong. It says the average
    and the typical member disagree, so whichever one gets quoted decides the
    conclusion.

    The sign tests alone were not enough. They caught the cohort of losers
    carried by one winner only because its median came out negative; nudge the
    crowd to +0.01%, below what it costs to trade, and the same single name
    carrying the whole result reported `directional`. Two large names defeated
    the check outright, since only one is ever removed. What both cases have in
    common is not a sign but a magnitude: the mean is a multiple of what the
    middle of the cohort earns. `tail_share` measures that directly, and above
    a half the headline belongs to the ends rather than to the group.

    Takes the p-value as an argument rather than reading it off the summary, so
    the caller that holds the corrected value can recompute the verdict with it.
    A verdict left on the raw p-value would keep saying `directional` for
    cohorts the correction has already dismissed, which is the whole point of
    correcting.
    """
    if mean is None or median is None:
        return "not_tested"
    # The average and the middle pointing opposite ways, or the average
    # changing sign when a single name leaves either end, both mean the
    # headline rests on the tail rather than on the group.
    opposed = _sign(median) != 0 and _sign(median) != _sign(mean)
    flips = any(
        end is not None and _sign(end) != 0 and _sign(mean) != 0 and _sign(end) != _sign(mean)
        for end in (mean_without_best, mean_without_worst)
    )
    share = tail_share(mean, trimmed_mean)
    carried = share is not None and share > 0.5
    if opposed or flips or carried:
        return "tail_driven"
    if p_value is None:
        # No test was run — the descriptive views have their p-values stripped.
        # Saying `no_signal` there would report an absence of evidence that
        # nobody went looking for.
        return "not_tested"
    if p_value < 1 - CONFIDENCE:
        return "directional"
    return "no_signal"


def _verdict(summary: CohortSummary) -> str:
    return verdict_for(
        summary.mean,
        summary.median,
        summary.mean_without_best,
        summary.sign_test_p,
        trimmed_mean=summary.trimmed_mean,
        mean_without_worst=summary.mean_without_worst,
    )


@dataclass(frozen=True)
class TailCapture:
    """Whether a cohort caught the large moves, and whether that is telling.

    For fat-tailed outcomes this often matters more than the middle. A cohort
    whose median sits at zero is still worth holding if it contains the +40%
    names at better than the base rate, and a cohort with a tidy median is not
    if it never catches one.
    """

    threshold: float
    n: int
    hits: int
    rate: Optional[float]
    interval: Interval
    base_rate: Optional[float]
    lift: Optional[float]
    distinguishable: bool
    p_value: Optional[float] = None
    # Which way it differs. Without this a cohort that caught none of the large
    # moves reports exactly what a cohort that caught all of them reports.
    direction: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "threshold": self.threshold,
            "n": self.n,
            "hits": self.hits,
            "rate": self.rate,
            "interval": self.interval.as_dict(),
            "base_rate": self.base_rate,
            "lift": self.lift,
            "distinguishable": self.distinguishable,
            "direction": self.direction,
            "p_value": self.p_value,
        }


def tail_capture(
    values: Sequence[float],
    threshold: float,
    base_rate: Optional[float] = None,
    *,
    comparison: Optional[Sequence[float]] = None,
) -> TailCapture:
    """How often this cohort reached ``threshold``, against the base rate.

    The lift on its own invites reading noise: one hit out of twelve is 1.7x
    the base rate and means nothing. ``distinguishable`` is the figure to read,
    and it is true only when the exact interval clears the base rate entirely.
    """
    if comparison is not None:
        base_rate = globals()["base_rate"](comparison, threshold)
    n = len(values)
    if n < MIN_REPORTABLE:
        # The same floor the rest of the summary keeps. Without it thirteen of
        # the fifteen cohorts calling themselves distinguishable had fewer than
        # five observations and nine had exactly one, which reads as a finding
        # and is a single company's single quarter.
        return TailCapture(threshold, n, 0, None, Interval(None, None), base_rate, None, False)
    hits = sum(1 for value in values if value >= threshold)
    rate = hits / n
    interval = clopper_pearson(hits, n)
    lift = None
    distinguishable = False
    direction = None
    if base_rate is not None:
        lift = round(rate / base_rate, 4) if base_rate > 0 else None
        distinguishable = (
            interval.low is not None
            and interval.high is not None
            and (interval.low > base_rate or interval.high < base_rate)
        )
        if distinguishable:
            direction = "above" if interval.low > base_rate else "below"
    return TailCapture(
        threshold=threshold,
        n=n,
        hits=hits,
        rate=rate,
        interval=interval,
        base_rate=base_rate,
        lift=lift,
        distinguishable=distinguishable,
        direction=direction,
        p_value=(
            fisher_exact(
                hits,
                n,
                sum(1 for value in comparison if value >= threshold),
                len(comparison),
            )
            if comparison is not None
            else (binomial_against(hits, n, base_rate) if base_rate is not None else None)
        ),
    )


def binomial_against(successes: int, n: int, probability: float) -> Optional[float]:
    """Exact two-sided probability of this many hits at the base rate.

    A lift needs this beside it. Fifteen reason codes each showing a lift will
    always contain a three-times one, and without a p-value entering the
    multiplicity correction there is nothing to stop it being quoted.
    """
    if n == 0 or probability is None or not 0 <= probability <= 1:
        return None
    if probability == 0:
        # Nothing in the comparison population ever got there. Any hit at all
        # has probability zero under that null, and no hits is the certain
        # outcome. Returning None here instead lost the strongest evidence the
        # measure can produce, and it becomes reachable the moment the base
        # rate stops including the cohort itself.
        return 0.0 if successes > 0 else 1.0
    if probability == 1:
        return 1.0 if successes == n else 0.0
    probabilities = [_binomial_range(n, probability, k, k) for k in range(n + 1)]
    observed = probabilities[successes]
    return _round_p(min(1.0, fsum(p for p in probabilities if p <= observed * (1 + 1e-9))))


def _round_p(value: float) -> float:
    """Six decimals, except never all the way down to zero.

    A p-value of 1e-53 rounded to six places is 0.0, which claims a certainty
    no finite sample can produce and propagates through the correction as one.
    """
    rounded = round(value, 6)
    if rounded == 0 and value > 0:
        return float("%.3g" % value)
    return rounded


def fisher_exact(hits: int, n: int, other_hits: int, other_n: int) -> Optional[float]:
    """Two-sided exact test of a cohort against the rest of the record.

    The binomial test this replaces asked whether the cohort's count was
    surprising under a base rate treated as known. It is not known — it is
    estimated from the other rows — and where those rows happened never to
    reach the threshold the base rate came out at exactly zero, under which any
    hit at all has probability zero. Two cohorts shipped a p-value of 0.0 and
    survived the correction on it.

    Conditioning on the observed margins asks the question that is actually
    being asked, which is whether the hits fall disproportionately inside the
    cohort. The same two cohorts move to 0.0033 and 0.072, and neither survives
    its family.
    """
    total = n + other_n
    if n == 0 or other_n == 0:
        return None
    successes = hits + other_hits
    def probability(k: int) -> float:
        return comb(n, k) * comb(other_n, successes - k) / comb(total, successes)

    observed = probability(hits)
    lowest = max(0, successes - other_n)
    highest = min(n, successes)
    return _round_p(
        min(
            1.0,
            fsum(
                probability(k)
                for k in range(lowest, highest + 1)
                if probability(k) <= observed * (1 + 1e-9)
            ),
        )
    )


def base_rate(values: Sequence[float], threshold: float) -> Optional[float]:
    """Share of the comparison population that reached ``threshold``.

    None means there was no population to compare against. Zero means there was
    one and it never got there, which is a much stronger statement and has to
    stay distinguishable from the first.
    """
    if not values:
        return None
    return sum(1 for value in values if value >= threshold) / len(values)


def sign_test(
    values: Sequence[float],
    clusters: Optional[Sequence[object]] = None,
) -> Tuple[Optional[float], int]:
    """Two-sided exact binomial probability of this many winners by chance.

    Returns the p-value and the number of names that actually voted. Those are
    two different numbers from the count of names present, and the second is
    the one a reader dividing the evidence needs: a cohort reporting six
    independent names can be resting on five votes, because a name whose own
    rows cancel has no direction to contribute.

    Each name gets one vote, decided by which way more of its own rows went.
    Using the name's median instead let magnitude decide: a two-row name
    holding -0.1% and +80% voted up, and the same name holding -80% and +0.1%
    voted down, on identical signs. It was discontinuous too — moving a single
    row 1e-7 across zero took a cohort from p=0.0625 to p=0.03125, in either
    direction.

    Rescaling the row count instead — twenty wins out of twenty-five becoming
    five out of six — keeps whichever name appeared most often in charge of the
    answer. One company appearing twenty times with the other five going the
    other way reads as five names winning when one did.

    Ties carry no direction and are dropped, which keeps a cohort of flat
    outcomes from looking decisive.
    """
    if clusters is None:
        directions = [_sign(float(value)) for value in values]
    else:
        grouped: Dict[object, List[float]] = {}
        for value, cluster in zip(values, clusters):
            grouped.setdefault(cluster, []).append(float(value))
        directions = [
            _sign(
                sum(1 for value in group if value > 0)
                - sum(1 for value in group if value < 0)
            )
            for group in grouped.values()
        ]
    directional = [value for value in directions if value != 0]
    if not directional:
        return None, 0
    wins = sum(1 for value in directional if value > 0)
    return _binomial_two_sided(wins, len(directional)), len(directional)


def _binomial_two_sided(successes: int, n: int) -> float:
    """Exact two-sided probability of this split under an even coin.

    Summed as whole binomial coefficients and divided once at the end: the
    per-term form stopped fitting in a float at n=1030 and raised OverflowError
    out of a cohort large enough to be a whole market.
    """
    weights = [comb(n, k) for k in range(n + 1)]
    observed = weights[successes]
    return _round_p(min(1.0, sum(w for w in weights if w <= observed) / 2 ** n))


def clopper_pearson(successes: int, n: int, confidence: float = CONFIDENCE) -> Interval:
    """Exact interval for a proportion, found by inverting the binomial test."""
    if n == 0:
        return Interval(None, None)
    if not 0 <= successes <= n:
        raise ValueError("successes must sit between 0 and n")
    if not 0 < confidence < 1:
        # A confidence outside the unit interval returned a plausible-looking
        # interval with its bounds the wrong way round.
        raise ValueError("confidence must sit between 0 and 1")
    alpha = 1 - confidence
    low = 0.0
    high = 1.0
    if successes > 0:
        low = _invert(lambda p: _upper_tail(successes, n, p), alpha / 2, rising=True)
    if successes < n:
        high = _invert(lambda p: _lower_tail(successes, n, p), alpha / 2, rising=False)
    return Interval(round(low, 6), round(high, 6))


def _binomial_range(n: int, p: float, first: int, last: int) -> float:
    """Sum the binomial mass from ``first`` to ``last`` inclusive.

    In log space, because the direct form multiplies an exact integer binomial
    coefficient by a float and comb(1030, 515) is a 309-digit number that no
    longer fits: every cohort of a thousand or more rows raised OverflowError
    out of a public function, except the all-win and all-lose cases, which took
    a different branch. Several years of quarterly events reach that size. The
    values agree to the last bit with the direct form and it is thirty-five
    times faster.
    """
    if p <= 0.0:
        return 1.0 if first <= 0 <= last else 0.0
    if p >= 1.0:
        return 1.0 if first <= n <= last else 0.0
    log_p, log_q = log(p), log1p(-p)
    return fsum(
        exp(lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1) + k * log_p + (n - k) * log_q)
        for k in range(first, last + 1)
    )


def _upper_tail(successes: int, n: int, p: float) -> float:
    return _binomial_range(n, p, successes, n)


def _lower_tail(successes: int, n: int, p: float) -> float:
    return _binomial_range(n, p, 0, successes)


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

    The bound is the last rank whose cumulative binomial tail still fits inside
    alpha/2 — not the first rank that passes it, which would spend more of the
    tail than the interval is allowed and undercover at every size. It holds
    for any continuous distribution, which matters because returns are nothing
    like normal.
    """
    # Only the argument name enforced the ordering. Reversed input returned
    # low > high, and excludes_zero() reads that as a cohort asserting a
    # direction. Sorting costs nothing the caller has not already paid.
    ordered = sorted(ordered)
    n = len(ordered)
    if n < MIN_REPORTABLE:
        return Interval(None, None)
    alpha = 1 - confidence
    cumulative = 0.0
    lower_rank = None
    for k in range(n):
        # The rank is the last one whose cumulative tail still fits inside
        # alpha/2. Taking the first rank that exceeds it spends more of the
        # tail than the interval is allowed and undercovers at every size.
        # comb(n, k) * 0.5 ** n raises OverflowError from n=1033: the
        # binomial coefficient stops fitting in a float long before the
        # quotient does. Dividing two ints keeps the exact numerator.
        tail = cumulative + comb(n, k) / 2 ** n
        if tail > alpha / 2:
            break
        cumulative = tail
        lower_rank = k
    if lower_rank is None:
        # No rank leaves enough room; at this size the level cannot be met.
        return Interval(None, None)
    upper_rank = n - 1 - lower_rank
    if lower_rank >= upper_rank:
        # Equal ranks give a single point, whose true coverage is zero. Out of
        # reach at 95%, reachable at lower confidence, which is a public
        # argument.
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
