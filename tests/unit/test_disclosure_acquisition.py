import json
from pathlib import Path

import pytest

from earnings_research.document_analysis.acquisition import (
    AUTHORIZED_DOCUMENT_HOSTS,
    MAX_DOCUMENTS_PER_RUN,
    AcquisitionNotAuthorized,
    authorized_host,
    handed_over_documents,
    within_run_limit,
)
from earnings_research.document_analysis.disclosure import analyze_named_disclosure

TDNET_PDF = "https://www.release.tdnet.info/inbs/140120260807514298.pdf"
TITLE = "2027年３月期第１四半期決算短信〔日本基準〕(非連結)"


def handoff(**overrides):
    payload = {
        "monitor_target_id": "ICECO_TDNET_INDEX",
        "source_category": "tdnet_index_json",
        "source_url": "https://webapi.yanoshin.jp/webapi/tdnet/list/7698.json2?limit=10",
        "last_seen_title": TITLE,
        "last_seen_document_url": TDNET_PDF,
    }
    payload.update(overrides)
    return payload


def write_handoff(tmp_path, payload):
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("host", sorted(AUTHORIZED_DOCUMENT_HOSTS))
def test_approved_publishers_are_accepted(host):
    assert authorized_host("https://%s/inbs/doc.pdf" % host)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/doc.pdf",
        "http://www.release.tdnet.info/doc.pdf",
        "https://user:pass@www.release.tdnet.info/doc.pdf",
        "https://@www.release.tdnet.info/doc.pdf",
        "https://evil.www.release.tdnet.info/doc.pdf",
        "",
    ],
)
def test_anything_else_is_not_a_publisher_this_pilot_may_read(url):
    assert not authorized_host(url)


def test_an_unexpected_publisher_is_raised_not_skipped():
    """A silent skip would look identical to a disclosure with no document."""
    with pytest.raises(AcquisitionNotAuthorized, match="example.invalid"):
        handed_over_documents(handoff(last_seen_document_url="https://example.invalid/a.pdf"))


@pytest.mark.parametrize("field", ["last_seen_document_url", "last_seen_title"])
def test_a_handoff_naming_nothing_asks_for_nothing(field):
    assert handed_over_documents(handoff(**{field: None})) == []


def test_one_announcement_is_one_document():
    assert len(handed_over_documents(handoff())) == 1


def test_a_batch_over_the_run_limit_is_refused():
    batch = [{"url": TDNET_PDF, "title": TITLE}] * (MAX_DOCUMENTS_PER_RUN + 1)
    assert within_run_limit(batch) is not None
    assert within_run_limit(batch[:MAX_DOCUMENTS_PER_RUN]) is None


def test_named_document_is_read_without_any_discovery(tmp_path, monkeypatch):
    calls = []

    def fake_analyze(url, title, acquired_at=None, fetcher=None):
        calls.append((url, title))
        return _stub_analysis()

    monkeypatch.setattr(
        "earnings_research.document_analysis.disclosure.analyze_document_url", fake_analyze
    )
    monkeypatch.setattr(
        "earnings_research.document_analysis.disclosure.analyze_handoff",
        lambda *_args, **_kwargs: pytest.fail("discovery must not run for a named document"),
    )
    dispatch = analyze_named_disclosure(
        handoff_path=write_handoff(tmp_path, handoff()), output_dir=tmp_path / "out"
    )
    assert calls == [(TDNET_PDF, TITLE)]
    assert dispatch["status"] == "analysis_completed"
    assert dispatch["raw_document_retained"] is False


def test_a_handoff_without_a_named_document_still_uses_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "earnings_research.document_analysis.disclosure.analyze_handoff",
        lambda *_args, **_kwargs: {"status": "no_target_documents", "analyzed_outputs": []},
    )
    dispatch = analyze_named_disclosure(
        handoff_path=write_handoff(tmp_path, handoff(last_seen_document_url=None)),
        output_dir=tmp_path / "out",
    )
    assert dispatch["status"] == "no_target_documents"


def test_a_named_document_that_is_not_an_earnings_release_is_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "earnings_research.document_analysis.disclosure.analyze_document_url",
        lambda *_args, **_kwargs: pytest.fail("a non-earnings document must not be read"),
    )
    dispatch = analyze_named_disclosure(
        handoff_path=write_handoff(tmp_path, handoff(last_seen_title="人事異動に関するお知らせ")),
        output_dir=tmp_path / "out",
    )
    assert dispatch["status"] == "no_target_documents"
    assert dispatch["excluded_document_count"] == 1


def _stub_analysis():
    """Reuse the analyzer's own output so the stub cannot drift from the model."""
    from tests.unit.test_document_analysis import analyze_fixture

    return analyze_fixture()
