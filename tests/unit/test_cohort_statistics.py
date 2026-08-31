import pytest

from earnings_research.statistics.cohort import (
    MIN_REPORTABLE,
    Interval,
    adjust_for_multiplicity,
    base_rate,
    binomial_against,
    clopper_pearson,
    concentration,
    fisher_exact,
    median_interval,
    sign_test,
    summarise,
    tail_capture,
    verdict_for,
)
from earnings_research.statistics.lookahead import contamination, sound_fields

# One name limit-up for three days beside thirty-nine that went nowhere.
CARRIED_BY_ONE = [0.80] + [-0.005] * 39
# The same average reached by the whole group drifting up together.
MOVED_TOGETHER = [0.02] * 20 + [0.01] * 20


def test_a_mean_cannot_tell_these_two_cohorts_apart():
    carried = summarise(CARRIED_BY_ONE)
    together = summarise(MOVED_TOGETHER)
    assert round(carried.mean, 3) == round(together.mean, 3) == 0.015


def test_but_the_win_rate_and_the_median_can():
    carried = summarise(CARRIED_BY_ONE)
    together = summarise(MOVED_TOGETHER)
    assert carried.win_rate < 0.05 and carried.median < 0
    assert together.win_rate == 1.0 and together.median > 0
    assert carried.verdict == "tail_driven"
    assert together.verdict == "directional"


def test_dropping_the_largest_name_is_what_decides_tail_driven():
    """Not a guessed concentration threshold: does the conclusion survive?"""
    values = [0.30] + [-0.004] * 20
    summary = summarise(values)
    assert summary.mean > 0
    assert summary.mean_without_best < 0
    assert summary.verdict == "tail_driven"


def test_a_cohort_that_survives_losing_its_best_name_is_not_flagged():
    values = [0.30] + [0.02] * 20
    summary = summarise(values)
    assert summary.mean_without_best > 0
    assert summary.verdict != "tail_driven"


@pytest.mark.parametrize("size", range(MIN_REPORTABLE))
def test_a_handful_of_observations_reports_its_size_and_nothing_else(size):
    summary = summarise([0.01] * size)
    assert summary.reportable is False
    assert summary.median is None and summary.win_rate is None


def test_repeated_names_are_not_repeated_evidence():
    """Six earnings from two companies are not six independent tries."""
    values = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    distinct = summarise(values, clusters=list("ABCDEF"))
    repeated = summarise(values, clusters=["A", "A", "A", "B", "B", "B"])
    assert repeated.n_independent == 2
    assert repeated.sign_test_p > distinct.sign_test_p


def test_one_name_appearing_often_does_not_decide_the_test():
    """Twenty rows from one company against five other companies going the
    other way: one name won, not five."""
    values = [0.01] * 20 + [-0.01] * 5
    clusters = ["SAME"] * 20 + list("BCDEF")
    summary = summarise(values, clusters=clusters)
    assert summary.win_rate == 0.8  # rows
    # Aggregating each name to its own median leaves one winner out of six, so
    # the test cannot read the repeated name as a majority.
    assert summary.sign_test_p == sign_test([-0.01] * 5 + [0.01])[0]


def test_a_name_votes_by_its_own_middle():
    # A's median is negative even though its best row is not.
    values = [0.05, -0.01, -0.01] + [0.02, 0.03, 0.04]
    clusters = ["A", "A", "A", "B", "C", "D"]
    assert summarise(values, clusters=clusters).sign_test_p == sign_test([-0.01, 0.02, 0.03, 0.04])[0]


def test_the_sign_test_pairs_values_with_their_own_cluster():
    """Sorting the values before the test would scramble the pairing."""
    values = [0.05, -0.02, 0.04, -0.03, 0.06, -0.04]
    clusters = ["A", "B", "A", "B", "A", "B"]
    # A is entirely positive and B entirely negative; scrambling the pairing
    # would mix them and change the vote.
    assert summarise(values, clusters=clusters).sign_test_p == sign_test([0.05, -0.03])[0]


def test_clusters_must_line_up_with_values():
    with pytest.raises(ValueError, match="line up"):
        summarise([0.01, 0.02], clusters=["A"])


