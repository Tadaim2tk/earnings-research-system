"""Cohort-safe aggregation for legacy observations and TSO context."""

from collections import defaultdict
from statistics import mean, median


RETURN_FIELDS = ("gap", "ret_d1", "ret_d5", "ret_d20")


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metrics(rows):
    result = {"record_count": len(rows)}
    for field in RETURN_FIELDS:
        values = [value for row in rows if (value := _number(row.get(field))) is not None]
        result[field] = {
            "available_count": len(values),
            "missing_count": len(rows) - len(values),
            "mean": round(mean(values), 6) if values else None,
            "median": round(median(values), 6) if values else None,
        }
    return result


def _group(rows, key):
    groups = defaultdict(list)
    for row in rows:
        value = row.get(key) or "not_recorded"
        groups[value].append(row)
    return {value: _metrics(items) for value, items in sorted(groups.items())}


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
    return {
        "schema_version": "legacy_aggregation_summary_v1",
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
    }
