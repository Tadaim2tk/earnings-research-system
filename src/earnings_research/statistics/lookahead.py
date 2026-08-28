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
COHORT_SPAN: Dict[str, FrozenSet[str]] = {
    # Split on the gap: the move away from the previous close.
    "shodo": frozenset({"prev_close"}),
    # Split on the gap *and* on whether day one closed above its own open, so
    # an opening-anchored return still contains half the definition. Seeing the
    # rebound means waiting for the close, which is where the measure starts.
    "reaction": frozenset({"prev_close", "next_open"}),
}


def contamination(cohort_key: str, outcome_field: str) -> Optional[str]:
    """Return why this pairing is circular, or None when it is sound.

    An unknown cohort key is treated as sound: this guards the pairings we know
    are circular rather than pretending to know every one.
    """
    span = COHORT_SPAN.get(cohort_key)
    if span is None:
        return None
    anchor = RETURN_ANCHOR.get(outcome_field)
    if anchor is None:
        return None
    if anchor in span:
        return (
            "%s splits on the move away from %s, and %s is measured from %s, "
            "so the split is inside the result" % (cohort_key, anchor, outcome_field, anchor)
        )
    return None


def sound_fields(cohort_key: str, outcome_fields) -> list:
    """The outcome fields this cohort may be scored on."""
    return [field for field in outcome_fields if contamination(cohort_key, field) is None]