def test_flat_outcomes_do_not_look_decisive():
    """Zeroes carry no direction, so they are dropped rather than counted."""
    assert sign_test([0.0] * 20) == (None, 0)
    assert sign_test([0.01, 0.0, 0.0, 0.0, 0.0]) == sign_test([0.01])


@pytest.mark.parametrize(
    "successes,n,contains_half",
    [(5, 10, True), (9, 10, False), (50, 100, True), (70, 100, False)],
)
def test_the_win_rate_interval_says_whether_a_coin_would_do(successes, n, contains_half):
    interval = clopper_pearson(successes, n)
    assert (interval.low <= 0.5 <= interval.high) is contains_half


def test_the_win_rate_interval_is_exact_at_the_edges():
    assert clopper_pearson(0, 20).low == 0.0
    assert clopper_pearson(20, 20).high == 1.0


def test_the_median_interval_is_made_of_observed_values():
    """Order statistics, so the bound is a return that actually happened."""
    values = sorted([0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07])
    interval = median_interval(values)
    assert interval.low in values and interval.high in values


def test_the_median_interval_narrows_as_observations_accumulate():
    """Same spread of outcomes, more of them: the middle is pinned down."""
    few = [0.01 * i for i in range(8)]
    many = [0.07 * i / 59 for i in range(60)]  # same 0 to 0.07 range
    assert max(few) == pytest.approx(max(many))
    tight = median_interval(sorted(many))
    loose = median_interval(sorted(few))
    assert (tight.high - tight.low) < (loose.high - loose.low)


def test_concentration_is_one_when_every_move_is_the_same_size():
    assert concentration([0.01, -0.01, 0.01, -0.01]) == 1.0


def test_concentration_does_not_change_when_everything_is_scaled():
    """It reports shape, so a cohort in percent reads the same as in basis points."""
    values = [0.05, 0.01, -0.02, 0.03, -0.01]
    assert concentration(values) == concentration([v * 100 for v in values])


# Nineteen ordinary outcomes with ordinary variation between them.
CROWD = [0.005, 0.008, 0.010, 0.012, 0.015] * 3 + [0.009, 0.011, 0.013, 0.007]


def test_concentration_grows_as_one_name_pulls_away_from_the_rest():
    measured = [concentration(CROWD + [outlier]) for outlier in (0.010, 0.02, 0.05)]
    assert measured == sorted(measured) and measured[0] < measured[-1]


@pytest.mark.parametrize("size", [6, 20, 50])
def test_concentration_tops_out_at_half_the_cohort(size):
    """One name accounting for everything is the most it can say."""
    everything = [1000.0] + [0.0] * (size - 1)
    assert concentration(everything) == pytest.approx(size / 2)


def test_concentration_saturates_rather_than_running_away():
    """Past a point a larger outlier says nothing more, so the ceiling is n/2."""
    huge = concentration(CROWD + [1.0])
    vast = concentration(CROWD + [100.0])
    assert huge == vast == pytest.approx(len(CROWD + [1.0]) / 2)


def test_thirty_cohorts_will_always_show_one_under_five_percent():
    """Which is why the family is corrected rather than read one at a time."""
    raw = {"c%d" % i: 0.04 + i * 0.03 for i in range(30)}
    adjusted = adjust_for_multiplicity(raw)
    assert raw["c0"] < 0.05
    assert adjusted["c0"] > 0.05


def test_multiplicity_correction_never_lowers_a_p_value():
    raw = {"a": 0.001, "b": 0.02, "c": 0.5}
    adjusted = adjust_for_multiplicity(raw)
    assert all(adjusted[name] >= raw[name] for name in raw)


def test_multiplicity_correction_keeps_the_ordering():
    raw = {"a": 0.001, "b": 0.02, "c": 0.5, "d": 0.9}
    adjusted = adjust_for_multiplicity(raw)
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"] <= adjusted["d"]


def test_a_cohort_with_no_testable_outcome_carries_no_adjusted_value():
    assert adjust_for_multiplicity({"a": None}) == {"a": None}


