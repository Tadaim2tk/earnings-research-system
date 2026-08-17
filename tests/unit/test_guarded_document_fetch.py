import httpx
import pytest

from earnings_research.document_analysis.acquisition import AcquisitionNotAuthorized
from earnings_research.document_analysis.guarded_fetch import (
    MAX_REDIRECT_HOPS,
    DocumentRefusedError,
    GuardedDocumentFetcher,
)
from earnings_research.document_analysis.pipeline import DocumentAcquisitionError

APPROVED = "https://www.release.tdnet.info/inbs/140120260807514298.pdf"
OTHER_APPROVED = "https://contents.xj-storage.jp/xcontents/a.pdf"
PDF_BODY = b"%PDF-1.4 minimal"


def pdf_response(_request):
    return httpx.Response(200, content=PDF_BODY, headers={"content-type": "application/pdf"})


def fetch(handler, url=APPROVED):
    """Run one guarded fetch and return (outcome, hosts actually contacted)."""
    contacted = []

    def recording(request):
        contacted.append(str(request.url))
        return handler(request)

    fetcher = GuardedDocumentFetcher(
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(recording), follow_redirects=False
        )
    )
    try:
        with fetcher.pdf(url) as path:
            return path.read_bytes(), contacted
    except Exception as exc:  # noqa: BLE001 - the type is the assertion
        return exc, contacted


def test_an_approved_document_is_read():
    body, contacted = fetch(pdf_response)
    assert body == PDF_BODY
    assert contacted == [APPROVED]


@pytest.mark.parametrize(
    "url",
    [
        "https://elsewhere.invalid/a.pdf",
        "https://evil.www.release.tdnet.info/a.pdf",
        "https://www.release.tdnet.info.evil.com/a.pdf",
        "https://www.release.tdnet.info./a.pdf",
        "http://www.release.tdnet.info/a.pdf",
        "https://@www.release.tdnet.info/a.pdf",
        "https://user:pass@www.release.tdnet.info/a.pdf",
        "https://www.release.tdnet.info@evil.invalid/a.pdf",
        "https://www.release.tdnet.info:8443/a.pdf",
        "https://www.release.tdnet.info\n/a.pdf",
        "https://www.release.tdnet.info/a.pdf\x00evil",
        " https://www.release.tdnet.info/a.pdf",
        "https://192.0.2.1/a.pdf",
        "https://[2001:db8::1]/a.pdf",
        "data:application/pdf;base64,AAAA",
        "javascript:alert(1)",
        "ftp://www.release.tdnet.info/a.pdf",
        "file:///etc/passwd",
        "",
    ],
)
def test_an_unapproved_url_sends_no_request_at_all(url):
    outcome, contacted = fetch(pdf_response, url=url)
    assert isinstance(outcome, AcquisitionNotAuthorized)
    assert contacted == []


def test_a_redirect_off_the_approved_publishers_is_not_followed():
    """The generic fetcher follows redirects, which would widen the grant."""

    def handler(request):
        if "release.tdnet.info" in request.url.host:
            return httpx.Response(302, headers={"location": "https://elsewhere.invalid/leak.pdf"})
        return pdf_response(request)

    outcome, contacted = fetch(handler)
    assert isinstance(outcome, AcquisitionNotAuthorized)
    assert contacted == [APPROVED]


def test_a_redirect_between_approved_publishers_is_followed():
    def handler(request):
        if "release.tdnet.info" in request.url.host:
            return httpx.Response(302, headers={"location": OTHER_APPROVED})
        return pdf_response(request)

    body, contacted = fetch(handler)
    assert body == PDF_BODY
    assert contacted == [APPROVED, OTHER_APPROVED]


def test_a_relative_redirect_stays_on_the_same_publisher():
    def handler(request):
        if request.url.path.endswith("140120260807514298.pdf"):
            return httpx.Response(302, headers={"location": "/inbs/moved.pdf"})
        return pdf_response(request)

    body, contacted = fetch(handler)
    assert body == PDF_BODY
    assert contacted[-1] == "https://www.release.tdnet.info/inbs/moved.pdf"


def test_a_redirect_loop_stops_at_the_hop_limit():
    def handler(_request):
        return httpx.Response(302, headers={"location": APPROVED})

    outcome, contacted = fetch(handler)
    assert isinstance(outcome, DocumentAcquisitionError)
    # Pinned, not derived: reading the constant here would pass at any value.
    assert MAX_REDIRECT_HOPS == 3
    assert len(contacted) == 4


def test_the_default_client_refuses_an_offsite_redirect(monkeypatch):
    """Without a factory of our own, the shipped client settings must hold.

    Every other redirect test injects follow_redirects=False, so flipping the
    real default to True left them all green while the fetch walked off the
    approved list.
    """
    contacted = []
    captured = {}
    real_client = httpx.Client

    def recording(request):
        contacted.append(str(request.url))
        if "release.tdnet.info" in request.url.host:
            return httpx.Response(302, headers={"location": "https://elsewhere.invalid/leak.pdf"})
        return pdf_response(request)

    def client_factory(**kwargs):
        captured.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(recording)
        return real_client(**kwargs)

    monkeypatch.setattr("earnings_research.document_analysis.guarded_fetch.httpx.Client", client_factory)
    with pytest.raises(AcquisitionNotAuthorized):
        with GuardedDocumentFetcher().pdf(APPROVED):
            pass
    assert contacted == [APPROVED]
    assert captured["follow_redirects"] is False
    assert captured["trust_env"] is False


def test_the_guarded_fetcher_does_not_retrieve_pages():
    """Discovery on an approved host would still be link following."""
    with pytest.raises(AcquisitionNotAuthorized):
        GuardedDocumentFetcher().html(APPROVED)


@pytest.mark.parametrize("status", [401, 403, 429, 451])
def test_a_refusal_is_not_retried(status):
    outcome, contacted = fetch(lambda _request: httpx.Response(status))
    assert isinstance(outcome, DocumentRefusedError)
    assert contacted == [APPROVED]


@pytest.mark.parametrize("status", [404, 410, 500, 503])
def test_other_failures_are_reported_without_a_body(status):
    outcome, _ = fetch(lambda _request: httpx.Response(status))
    assert isinstance(outcome, DocumentAcquisitionError)
    assert not isinstance(outcome, DocumentRefusedError)


def test_a_non_pdf_body_is_refused():
    outcome, _ = fetch(
        lambda _request: httpx.Response(
            200, content=b"<html>", headers={"content-type": "text/html"}
        )
    )
    assert isinstance(outcome, DocumentAcquisitionError)


def test_an_oversized_document_is_cut_off():
    def handler(_request):
        return httpx.Response(
            200, content=b"x" * (21 * 1024 * 1024), headers={"content-type": "application/pdf"}
        )

    outcome, _ = fetch(handler)
    assert isinstance(outcome, DocumentAcquisitionError)
    assert "maximum size" in str(outcome)


def test_the_document_is_deleted_after_use():
    fetcher = GuardedDocumentFetcher(
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(pdf_response), follow_redirects=False
        )
    )
    with fetcher.pdf(APPROVED) as path:
        held = path
        assert held.is_file()
    assert not held.exists()
