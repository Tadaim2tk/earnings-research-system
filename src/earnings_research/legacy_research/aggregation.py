"""Cohort-safe aggregation for legacy observations and TSO context."""

from collections import defaultdict
from statistics import mean

from earnings_research.statistics.cohort import adjust_for_multiplicity, summarise
from earnings_research.statistics.lookahead import contamination

# Returns from the previous close, and the same horizons from the opening
# price. The opening price is the first one anyone can transact at, so it is
# what a cohort split on the gap has to be scored against.
RETURN_FIELDS = (
    "gap", "ret_d1", "ret_d5", "ret_d20",
    "open_d1", "open_d5", "open_d20",
    "close_d5", "close_d20",
)


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metrics(rows, cohort_key=None):
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
            **summary.as_dict(),
        }
    return result


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


def _group(rows, key):
    groups = defaultdict(list)
    for row in rows:
        value = row.get(key) or "not_recorded"
        groups[value].append(row)
    return {value: _metrics(items, cohort_key=key) for value, items in sorted(groups.items())}


def _multiplicity(summary):
    """Correct every cohort sign test together.

    Read one at a time, a report of this many groups will always show something
    under p<0.05. The corrected value is what says whether it is worth reading.
    """
    raw = {}
    for view, groups in summary.items():
        if not view.startswith("by_") or not isinstance(groups, dict):
            continue
        for label, metrics in groups.items():
            for field, stats in metrics.items():
                if isinstance(stats, dict) and stats.get("sign_test_p") is not None:
                    raw["%s/%s/%s" % (view, label, field)] = stats["sign_test_p"]
    adjusted = adjust_for_multiplicity(raw)
    for name, value in adjusted.items():
        view, label, field = name.split("/")
        summary[view][label][field]["sign_test_p_adjusted"] = value
    return {"comparisons": len(raw), "method": "benjamini_hochberg"}


def _reason_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        reasons = {row.get(field) for field in ("rc1", "rc2", "rc3") if row.get(field)}
        if not reasons:
            reasons = {"not_recorded"}
        for reason in reasons:
            groups[reason].append(row)
    return {value: _metrics(items) for value, items in sorted(groups.items())}


def build_aggregation(rows, context_views, source_commit):
    rows = [_open_anchored(row) for row in rows]
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
        "overall": _metrics(rows),
        "by_ticker": _group(rows, "code"),
        "by_rank": _group(rows, "rank"),
        "by_narrative": _group(rows, "narrative"),
        "by_reaction": _group(rows, "reaction"),
        "by_reason_code": _reason_groups(rows),
        "market_context": {
            "linked_count": len(context_by_id),
            "missing_count": len(rows) - len(context_by_id),
            "mean_risk_on_score": round(mean(risk_on_scores), 4) if risk_on_scores else None,
            "mean_risk_off_score": round(mean(risk_off_scores), 4) if risk_off_scores else None,
            "by_relative_dominance": {
                label: _metrics(items) for label, items in sorted(context_groups.items())
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
