"""Retrieve an approved disclosure document without leaving the approved list.

The generic document fetcher follows redirects automatically, which means an
approved publisher can hand the client on to any other host and the narrow
grant in ``acquisition`` stops being narrow. Measured before this existed: a
302 from an approved host to an arbitrary one was followed without complaint.

Redirects are therefore resolved one hop at a time here, with the destination
checked against the same approved list as the original URL, and a refusal from
the publisher ends the attempt rather than being retried.
"""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx

from earnings_research.document_analysis.acquisition import (
    REFUSAL_STATUSES,
    AcquisitionNotAuthorized,
    authorized_host,
)
from earnings_research.document_analysis.pipeline import (
    MAX_PDF_BYTES,
    DocumentAcquisitionError,
    TemporaryDocumentFetcher,
)

MAX_REDIRECT_HOPS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 30.0
USER_AGENT = "EarningsResearchSystem-DocumentAnalysis/1.0"


class DocumentRefusedError(DocumentAcquisitionError):
    """The publisher answered with a refusal. It is not retried."""


class GuardedDocumentFetcher(TemporaryDocumentFetcher):
    """Fetch one PDF, never leaving the hosts the Human approved."""

    def __init__(self, client_factory=None) -> None:
        super().__init__(
            client_factory
            or (
                lambda: httpx.Client(
                    timeout=httpx.Timeout(
                        READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
                    ),
                    follow_redirects=False,
                    trust_env=False,
                )
            )
        )

    def html(self, url: str) -> str:
        """Discovery is outside the grant, so this fetcher does not do it.

        Inheriting the generic implementation would mean a future caller could
        pass this fetcher to the discovery pipeline and get link following on
        hosts nobody approved.
        """
        raise AcquisitionNotAuthorized("page retrieval is outside the approved grant")

    @contextmanager
    def pdf(self, url: str) -> Iterator[Path]:
        if not authorized_host(url):
            raise AcquisitionNotAuthorized("document URL is outside the approved publishers")
        with tempfile.TemporaryDirectory(prefix="ers-earnings-pdf-") as directory:
            path = Path(directory) / "source.pdf"
            with self._client_factory() as client:
                self._download(client, url, path)
            yield path

    def _download(self, client: httpx.Client, url: str, path: Path) -> None:
        current = url
        for _hop in range(MAX_REDIRECT_HOPS + 1):
            with client.stream(
                "GET", current, headers={"User-Agent": USER_AGENT}
            ) as response:
                if response.status_code in REFUSAL_STATUSES:
                    raise DocumentRefusedError(
                        "publisher refused the request with status %s" % response.status_code
                    )
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location", "")
                    target = str(httpx.URL(current).join(location)) if location else ""
                    if not authorized_host(target):
                        raise AcquisitionNotAuthorized(
                            "redirect leaves the approved publishers"
                        )
                    current = target
                    continue
                if response.status_code != 200:
                    raise DocumentAcquisitionError(
                        "PDF request failed with status %s" % response.status_code
                    )
                media_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if media_type != "application/pdf":
                    raise DocumentAcquisitionError("response is not a PDF")
                total = 0
                with path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_PDF_BYTES:
                            raise DocumentAcquisitionError("PDF exceeds maximum size")
                        handle.write(chunk)
                return
        raise DocumentAcquisitionError("redirect hop limit exceeded")
