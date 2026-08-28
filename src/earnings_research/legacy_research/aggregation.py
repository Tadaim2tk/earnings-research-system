"""Cohort-safe aggregation for legacy observations and TSO context."""

from collections import defaultdict
from statistics import mean

from earnings_research.statistics.cohort import (
    adjust_for_multiplicity,
    base_rate,
    summarise,
    tail_capture,
)
from earnings_research.statistics.lookahead import contamination

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


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metrics(rows, cohort_key=None, base_rates=None):
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
                    values, threshold, (base_rates or {}).get((field, threshold))
                ).as_dict()
                for threshold in TAIL_THRESHOLDS
            ],
        }
    return result


def _rounded(values, places=6):
    """Keep the six-figure rounding the previous summary had."""
    return {
        key: round(value, places) if isinstance(value, float) else value
        for key, value in values.items()
    }


def _base_rates(rows):
    """How often the whole field reached each threshold, for comparison."""
    rates = {}
    for field in RETURN_FIELDS:
        values = [value for row in rows if (value := _number(row.get(field))) is not None]
        for threshold in TAIL_THRESHOLDS:
            rates[(field, threshold)] = base_rate(values, threshold)
    return rates


def _open_anchored(row):
    """Add the same horizons measured from the opening price."""
    opening = _number(row.get("next_open"))
    if not opening:
        return row
    enriched = dict(row)
    for name, close_field in (
        ("open_d1", "next_close"), ("open_d5", "d5_close"), ("open_d20", "d20_close")
    ):
        close = _number(row.get(close_field))
        enriched[name] = (close - opening) / opening if close else None
    # Acting on the first day's pattern means acting at its close, so the
    # horizons a reaction cohort can be scored on start there.
    first_close = _number(row.get("next_close"))
    if first_close:
        for name, close_field in (("close_d5", "d5_close"), ("close_d20", "d20_close")):
            close = _number(row.get(close_field))
            enriched[name] = (close - first_close) / first_close if close else None
    return enriched


def _group(rows, key, base_rates=None):
    groups = defaultdict(list)
    for row in rows:
        value = row.get(key) or "not_recorded"
        groups[value].append(row)
    return {
        value: _metrics(items, cohort_key=key, base_rates=base_rates)
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
                    else:
                        raw["%s/%s/sign" % (label, field)] = stats["sign_test_p"]
                for index, tail in enumerate(stats.get("tail_capture") or []):
                    if tail.get("p_value") is None:
                        continue
                    if descriptive:
                        tail.pop("p_value")
                    else:
                        raw["%s/%s/tail%d" % (label, field, index)] = tail["p_value"]
        if descriptive:
            families[view] = {"comparisons": 0, "corrected": False, "reason": "lookup, not a hypothesis"}
            continue
        for name, value in adjust_for_multiplicity(raw).items():
            label, field, which = name.split("/")
            if which == "sign":
                groups[label][field]["sign_test_p_adjusted"] = value
            else:
                groups[label][field]["tail_capture"][int(which[4:])]["p_value_adjusted"] = value
        families[view] = {"comparisons": len(raw), "corrected": True}
    return {"method": "benjamini_hochberg", "scope": "per_view", "families": families}


def _reason_groups(rows, base_rates=None):
    groups = defaultdict(list)
    for row in rows:
        reasons = {row.get(field) for field in ("rc1", "rc2", "rc3") if row.get(field)}
        if not reasons:
            reasons = {"not_recorded"}
        for reason in reasons:
            groups[reason].append(row)
    return {
        value: _metrics(items, base_rates=base_rates)
        for value, items in sorted(groups.items())
    }


def build_aggregation(rows, context_views, source_commit):
    rows = [_open_anchored(row) for row in rows]
    rates = _base_rates(rows)
    context_by_id = {item["legacy_record_id"]: item for item in context_views}
    context_groups = defaultdict(list)
    risk_on_scores = []
    risk_off_scores = []
    for record, row in zip(context_views, rows):
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
        "overall": _metrics(rows, base_rates=rates),
        "by_ticker": _group(rows, "code", rates),
        "by_shodo": _group(rows, "shodo", rates),
        "by_rank": _group(rows, "rank", rates),
        "by_narrative": _group(rows, "narrative", rates),
        "by_reaction": _group(rows, "reaction", rates),
        "by_reason_code": _reason_groups(rows, rates),
        "market_context": {
            "linked_count": len(context_by_id),
            "missing_count": len(rows) - len(context_by_id),
            "mean_risk_on_score": round(mean(risk_on_scores), 4) if risk_on_scores else None,
            "mean_risk_off_score": round(mean(risk_off_scores), 4) if risk_off_scores else None,
            "by_relative_dominance": {
                label: _metrics(items, base_rates=rates) for label, items in sorted(context_groups.items())
            },
            "classification_note": "Relative dominance compares the two stored TSO scores only; it is not a TSO regime or trading signal.",
        },
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
