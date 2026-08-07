"""Small data models shared by the offline monitor layers."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Union

from earnings_research.validation.validator import ValidationReport


@dataclass(frozen=True)
class SourceObservation:
    """Normalized source metadata; this is not formal evidence."""

    source_url: str
    title: Optional[str]
    document_id: Optional[str]
    published_at: Optional[datetime]
    etag: Optional[str]
    last_modified: Optional[str]
    content_length: Optional[int]
    replacement_suspected: bool
    observed_at: datetime
    stable_metadata: Mapping[str, Optional[str]] = field(default_factory=dict)
    response_date: Optional[str] = None
    content_type: Optional[str] = None


@dataclass(frozen=True)
class ObservationFailure:
    """A sanitized representation of an observation failure."""

    error_code: str
    error_detail: str
    observed_at: datetime
    retry_count: int = 0
    source_url: Optional[str] = None
    retryable: bool = False


ObservationResult = Union[SourceObservation, ObservationFailure]


@dataclass(frozen=True)
class OfflineSourceInput:
    """Paths and clock value supplied to the network-free adapter."""

    observed_at: datetime
    html_path: Optional[Path] = None
    metadata_path: Optional[Path] = None


@dataclass(frozen=True)
class LiveSourceContext:
    """Caller-owned time, URL, and prior metadata for one bounded live observation."""

    observed_at: datetime
    source_url: Optional[str] = None
    previous_checkpoint: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MonitorTransitionResult:
    """One atomic runtime proposal and its in-memory validation result."""

    monitor_run: Dict[str, str]
    checkpoint_after: Dict[str, str]
    validation_report: ValidationReport
    monitor_runs: List[Dict[str, str]]
    monitor_resolutions: List[Dict[str, str]]