@pytest.mark.parametrize("field", ["gap", "ret_d1", "ret_d5", "ret_d20"])
def test_a_gap_cohort_may_not_be_scored_on_a_previous_close_return(field):
    """The split is inside the result, so the answer is arithmetic."""
    assert contamination("shodo", field) is not None


@pytest.mark.parametrize("field", ["open_d1", "open_d5", "open_d20"])
def test_a_gap_cohort_may_be_scored_from_the_opening_price(field):
    assert contamination("shodo", field) is None


@pytest.mark.parametrize("field", ["ret_d5", "open_d5", "open_d20"])
def test_a_reaction_cohort_is_contaminated_one_level_deeper(field):
    """It splits on the first day's own move, so the open is inside it too."""
    assert contamination("reaction", field) is not None


@pytest.mark.parametrize("field", ["close_d5", "close_d20"])
def test_a_reaction_cohort_is_scored_from_the_close_it_was_read_at(field):
    assert contamination("reaction", field) is None


def test_an_unrecognised_cohort_is_not_silently_blessed_or_blocked():
    assert contamination("some_new_split", "ret_d5") is None
    assert sound_fields("some_new_split", ["ret_d5", "open_d5"]) == ["ret_d5", "open_d5"]


def test_a_label_decided_after_the_close_cannot_be_scored_from_it():
    """The judgement fields, which the first pass of this table missed.

    They are not arithmetically inside the return the way a gap is. They simply
    did not exist yet: across 254 records every rank, narrative and reason code
    was committed after 15:00 JST, one memo quotes an after-hours PTS move, and
    there is a pts_negative reason code. prev_close is that afternoon's close.
    """
    for cohort in ("rank", "narrative", "reason_code", "judge", "surprise"):
        for field in ("gap", "ret_d1", "ret_d5", "ret_d20"):
            assert contamination(cohort, field) is not None
        for field in ("open_d1", "open_d5", "open_d20", "close_d5", "close_d20"):
            assert contamination(cohort, field) is None


def test_an_outcome_field_with_no_declared_anchor_is_refused():
    """Adding a return and forgetting the table reproduces the original bug.

    Silently: a ret_d60 measured from prev_close restores gap-up at 74%
    positive and gap-down at 24% — the numbers this module exists to withhold —
    while the sound field beside it says the opposite.
    """
    assert contamination("shodo", "ret_d60") is not None
    assert sound_fields("shodo", ["ret_d60", "open_d5"]) == ["open_d5"]


def test_every_reported_return_declares_the_price_it_is_measured_from():
    from earnings_research.legacy_research.aggregation import RETURN_FIELDS
    from earnings_research.statistics.lookahead import RETURN_ANCHOR

    assert set(RETURN_FIELDS) <= set(RETURN_ANCHOR)


def test_sound_fields_drops_only_the_circular_ones():
    assert sound_fields("shodo", ["gap", "ret_d5", "open_d5"]) == ["open_d5"]


# --- 大幅上昇を捕まえられたか -------------------------------------------------

def test_a_flat_median_cohort_can_still_be_the_one_holding_the_big_moves():
    """Which is the whole reason this is measured separately from the middle."""
    flat_but_catches = [0.40, 0.35] + [-0.002] * 18
    tidy_but_never = [0.01] * 20
    assert summarise(flat_but_catches).median < summarise(tidy_but_never).median
    assert tail_capture(flat_but_catches, 0.10, 0.05).hits == 2
    assert tail_capture(tidy_but_never, 0.10, 0.05).hits == 0


def test_a_lift_on_its_own_is_not_read_as_a_finding():
    """One hit in twelve is 1.7x the base rate and means nothing."""
    capture = tail_capture([0.15] + [0.0] * 11, 0.10, 0.05)
    assert capture.lift > 1.5
    assert capture.distinguishable is False
    assert capture.p_value > 0.05


def test_a_rate_clear_of_the_base_rate_is_distinguishable():
    capture = tail_capture([0.15] * 12 + [0.0] * 8, 0.10, 0.05)
    assert capture.interval.low > 0.05
    assert capture.distinguishable is True
    assert capture.p_value < 0.05


def test_the_threshold_is_inclusive():
    assert tail_capture([0.10, 0.0999, 0.0, 0.0, 0.0], 0.10, 0.05).hits == 1


