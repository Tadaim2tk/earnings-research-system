"""Cohort-safe aggregation for legacy observations and TSO context."""

from collections import defaultdict
from statistics import mean

from earnings_research.statistics.cohort import (
    CONFIDENCE,
    adjust_for_multiplicity,
    base_rate,
    summarise,
    tail_capture,
    verdict_for,
)
from earnings_research.legacy_research.labels import cohort_label
from earnings_research.statistics.holdout import split_by_date
from earnings_research.statistics.lookahead import contamination, prices_for
from earnings_research.statistics.stability import assess as assess_stability

# Returns from the previous close, and the same horizons from the opening
# price. The opening price is the first one anyone can transact at, so it is
# what a cohort split on the gap has to be scored against.
RETURN_FIELDS = (
    "gap", "ret_d1", "ret_d5", "ret_d20",
    "open_d1", "open_d5", "open_d20",
    "close_d5", "close_d20",
)

# Where the money is when outcomes are fat-tailed. A cohort with a flat median
# still earns its place if it holds the large moves more often than the run of
# the field, and a tidy median is worth little if it never catches one.
TAIL_THRESHOLDS = (0.10, 0.20)

# A per-ticker breakdown answers "what did this company do", not "does this
# predict". It carries no test.
DESCRIPTIVE_VIEW = "by_ticker"

# Carries a row's market context through the split so the two cannot drift apart.
_CONTEXT = "__context__"


