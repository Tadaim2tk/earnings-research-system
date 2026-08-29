"""One definition of what a cohort label is, because there were three.

The same value arrived at three modules and each canonicalised it differently:
the importer folded the sign characters that are the same mark typed on a
different keyboard, `knowledge.py` mapped the missing markers and left the
signs alone, and the aggregation — the one that produces the published tables —
did neither. So `＋1` and `+1` were counted as two categories in the tables a
reader actually sees, and six of 254 records sat in cohorts of one.

Six records is small until you notice where they land. `surprise` has five
levels over 165 exploration records; its smallest real cohort holds six. A
category losing three of its members is losing a third of them, and the widths
of these intervals are set by exactly that.
"""

# A label that means "nobody wrote one down". Kept exactly as knowledge.py has
# always had it: widening this set would silently retire real categories.
MISSING_LABELS = frozenset({"", "—", "…"})

# The same mark, typed differently. Full-width plus from a Japanese IME, en
# dash and non-breaking hyphen from a paste. Not a spelling variation — the
# writer meant one thing.
#
# The em dash is deliberately absent: it is a missing marker above, and folding
# it to a hyphen would turn "not recorded" into an unparseable level rather
# than leaving it as the blank it is.
SIGN_VARIANTS = str.maketrans({"＋": "+", "−": "-", "–": "-", "‑": "-"})


def fold_signs(value: str) -> str:
    """Strip, and fold sign characters that differ only by how they were typed."""
    return (value or "").strip().translate(SIGN_VARIANTS)


def cohort_label(value: str) -> str:
    """What a published table groups on.

    Folded, with the missing markers collapsed to one name so that "—" and "…"
    do not appear as two separate cohorts of one record each.
    """
    folded = fold_signs(value)
    return "not_recorded" if folded in MISSING_LABELS else folded


def frozen_cohort_label(value: str) -> str:
    """What `knowledge.py` groups on, which is deliberately not the above.

    `research_knowledge.json` is hash-bound to the frozen hypothesis registry:
    `verify-hypothesis-registry` re-derives the registry from it and refuses a
    mismatch. Folding the signs here would move that hash and unfreeze
    nineteen definitions — which is the correct thing to refuse, and the
    correct way to do it is a new registry version built from research that has
    the fix, not an edit underneath the one that is frozen.

    So the divergence is on purpose and is stated here rather than left to be
    discovered. It costs six records in the frozen registry's inputs, all in
    `surprise`; every one of those nineteen hypotheses is already invalid under
    the contamination rules, so nothing is currently gathering evidence on
    them.
    """
    return "not_recorded" if (value or "") in MISSING_LABELS else value