def test_a_handful_of_observations_is_not_a_tail_finding():
    """The floor the rest of the summary keeps, which this measure lacked.

    Thirteen of the fifteen cohorts calling themselves distinguishable had
    fewer than five observations; nine had exactly one. One company's one
    quarter reading as a caught tail is the same error the win rate refuses.
    """
    assert tail_capture([0.5] * 4, 0.10, 0.01).distinguishable is False
    assert tail_capture([0.5] * 4, 0.10, 0.01).p_value is None
    assert tail_capture([0.5] * 5, 0.10, 0.01).distinguishable is True


def test_base_rate_counts_the_whole_field():
    assert base_rate([0.2, 0.05, 0.0, 0.0], 0.10) == 0.25
    assert base_rate([], 0.10) is None


def test_a_cohort_without_a_base_rate_offers_no_verdict():
    """Nothing to compare against, so no lift and no claim."""
    capture = tail_capture([0.5, 0.5], 0.10, None)
    assert capture.lift is None and capture.p_value is None
    assert capture.distinguishable is False


@pytest.mark.parametrize("probability", [-0.1, 1.5, None])
def test_a_base_rate_outside_the_unit_interval_produces_no_p_value(probability):
    assert binomial_against(3, 10, probability) is None


def test_a_base_rate_of_zero_is_evidence_rather_than_silence():
    """It is the strongest statement the comparison can make, not a gap.

    Nothing outside the cohort ever reached the threshold. Any hit at all has
    probability zero under that null. Returning None threw that away, and it
    stops being hypothetical once the base rate excludes the cohort itself:
    the two records in the whole set that reached +10% on open_d1 are both
    inside one cohort, so its comparison base is exactly zero.
    """
    assert binomial_against(3, 20, 0.0) == 0.0
    assert binomial_against(0, 20, 0.0) == 1.0
    assert binomial_against(20, 20, 1.0) == 1.0
    assert binomial_against(19, 20, 1.0) == 0.0


def test_a_p_value_is_never_rounded_all_the_way_to_zero():
    """Six decimals would report 9e-53 as certainty."""
    assert 0 < binomial_against(40, 40, 0.05) < 1e-50


def test_the_binomial_is_symmetric_about_the_base_rate():
    assert binomial_against(0, 10, 0.5) == binomial_against(10, 10, 0.5)


# --- 中央値区間の被覆 ---------------------------------------------------------

def normal_samples(n, count, seed=20260828):
    """Deterministic draws, so the coverage figure is reproducible."""
    import random
    generator = random.Random(seed)
    return [sorted(generator.gauss(0, 1) for _ in range(n)) for _ in range(count)]


@pytest.mark.parametrize("n", [6, 10, 20, 40])
def test_the_median_interval_actually_covers_what_it_claims(n):
    """It claimed 95% and delivered 78% at n=6: the rank was one place inside."""
    samples = normal_samples(n, 4000)
    covered = 0
    for ordered in samples:
        interval = median_interval(ordered)
        assert interval.low is not None
        if interval.low <= 0 <= interval.high:
            covered += 1
    assert covered / len(samples) >= 0.95


def test_no_interval_is_offered_where_the_level_cannot_be_reached():
    """Five observations cannot bracket a median at 95%; saying so beats guessing."""
    assert median_interval([0.01, 0.02, 0.03, 0.04, 0.05]).low is None


def test_the_median_interval_uses_the_expected_ranks():
    values = [float(i) for i in range(20)]
    interval = median_interval(values)
    assert (interval.low, interval.high) == (values[5], values[14])


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Without the running minimum the first of these adjusts to 0.08:
        # a smaller raw value must never end up with a larger adjusted one.
        ({"a": 0.04, "b": 0.041}, {"a": 0.041, "b": 0.041}),
        (
            {"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.04, "e": 0.05},
            {"a": 0.05, "b": 0.05, "c": 0.05, "d": 0.05, "e": 0.05},
        ),
        (
            {"a": 0.001, "b": 0.9, "c": 0.02, "d": 0.5},
            {"a": 0.004, "b": 0.9, "c": 0.04, "d": 0.666667},
        ),
    ],
)
def test_the_correction_matches_benjamini_hochberg(raw, expected):
    """Pinned against the standard definition, not just against monotonicity."""
    assert adjust_for_multiplicity(raw) == expected