def _number(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # "nan" parses. It then passes `if not opening`, is counted as available,
    # loses the win rate one silent point, poisons the mean, and turns a
    # published verdict from directional into tail_driven. This is the only
    # gate between an outside CSV and every number downstream.
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _metrics(rows, cohort_key=None, population=None):
    """Summarise one group, refusing outcomes that contain its own definition."""
    result = {"record_count": len(rows)}
    for field in RETURN_FIELDS:
        reason = contamination(cohort_key, field) if cohort_key else None
        if reason:
            result[field] = {"withheld": reason}
            continue
        pairs = [
            (value, row.get("code"))
            for row in rows
            if (value := _number(row.get(field))) is not None
        ]
        values = [value for value, _code in pairs]
        summary = summarise(values, clusters=[code for _value, code in pairs])
        result[field] = {
            "available_count": len(values),
            "missing_count": len(rows) - len(values),
            **_rounded(summary.as_dict()),
            "tail_capture": [
                tail_capture(
                    values,
                    threshold,
                    clusters=[code for _value, code in pairs],
                    comparison=population.outside(rows, field) if population else None,
                    comparison_clusters=(
                        population.names_outside(rows, field) if population else None
                    ),
                ).as_dict()
                for threshold in TAIL_THRESHOLDS
            ],
            "stability": assess_stability(
                rows,
                lambda row, field=field: _number(row.get(field)),
                cluster_of=lambda row: row.get("code"),
            ).as_dict(),
        }
    return result


def _rounded(values, places=6):
    """Keep the six-figure rounding the previous summary had."""
    return {
        key: round(value, places) if isinstance(value, float) else value
        for key, value in values.items()
    }


class _Population:
    """The comparison set for tail capture, with the cohort taken out of it.

    Comparing a cohort against a base rate computed over everything including
    that cohort asks it to beat a number it helped set. Every cohort here is a
    subset of the record — one of them is 54.7% of it — so the comparison was
    systematically easy: of the 298 cells the correction moved, 281 moved
    towards significance. The cell the tests pin was passing its own assertion
    by 0.008 on the biased figure.

    Removing the cohort leaves nothing to compare `overall` against, which is
    correct: a set has no outside, and the lift of 1.0 and p of 1.0 it reported
    were arithmetic, not evidence.
    """

    def __init__(self, rows):
        self.by_field = {}
        for field in RETURN_FIELDS:
            self.by_field[field] = [
                (id(row), value, row.get("code"))
                for row in rows
                if (value := _number(row.get(field))) is not None
            ]

    def outside(self, cohort_rows, field):
        excluded = {id(row) for row in cohort_rows}
        return [value for key, value, _code in self.by_field[field] if key not in excluded]

    def names_outside(self, cohort_rows, field):
        excluded = {id(row) for row in cohort_rows}
        return [code for key, _value, code in self.by_field[field] if key not in excluded]

    def rate_excluding(self, cohort_rows, field, threshold):
        return base_rate(self.outside(cohort_rows, field), threshold)


def _open_anchored(row):
    """Add the same horizons measured from prices a trade could have used.

    close_d5 and close_d20 never touch next_open, so a missing opening price
    used to drop them too — the very columns a reaction cohort has left after
    the contaminated ones are withheld. Each anchor now stands or falls alone.

    The exits stay fixed at the fifth and twentieth session after the
    announcement, so close_d5 is a four-session hold and open_d5 a five-session
    one. Only the entry moves; that is the comparison.
    """
    enriched = dict(row)
    # Acting on the first day's pattern means acting at its close, so the
    # horizons a reaction cohort can be scored on start there; acting on the
    # gap means the opening price. Both pairs come from the declaration table
    # rather than being written out again here.
    for name in ("open_d1", "open_d5", "open_d20", "close_d5", "close_d20"):
        entry_field, exit_field = prices_for(name)
        entry, exit_ = _number(row.get(entry_field)), _number(row.get(exit_field))
        # The key is always present, None where it cannot be computed. Leaving
        # it out for a missing entry price and setting None for a missing exit
        # made the same absence read two ways depending on which price was
        # gone.
        usable = entry and entry > 0 and exit_ and exit_ > 0
        enriched[name] = (exit_ - entry) / entry if usable else None
    return enriched


def _group(rows, key, population=None):
    """Group on the canonical label, not on the characters that were typed.

    `row.get(key) or "not_recorded"` grouped on the raw cell, so a full-width
    plus made `＋1` a second cohort beside `+1`, and the em dash and the ellipsis
    — both of which mean "not recorded" — became two more. Six of 254 records
    sat in cohorts of one or two, taken out of the levels they belong to, in
    the tables a reader actually reads.
    """
    groups = defaultdict(list)
    for row in rows:
        groups[cohort_label(row.get(key))].append(row)
    return {
        value: _metrics(items, cohort_key=key, population=population)
        for value, items in sorted(groups.items())
    }


def _cohort_views(summary, prefix=""):
    """Every view that groups records, wherever it sits in the summary.

    by_relative_dominance lives under market_context, so a scan that only
    looked at top-level `by_` keys skipped it entirely: 52 tests, five of them
    nominally significant, corrected by nothing and not even listed as
    uncorrected.
    """
    for name, value in summary.items():
        if not isinstance(value, dict):
            continue
        if name.startswith("by_"):
            yield prefix + name, value
        elif not prefix and name == "overall":
            # Not a grouped view — its children are field names, so the
            # recursion below walked past it and it entered no family at all.
            # That left the report's headline row as the one place a raw
            # p-value could still be quoted, and it was: close_d20 shipped
            # directional at 0.0317 while a cohort with a smaller raw p-value
            # was correctly buried at 0.95 after its own family was counted.
            yield name, {"__overall__": value}
        elif not prefix:
            yield from _cohort_views(value, prefix=name + ".")


def _multiplicity(summary):
    """Correct each view's tests together, and only where a test was asked.

    Benjamini-Hochberg controls the false discovery rate within one family of
    related questions, so each view is corrected separately: "does rank predict"
    and "does this reason code predict" are different questions and pooling them
    would spend one's power on the other.

    by_ticker is left out entirely. A per-ticker breakdown is a lookup, not a
    hypothesis, and it accounted for 3466 of 4252 comparisons here — correcting
    across it would bury a real effect in the views that are asking something.
    Its p-values are removed rather than shown uncorrected, because a p beside
    one company's five observations invites being read as evidence.
    """
    families = {}
    for view, groups in _cohort_views(summary):
        descriptive = view.split(".")[-1] == DESCRIPTIVE_VIEW
        raw = {}
        for label, metrics in groups.items():
            for field, stats in metrics.items():
                if not isinstance(stats, dict):
                    continue
                if stats.get("sign_test_p") is not None:
                    if descriptive:
                        stats.pop("sign_test_p")
                        stats["verdict"] = _verdict_from(stats, None)
                    else:
                        raw[(label, field, "sign")] = stats["sign_test_p"]
                # Each half of the stability split carries its own sign test and
                # its own verdict. They were being published outside the family,
                # so the count of comparisons the correction declared was short
                # by one per half, and a half could call itself directional on a
                # raw p-value the correction would have dismissed.
                for half in ("first_half", "second_half"):
                    part = (stats.get("stability") or {}).get(half)
                    if not isinstance(part, dict) or part.get("sign_test_p") is None:
                        continue
                    if descriptive:
                        part.pop("sign_test_p")
                        part["verdict"] = _verdict_from(part, None)
                    else:
                        raw[(label, field, half)] = part["sign_test_p"]
                for index, tail in enumerate(stats.get("tail_capture") or []):
                    if tail.get("p_value") is None:
                        continue
                    if descriptive:
                        # The p-value was removed here because a p beside one
                        # company's observations invites being read as
                        # evidence. distinguishable is the same claim as a
                        # boolean and was left behind, so it went too.
                        tail.pop("p_value")
                        tail["distinguishable"] = False
                        tail["direction"] = None
                    else:
                        raw[(label, field, "tail%d" % index)] = tail["p_value"]
        if descriptive:
            families[view] = {"comparisons": 0, "corrected": False, "reason": "lookup, not a hypothesis"}
            continue
        for (label, field, which), value in adjust_for_multiplicity(raw).items():
            stats = groups[label][field]
            if which in ("first_half", "second_half"):
                part = stats["stability"][which]
                part["sign_test_p_adjusted"] = value
                part["verdict"] = _verdict_from(part, value)
            elif which == "sign":
                stats["sign_test_p_adjusted"] = value
                # The verdict was formed before the family was counted. Leaving
                # it on the raw p-value would keep calling a cohort directional
                # after the correction has dismissed it, which would make the
                # correction decorative.
                stats["verdict"] = _verdict_from(stats, value)
            else:
                tail = stats["tail_capture"][int(which[4:])]
                tail["p_value_adjusted"] = value
                # The same reasoning that made the verdict recompute on the
                # corrected p-value. distinguishable is the figure this measure
                # tells the reader to read, and it was the one the correction
                # never touched: eight cohorts kept claiming it at adjusted
                # p-values of 0.49 and 1.0.
                if value >= 1 - CONFIDENCE:
                    tail["distinguishable"] = False
                    tail["direction"] = None
        families[view] = {"comparisons": len(raw), "corrected": True}
    return {"method": "benjamini_hochberg", "scope": "per_view", "families": families}


def _verdict_from(stats, p_value):
    """Recompute a cell's verdict from the numbers it already carries.

    Reading every input off the same dict keeps the caller from passing three
    of the five and silently losing the tail checks, which is how the mean
    ended up unguarded the first time.
    """
    return verdict_for(
        stats.get("mean"),
        stats.get("median"),
        p_value,
        trimmed_mean=stats.get("trimmed_mean"),
    )


def _reason_groups(rows, population=None):
    groups = defaultdict(list)
    for row in rows:
        reasons = {row.get(field) for field in ("rc1", "rc2", "rc3") if row.get(field)}
        if not reasons:
            reasons = {"not_recorded"}
        for reason in reasons:
            groups[reason].append(row)
    return {
        # Without a cohort key the guard is not consulted at all, and this view
        # carries the largest family of tests in the summary. Reason codes are
        # read off the disclosure, so they are fixed after the close they were
        # being scored from.
        value: _metrics(items, cohort_key="reason_code", population=population)
        for value, items in sorted(groups.items())
    }


def build_aggregation(rows, context_views, source_commit):
    # The most recent third is reserved. Nothing below sees it, so a cohort
    # cannot be shaped against the period it will later be judged on.
    #
    # Each row travels with its context view through the split. They are matched
    # by position, so filtering one without the other silently pairs a record
    # with someone else's market context.
    paired = []
    for row, view in zip(rows, list(context_views) + [None] * len(rows)):
        # The pairing before the split is positional too, and nothing checked
        # it. Dropping one context view shifts every later row onto a
        # neighbour's market context and raises nothing: the linked count is
        # unchanged and the dominance tables merely move by one. The producer
        # enforces a one-to-one join today, which is exactly why this went
        # unnoticed, and exactly why it is worth one comparison here.
        identity = (view.get("ticker"), view.get("legacy_event_date")) if view else None
        if identity is not None and identity != (row.get("code"), row.get("date")):
            raise ValueError(
                "market context for %s on %s does not belong to legacy record %s on %s"
                % (identity[0], identity[1], row.get("code"), row.get("date"))
            )
        paired.append({**_open_anchored(row), _CONTEXT: view})
    split = split_by_date(paired)
    rows = [{key: value for key, value in row.items() if key != _CONTEXT} for row in split.exploration]
    # Keep each row beside its own context rather than re-zipping the two
    # lists: a row whose TSO link is missing drops out of one list and not the
    # other, and every row after it inherits the next row's market context. The
    # 254 legacy records all link, so this is silent today and would stay silent
    # on the first record that does not.
    explored = [
        (row, carrier[_CONTEXT])
        for row, carrier in zip(rows, split.exploration)
        if carrier.get(_CONTEXT)
    ]
    explored_context = [record for _row, record in explored]
    rates = _Population(rows)
    context_by_id = {item["legacy_record_id"]: item for item in explored_context}
    context_groups = defaultdict(list)
    risk_on_scores = []
    risk_off_scores = []
    for row, record in explored:
        context = record["market_context"]
        risk_on = _number(context.get("risk_on_score"))
        risk_off = _number(context.get("risk_off_score"))
        if risk_on is not None:
            risk_on_scores.append(risk_on)
        if risk_off is not None:
            risk_off_scores.append(risk_off)
        if risk_on is None or risk_off is None:
            label = "not_recorded"
        elif risk_on > risk_off:
            label = "risk_on_dominant"
        elif risk_off > risk_on:
            label = "risk_off_dominant"
        else:
            label = "balanced"
        context_groups[label].append(row)
    summary = {
        "schema_version": "legacy_aggregation_summary_v2",
        "dataset_origin": "earnings-research-os",
        "record_mode": "legacy_observational",
        "source_commit": source_commit,
        "record_count": len(rows),
        "record_count_including_reserved": len(rows) + len(split.reserved),
        "context_linked_count": len(explored_context),
        # No outside to compare against, so tail capture reports counts only.
        "overall": _metrics(rows, population=rates),
        "by_ticker": _group(rows, "code", rates),
        "by_shodo": _group(rows, "shodo", rates),
        "by_rank": _group(rows, "rank", rates),
        "by_narrative": _group(rows, "narrative", rates),
        # Published in the dashboard since the retired system, but with no view
        # here they were guarded by nothing and counted in no family. The
        # surprise table was quoting mean gap, the single most contaminated
        # field available.
        "by_judge": _group(rows, "judge", rates),
        "by_surprise": _group(rows, "surprise", rates),
        "by_reaction": _group(rows, "reaction", rates),
        "by_reason_code": _reason_groups(rows, rates),
        "market_context": {
            "linked_count": len(context_by_id),
            "missing_count": len(rows) - len(context_by_id),
            "mean_risk_on_score": round(mean(risk_on_scores), 4) if risk_on_scores else None,
            "mean_risk_off_score": round(mean(risk_off_scores), 4) if risk_off_scores else None,
            "by_relative_dominance": {
                # Sound on inspection — the TSO snapshot is usable a median of
                # seven hours before the close — but stated rather than assumed,
                # so a later change to the snapshot's timing has something to
                # break against.
                label: _metrics(items, cohort_key="relative_dominance", population=rates)
                for label, items in sorted(context_groups.items())
            },
            "classification_note": "Relative dominance compares the two stored TSO scores only; it is not a TSO regime or trading signal.",
        },
        "holdout": split.as_dict(),
        "prospective_records_included": 0,
        "trade_decisions_generated": 0,
        "reading_note": (
            "Each field carries win_rate, median and mean with exact intervals. "
            "A mean alone cannot separate one name limit-up from a group that "
            "moved together; concentration says how many observations' worth of "
            "the spread the largest single move carries. Cohorts split on the "
            "opening gap withhold the previous-close returns, which contain that "
            "gap by construction."
        ),
    }
    summary["multiplicity"] = _multiplicity(summary)
    return summary
