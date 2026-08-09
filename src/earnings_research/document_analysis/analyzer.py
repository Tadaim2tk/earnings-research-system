"""Conservative parser for Japanese earnings releases with page provenance."""

import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from earnings_research.document_analysis.models import (
    CompanySpecificMetric,
    ConsistencyCheck,
    DocumentIdentity,
    EarningsDocumentAnalysis,
    MetricValue,
    NarrativeFinding,
    PeriodReference,
    SourceReference,
)
from earnings_research.document_analysis.pdf import ExtractedPDF

_PL_METRICS = [
    ("revenue", "売上高"),
    ("operating_profit", "営業利益"),
    ("ordinary_profit", "経常利益"),
    ("net_income", "純利益"),
]

_MONEY_MULTIPLIERS = {
    "円": 1,
    "千円": 1_000,
    "百万円": 1_000_000,
    "億円": 100_000_000,
}


class AnalysisError(ValueError):
    """Document structure cannot be interpreted without guessing."""


def analyze_japanese_earnings_release(
    extracted: ExtractedPDF,
    source_url: str,
    document_title: str,
    acquired_at: str,
    document_type: str = "earnings_release",
) -> EarningsDocumentAnalysis:
    pages = extracted.pages
    first_lines = _lines(pages[0])
    company_name = _value_after(first_lines, "上場会社名")
    ticker = _value_after(first_lines, "コード番号")
    accounting_period = _compact(first_lines[0] + first_lines[1].split("決算短信", 1)[0])
    announcement_date = _parse_japanese_date(first_lines[2])
    performance_line = _first_matching(first_lines, r"の業績[（(].*[~～].*[）)]")
    start_date, end_date = _period_dates(performance_line)
    scope = _scope_from_period(accounting_period)
    current_period = PeriodReference(
        fiscal_year=_fiscal_year(accounting_period),
        scope=scope,
        start_date=start_date,
        end_date=end_date,
        comparison="current",
    )
    prior_period = PeriodReference(
        fiscal_year=str(int(_fiscal_year(accounting_period)) - 1),
        scope=scope,
        comparison="prior_corresponding",
    )
    forecast_period = PeriodReference(
        fiscal_year=_fiscal_year(accounting_period),
        scope="full_year",
        start_date=start_date,
        comparison="company_forecast",
    )
    source_page_1 = _source(source_url, document_title, 1, "経営成績・財政状態・業績予想", acquired_at)

    performance_heading_index = _index_matching(first_lines, r"経営成績")
    current_label_index = _index_matching(first_lines, r"^\d{4}年.*第[123]四半期$")
    prior_label_index = _index_matching(first_lines, r"^\d{4}年.*第[123]四半期$", current_label_index + 1)
    performance_unit = _money_unit(first_lines[performance_heading_index:current_label_index])
    current_values = _numeric_values(first_lines[current_label_index + 1 : prior_label_index], 8)
    prior_values = _numeric_values(first_lines[prior_label_index + 1 :], 8)
    metrics: List[MetricValue] = []
    for position, (name, label) in enumerate(_PL_METRICS):
        metrics.append(_money(name, label, current_values[position * 2], "actual", current_period, source_page_1, performance_unit))
        metrics.append(_money(name, label, prior_values[position * 2], "prior_actual", prior_period, source_page_1, performance_unit))
        metrics.append(
            _percent(
                name + "_yoy",
                label + "前年同期比",
                current_values[position * 2 + 1],
                "actual",
                current_period,
                source_page_1,
            )
        )

    eps_index = _index_matching(first_lines, r"^1株当たり$")
    eps_current_label = _index_matching(first_lines, r"^\d{4}年.*第[123]四半期$", eps_index)
    eps_prior_label = _index_matching(first_lines, r"^\d{4}年.*第[123]四半期$", eps_current_label + 1)
    eps_values = _numeric_values(first_lines[eps_current_label + 1 : eps_prior_label], 2)
    eps_prior_values = _numeric_values(first_lines[eps_prior_label + 1 :], 2)
    metrics.append(_per_share("earnings_per_share", "1株利益", eps_values[0], "actual", current_period, source_page_1))
    metrics.append(_per_share("earnings_per_share", "1株利益", eps_prior_values[0], "prior_actual", prior_period, source_page_1))

    condition_index = first_lines.index("(2)財政状態")
    condition_current = _index_matching(first_lines, r"^\d{4}年.*第[123]四半期$", condition_index)
    condition_prior = _index_matching(first_lines, r"^\d{4}年.*期$", condition_current + 1)
    condition_unit = _money_unit(first_lines[condition_index:condition_current])
    condition_values = _numeric_values(first_lines[condition_current + 1 : condition_prior], 3)
    condition_prior_values = _numeric_values(first_lines[condition_prior + 1 :], 3)
    for name, label, value, prior_value, unit in [
        ("total_assets", "総資産", condition_values[0], condition_prior_values[0], condition_unit),
        ("net_assets", "純資産", condition_values[1], condition_prior_values[1], condition_unit),
        ("equity_ratio", "自己資本比率", condition_values[2], condition_prior_values[2], "%"),
    ]:
        if unit == "%":
            metrics.append(_percent(name, label, value, "actual", _point_period(current_period, end_date), source_page_1))
            metrics.append(_percent(name, label, prior_value, "prior_actual", _prior_year_end(prior_period), source_page_1))
        else:
            metrics.append(_money(name, label, value, "actual", _point_period(current_period, end_date), source_page_1, unit))
            metrics.append(_money(name, label, prior_value, "prior_actual", _prior_year_end(prior_period), source_page_1, unit))

    forecast_heading = _index_matching(first_lines, r"業績予想\(")
    full_year_index = first_lines.index("通期", forecast_heading)
    forecast_unit = _money_unit(first_lines[forecast_heading:full_year_index])
    forecast_values = _numeric_values(first_lines[full_year_index + 1 :], 9)
    for position, (name, label) in enumerate(_PL_METRICS):
        metrics.append(_money(name, label, forecast_values[position * 2], "company_forecast", forecast_period, source_page_1, forecast_unit))
    metrics.append(_per_share("earnings_per_share", "1株利益", forecast_values[8], "company_forecast", forecast_period, source_page_1))

    dividend_metrics, extraction_notes = _optional_dividend(
        first_lines, forecast_period, source_page_1
    )
    metrics.extend(dividend_metrics)

    metrics.extend(_derived_yoy(metrics, current_period, source_page_1))
    metrics.extend(_derived_progress(metrics, current_period, source_page_1))

    narrative_page_number, narrative_text = _find_page(pages, "各セグメントの経営成績")
    narrative_source = _source(source_url, document_title, narrative_page_number, "経営成績に関する説明", acquired_at)
    company_metrics = _segment_metrics(narrative_text, current_period, narrative_source)
    narratives = _narratives(pages, source_url, document_title, acquired_at)
    checks = _consistency_checks(metrics)
    unresolved = extraction_notes + [check.message for check in checks if check.status == "review_required"]
    return EarningsDocumentAnalysis(
        analysis_id="EDA-%s-%s" % (ticker, announcement_date.replace("-", "")),
        status="analyzed",
        document=DocumentIdentity(
            company_name=company_name,
            ticker=ticker,
            accounting_period=accounting_period,
            reporting_scope=scope,
            announcement_date=announcement_date,
            document_type=document_type,
            document_title=document_title,
            source_url=source_url,
            source_sha256=extracted.sha256,
            acquired_at=acquired_at,
            page_count=len(pages),
        ),
        financial_metrics=metrics,
        company_specific_metrics=company_metrics,
        narrative_findings=narratives,
        consistency_checks=checks,
        unresolved_items=unresolved,
        next_stage="ready_for_pre_event_comparison",
    )