def test_a_verdict_is_computed_from_whichever_p_value_it_is_given():
    """So a caller holding the corrected value can recompute with it."""
    from earnings_research.statistics.cohort import verdict_for

    assert verdict_for(0.02, 0.02, 0.01, trimmed_mean=0.02) == "directional"
    assert verdict_for(0.02, 0.02, 0.9, trimmed_mean=0.02) == "no_signal"
    # A tail-driven cohort stays tail-driven whatever the p-value says.
    assert verdict_for(0.02, -0.01, 0.001, trimmed_mean=0.02) == "tail_driven"
    # No p-value means no test was run, which is not the same as no signal.
    assert verdict_for(0.02, 0.02, None, trimmed_mean=0.02) == "not_tested"


# --- 監査が「生存した変異」と報告した箇所を固定する ---------------------------

# Reference Clopper-Pearson bounds, computed independently (scipy beta.ppf) and
# rounded to six places. Pinning them kills at once: halving alpha the wrong
# way, the classic off-by-one in the lower tail, cutting the bisection short,
# rounding the bounds coarsely, and losing the lower bound at one success —
# every one of which passed the whole suite before this existed.
# Generated with scipy.stats.beta.ppf, an implementation this repository does
# not use, so the check is against something other than itself.
CLOPPER_PEARSON_REFERENCE = {
    (0, 1): (0.0, 0.975), (1, 1): (0.025, 1.0),
    (0, 5): (0.0, 0.521824), (1, 5): (0.005051, 0.716418),
    (3, 5): (0.146633, 0.947255), (5, 5): (0.478176, 1.0),
    (1, 10): (0.002529, 0.445016), (5, 10): (0.187086, 0.812914),
    (8, 12): (0.348876, 0.900754),
}


@pytest.mark.parametrize("key,expected", sorted(CLOPPER_PEARSON_REFERENCE.items()))
def test_the_win_rate_interval_matches_an_independent_reference(key, expected):
    successes, n = key
    interval = clopper_pearson(successes, n)
    assert interval.low == pytest.approx(expected[0], abs=1e-6)
    assert interval.high == pytest.approx(expected[1], abs=1e-6)


@pytest.mark.parametrize("n", [5, 10, 20, 40])
def test_the_win_rate_interval_covers_what_it_claims(n):
    """Exact coverage by enumeration — no sampling, so no tolerance needed.

    Substituting the normal approximation the module docstring rejects passed
    every test in the suite while dropping coverage as low as 0.005.
    """
    from math import comb

    bounds = [clopper_pearson(k, n) for k in range(n + 1)]
    for p in (0.05, 0.1, 0.3, 0.5, 0.7, 0.9):
        covered = sum(
            comb(n, k) * p ** k * (1 - p) ** (n - k)
            for k in range(n + 1)
            if bounds[k].low <= p <= bounds[k].high
        )
        assert covered >= 0.95, (n, p, covered)


def test_a_summary_carries_the_win_rate_interval_at_all():
    """Deleting it outright used to pass the suite."""
    summary = summarise([0.01] * 8 + [-0.01] * 2)
    assert summary.win_rate_interval.low is not None
    assert summary.win_rate_interval.high is not None


def test_a_cohort_of_a_thousand_names_does_not_crash():
    """comb(1030, 515) stops fitting in a float, and every public entry point
    that summed binomial terms term-by-term raised OverflowError there."""
    summary = summarise([0.01] * 600 + [-0.01] * 500)
    assert summary.reportable
    assert summary.win_rate_interval.low is not None
    assert summary.sign_test_p is not None
    assert tail_capture([0.2] * 600 + [0.0] * 500, 0.10, 0.05).p_value is not None


def test_a_flat_outcome_is_not_counted_as_a_loss():
    """The win rate and the sign test now drop ties by the same rule."""
    summary = summarise([0.0] * 10 + [0.02] * 10)
    assert summary.ties == 10
    assert summary.win_rate == 1.0
    assert summarise([0.0] * 20).win_rate is None


