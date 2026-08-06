"""Network-free HTML and metadata fixture adapter."""

import json
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, Optional

from earnings_research.monitoring.models import (
    ObservationFailure,
    ObservationResult,
    OfflineSourceInput,
    SourceObservation,
)


class _FixtureHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._title_parts = []
        self.metadata: Dict[str, str] = {}

    @property
    def title(self) -> Optional[str]:
        value = "".join(self._title_parts)
        return value if value else None

    def handle_starttag(self, tag, attrs) -> None:
        attributes = dict(attrs)
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta":
            name = attributes.get("name") or attributes.get("property")
            content = attributes.get("content")
            if name and content is not None:
                self.metadata[name.lower()] = content

    def handle_endtag(self, tag) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data) -> None:
        if self._in_title:
            self._title_parts.append(data)


class OfflineSourceAdapter:
    """Convert caller-supplied fixtures into a source observation."""

    def observe(self, target: Dict[str, str], source_input: OfflineSourceInput) -> ObservationResult:
        if source_input.observed_at.tzinfo is None or source_input.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        metadata = self._load_metadata(source_input)
        if metadata.get("error_code"):
            return ObservationFailure(
                error_code=str(metadata["error_code"]),
                error_detail=str(metadata.get("error_detail") or "offline fixture observation failed"),
                observed_at=source_input.observed_at,
                retry_count=int(metadata.get("retry_count") or 0),
            )

        parser = _FixtureHTMLParser()
        if source_input.html_path is not None:
            parser.feed(source_input.html_path.read_text(encoding="utf-8"))

        def value(key: str, meta_name: Optional[str] = None):
            if key in metadata:
                return metadata[key]
            return parser.metadata.get(meta_name or key.replace("_", "-"))

        published_at = _parse_optional_datetime(value("published_at"))
        content_length = value("content_length")
        replacement_marker = value("replacement_suspected")
        corrected_marker = parser.metadata.get("corrected") or parser.metadata.get("updated")
        title = metadata["title"] if "title" in metadata else parser.title
        stable_metadata = metadata.get("stable_metadata") or {}
        if not isinstance(stable_metadata, dict):
            raise ValueError("stable_metadata must be an object")

        return SourceObservation(
            source_url=str(metadata.get("source_url") or target.get("source_url") or ""),
            title=None if title is None else str(title),
            document_id=_optional_string(value("document_id")),
            published_at=published_at,
            etag=_optional_string(value("etag")),
            last_modified=_optional_string(value("last_modified")),
            content_length=None if content_length is None else int(content_length),
            replacement_suspected=_as_bool(replacement_marker) or _as_bool(corrected_marker),
            observed_at=source_input.observed_at,
            stable_metadata={str(key): _optional_string(item) for key, item in stable_metadata.items()},
        )

    @staticmethod
    def _load_metadata(source_input: OfflineSourceInput) -> dict:
        if source_input.metadata_path is None:
            return {}
        with source_input.metadata_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("offline metadata fixture must contain an object")
        return loaded


def _parse_optional_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must be timezone-aware")
    return parsed


def _optional_string(value) -> Optional[str]:
    return None if value is None else str(value)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}
