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

import hashlib
import json
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
    # The price an order actually gets. The disclosure lands after the close,
    # the first session reacts, the reaction is read off that session's close,
    # and the order fills at the next open — session i0+2, counting the
    # announcement day as i0. Every other anchor here is a price the record
    # happened to carry; this is the one a decision is executed at.
    #
    # It is also the only anchor no label reaches. A reaction cohort is fixed
    # at the first session's close, which is strictly before this price exists,
    # so the split and the result share no bar at all — where scoring the same
    # cohort from next_close means entering at the very price that decides the
    # label.
    "entry_d5": "entry_open",
    "entry_d20": "entry_open",
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
    # Every anchor, because these labels are not available at any of them. The
    # score behind them is point-in-time — the market snapshot is usable a
    # median of seven hours before the close it would be measured from — but
    # the label is not the score. It is which third of the whole record the
    # score falls in, and those boundaries are computed over all 254 rows. The
    # scores sit between 49.55 and 50.49 with the boundaries 0.09 apart, so the
    # third a row lands in turns on rows that had not happened yet: moving only
    # the later scores by a tenth, with the row's own input untouched, moves it
    # through all three labels. Recomputed as each row arrives, 40 of 252
    # labels differ. The last score the boundaries need is usable on 2026-08-21
    # and the earliest event is 2026-06-10, so the label is fixed seventy-two
    # days after the day it describes.
    "dollar_environment": frozenset(RETURN_ANCHOR.values()),
    "volatility_environment": frozenset(RETURN_ANCHOR.values()),
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


def canonical_rules() -> str:
    """The rules as one deterministic string, so a change to them is nameable.

    Everything that can change what ``contamination`` answers goes in, and
    nothing else: the two anchor tables and the cohort spans. Frozen knowledge
    is judged against a particular version of these, and without a name for the
    version, a verdict recorded today cannot be told apart from one recorded
    before a rule was added — which is precisely when a hypothesis that used to
    pass stops passing.
    """
    return json.dumps(
        {
            "return_anchor": dict(sorted(RETURN_ANCHOR.items())),
            "return_exit": dict(sorted(RETURN_EXIT.items())),
            "cohort_span": {key: sorted(value) for key, value in sorted(COHORT_SPAN.items())},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def rules_digest() -> str:
    """SHA-256 of the canonical rules."""
    return hashlib.sha256(canonical_rules().encode("utf-8")).hexdigest()


def declares(cohort_key: str) -> bool:
    """Whether the rules have anything to say about this cohort at all.

    An undeclared cohort is passed by ``contamination`` on purpose — the table
    guards the pairings that have been established rather than pretending to
    know every one — but "checked and sound" and "not covered" are different
    findings, and a ledger that records them as the same number hides the
    second.
    """
    return cohort_key in COHORT_SPAN


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
    "entry_d5": "d5_close",
    "entry_d20": "d20_close",
}


# The fields a row does not arrive with and has to be given. The source CSV
# carries the previous-close returns as columns; everything else is derived
# from the price pair declared above. Read off RETURN_ANCHOR rather than listed
# again, because a list beside a table is a second place to forget: the entry
# anchor was added to the table and the aggregation went on computing the five
# fields it had been written with, reporting the new one as absent everywhere.
DERIVED_FIELDS = tuple(
    field for field, anchor in RETURN_ANCHOR.items() if anchor != "prev_close"
)


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
