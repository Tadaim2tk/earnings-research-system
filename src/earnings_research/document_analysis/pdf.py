"""Text-first PDF extraction without OCR."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pymupdf


class PDFExtractionError(ValueError):
    """PDF content cannot be safely extracted as text."""


@dataclass(frozen=True)
class ExtractedPDF:
    pages: List[str]
    sha256: str


def extract_pdf(path: Path) -> ExtractedPDF:
    path = Path(path)
    try:
        raw = path.read_bytes()
        document = pymupdf.open(stream=raw, filetype="pdf")
    except (OSError, RuntimeError, ValueError) as exc:
        raise PDFExtractionError("malformed PDF") from exc
    try:
        pages = [page.get_text("text").strip() for page in document]
    finally:
        document.close()
    if not pages or sum(len(page) for page in pages) < 80:
        raise PDFExtractionError("textless PDF; OCR is not used")
    return ExtractedPDF(pages=pages, sha256=hashlib.sha256(raw).hexdigest())
