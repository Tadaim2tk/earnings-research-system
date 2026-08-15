"""Temporary acquisition and end-to-end earnings-document analysis."""

import json
import hashlib
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional
from urllib.parse import urlsplit

import httpx

from earnings_research.document_analysis.analyzer import AnalysisError, analyze_japanese_earnings_release
from earnings_research.document_analysis.discovery import classify_document, discover_earnings_documents
from earnings_research.document_analysis.pdf import PDFExtractionError, extract_pdf
from earnings_research.document_analysis.models import DocumentIdentity, EarningsDocumentAnalysis

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024


class DocumentAcquisitionError(ValueError):
    """A remote document cannot be acquired under the bounded contract."""


class TemporaryDocumentFetcher:
    def __init__(self, client_factory: Optional[Callable[[], httpx.Client]] = None) -> None:
        self._client_factory = client_factory or (
            lambda: httpx.Client(timeout=httpx.Timeout(20.0), follow_redirects=True)
        )

    @contextmanager
    def pdf(self, url: str) -> Iterator[Path]:
        _require_public_https(url)
        with tempfile.TemporaryDirectory(prefix="ers-earnings-pdf-") as directory:
            path = Path(directory) / "source.pdf"
            with self._client_factory() as client:
                with client.stream("GET", url, headers={"User-Agent": "EarningsResearchSystem-DocumentAnalysis/1.0"}) as response:
                    if response.status_code != 200:
                        raise DocumentAcquisitionError("PDF request failed with status %s" % response.status_code)
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if media_type != "application/pdf":
                        raise DocumentAcquisitionError("response is not a PDF")
                    total = 0
                    with path.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > MAX_PDF_BYTES:
                                raise DocumentAcquisitionError("PDF exceeds maximum size")
                            handle.write(chunk)
            try:
                yield path
            finally:
                # TemporaryDirectory removes the raw document even when parsing fails.
                pass

    def html(self, url: str) -> str:
        _require_public_https(url)
        with self._client_factory() as client:
            response = client.get(url, headers={"User-Agent": "EarningsResearchSystem-DocumentAnalysis/1.0"})
        if response.status_code != 200:
            raise DocumentAcquisitionError("HTML request failed with status %s" % response.status_code)
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "text/html":
            raise DocumentAcquisitionError("response is not HTML")
        if len(response.content) > MAX_HTML_BYTES:
            raise DocumentAcquisitionError("HTML exceeds maximum size")
        return response.text


def analyze_document_url(
    url: str,
    title: str,
    acquired_at: Optional[str] = None,
    fetcher: Optional[TemporaryDocumentFetcher] = None,
):
    document_type = classify_document(title, url)
    if document_type is None:
        raise AnalysisError("document is not an earnings release or earnings presentation")
    acquired_at = acquired_at or datetime.now(timezone.utc).isoformat()
    fetcher = fetcher or TemporaryDocumentFetcher()
    with fetcher.pdf(url) as temporary_pdf:
        raw_hash = hashlib.sha256(temporary_pdf.read_bytes()).hexdigest()
        try:
            extracted = extract_pdf(temporary_pdf)
            result = analyze_japanese_earnings_release(
                extracted, url, title, acquired_at, document_type=document_type
            )
        except (PDFExtractionError, AnalysisError) as exc:
            result = _unparseable_result(
                url, title, acquired_at, document_type, raw_hash, str(exc)
            )
    if temporary_pdf.exists():
        raise RuntimeError("temporary raw PDF was not deleted")
    return result


_INDEX_ONLY_CATEGORIES = {"tdnet_index_json"}


def analyze_handoff(
    handoff_path: Path,
    output_dir: Path,
    acquired_at: Optional[str] = None,
    fetcher: Optional[TemporaryDocumentFetcher] = None,
) -> Dict[str, object]:
    payload = json.loads(Path(handoff_path).read_text(encoding="utf-8"))
    fetcher = fetcher or TemporaryDocumentFetcher()
    source_url = payload["source_url"]
    candidates = []
    if payload.get("source_category") in _INDEX_ONLY_CATEGORIES:
        # A disclosure index is metadata, not a document, and it is only
        # authorized for the hardened monitoring adapter. Re-fetching it here
        # would add an unpinned request that skips the robots check, and the
        # documents it points at live on hosts that forbid automated access.
        candidates = []
    else:
        direct_type = classify_document(payload.get("last_seen_title") or "", source_url)
        if direct_type:
            candidates = [{"url": source_url, "title": payload.get("last_seen_title") or source_url}]
        else:
            html = fetcher.html(source_url)
            candidates = [candidate.__dict__ for candidate in discover_earnings_documents(html, source_url)]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    analyzed = []
    excluded = 0
    for candidate in candidates:
        document_type = classify_document(candidate["title"], candidate["url"])
        if document_type is None:
            excluded += 1
            continue
        result = analyze_document_url(candidate["url"], candidate["title"], acquired_at, fetcher)
        path = output_dir / (result.analysis_id + ".json")
        write_analysis(result, path)
        analyzed.append(str(path))
    dispatch = {
        "dispatch_version": "earnings_document_dispatch_v1",
        "status": "analysis_completed" if analyzed else "no_target_documents",
        "monitor_target_id": payload.get("monitor_target_id"),
        "analyzed_outputs": analyzed,
        "excluded_document_count": excluded,
        "raw_document_retained": False,
    }
    (output_dir / "dispatch_result.json").write_text(
        json.dumps(dispatch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return dispatch


def write_analysis(result, output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require_public_https(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise DocumentAcquisitionError("document URL must be public HTTPS without userinfo")


def _unparseable_result(url, title, acquired_at, document_type, source_hash, reason):
    normalized = title.replace(" ", "")
    ticker_match = re.search(r"(?:コード|\()([0-9]{4})(?:\)|番)", normalized)
    period_match = re.search(r"([0-9]{4}年[^決]{0,20})決算", normalized)
    date_value = acquired_at[:10]
    return EarningsDocumentAnalysis(
        analysis_id="EDA-UNPARSEABLE-%s" % source_hash[:12],
        status="unparseable",
        document=DocumentIdentity(
            company_name="unknown",
            ticker=ticker_match.group(1) if ticker_match else "unknown",
            accounting_period=period_match.group(1) if period_match else "unknown",
            reporting_scope="unknown",
            announcement_date=date_value,
            document_type=document_type,
            document_title=title,
            source_url=url,
            source_sha256=source_hash,
            acquired_at=acquired_at,
            page_count=0,
        ),
        unresolved_items=["解析不能: %s" % reason],
        next_stage="analysis_not_available",
    )
