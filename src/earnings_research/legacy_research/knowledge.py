"""Reproducible descriptive research over the legacy observational cohort."""

from __future__ import annotations

import json
import hashlib
import math
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median


HORIZONS = {"d1": "ret_d1", "d5": "ret_d5", "d20": "ret_d20"}
CLASSIFICATION_FIELDS = ("rank", "narrative", "judge")
HIGH_RANKS = {"A", "B+"}
LOW_RANKS = {"C+", "C", "B-", "D"}
MISSING_LABELS = {"", "—", "…"}
MIN_LIMITED_SAMPLE = 10
MIN_DESCRIPTIVE_SAMPLE = 30


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _number(value):
    if value in (None, ""):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _label(value):
    value = str(value or "").strip()
    return "not_recorded" if value in MISSING_LABELS else value


def _rounded(value, digits=6):
    return round(value, digits) if value is not None else None


def _sample_grade(distinct_tickers):
    if distinct_tickers < MIN_LIMITED_SAMPLE:
        return "insufficient"
    if distinct_tickers < MIN_DESCRIPTIVE_SAMPLE:
        return "limited"
    return "descriptive"


def _horizon_metrics(rows, field):
    available = [(row["ticker"], value) for row in rows if (value := _number(row.get(field))) is not None]
    ticker_values = defaultdict(list)
    context_values = defaultdict(list)
    for ticker, value in available:
        ticker_values[ticker].append(value)
    for row in rows:
        value = _number(row.get(field))
        if value is not None:
            context_values[row["context_snapshot_id"]].append(value)
    values = [value for _, value in available]
    ticker_means = [mean(items) for items in ticker_values.values()]
    context_means = [mean(items) for items in context_values.values()]
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    zero = sum(value == 0 for value in values)
    distinct = len(ticker_values)
    distinct_contexts = len(context_values)
    effective_units = min(distinct, distinct_contexts)
    return {
        "available_count": len(values),
        "missing_count": len(rows) - len(values),
        "distinct_ticker_count": distinct,
        "repeated_observation_count": len(values) - distinct,
        "distinct_context_snapshot_count": distinct_contexts,
        "repeated_context_observation_count": len(values) - distinct_contexts,
        "effective_unit_count": effective_units,
        "mean_return": _rounded(mean(values)) if values else None,
        "median_return": _rounded(median(values)) if values else None,
        "ticker_balanced_mean_return": _rounded(mean(ticker_means)) if ticker_means else None,
        "context_balanced_mean_return": _rounded(mean(context_means)) if context_means else None,
        "positive_count": positive,
        "negative_count": negative,
        "zero_count": zero,
        "positive_rate": _rounded(positive / len(values)) if values else None,
        "sample_grade": _sample_grade(effective_units),
        "sample_grade_basis": "minimum_of_distinct_tickers_and_context_snapshots",
        "conclusion_boundary": "descriptive_not_causal" if effective_units >= MIN_DESCRIPTIVE_SAMPLE else "hypothesis_only",
    }


def _summary(rows):
    tickers = Counter(row["ticker"] for row in rows)
    contexts = Counter(row["context_snapshot_id"] for row in rows)
    return {
        "record_count": len(rows),
        "distinct_ticker_count": len(tickers),
        "repeated_ticker_count": sum(count > 1 for count in tickers.values()),
        "repeated_observation_count": len(rows) - len(tickers),
        "distinct_context_snapshot_count": len(contexts),
        "repeated_context_observation_count": len(rows) - len(contexts),
        "horizons": {name: _horizon_metrics(rows, field) for name, field in HORIZONS.items()},
    }