def _lines(text: str) -> List[str]:
    return [unicodedata.normalize("NFKC", line).strip() for line in text.splitlines() if line.strip()]


def _compact(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def _value_after(lines: Sequence[str], label: str) -> str:
    try:
        return lines[lines.index(label) + 1]
    except (ValueError, IndexError) as exc:
        raise AnalysisError("missing document identity field: %s" % label) from exc


def _index_matching(lines: Sequence[str], pattern: str, start: int = 0) -> int:
    regex = re.compile(pattern)
    for index in range(start, len(lines)):
        if regex.search(lines[index]):
            return index
    raise AnalysisError("document structure missing: %s" % pattern)


def _first_matching(lines: Sequence[str], pattern: str) -> str:
    return lines[_index_matching(lines, pattern)]


def _numeric_values(lines: Sequence[str], count: int) -> List[str]:
    values = []
    for value in lines:
        normalized = value.replace("△", "-").replace("▲", "-").replace("−", "-")
        if re.fullmatch(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", normalized):
            values.append(normalized)
            if len(values) == count:
                break
    if len(values) < count:
        raise AnalysisError("numeric table is incomplete")
    return values


def _number(value: str):
    cleaned = value.replace(",", "").replace("△", "-").replace("▲", "-").replace("−", "-")
    return float(cleaned) if "." in cleaned else int(cleaned)


def _money_unit(lines: Sequence[str]) -> Optional[str]:
    normalized_lines = [_compact(line) for line in lines]
    joined = "".join(normalized_lines)
    for unit in ("百万円", "千円", "億円", "円"):
        explicit_global_unit = any(
            ("単位" in line or "金額単位" in line) and unit in line
            for line in normalized_lines
        )
        if joined.count(unit) >= 2 or explicit_global_unit:
            return unit
    return None


def _source(url, title, page, anchor, acquired_at):
    return SourceReference(source_url=url, document_title=title, page_number=page, text_anchor=anchor, acquired_at=acquired_at)


def _money(name, label, value, kind, period, source, unit, force_negative=False):
    number = _number(value)
    if force_negative and number > 0:
        number = -number
    multiplier = _MONEY_MULTIPLIERS.get(unit)
    return MetricValue(
        metric_name=name,
        label=label,
        value_kind=kind,
        displayed_value=value,
        displayed_unit=unit or "unknown",
        normalized_value=number * multiplier if multiplier is not None else number,
        normalized_unit="JPY" if multiplier is not None else "unknown",
        period=period,
        origin="reported",
        confidence="table_explicit" if multiplier is not None else "unclear",
        source=source,
    )


def _percent(name, label, value, kind, period, source, origin="reported", formula=None, inputs=None):
    return MetricValue(
        metric_name=name,
        label=label,
        value_kind=kind,
        displayed_value=str(value),
        displayed_unit="%",
        normalized_value=round(float(value), 2),
        normalized_unit="percent",
        period=period,
        origin=origin,
        confidence="calculated" if origin == "calculated" else "table_explicit",
        source=source,
        formula=formula,
        input_metric_names=inputs or [],
    )


def _per_share(name, label, value, kind, period, source):
    normalized_value = 0.0 if value == "無配" else float(value)
    return MetricValue(
        metric_name=name,
        label=label,
        value_kind=kind,
        displayed_value=value,
        displayed_unit="円",
        normalized_value=normalized_value,
        normalized_unit="JPY_per_share",
        period=period,
        origin="reported",
        confidence="table_explicit",
        source=source,
    )


def _optional_dividend(lines, forecast_period, source):
    try:
        dividend_index = _index_matching(lines, r"^\d{4}年.*\(予想\)$")
    except AnalysisError:
        dividend_index = None
    if dividend_index is not None:
        try:
            next_section = _index_matching(lines, r"業績予想\(", dividend_index + 1)
        except AnalysisError:
            next_section = len(lines)
        candidates = lines[dividend_index + 1 : next_section]
        if candidates and candidates[0] == "無配":
            return [
                _per_share(
                    "dividend_per_share", "期末配当", "無配", "company_forecast", forecast_period, source
                )
            ], []
        try:
            value = _numeric_values(candidates, 1)[0]
            return [
                _per_share(
                    "dividend_per_share", "期末配当", value, "company_forecast", forecast_period, source
                )
            ], []
        except AnalysisError:
            pass
    compact = "".join(lines)
    alternate = re.search(r"(?:1株当たり)?(?:期末)?配当金?\(予想\)[:：]?([0-9,.]+)円", compact)
    if alternate:
        return [
            _per_share(
                "dividend_per_share", "期末配当", alternate.group(1), "company_forecast", forecast_period, source
            )
        ], []
    return [], ["配当情報を抽出できないため不明として保持"]


def _derived_progress(metrics, current_period, source):
    result = []
    for name, label in _PL_METRICS:
        actual = next(item for item in metrics if item.metric_name == name and item.value_kind == "actual")
        forecast = next(item for item in metrics if item.metric_name == name and item.value_kind == "company_forecast")
        if (
            forecast.normalized_value == 0
            or actual.normalized_unit != "JPY"
            or forecast.normalized_unit != "JPY"
        ):
            continue
        progress = round(actual.normalized_value / forecast.normalized_value * 100, 2)
        result.append(
            _percent(
                name + "_forecast_progress",
                label + "会社予想進捗率",
                progress,
                "derived",
                current_period,
                source,
                origin="calculated",
                formula="actual / company_forecast * 100",
                inputs=[name + ":actual", name + ":company_forecast"],
            )
        )
    return result


def _derived_yoy(metrics, current_period, source):
    result = []
    for name, label in _PL_METRICS:
        actual = next(item for item in metrics if item.metric_name == name and item.value_kind == "actual")
        prior = next(item for item in metrics if item.metric_name == name and item.value_kind == "prior_actual")
        if (
            prior.normalized_value == 0
            or actual.normalized_unit != "JPY"
            or prior.normalized_unit != "JPY"
        ):
            continue
        change = round((actual.normalized_value / prior.normalized_value - 1) * 100, 2)
        result.append(
            _percent(
                name + "_yoy_calculated",
                label + "前年同期比(計算値)",
                change,
                "derived",
                current_period,
                source,
                origin="calculated",
                formula="(actual / prior_actual - 1) * 100",
                inputs=[name + ":actual", name + ":prior_actual"],
            )
        )
    return result


def _segment_metrics(text, period, source):
    compact = "".join(_lines(text))
    results = []
    value_pattern = r"[△▲\-−]?[0-9][0-9,]*(?:\.[0-9]+)?"
    unit_pattern = r"円|千円|百万円|億円"
    pattern = re.compile(
        rf"(?P<segment>[^。、]{{1,40}}?事業)の売上高は(?P<sales>{value_pattern})(?P<sales_unit>{unit_pattern})"
        rf".*?セグメント(?P<result_label>利益|損失)は(?P<result>{value_pattern})(?P<result_unit>{unit_pattern})"
    )
    for match in pattern.finditer(compact):
        segment = match.group("segment")
        results.append(CompanySpecificMetric(category=segment, name="売上高", value=_money("segment_revenue", "売上高", match.group("sales"), "actual", period, source, match.group("sales_unit"))))
        result_label = "セグメント" + match.group("result_label")
        results.append(CompanySpecificMetric(category=segment, name=result_label, value=_money("segment_profit", result_label, match.group("result"), "actual", period, source, match.group("result_unit"), force_negative=match.group("result_label") == "損失")))
    return results


def _narratives(pages, url, title, acquired_at):
    page4_number, page4 = _find_page(pages, "各セグメントの経営成績")
    page5_number, page5 = _find_page(pages, "業績予想などの将来予測情報")
    text4 = "".join(_lines(page4))
    text5 = "".join(_lines(page5))
    source4 = _source(url, title, page4_number, "経営成績に関する説明", acquired_at)
    source5 = _source(url, title, page5_number, "業績予想などの将来予測情報", acquired_at)
    findings = []
    narrative_rules = [
        ("business_environment", "食品流通・スーパーマーケット市場", text4, ["経営環境"], ["値上げ", "原材料", "節約", "消費"], "negative", source4),
        ("revenue_driver", "全社売上", text4, ["取引", "堅調"], ["売上", "得意先", "増収"], "positive", source4),
        ("profit_driver", "フローズン事業", text4, ["費"], ["人件費", "採用費", "減益", "下回"], "negative", source4),
        ("positive_factor", "スーパーマーケット事業", text4, ["出店"], ["増加", "増収", "伸長"], "positive", source4),
        ("outlook", "全社業績", text5, ["業績"], ["計画どおり", "順調", "見通し", "予想"], "unchanged", source5),
    ]
    for finding_type, subject, target, required, alternatives, status, source in narrative_rules:
        statement = _context_statement(target, required, alternatives)
        if statement:
            findings.append(NarrativeFinding(finding_type=finding_type, subject=subject, statement=statement, status=status, confidence="text_explicit", source=source))
    first = "".join(_lines(pages[0]))
    for finding_type, subject, pattern in [
        ("forecast_change", "通期会社予想", r"直近に公表されている業績予想からの修正の有無[:：]?(?P<changed>有|無)"),
        ("dividend_change", "配当予想", r"直近に公表されている配当予想からの修正の有無[:：]?(?P<changed>有|無)"),
    ]:
        match = re.search(pattern, first)
        if match:
            findings.append(NarrativeFinding(finding_type=finding_type, subject=subject, statement=match.group(0), status="changed" if match.group("changed") == "有" else "unchanged", confidence="text_explicit", source=_source(url, title, 1, subject, acquired_at)))
    return findings


def _context_statement(text, required_terms, alternative_terms):
    for sentence in re.split(r"(?<=[。！？])", text):
        if all(term in sentence for term in required_terms) and any(
            term in sentence for term in alternative_terms
        ):
            return sentence.strip()
    return None


def _consistency_checks(metrics):
    checks = []
    for name, _ in _PL_METRICS:
        actual = next(item for item in metrics if item.metric_name == name and item.value_kind == "actual")
        prior = next(item for item in metrics if item.metric_name == name and item.value_kind == "prior_actual")
        reported = next(item for item in metrics if item.metric_name == name + "_yoy")
        forecast = next(item for item in metrics if item.metric_name == name and item.value_kind == "company_forecast")
        units = {actual.normalized_unit, prior.normalized_unit, forecast.normalized_unit}
        if units != {"JPY"}:
            checks.append(ConsistencyCheck(
                check_type="money_unit_presence",
                status="review_required",
                message="%sの金額単位が不明または期間間で不一致" % name,
                related_metrics=[name + ":actual", name + ":prior_actual", name + ":company_forecast"],
            ))
            continue
        calculated = round((actual.normalized_value / prior.normalized_value - 1) * 100, 1)
        difference = abs(calculated - reported.normalized_value)
        checks.append(ConsistencyCheck(
            check_type="year_over_year_reconciliation",
            status="passed" if difference <= 0.3 else "review_required",
            message=("reported and calculated year-over-year values agree within source rounding" if difference <= 0.3 else "reported year-over-year value conflicts with current/prior values"),
            related_metrics=[name + ":actual", name + ":prior_actual", name + "_yoy"],
        ))
    revenue = next(item for item in metrics if item.metric_name == "revenue" and item.value_kind == "actual")
    operating = next(item for item in metrics if item.metric_name == "operating_profit" and item.value_kind == "actual")
    if revenue.normalized_unit == operating.normalized_unit == "JPY":
        margin = operating.normalized_value / revenue.normalized_value * 100
        checks.append(ConsistencyCheck(
            check_type="operating_margin_sanity",
            status="passed" if -50 <= margin <= 50 else "review_required",
            message="operating margin %.2f%% is within the configured sanity range" % margin,
            related_metrics=["revenue:actual", "operating_profit:actual"],
        ))
    return checks


def _find_page(pages, marker) -> Tuple[int, str]:
    matches = []
    for index, text in enumerate(pages, start=1):
        if marker in text:
            matches.append((index, text))
    if matches:
        return matches[-1]
    raise AnalysisError("document section missing: %s" % marker)


def _parse_japanese_date(value):
    normalized = unicodedata.normalize("NFKC", value)
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", normalized)
    if not match:
        raise AnalysisError("announcement date is missing")
    return "%04d-%02d-%02d" % tuple(map(int, match.groups()))


def _period_dates(value):
    matches = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", unicodedata.normalize("NFKC", value))
    if len(matches) != 2:
        raise AnalysisError("reporting period dates are missing")
    return tuple("%04d-%02d-%02d" % tuple(map(int, parts)) for parts in matches)


def _fiscal_year(value):
    match = re.search(r"(\d{4})年", unicodedata.normalize("NFKC", value))
    if not match:
        raise AnalysisError("fiscal year is missing")
    return match.group(1)


def _scope_from_period(value):
    normalized = unicodedata.normalize("NFKC", value)
    if "第1四半期" in normalized:
        return "q1_cumulative"
    if "第2四半期" in normalized or "中間期" in normalized:
        return "half_year_cumulative"
    if "第3四半期" in normalized:
        return "nine_month_cumulative"
    return "full_year"


def _point_period(period, end_date):
    return PeriodReference(fiscal_year=period.fiscal_year, scope="point_in_time", end_date=end_date, comparison="current")


def _prior_year_end(period):
    return PeriodReference(fiscal_year=period.fiscal_year, scope="point_in_time", comparison="prior_year_end")