def test_the_intervals_are_built_on_names_not_on_repeat_appearances():
    """The cohort this module's own docstring describes.

    One company twenty times against five others once each. On rows the win
    rate interval excluded a coin entirely while the sign test beside it said
    nothing had been shown; measured coverage falls to 62% when eight earnings
    share a name.
    """
    summary = summarise([0.01] * 20 + [-0.01] * 5, clusters=["SAME"] * 20 + list("BCDEF"))
    assert (summary.n, summary.n_independent) == (25, 6)
    assert summary.win_rate == 0.8
    assert summary.win_rate_interval.low < 0.5 < summary.win_rate_interval.high
    assert summary.median_interval.excludes_zero() is False
    assert summary.verdict != "directional"


def test_the_vote_count_is_reported_beside_the_name_count():
    """They differ whenever a name's own rows cancel, and the p-value is on the
    second one."""
    summary = summarise([0.01, -0.01] + [0.02] * 5, clusters=["A", "A"] + list("BCDEF"))
    assert summary.n_independent == 6
    assert summary.n_directional == 5


@pytest.mark.parametrize("n", range(1, 26))
def test_the_sign_test_is_two_sided_and_stays_a_probability(n):
    """One-sided was the mutation nobody caught: five names losing five times
    went from 0.0625 to 0.03125 and a cohort that showed nothing became
    significant."""
    for wins in range(n + 1):
        p, votes = sign_test([1.0] * wins + [-1.0] * (n - wins))
        assert votes == n
        assert 0 < p <= 1.0
        assert p == sign_test([-1.0] * wins + [1.0] * (n - wins))[0]
    assert sign_test([1.0] * 5)[0] == pytest.approx(0.0625)


def test_a_name_votes_by_which_way_more_of_its_rows_went():
    """Its median let magnitude decide, and moved with 1e-7 of noise."""
    quiet = list("BCDEF")
    assert sign_test([-0.001, 0.80] + [-0.02] * 5, ["A", "A"] + quiet)[0] == pytest.approx(
        sign_test([-0.80, 0.001] + [-0.02] * 5, ["A", "A"] + quiet)[0]
    )


def test_the_threshold_and_the_base_rate_use_the_same_comparison():
    """Relaxing one of the two >= comparisons moved real base rates and no test
    noticed."""
    values = [0.10, 0.09, 0.0, 0.0, 0.0]
    assert tail_capture(values, 0.10, base_rate(values, 0.10)).hits == 1
    assert base_rate([0.10, 0.0], 0.10) == 0.5


def test_a_cohort_that_caught_none_of_the_large_moves_says_so():
    """Direction-blind, it reported the same thing as a cohort that caught them
    all."""
    missed = tail_capture([0.0] * 60, 0.10, 0.20)
    caught = tail_capture([0.15] * 20, 0.10, 0.02)
    assert (missed.distinguishable, missed.direction) == (True, "below")
    assert (caught.distinguishable, caught.direction) == (True, "above")


def test_the_trimmed_mean_actually_trims_at_every_reportable_size():
    """A tenth of nine rounds to nothing, so below ten it was the mean under
    another name — and no test in the suite asserted anything about it at all."""
    for n in range(MIN_REPORTABLE, 12):
        values = [-0.01] * (n - 1) + [1.50]
        summary = summarise(values)
        assert summary.trimmed_mean != summary.mean, n
        assert summary.trimmed_mean == pytest.approx(-0.01)


def test_the_quartiles_and_extremes_are_the_ones_they_claim_to_be():
    """Swapping q1 with q3, or best with worst, passed the whole suite."""
    summary = summarise([-0.05, -0.01, 0.0, 0.01, 0.02, 0.03, 0.50])
    assert summary.worst == -0.05
    assert summary.best == 0.50
    assert summary.q1 < summary.median < summary.q3


def test_the_significance_threshold_is_the_one_the_module_declares():
    """Loosening it from 0.05 to 0.5 passed the whole suite."""
    assert verdict_for(0.02, 0.02, 0.049, trimmed_mean=0.02) == "directional"
    assert verdict_for(0.02, 0.02, 0.051, trimmed_mean=0.02) == "no_signal"


