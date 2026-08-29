"""Which disclosure documents this pilot is allowed to retrieve, and how many.

Acquisition policy lives here rather than in the analysis pipeline so that the
question "may this document be fetched at all" is answered in one place, by
data, before any request is made.

The Human authorized retrieval from the publishers listed below (ERS-ADR-0033).
The authorization is deliberately narrow. Only a document URL that a permitted
index already handed over is retrieved; nothing is discovered by following
links, no directory is walked, and a single run stops after a small number of
documents. A refusal from the publisher ends the attempt instead of being
retried.
"""

from typing import Dict, List, Optional
from urllib.parse import urlsplit

# Publishers of the statutory timely-disclosure documents themselves.
AUTHORIZED_DOCUMENT_HOSTS = frozenset({"www.release.tdnet.info", "contents.xj-storage.jp"})

# One announcement is one document, sometimes with supplementary material. A
# handoff asking for more than this is malformed, and a malformed handoff must
# not become a burst of requests.
MAX_DOCUMENTS_PER_RUN = 4

# 日々の掃き出しで1回に回る**開示の数**。上の定数とは別の問いに答えている——
# あちらは「1つの開示に対する handoff が壊れていないか」で、こちらは「1回の
# 実行でいくつの開示を見るか」である。最初はあちらを流用したが、それだと
# 上限を上げたときに handoff の壊れ検査まで緩む。
#
# 台帳の248社では、決算の多い日で8〜9社が同じ日に出す。20 はそれに余裕を持たせた
# 値で、1.2秒間隔なら25秒ぶんの取得にあたる。Human承認: 2026-08-30。
MAX_DOCUMENTS_PER_SWEEP = 20

# A refusal is an instruction, not a transient error. Retrying it is what turns
# one unwelcome request into a pattern.
REFUSAL_STATUSES = frozenset({401, 403, 429, 451})


class AcquisitionNotAuthorized(ValueError):
    """The document is outside what the Human approved for retrieval."""


def authorized_host(url: str) -> bool:
    text = url or ""
    # A newline or a NUL in a URL is never legitimate here, and both have a long
    # history of being read differently by different layers.
    if any(character in text for character in "\n\r\t\x00") or text.strip() != text:
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        return False
    # A different port on an approved name is a different service.
    try:
        if parts.port not in (None, 443):
            return False
    except ValueError:
        return False
    return (parts.hostname or "").lower() in AUTHORIZED_DOCUMENT_HOSTS


def handed_over_documents(handoff: Dict) -> List[Dict[str, str]]:
    """Return the documents a monitor handoff already named.

    Returns an empty list when the handoff names nothing, which is the ordinary
    case for a schedule page. Raises when it names something this pilot is not
    allowed to retrieve, so an unexpected publisher is visible rather than
    quietly skipped.
    """
    url = handoff.get("last_seen_document_url")
    title = handoff.get("last_seen_title")
    if not url or not title:
        return []
    if not authorized_host(str(url)):
        raise AcquisitionNotAuthorized(
            "document publisher is outside the approved list: %s"
            % (urlsplit(str(url)).hostname or "unknown")
        )
    return [{"url": str(url), "title": str(title)}]


def within_run_limit(documents: List[Dict[str, str]]) -> Optional[str]:
    """Return the reason a batch exceeds the per-run bound, or None."""
    if len(documents) > MAX_DOCUMENTS_PER_RUN:
        return "handoff names %d documents, more than the %d allowed in one run" % (
            len(documents),
            MAX_DOCUMENTS_PER_RUN,
        )
    return None
