"""Conservative classification of earnings-document links."""

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urljoin, urlsplit


@dataclass(frozen=True)
class DocumentCandidate:
    url: str
    title: str
    document_type: str


def classify_document(title: str, url: str) -> Optional[str]:
    normalized = "".join((title or "").split())
    path = urlsplit(url).path.lower()
    if not path.endswith(".pdf"):
        return None
    if "決算短信" in normalized:
        return "earnings_release"
    if "決算説明" in normalized:
        return "earnings_presentation"
    return None


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._parts = []

    def handle_data(self, data):
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._parts).strip()))
            self._href = None
            self._parts = []


def discover_earnings_documents(html: str, base_url: str) -> List[DocumentCandidate]:
    parser = _LinkParser()
    parser.feed(html)
    candidates = []
    seen = set()
    for href, title in parser.links:
        url = urljoin(base_url, href)
        document_type = classify_document(title, url)
        if document_type and url not in seen:
            candidates.append(DocumentCandidate(url=url, title=title, document_type=document_type))
            seen.add(url)
    return candidates