def test_concentration_answers_to_a_large_loss_as_well_as_a_large_gain():
    """It measured the largest deviation, but nothing checked the sign, and
    taking the maximum before the absolute value passed the suite."""
    up = concentration([0.001] * 20 + [1.5])
    down = concentration([-0.001] * 20 + [-1.5])
    assert up == pytest.approx(down)


def test_concentration_is_reported_beside_the_ceiling_it_saturates_at():
    """9.4 is 57% of the ceiling at n=33 and 12% of it at n=163."""
    summary = summarise([0.01] * 32 + [0.5])
    assert summary.concentration_ceiling == 33 / 2


def test_a_cohort_carried_by_its_tail_is_named_however_the_crowd_sits():
    """The sign checks caught the flagship case only because its crowd was
    negative. Nudge the crowd to +0.01%, below what it costs to trade, and the
    same single name carrying everything reported directional. Two large names
    defeated the check outright, since only one is ever removed."""
    for outliers in (1, 2, 3, 5):
        summary = summarise([0.0001] * (100 - outliers) + [1.0] * outliers)
        assert summary.verdict == "tail_driven", outliers
        assert summary.tail_share > 0.5
        assert summary.tail_direction == "up"


def test_a_cohort_dragged_by_one_loss_is_named_too():
    """The mirror image, which removing only the largest name could not see."""
    summary = summarise([-0.001] * 99 + [-1.50])
    assert summary.verdict == "tail_driven"
    assert summary.tail_direction == "down"
    assert summary.mean_without_worst == pytest.approx(-0.001)


def test_a_cohort_the_group_actually_carries_is_left_alone():
    """The control: ninety-nine at +1.00% and one at +1.01% is not tail-driven,
    though concentration saturates at n/2 for both."""
    summary = summarise([0.01] * 99 + [0.0101])
    assert summary.verdict != "tail_driven"
    assert summary.tail_share < 0.01
    assert summary.concentration == summary.concentration_ceiling


def test_a_return_that_is_not_a_number_is_refused_rather_than_averaged():
    """A single "nan" left the available count untouched, cost the win rate a
    silent point, poisoned the mean and flipped a published verdict."""
    with pytest.raises(ValueError):
        summarise([0.01, 0.02, float("nan"), 0.03, 0.04, 0.05])
    with pytest.raises(ValueError):
        summarise([0.01, 0.02, float("inf"), 0.03, 0.04, 0.05])


@pytest.mark.parametrize(
    "bounds,expected",
    [((0.0, 0.5), False), ((-0.5, 0.0), False), ((-0.0, 0.5), False),
     ((-0.5, -0.0), False), ((5e-324, 0.5), True), ((-0.5, -1e-9), True)],
)
def test_a_bound_sitting_on_zero_is_not_a_direction(bounds, expected):
    """The gate stability uses to decide whether a hypothesis is finished.
    Relaxing either comparison passed the whole suite while turning
    inconclusive halves into a reversal."""
    assert Interval(*bounds).excludes_zero() is expected


def test_an_interval_is_refused_when_it_cannot_be_built_rather_than_faked():
    assert median_interval([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7], 0.0) == Interval(None, None)
    with pytest.raises(ValueError):
        clopper_pearson(5, 10, 1.5)
    with pytest.raises(ValueError):
        clopper_pearson(11, 10)


def test_the_median_interval_does_not_depend_on_the_order_it_is_given():
    ascending = [-0.05, -0.04, -0.03, -0.02, -0.01, 0.01, 0.02, 0.03, 0.04, 0.05]
    assert median_interval(ascending) == median_interval(list(reversed(ascending)))


def test_a_close_anchored_field_declares_its_price_like_every_other():
    """Deleting close_d5 and close_d20 from the anchor table passed the suite,
    because the tests only asked whether the pairing was contaminated and an
    undeclared field answered no."""
    from earnings_research.statistics.lookahead import RETURN_ANCHOR

    assert RETURN_ANCHOR["close_d5"] == "next_close"
    assert RETURN_ANCHOR["close_d20"] == "next_close"


