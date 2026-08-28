import pytest

from earnings_research.statistics.cohort import (
    MIN_REPORTABLE,
    adjust_for_multiplicity,
    base_rate,
    binomial_against,
    clopper_pearson,
    concentration,
    median_interval,
    sign_test,
    summarise,
    tail_capture,
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
    assert summary.sign_test_p == sign_test([-0.01] * 5 + [0.01])


def test_a_name_votes_by_its_own_middle():
    # A's median is negative even though its best row is not.
    values = [0.05, -0.01, -0.01] + [0.02, 0.03, 0.04]
    clusters = ["A", "A", "A", "B", "C", "D"]
    assert summarise(values, clusters=clusters).sign_test_p == sign_test([-0.01, 0.02, 0.03, 0.04])


def test_the_sign_test_pairs_values_with_their_own_cluster():
    """Sorting the values before the test would scramble the pairing."""
    values = [0.05, -0.02, 0.04, -0.03, 0.06, -0.04]
    clusters = ["A", "B", "A", "B", "A", "B"]
    # A is entirely positive and B entirely negative; scrambling the pairing
    # would mix them and change the vote.
    assert summarise(values, clusters=clusters).sign_test_p == sign_test([0.05, -0.03])


def test_clusters_must_line_up_with_values():
    with pytest.raises(ValueError, match="line up"):
        summarise([0.01, 0.02], clusters=["A"])


def test_flat_outcomes_do_not_look_decisive():
    """Zeroes carry no direction, so they are dropped rather than counted."""
    assert sign_test([0.0] * 20) is None
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
    assert contamination("rank", "ret_d5") is None
    assert sound_fields("rank", ["ret_d5", "open_d5"]) == ["ret_d5", "open_d5"]


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
    assert tail_capture([0.10, 0.0999], 0.10, 0.05).hits == 1


def test_base_rate_counts_the_whole_field():
    assert base_rate([0.2, 0.05, 0.0, 0.0], 0.10) == 0.25
    assert base_rate([], 0.10) is None


def test_a_cohort_without_a_base_rate_offers_no_verdict():
    """Nothing to compare against, so no lift and no claim."""
    capture = tail_capture([0.5, 0.5], 0.10, None)
    assert capture.lift is None and capture.p_value is None
    assert capture.distinguishable is False


@pytest.mark.parametrize("probability", [0.0, 1.0, -0.1, 1.5])
def test_an_impossible_base_rate_produces_no_p_value(probability):
    assert binomial_against(3, 10, probability) is None


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

    assert verdict_for(0.02, 0.02, 0.01, 0.01) == "directional"
    assert verdict_for(0.02, 0.02, 0.01, 0.9) == "no_signal"
    # A tail-driven cohort stays tail-driven whatever the p-value says.
    assert verdict_for(0.02, -0.01, 0.01, 0.001) == "tail_driven"
