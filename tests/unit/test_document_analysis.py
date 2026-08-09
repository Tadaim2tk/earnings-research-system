import json
from pathlib import Path

import httpx
import pymupdf
import pytest

from earnings_research.document_analysis.analyzer import AnalysisError, analyze_japanese_earnings_release
from earnings_research.document_analysis.discovery import classify_document, discover_earnings_documents
from earnings_research.document_analysis.pdf import ExtractedPDF, PDFExtractionError, extract_pdf
from earnings_research.document_analysis.pipeline import (
    TemporaryDocumentFetcher,
    analyze_document_url,
    analyze_handoff,
)


def extracted_fixture(reported_operating_yoy="3.6"):
    page1 = "\n".join(
        [
            "2025年３月期",
            "第３四半期決算短信〔日本基準〕(非連結)",
            "2025年２月12日",
            "上場会社名",
            "株式会社アイスコ",
            "コード番号",
            "7698",
            "１．2025年３月期第３四半期の業績（2024年４月１日～2024年12月31日）",
            "（１）経営成績(累計)",
            "売上高",
            "営業利益",
            "経常利益",
            "四半期純利益",
            "2025年３月期第３四半期",
            "42,415",
            "9.0",
            "542",
            reported_operating_yoy,
            "589",
            "3.9",
            "383",
            "4.7",
            "2024年３月期第３四半期",
            "38,912",
            "12.6",
            "524",
            "232.9",
            "567",
            "186.8",
            "366",
            "133.9",
            "１株当たり",
            "四半期純利益",
            "2025年３月期第３四半期",
            "98.44",
            "95.35",
            "2024年３月期第３四半期",
            "94.78",
            "92.91",
            "（２）財政状態",
            "2025年３月期第３四半期",
            "17,854",
            "3,742",
            "21.0",
            "2024年３月期",
            "16,756",
            "3,431",
            "20.5",
            "2025年３月期(予想)",
            "9.5",
            "３．2025年３月期の業績予想（2024年４月１日～2025年３月31日）",
            "通期",
            "54,000",
            "6.9",
            "500",
            "10.5",
            "550",
            "10.5",
            "355",
            "11.3",
            "91.26",
            "直近に公表されている配当予想からの修正の有無：無",
            "直近に公表されている業績予想からの修正の有無：無",
        ]
    )
    narrative = "\n".join(
        [
            "経営成績に関する説明",
            "当社が身を置く食品流通業及びスーパーマーケット業につきましては、原材料価格の高騰に伴う食品の値上げにより、厳しい経営環境となっております。",
            "昨年の猛暑の反動があった一方で、主要得意先との取引が堅調に推移したことにより",
            "各セグメントの経営成績は以下のとおりであります。",
            "フローズン事業の売上高は37,097百万円（前年同期比8.9％増）、セグメント利益は474百万円（前年同期比19.7％減）となりました。",
            "人事制度の改定や、採用を強化した結果、人件費や採用費が増加したことにより、前年同期を下回りました。",
            "スーパーマーケット事業の売上高は5,318百万円（前年同期比9.5％増）、セグメント利益は68百万円（前年同期は損失）となりました。",
            "スーパー生鮮館TAIGA藤が丘店を出店したことにより増加しております。",
        ]
    )
    outlook = "業績予想などの将来予測情報に関する説明\n2025年３月期の業績は、計画どおりに推移しております。"
    return ExtractedPDF(pages=[page1, "index", narrative, outlook], sha256="a" * 64)


def analyze_fixture(extracted=None):
    return analyze_japanese_earnings_release(
        extracted or extracted_fixture(),
        "https://example.com/results.pdf",
        "2025年３月期第３四半期決算短信〔日本基準〕(非連結)",
        "2026-08-10T07:00:00+09:00",
    )


def test_financial_metrics_keep_units_periods_and_value_kinds_separate():
    result = analyze_fixture()
    revenue = [item for item in result.financial_metrics if item.metric_name == "revenue"]
    assert [(item.value_kind, item.displayed_value) for item in revenue] == [
        ("actual", "42,415"),
        ("prior_actual", "38,912"),
        ("company_forecast", "54,000"),
    ]
    assert revenue[0].normalized_value == 42_415_000_000
    assert revenue[0].normalized_unit == "JPY"
    assert revenue[0].period.scope == "nine_month_cumulative"
    assert revenue[2].period.scope == "full_year"


def test_calculated_progress_and_reported_yoy_are_distinguished():
    result = analyze_fixture()
    yoy = next(item for item in result.financial_metrics if item.metric_name == "revenue_yoy")
    calculated_yoy = next(
        item for item in result.financial_metrics if item.metric_name == "revenue_yoy_calculated"
    )
    progress = next(item for item in result.financial_metrics if item.metric_name == "revenue_forecast_progress")
    assert yoy.origin == "reported"
    assert calculated_yoy.origin == "calculated"
    assert calculated_yoy.formula == "(actual / prior_actual - 1) * 100"
    assert progress.origin == "calculated"
    assert progress.normalized_value == 78.55
    assert progress.formula == "actual / company_forecast * 100"


def test_page_sources_and_company_specific_metrics_are_preserved():
    result = analyze_fixture()
    assert result.financial_metrics[0].source.page_number == 1
    segments = {(item.category, item.name): item.value.normalized_value for item in result.company_specific_metrics}
    assert segments[("フローズン事業", "売上高")] == 37_097_000_000
    assert segments[("スーパーマーケット事業", "セグメント利益")] == 68_000_000
    assert all(item.value.source.page_number == 3 for item in result.company_specific_metrics)