def test_a_cohort_is_tested_against_the_rest_rather_than_a_rate_assumed_known():
    """The base rate is estimated from the other rows, not given. Where those
    rows happened never to reach the threshold it came out at exactly zero, and
    under a point null of zero any hit at all has probability zero: two real
    cohorts shipped p=0.0 and survived the correction on it. Conditioning on
    the observed margins asks whether the hits fall disproportionately inside
    the cohort, which is the actual question."""
    from earnings_research.statistics.cohort import fisher_exact

    assert fisher_exact(2, 10, 0, 155) == pytest.approx(0.003326, abs=1e-5)
    assert binomial_against(2, 10, 0.0) == 0.0
    capture = tail_capture([0.5, 0.5] + [0.0] * 8, 0.10, comparison=[0.0] * 155)
    assert capture.base_rate == 0.0
    assert 0.001 < capture.p_value < 0.01


def test_a_cohort_indistinguishable_from_the_rest_says_so():
    assert fisher_exact(1, 20, 8, 160) > 0.5
    assert fisher_exact(0, 20, 0, 160) is not None


def test_the_tail_measure_counts_names_like_every_other_measure():
    """The interval fix moved the win rate and the median onto names and left
    this one on rows. Same cohort, same page: twenty hits out of twenty-five
    with an interval of [0.593, 0.932] and p = 4e-9, beside a sign test on the
    same summary saying p = 1.0."""
    rows = [0.5] * 20 + [0.0] * 5
    names = ["SAME"] * 20 + list("BCDEF")
    outside = [0.0] * 80 + [0.5] * 20
    outside_names = ["X%d" % index for index in range(100)]
    by_row = tail_capture(rows, 0.10, comparison=outside, comparison_clusters=outside_names)
    by_name = tail_capture(
        rows, 0.10, clusters=names, comparison=outside, comparison_clusters=outside_names
    )
    assert (by_row.n, by_row.hits) == (25, 20)
    assert (by_name.n, by_name.hits) == (6, 1)
    assert by_row.distinguishable is True
    assert by_name.distinguishable is False
    assert summarise(rows, clusters=names).sign_test_p == 1.0


def test_a_name_that_reached_the_threshold_once_counts_once():
    """Its best, not its middle: a company that hit +20% in one quarter out of
    eight did reach it."""
    capture = tail_capture(
        [0.0, 0.0, 0.0, 0.5] + [0.0] * 16,
        0.10,
        clusters=["A"] * 4 + ["B%d" % index for index in range(16)],
        comparison=[0.0] * 40,
        comparison_clusters=["Y%d" % index for index in range(40)],
    )
    assert (capture.n, capture.hits) == (17, 1)


@pytest.mark.parametrize(
    "field,expected",
    [("gap", ("prev_close", "next_open")), ("ret_d1", ("prev_close", "next_close")),
     ("ret_d20", ("prev_close", "d20_close")), ("open_d1", ("next_open", "next_close")),
     ("open_d5", ("next_open", "d5_close")), ("open_d20", ("next_open", "d20_close")),
     ("close_d5", ("next_close", "d5_close")), ("close_d20", ("next_close", "d20_close"))],
)
def test_each_field_spans_the_two_prices_its_name_claims(field, expected):
    """Both the aggregation and the published tables read their prices here, so
    a wrong pair moves every figure at once and nothing else would notice."""
    from earnings_research.statistics.lookahead import prices_for

    assert prices_for(field) == expected


def test_the_win_rate_interval_and_the_sign_test_agree_on_a_name_s_direction():
    """Reading it off the name's median let magnitude decide for an even number
    of rows, so two cohorts with identical signs disagreed about whether they
    cleared a coin while the sign test gave them the same p."""
    quiet = list("BCDEF")
    up = summarise([-0.001, 0.80] + [-0.02] * 5, clusters=["A", "A"] + quiet)
    down = summarise([-0.80, 0.001] + [-0.02] * 5, clusters=["A", "A"] + quiet)
    assert up.sign_test_p == down.sign_test_p
    assert up.win_rate_interval == down.win_rate_interval
