"""Canonical metadata_v1 fingerprint generation."""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Mapping, Optional
from urllib.parse import SplitResult, urlsplit, urlunsplit

from earnings_research.monitoring.models import SourceObservation

FINGERPRINT_VERSION = "metadata_v1"
_WHITESPACE = re.compile(r"\s+")


def canonicalize_url(value: str) -> str:
    """Lowercase scheme and host, remove fragments, and preserve path/query case."""
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.port is not None:
        hostname = "%s:%s" % (hostname, parsed.port)
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += ":" + parsed.password
        hostname = userinfo + "@" + hostname
    normalized = SplitResult(parsed.scheme.lower(), hostname, parsed.path, parsed.query, "")
    return urlunsplit(normalized)


def canonicalize_title(value: Optional[str]) -> Optional[str]:
    """Apply NFKC, trim, and collapse consecutive whitespace."""
    if value is None:
        return None
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).strip())


def canonicalize_datetime(value: Optional[datetime]) -> Optional[str]:
    """Convert an aware datetime to an ISO 8601 UTC representation."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("monitor fingerprint datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def canonicalize_stable_metadata(
    values: Mapping[str, Optional[str]],
) -> List[List[Optional[str]]]:
    """Order only caller-approved stable metadata keys."""
    return [[key, values[key]] for key in sorted(values)]


def metadata_fingerprint_payload(observation: SourceObservation) -> List[list]:
    """Return the exact ordered metadata_v1 hash input."""
    return [
        ["source_url", canonicalize_url(observation.source_url)],
        ["title", canonicalize_title(observation.title)],
        ["document_id", observation.document_id],
        ["published_at", canonicalize_datetime(observation.published_at)],
        ["stable_metadata", canonicalize_stable_metadata(observation.stable_metadata)],
    ]


def build_metadata_fingerprint(observation: SourceObservation) -> str:
    """Serialize metadata_v1 as compact UTF-8 JSON and return lowercase SHA-256."""
    serialized = json.dumps(
        metadata_fingerprint_payload(observation),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