def test_narratives_do_not_invent_forecast_or_dividend_changes():
    result = analyze_fixture()
    statuses = {item.finding_type: item.status for item in result.narrative_findings}
    assert statuses["forecast_change"] == "unchanged"
    assert statuses["dividend_change"] == "unchanged"
    assert statuses["profit_driver"] == "negative"


def test_conflicting_reported_yoy_marks_review_required_without_dropping_metrics():
    result = analyze_fixture(extracted_fixture(reported_operating_yoy="99.0"))
    assert any(item.status == "review_required" for item in result.consistency_checks)
    assert any(item.metric_name == "revenue" for item in result.financial_metrics)
    assert result.unresolved_items


def test_missing_required_table_value_is_not_guessed():
    broken = extracted_fixture()
    broken.pages[0] = broken.pages[0].replace("\n383\n4.7", "\n4.7")
    with pytest.raises(AnalysisError):
        analyze_fixture(broken)


def test_pdf_text_extraction_and_textless_and_malformed(tmp_path):
    text_pdf = tmp_path / "text.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Earnings release text " * 10)
    document.save(text_pdf)
    document.close()
    assert "Earnings release" in extract_pdf(text_pdf).pages[0]

    textless_pdf = tmp_path / "textless.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(textless_pdf)
    document.close()
    with pytest.raises(PDFExtractionError, match="textless"):
        extract_pdf(textless_pdf)

    malformed = tmp_path / "malformed.pdf"
    malformed.write_bytes(b"not a PDF")
    with pytest.raises(PDFExtractionError, match="malformed"):
        extract_pdf(malformed)


def test_temporary_fetcher_removes_raw_pdf(tmp_path):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "temporary PDF " * 10)
    raw = document.tobytes()
    document.close()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=raw, headers={"content-type": "application/pdf"}))
    fetcher = TemporaryDocumentFetcher(lambda: httpx.Client(transport=transport))
    with fetcher.pdf("https://example.com/results.pdf") as path:
        captured = path
        assert path.exists()
    assert not captured.exists()


def test_document_discovery_selects_only_target_earnings_pdfs():
    html = """
    <a href="/q3.pdf">2025年3月期 第3四半期決算短信</a>
    <a href="/briefing.pdf">決算説明資料</a>
    <a href="/notice.pdf">人事異動のお知らせ</a>
    """
    candidates = discover_earnings_documents(html, "https://example.com/ir/")
    assert [item.document_type for item in candidates] == ["earnings_release", "earnings_presentation"]
    assert classify_document("一般IR", "https://example.com/notice.pdf") is None


def test_monitor_handoff_calls_analysis_and_records_non_target_exclusion(tmp_path, monkeypatch):
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({
        "source_url": "https://example.com/ir/",
        "last_seen_title": "IR library",
        "monitor_target_id": "MON-1",
    }), encoding="utf-8")

    class Fetcher:
        def html(self, _url):
            return '<a href="q3.pdf">第3四半期決算短信</a><a href="notice.pdf">人事異動</a>'

    monkeypatch.setattr(
        "earnings_research.document_analysis.pipeline.analyze_document_url",
        lambda *_args, **_kwargs: analyze_fixture(),
    )
    result = analyze_handoff(handoff, tmp_path / "out", fetcher=Fetcher())
    assert result["status"] == "analysis_completed"
    assert len(result["analyzed_outputs"]) == 1
    assert (tmp_path / "out" / "dispatch_result.json").exists()


def test_non_earnings_handoff_continues_without_analysis(tmp_path):
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({
        "source_url": "https://example.com/ir/",
        "last_seen_title": "IR library",
        "monitor_target_id": "MON-1",
    }), encoding="utf-8")

    class Fetcher:
        def html(self, _url):
            return '<a href="notice.pdf">人事異動のお知らせ</a>'

    result = analyze_handoff(handoff, tmp_path / "out", fetcher=Fetcher())
    assert result["status"] == "no_target_documents"
    assert result["analyzed_outputs"] == []


def test_presentation_type_is_preserved_when_standard_financial_tables_exist():
    result = analyze_japanese_earnings_release(
        extracted_fixture(),
        "https://example.com/presentation.pdf",
        "2025年3月期 第3四半期決算説明資料",
        "2026-08-10T07:00:00+09:00",
        document_type="earnings_presentation",
    )
    assert result.document.document_type == "earnings_presentation"
    assert result.status == "analyzed"


def test_unparseable_pdf_returns_explicit_status_and_no_guess(tmp_path, monkeypatch):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "not a standard earnings table " * 8)
    raw = document.tobytes()
    document.close()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=raw, headers={"content-type": "application/pdf"}))
    fetcher = TemporaryDocumentFetcher(lambda: httpx.Client(transport=transport))
    result = analyze_document_url(
        "https://example.com/results.pdf",
        "2025年3月期 決算短信",
        "2026-08-10T07:00:00+09:00",
        fetcher,
    )
    assert result.status == "unparseable"
    assert result.financial_metrics == []
    assert result.unresolved_items[0].startswith("解析不能")


def test_committed_iceco_proof_remains_machine_readable():
    from earnings_research.document_analysis.models import EarningsDocumentAnalysis

    path = Path(__file__).parents[2] / "data/research/iceco/EDA-7698-20250212.json"
    result = EarningsDocumentAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
    revenue = next(
        item
        for item in result.financial_metrics
        if item.metric_name == "revenue" and item.value_kind == "actual"
    )
    assert result.document.ticker == "7698"
    assert result.document.reporting_scope == "nine_month_cumulative"
    assert revenue.normalized_value == 42_415_000_000
    assert result.raw_document_retained is False
    assert result.next_stage == "ready_for_pre_event_comparison"
