"""Refuse to score a cohort on an outcome that already contains its definition.

Splitting stocks by their opening gap and then measuring the result from the
previous close guarantees the answer: the previous-close return contains the
gap, so the gap-up group looks strong and the gap-down group looks weak no
matter what happens afterwards. The finding is arithmetic, not evidence, and it
cannot be traded either way — the gap happens at the open, before anyone can
act on it.

Measured from the opening price, which is the first price anyone can actually
transact at, the same 254 legacy records reverse: gap-up goes from 74% positive
with a +3.5% median to 47% and -0.5%, and gap-down goes from 21% and -3.8% to
59% and +0.7%.

The pairing is declared here as data so a new cohort or a new horizon has to
say which price it starts from rather than inheriting the mistake.
"""

from typing import Dict, FrozenSet, Optional

# What each outcome field is measured from.
RETURN_ANCHOR: Dict[str, str] = {
    "gap": "prev_close",
    "ret_d1": "prev_close",
    "ret_d5": "prev_close",
    "ret_d20": "prev_close",
    "open_d1": "next_open",
    "open_d5": "next_open",
    "open_d20": "next_open",
    "close_d5": "next_close",
    "close_d20": "next_close",
}

# What each cohort variable is derived from. A cohort split on the gap is
# already a statement about the move between prev_close and next_open.
#
# The judgement fields belong here too, which is less obvious than the gap and
# was missed the first time. They are not derived from prices at all — they are
# read off the disclosure — but the question a span answers is "was this label
# available at the anchor", and they were not. The commit record settles it:
# across 254 records, rank, narrative, reason codes, judge and surprise were
# all written after 15:00 JST, so prev_close is that day's closing price and
# every one of these labels was decided after it. One memo quotes an
# after-hours PTS move, and there is a pts_negative reason code, neither of
# which can exist before the close. Scoring them from prev_close counts a move
# nobody holding that label could have taken.
COHORT_SPAN: Dict[str, FrozenSet[str]] = {
    # Split on the gap: the move away from the previous close.
    "shodo": frozenset({"prev_close"}),
    # Split on the gap *and* on whether day one closed above its own open, so
    # an opening-anchored return still contains half the definition. Seeing the
    # rebound means waiting for the close, which is where the measure starts.
    # next_close is the right edge of that span, not inside it: the labels fix
    # the sign of open_d1 completely and leave close_d5 at 39-60% positive.
    "reaction": frozenset({"prev_close", "next_open"}),
    # Decided from the disclosure, after the close it would be measured from.
    "rank": frozenset({"prev_close"}),
    "narrative": frozenset({"prev_close"}),
    "reason_code": frozenset({"prev_close"}),
    "rc1": frozenset({"prev_close"}),
    "rc2": frozenset({"prev_close"}),
    "rc3": frozenset({"prev_close"}),
    "judge": frozenset({"prev_close"}),
    "surprise": frozenset({"prev_close"}),
}


def contamination(cohort_key: str, outcome_field: str) -> Optional[str]:
    """Return why this pairing is unsound, or None when it holds.

    Two ways a pairing fails, and the second is the one that was missed: the
    split can be arithmetically inside the result, as a gap cohort is inside a
    previous-close return; or the label can simply not have existed yet at the
    anchor, as every judgement field is at the previous close. Both mean the
    same thing in practice — nobody could have acted on the label at the price
    the result is measured from.

    An unknown cohort key is treated as sound, deliberately: this guards the
    pairings we have established rather than pretending to know every one.

    An unknown *outcome* field is refused, which is the opposite choice and for
    a reason. Adding a return field and forgetting to declare its anchor
    reproduces the original bug exactly and silently: a ret_d60 measured from
    prev_close but left out of the table restores gap-up 74% positive and
    gap-down 24%, the very numbers this module exists to withhold, while the
    sound open-anchored field next to it says the opposite.
    """
    anchor = RETURN_ANCHOR.get(outcome_field)
    if anchor is None:
        return (
            "%s is not declared in RETURN_ANCHOR, so the price it is measured "
            "from is unknown and it cannot be shown to be safe" % outcome_field
        )
    span = COHORT_SPAN.get(cohort_key)
    if span is None:
        return None
    if anchor in span:
        return (
            "%s is fixed only after %s, and %s is measured from %s, so the "
            "split is inside the result" % (cohort_key, anchor, outcome_field, anchor)
        )
    return None


def sound_fields(cohort_key: str, outcome_fields) -> list:
    """The outcome fields this cohort may be scored on."""
    return [field for field in outcome_fields if contamination(cohort_key, field) is None]


# The price each field is measured to. With RETURN_ANCHOR above this gives the
# pair of prices a field spans, which is the whole definition of the field.
RETURN_EXIT: Dict[str, str] = {
    "gap": "next_open",
    "ret_d1": "next_close",
    "ret_d5": "d5_close",
    "ret_d20": "d20_close",
    "open_d1": "next_close",
    "open_d5": "d5_close",
    "open_d20": "d20_close",
    "close_d5": "d5_close",
    "close_d20": "d20_close",
}


def prices_for(outcome_field: str) -> tuple:
    """The two prices a field spans, refusing to guess at an undeclared one.

    Both the aggregation and the published tables used to name their prices by
    hand, so the tables could be corrected here and the reports would not move
    — and for a while they did not: the dashboard went on publishing the
    previous-close figures this table withholds. There is one place to change
    now, and both readers take it from here.
    """
    entry, exit_ = RETURN_ANCHOR.get(outcome_field), RETURN_EXIT.get(outcome_field)
    if entry is None or exit_ is None:
        raise KeyError("no declared prices for %r" % outcome_field)
    return entry, exit_