def _quantile_thresholds(values):
    ordered = sorted(values)
    if not ordered:
        return None
    low = ordered[(len(ordered) - 1) // 3]
    high = ordered[(2 * (len(ordered) - 1)) // 3]
    return {"lower_max": _rounded(low, 4), "upper_min": _rounded(high, 4)}


def _bucket(value, thresholds, labels):
    if value is None or thresholds is None:
        return "not_recorded"
    if value <= thresholds["lower_max"]:
        return labels[0]
    if value >= thresholds["upper_min"]:
        return labels[2]
    return labels[1]


def _group(rows, dimensions):
    groups = defaultdict(list)
    for row in rows:
        key = tuple(row[dimension] for dimension in dimensions)
        groups[key].append(row)
    return [
        {
            "dimensions": dict(zip(dimensions, key)),
            "summary": _summary(items),
        }
        for key, items in sorted(groups.items())
    ]


def _feature_distribution(rows):
    fields = ("rank", "narrative", "judge", "reaction", "risk_balance", "volatility_environment", "dollar_environment")
    result = {}
    for field in fields:
        counts = Counter(row[field] for row in rows)
        result[field] = [
            {"value": value, "count": count, "share": _rounded(count / len(rows))}
            for value, count in counts.most_common()
        ] if rows else []
    reasons = Counter(reason for row in rows for reason in row["reason_codes"])
    result["reason_code"] = [
        {"value": value, "count": count, "share": _rounded(count / len(rows))}
        for value, count in reasons.most_common()
    ] if rows else []
    return result


def _reversal_analysis(rows):
    groups = defaultdict(list)
    for row in rows:
        d1 = _number(row.get("ret_d1"))
        d20 = _number(row.get("ret_d20"))
        if d1 is None or d20 is None:
            label = "unavailable"
        elif d1 > 0 and d20 < 0:
            label = "positive_to_negative"
        elif d1 < 0 and d20 > 0:
            label = "negative_to_positive"
        elif d1 > 0 and d20 > 0:
            label = "positive_continuation"
        elif d1 < 0 and d20 < 0:
            label = "negative_continuation"
        else:
            label = "includes_zero"
        groups[label].append(row)
    return {
        "definition": "The sign of D1 return is compared with the sign of D20 return; missing values remain unavailable.",
        "groups": [
            {
                "transition": label,
                "summary": _summary(items),
                "common_features": _feature_distribution(items),
            }
            for label, items in sorted(groups.items())
        ],
    }


def _exception_analysis(rows):
    result = {}
    for horizon, field in (("d5", "ret_d5"), ("d20", "ret_d20")):
        high_down = [row for row in rows if row["rank"] in HIGH_RANKS and (_number(row.get(field)) or 0) < 0]
        low_up = [row for row in rows if row["rank"] in LOW_RANKS and (_number(row.get(field)) or 0) > 0]
        result[horizon] = {
            "high_rank_negative": {
                "rank_definition": sorted(HIGH_RANKS),
                "summary": _summary(high_down),
                "common_features": _feature_distribution(high_down),
            },
            "low_rank_positive": {
                "rank_definition": sorted(LOW_RANKS),
                "summary": _summary(low_up),
                "common_features": _feature_distribution(low_up),
            },
        }
    return result


def _candidate(dimension, value, horizon, metrics, overall):
    if metrics["effective_unit_count"] < MIN_LIMITED_SAMPLE:
        return None
    if metrics["mean_return"] is None or overall["mean_return"] is None:
        return None
    mean_delta = metrics["mean_return"] - overall["mean_return"]
    rate_delta = metrics["positive_rate"] - overall["positive_rate"]
    if mean_delta >= 0.01 and rate_delta >= 0.05:
        direction = "potentially_favorable"
    elif mean_delta <= -0.01 and rate_delta <= -0.05:
        direction = "potentially_unfavorable"
    elif abs(mean_delta) <= 0.005 and abs(rate_delta) <= 0.05:
        direction = "low_discrimination"
    else:
        return None
    return {
        "candidate_id": f"{dimension}:{value}:{horizon}:{direction}",
        "classification": direction,
        "dimension": dimension,
        "value": value,
        "horizon": horizon,
        "available_count": metrics["available_count"],
        "distinct_ticker_count": metrics["distinct_ticker_count"],
        "distinct_context_snapshot_count": metrics["distinct_context_snapshot_count"],
        "effective_unit_count": metrics["effective_unit_count"],
        "mean_return_delta_vs_overall": _rounded(mean_delta),
        "positive_rate_delta_vs_overall": _rounded(rate_delta),
        "sample_grade": metrics["sample_grade"],
        "temporal_role": {
            "reaction": "post_event_reaction_path",
            "risk_balance": "point_in_time_market_context",
            "volatility_environment": "point_in_time_market_context",
            "dollar_environment": "point_in_time_market_context",
        }.get(dimension, "legacy_classification_timing_not_guaranteed"),
        "interpretation": "This is a descriptive legacy association and a candidate for prospective validation, not a scoring or trading rule.",
    }


def _learning_candidates(overall, single_groups):
    candidates = []
    eligible_dimensions = (
        "rank", "narrative", "judge", "reaction", "risk_balance",
        "volatility_environment", "dollar_environment",
    )
    for dimension in eligible_dimensions:
        groups = single_groups[dimension]
        for group in groups:
            value = group["dimensions"][dimension]
            if value == "not_recorded":
                continue
            for horizon in ("d5", "d20"):
                candidate = _candidate(
                    dimension,
                    value,
                    horizon,
                    group["summary"]["horizons"][horizon],
                    overall["horizons"][horizon],
                )
                if candidate:
                    candidates.append(candidate)
    buckets = defaultdict(list)
    for item in candidates:
        buckets[item["classification"]].append(item)
    for classification, items in buckets.items():
        reverse = classification != "low_discrimination"
        items.sort(
            key=lambda item: (
                -abs(item["mean_return_delta_vs_overall"]) if reverse else abs(item["mean_return_delta_vs_overall"]),
                item["candidate_id"],
            )
        )
    selected = (
        buckets["potentially_favorable"][:8]
        + buckets["potentially_unfavorable"][:7]
        + buckets["low_discrimination"][:5]
    )
    hypotheses = [
        {
            "hypothesis_id": f"LEGACY-HYP-{index:03d}",
            "source_candidate_id": item["candidate_id"],
            "test": f"Prospectively test whether {item['dimension']}={item['value']} retains its {item['horizon']} association under fixed definitions and complete price observations.",
            "status": "learning_candidate",
            "automatic_rule_change": False,
        }
        for index, item in enumerate(selected[:10], 1)
    ]
    return {
        "selection_thresholds": {
            "minimum_effective_units": MIN_LIMITED_SAMPLE,
            "favorable_mean_delta": 0.01,
            "favorable_positive_rate_delta": 0.05,
            "low_discrimination_mean_delta": 0.005,
            "selection_quota": {
                "potentially_favorable": 8,
                "potentially_unfavorable": 7,
                "low_discrimination": 5,
            },
        },
        "candidates": selected,
        "next_hypotheses": hypotheses,
        "weight_changes_generated": 0,
        "rank_rule_changes_generated": 0,
        "trading_rules_generated": 0,
    }


def _classification_lineage(field_history, expected_record_ids):
    by_field = {}
    for field in CLASSIFICATION_FIELDS:
        items = [item for item in field_history if item.get("field_name") == field]
        item_ids = [item.get("legacy_record_id") for item in items]
        if len(item_ids) != len(expected_record_ids) or set(item_ids) != expected_record_ids:
            raise ValueError(f"classification history is incomplete or duplicated: {field}")
        changed = [item for item in items if item.get("first_seen_commit") != item.get("last_changed_commit")]
        by_field[field] = {
            "record_count": len(items),
            "changed_after_first_seen_count": len(changed),
            "changed_record_ids": sorted(item["legacy_record_id"] for item in changed),
            "limitation": "Git history identifies that a final classification changed, but this derived file does not claim the prior value was governed by a stable rubric.",
        }
    return by_field


NOTICE = [
    '> **⚠ この成果物は、統計ガードを通っていない経路から生成されています。**',
    '>',
    '> `knowledge.py` には留保期間の分割も、寄り付き起点のリターンも、多重比較補正も',
    '> 入っていません（`aggregation.py` と `publishing.py` にのみ入っています）。',
    '> したがって下の差分は、254件全部・前日終値起点・補正なしで算出されたもので、',
    '> 統計的な所見ではありません。`research_report.md` と `research_knowledge.json` に出る',
    '> `potentially_favorable` / `potentially_unfavorable` は方向の候補であって、',
    '> 検証結果ではありません。',
    '>',
    '> とくに `reaction` を `D5` / `D20` で評価している項目は、現在のコードが',
    '> 「分類の定義が結果に入っている」として withhold する組合せです。',
    '> この経路の是正は ERS-ADR-0045 の未対応事項として別PRに残しています。',
    '',
]


def build_research_knowledge(records, context_views, field_history, manifest):
    if manifest.get("dataset_origin") != "earnings-research-os" or manifest.get("record_mode") != "legacy_observational":
        raise ValueError("research input must be the frozen legacy observational cohort")
    context_by_id = {item["legacy_record_id"]: item for item in context_views}
    if len(context_by_id) != len(context_views):
        raise ValueError("legacy context contains duplicate record identity")
    combined = []
    record_ids = {record.get("legacy_record_id") for record in records}
    if None in record_ids or len(record_ids) != len(records) or set(context_by_id) != record_ids:
        raise ValueError("legacy record and context identities must form a one-to-one set")
    for record in records:
        if record.get("dataset_origin") != "earnings-research-os" or record.get("record_mode") != "legacy_observational":
            raise ValueError("prospective or foreign records cannot enter legacy research")
        context_view = context_by_id.get(record["legacy_record_id"])
        if not context_view or context_view.get("record_mode") != "legacy_observational" or context_view.get("join_status") != "ok":
            raise ValueError("every legacy record requires one valid read-only TSO context link")
        context_snapshot_id = context_view.get("tso_snapshot_id")
        if not context_snapshot_id:
            raise ValueError("every legacy context link requires a TSO snapshot identity")
        raw = record["raw_record"]
        context = context_view["market_context"]
        combined.append({
            "legacy_record_id": record["legacy_record_id"],
            "ticker": raw["code"],
            "event_date": raw["date"],
            "event_month": raw["date"][:7],
            "context_snapshot_id": context_snapshot_id,
            "rank": _label(raw.get("rank")),
            "narrative": _label(raw.get("narrative")),
            "judge": _label(raw.get("judge")),
            "reaction": _label(raw.get("reaction")),
            "reason_codes": [raw[field] for field in ("rc1", "rc2", "rc3") if raw.get(field)],
            "ret_d1": raw.get("ret_d1"),
            "ret_d5": raw.get("ret_d5"),
            "ret_d20": raw.get("ret_d20"),
            "risk_on_score": _number(context.get("risk_on_score")),
            "risk_off_score": _number(context.get("risk_off_score")),
            "volatility_stress_score": _number(context.get("volatility_stress_score")),
            "dollar_strength_score": _number(context.get("dollar_strength_score")),
        })
    if len(combined) != manifest.get("source_row_count"):
        raise ValueError("research input count does not match the frozen migration manifest")
    volatility_thresholds = _quantile_thresholds([row["volatility_stress_score"] for row in combined if row["volatility_stress_score"] is not None])
    dollar_thresholds = _quantile_thresholds([row["dollar_strength_score"] for row in combined if row["dollar_strength_score"] is not None])
    for row in combined:
        on, off = row["risk_on_score"], row["risk_off_score"]
        if on is None or off is None:
            row["risk_balance"] = "not_recorded"
        elif on > off:
            row["risk_balance"] = "risk_on_dominant"
        elif off > on:
            row["risk_balance"] = "risk_off_dominant"
        else:
            row["risk_balance"] = "balanced"
        row["volatility_environment"] = _bucket(
            row["volatility_stress_score"], volatility_thresholds, ("low", "middle", "high")
        )
        row["dollar_environment"] = _bucket(
            row["dollar_strength_score"], dollar_thresholds, ("weak", "middle", "strong")
        )
    single_dimensions = (
        "rank", "narrative", "judge", "reaction", "risk_balance",
        "volatility_environment", "dollar_environment", "event_month",
    )
    single_groups = {dimension: _group(combined, (dimension,)) for dimension in single_dimensions}
    combinations = {
        "rank_x_narrative": _group(combined, ("rank", "narrative")),
        "rank_x_judge": _group(combined, ("rank", "judge")),
        "narrative_x_risk_balance": _group(combined, ("narrative", "risk_balance")),
        "reaction_x_risk_balance": _group(combined, ("reaction", "risk_balance")),
        "reaction_x_volatility": _group(combined, ("reaction", "volatility_environment")),
    }
    overall = _summary(combined)
    repeated = Counter(row["ticker"] for row in combined)
    return {
        "schema_version": "legacy_research_knowledge_v1",
        "dataset_origin": "earnings-research-os",
        "record_mode": "legacy_observational",
        "source_commit": manifest["frozen_source_commit"],
        "tso_source_commit": manifest["tso_source_commit"],
        "analysis_scope": {
            "purpose": "descriptive_measurement_hypothesis_generation",
            "prospective_records_included": 0,
            "causal_claims_generated": 0,
            "multivariate_model_fitted": False,
            "automatic_scoring_or_trading_changes": False,
            "reaction_definition": "Legacy reaction uses the next-session open-to-close path; D5 and D20 comparisons are post-event continuation or reversal descriptions.",
        },
        "coverage": overall,
        "repeated_company_control": {
            "distinct_ticker_count": overall["distinct_ticker_count"],
            "repeated_tickers": [
                {"ticker": ticker, "record_count": count}
                for ticker, count in sorted(repeated.items()) if count > 1
            ],
            "method": "Every cohort reports both observation-weighted and ticker-balanced means; no claim treats all 254 rows as independent companies.",
        },
        "classification_lineage": _classification_lineage(field_history, record_ids),
        "market_bucketing": {
            "risk_balance": "Relative comparison of stored risk_on_score and risk_off_score; not a TSO regime or signal.",
            "volatility_tertiles": volatility_thresholds,
            "dollar_tertiles": dollar_thresholds,
            "boundary": "Market variables are reported one at a time. Correlated context variables are not interpreted as independent effects.",
        },
        "single_dimension_results": single_groups,
        "combination_results": combinations,
        "exception_patterns": _exception_analysis(combined),
        "initial_to_d20_transitions": _reversal_analysis(combined),
        "learning": _learning_candidates(overall, single_groups),
    }


def _percent(value):
    return "-" if value is None else f"{value * 100:.2f}%"


def _table(groups, dimension, horizons=("d5", "d20")):
    header = [dimension, "records"]
    for horizon in horizons:
        header.extend([f"{horizon} n", f"{horizon} units", f"{horizon} mean", f"{horizon} positive", f"{horizon} grade"])
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for group in groups:
        summary = group["summary"]
        cells = [group["dimensions"][dimension], str(summary["record_count"])]
        for horizon in horizons:
            item = summary["horizons"][horizon]
            cells.extend([
                str(item["available_count"]),
                str(item["effective_unit_count"]),
                _percent(item["mean_return"]),
                _percent(item["positive_rate"]),
                item["sample_grade"],
            ])
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _combination_lines(combination_results, limit=15):
    eligible = []
    for name, groups in combination_results.items():
        for group in groups:
            d5 = group["summary"]["horizons"]["d5"]
            d20 = group["summary"]["horizons"]["d20"]
            if max(d5["effective_unit_count"], d20["effective_unit_count"]) < MIN_LIMITED_SAMPLE:
                continue
            sort_value = max(abs(d5["mean_return"] or 0), abs(d20["mean_return"] or 0))
            eligible.append((sort_value, name, group, d5, d20))
    eligible.sort(key=lambda item: (-item[0], item[1], sorted(item[2]["dimensions"].items())))
    lines = []
    for _, name, group, d5, d20 in eligible[:limit]:
        dimensions = ", ".join(f"{key}={value}" for key, value in group["dimensions"].items())
        lines.append(
            f"- `{name}` {dimensions}: D5 {_percent(d5['mean_return'])} "
            f"(n={d5['available_count']}, {d5['sample_grade']}), D20 {_percent(d20['mean_return'])} "
            f"(n={d20['available_count']}, {d20['sample_grade']})。"
        )
    return lines


def _top_feature(pattern):
    fields = (
        "narrative", "judge", "reaction", "risk_balance",
        "volatility_environment", "dollar_environment", "reason_code",
    )
    for field in fields:
        values = pattern["common_features"].get(field, [])
        if values:
            top = values[0]
            return f"{field}={top['value']} ({top['count']}/{pattern['summary']['record_count']})"
    return "not_recorded"


def render_research_report(knowledge):
    coverage = knowledge["coverage"]
    candidates = knowledge["learning"]["candidates"]
    lines = [
        "# Legacy Earnings Research Knowledge",
        "",
        # Written by the generator, not stamped on afterwards: these files are
        # reproduced byte for byte by verify-legacy-research, so a notice added
        # by hand is a mismatch by construction.
        *NOTICE,
        "## 境界",
        "",
        "このレポートは旧OSの `legacy_observational` だけを記述集計した研究出力である。相関を因果、正式スコア、売買ルールとして扱わない。",
        "",
        "## データ利用可能性",
        "",
        f"- 全記録: {coverage['record_count']}",
        f"- 銘柄数: {coverage['distinct_ticker_count']}",
        f"- 反復銘柄数: {coverage['repeated_ticker_count']}",
        f"- TSO snapshot数: {coverage['distinct_context_snapshot_count']}",
    ]
    for horizon in ("d1", "d5", "d20"):
        item = coverage["horizons"][horizon]
        lines.append(
            f"- {horizon.upper()}: 利用可能 {item['available_count']} / 欠損 {item['missing_count']} / "
            f"銘柄 {item['distinct_ticker_count']} / snapshot {item['distinct_context_snapshot_count']} / "
            f"実効母数 {item['effective_unit_count']}"
        )
    for title, dimension in (("Rank", "rank"), ("Narrative", "narrative"), ("Judge", "judge"), ("株価反応", "reaction")):
        lines.extend(["", f"## {title}別", "", _table(knowledge["single_dimension_results"][dimension], dimension)])
    lines.extend(["", "## 市場環境別", ""])
    for dimension in ("risk_balance", "volatility_environment", "dollar_environment"):
        lines.extend([f"### {dimension}", "", _table(knowledge["single_dimension_results"][dimension], dimension), ""])
    lines.extend(["## 組み合わせ別の探索結果", ""])
    lines.extend(_combination_lines(knowledge["combination_results"]))
    lines.extend(["", "組み合わせは探索用の記述結果であり、多変量効果や独立要因を意味しない。", ""])
    lines.extend(["## 高rank下落・低rank上昇", ""])
    for horizon in ("d5", "d20"):
        high = knowledge["exception_patterns"][horizon]["high_rank_negative"]
        low = knowledge["exception_patterns"][horizon]["low_rank_positive"]
        lines.append(
            f"- {horizon.upper()} 高rank下落: {high['summary']['record_count']}件。最多条件: {_top_feature(high)}。"
        )
        lines.append(
            f"- {horizon.upper()} 低rank上昇: {low['summary']['record_count']}件。最多条件: {_top_feature(low)}。"
        )
    lines.extend(["", "## 初動からD20への反転", ""])
    for item in knowledge["initial_to_d20_transitions"]["groups"]:
        lines.append(f"- {item['transition']}: {item['summary']['record_count']}件")
    lines.extend(["", "## 評価分類の履歴", ""])
    for field, item in knowledge["classification_lineage"].items():
        lines.append(
            f"- {field}: {item['record_count']}件中、初回記録後に最終値が変わったもの "
            f"{item['changed_after_first_seen_count']}件。"
        )
    lines.append("")
    lines.extend(["## 学習候補", ""])
    if not candidates:
        lines.append("閾値を満たす学習候補はなかった。")
    for item in candidates:
        lines.append(
            f"- `{item['classification']}`: {item['dimension']}={item['value']} / {item['horizon'].upper()} / "
            f"平均差 {_percent(item['mean_return_delta_vs_overall'])} / 上昇率差 {_percent(item['positive_rate_delta_vs_overall'])} / "
            f"n={item['available_count']}。prospectiveで再検証する候補であり、ルールではない。"
        )
    lines.extend([
        "",
        "## 解釈上の制約",
        "",
        "- D1、D5、D20は利用可能件数が異なり、欠損は失敗として数えていない。",
        "- 同一銘柄の反復を考慮し、銘柄均等平均も機械可読データに保持した。",
        "- 小標本は `insufficient` または `limited` とし、強い結論を出さない。",
        "- 市場環境変数は相関し得るため、単変量結果と組み合わせ結果を因果効果として合算しない。",
        "- 自動weight変更、rank基準変更、売買ルール変更は生成していない。",
        "",
    ])
    return "\n".join(lines)


def render_digest(knowledge, title, limit):
    coverage = knowledge["coverage"]
    lines = [
        f"## {title}",
        "",
        *NOTICE,
        f"対象はlegacy_observational {coverage['record_count']}件。"
        f"D1 {coverage['horizons']['d1']['available_count']}件（実効{coverage['horizons']['d1']['effective_unit_count']}）、"
        f"D5 {coverage['horizons']['d5']['available_count']}件（実効{coverage['horizons']['d5']['effective_unit_count']}）、"
        f"D20 {coverage['horizons']['d20']['available_count']}件（実効{coverage['horizons']['d20']['effective_unit_count']}）を利用した。",
        "",
    ]
    for item in knowledge["learning"]["candidates"][:limit]:
        lines.append(
            f"- {item['dimension']}={item['value']}の{item['horizon'].upper()}は全体比平均差"
            f"{_percent(item['mean_return_delta_vs_overall'])}（n={item['available_count']}、{item['sample_grade']}）。"
        )
    lines.extend(["", "これらは次回検証用の学習候補であり、正式なスコア・売買ルールではない。", ""])
    return "\n".join(lines)


def build_research_outputs(input_root: Path):
    input_root = Path(input_root)
    manifest = json.loads((input_root / "migration_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("prospective_records_created") != 0 or manifest.get("formal_evidence_created") != 0:
        raise ValueError("frozen legacy migration boundary is invalid")
    if manifest.get("tso_writeback_performed") is not False:
        raise ValueError("frozen legacy migration must remain read-only to TSO")
    for name in ("legacy_records.jsonl", "legacy_context_view.jsonl", "field_history.jsonl"):
        expected_hash = manifest.get("output_sha256", {}).get(name)
        actual_hash = hashlib.sha256((input_root / name).read_bytes()).hexdigest()
        if not expected_hash or actual_hash != expected_hash:
            raise ValueError(f"frozen legacy research input hash mismatch: {name}")
    records = _read_jsonl(input_root / "legacy_records.jsonl")
    contexts = _read_jsonl(input_root / "legacy_context_view.jsonl")
    history = _read_jsonl(input_root / "field_history.jsonl")
    knowledge = build_research_knowledge(records, contexts, history, manifest)
    return {
        "research_knowledge.json": json.dumps(knowledge, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "research_report.md": render_research_report(knowledge),
        "weekly_research_digest.md": render_digest(knowledge, "Legacy Research Weekly Digest", 5),
        "note_research_digest.md": render_digest(knowledge, "Legacy Research Note Digest", 10),
    }


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def write_research_outputs(input_root: Path, output_dir: Path):
    outputs = build_research_outputs(input_root)
    output_dir = Path(output_dir)
    for name, text in outputs.items():
        _atomic_write(output_dir / name, text)
    knowledge = json.loads(outputs["research_knowledge.json"])
    return {
        "status": "generated",
        "record_count": knowledge["coverage"]["record_count"],
        "d1_available": knowledge["coverage"]["horizons"]["d1"]["available_count"],
        "d5_available": knowledge["coverage"]["horizons"]["d5"]["available_count"],
        "d20_available": knowledge["coverage"]["horizons"]["d20"]["available_count"],
        "learning_candidate_count": len(knowledge["learning"]["candidates"]),
        "output_dir": str(output_dir),
    }


def verify_research_outputs(input_root: Path, output_dir: Path):
    expected = build_research_outputs(input_root)
    output_dir = Path(output_dir)
    for name, text in expected.items():
        path = output_dir / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            raise ValueError(f"legacy research output mismatch: {name}")
    knowledge = json.loads(expected["research_knowledge.json"])
    return {
        "status": "verified",
        "record_count": knowledge["coverage"]["record_count"],
        "output_count": len(expected),
        "learning_candidate_count": len(knowledge["learning"]["candidates"]),
    }
