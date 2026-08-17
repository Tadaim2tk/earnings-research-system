"""Approval-gated HTTP adapter for public source metadata."""

import codecs
import hashlib
import ipaddress
import json
import re
import ssl
import time
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from html.parser import HTMLParser
from typing import Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpcore
import httpx

from earnings_research.identifiers import is_activation_authorizer
from earnings_research.monitoring.models import (
    LiveSourceContext,
    ObservationFailure,
    ObservationResult,
    SourceObservation,
)
from earnings_research.monitoring.network import (
    DNSResolutionError,
    DNSResolutionTimeout,
    PinnedHTTPTransport,
    Resolver,
    UnsafeResolvedAddress,
    is_safe_public_address,
    resolve_public_addresses_bounded,
    system_resolver,
)

CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 10.0
OVERALL_BUDGET_SECONDS = 15.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECT_HOPS = 3
DNS_RESOLUTION_TIMEOUT_SECONDS = 5.0
USER_AGENT = "EarningsResearchSystem-Monitor/1.0 (public-metadata-only)"

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SECRET_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "key",
    "secret",
    "sig",
    "signature",
    "token",
}
_ALLOWED_CHARSETS = {"utf-8", "shift_jis", "cp932", "euc_jp", "iso2022_jp"}
_ALLOWED_STABLE_METADATA_KEYS = {"category", "document_type", "language", "period"}
_TDNET_INDEX_CATEGORY = "tdnet_index_json"
_EARNINGS_CALENDAR_CATEGORY = "earnings_calendar_html"
_MAX_SCHEDULE_ROWS = 12
_JST = timezone(timedelta(hours=9))
_PUBLISHED_AT_TOLERANCE = timedelta(minutes=5)


class LiveSourcePolicyError(ValueError):
    """A request was rejected before network access."""

    def __init__(self, error_code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.error_code = error_code
        self.safe_message = safe_message


class _VisibleTextHTMLParser(HTMLParser):
    """Collect body text, dropping the elements that never carry schedule rows."""

    _SKIPPED = {"script", "style", "head", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, _attrs) -> None:
        if tag.lower() in self._SKIPPED:
            self._skip_depth += 1

    def handle_endtag(self, tag) -> None:
        if tag.lower() in self._SKIPPED and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    @property
    def segments(self) -> list:
        """Text nodes kept apart, so a table cell stays one unit."""
        cleaned = (re.sub(r"\s+", " ", part).strip() for part in self.parts)
        return [part for part in cleaned if part]


class _GenericHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self.title_closed = True
        self.title_parts = []
        self.metadata: Dict[str, str] = {}

    def handle_starttag(self, tag, attrs) -> None:
        attributes = {str(key).lower(): value for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
            self.title_closed = False
        if tag.lower() == "meta":
            name = attributes.get("name") or attributes.get("property")
            content = attributes.get("content")
            if name and content is not None:
                self.metadata[str(name).strip().lower()] = str(content).strip()

    def handle_endtag(self, tag) -> None:
        if tag.lower() == "title":
            self._in_title = False
            self.title_closed = True

    def handle_data(self, data) -> None:
        if self._in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> Optional[str]:
        if not self.title_parts:
            return None
        return _clean_text(" ".join(self.title_parts))


class LiveSourceAdapter:
    """Fetch one approved public source without automatic redirects or retries."""

    def __init__(
        self,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        resolver: Resolver = system_resolver,
        resolver_timeout_seconds: float = DNS_RESOLUTION_TIMEOUT_SECONDS,
        network_backend_factory: Optional[Callable[[], httpcore.NetworkBackend]] = None,
        monotonic=time.monotonic,
    ) -> None:
        self._monotonic = monotonic
        self._resolver = resolver
        self._resolver_timeout_seconds = resolver_timeout_seconds
        self._network_backend_factory = network_backend_factory
        self._ssl_context = ssl.create_default_context()
        self._injected_client = self._build_client(transport) if transport is not None else None

    def _build_client(self, transport: httpx.BaseTransport) -> httpx.Client:
        return httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(
                READ_TIMEOUT_SECONDS,
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=CONNECT_TIMEOUT_SECONDS,
                pool=CONNECT_TIMEOUT_SECONDS,
            ),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html, application/json",
                "Accept-Encoding": "identity",
            },
        )

    def close(self) -> None:
        if self._injected_client is not None:
            self._injected_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def observe(self, target: Dict[str, str], context: LiveSourceContext) -> ObservationResult:
        """Return one observation or sanitized failure without raising network details."""
        _require_aware(context.observed_at)
        requested_url = context.source_url or target.get("source_url", "")
        try:
            self._require_approval(target)
            _approved_url, approved_origin = _validate_initial_target_url(target.get("source_url", ""))
            current_url = _validate_request_url(requested_url, approved_origin)
            if _canonical_url(current_url) != _canonical_url(requested_url):
                current_url = _canonical_url(current_url)
            return self._fetch(
                current_url=current_url,
                approved_origin=approved_origin,
                context=context,
                source_category=target.get("source_category"),
            )
        except LiveSourcePolicyError as exc:
            return _failure(
                exc.error_code,
                exc.safe_message,
                requested_url or target.get("source_url", ""),
                context.observed_at,
            )

    def check_robots(
        self, target: Dict[str, str], context: LiveSourceContext
    ) -> Optional[ObservationFailure]:
        """Fail closed when robots policy cannot be checked or disallows the target path."""
        _require_aware(context.observed_at)
        target_url = target.get("source_url", "")
        try:
            self._require_approval(target)
            approved_url, approved_origin = _validate_initial_target_url(target_url)
            parts = urlsplit(approved_url)
            robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            result = self._fetch(
                current_url=robots_url,
                approved_origin=approved_origin,
                context=LiveSourceContext(observed_at=context.observed_at),
                robots_path=parts.path or "/",
            )
        except LiveSourcePolicyError as exc:
            return _failure(exc.error_code, exc.safe_message, target_url, context.observed_at)
        if isinstance(result, ObservationFailure):
            return result
        if result.stable_metadata.get("robots_allowed") != "true":
            return _failure(
                "terms_not_approved",
                "robots policy disallows the approved source path",
                target_url,
                context.observed_at,
            )
        return None

    def _fetch(
        self,
        *,
        current_url: str,
        approved_origin: Tuple[str, str, int],
        context: LiveSourceContext,
        robots_path: Optional[str] = None,
        source_category: Optional[str] = None,
    ) -> ObservationResult:
        started = self._monotonic()
        visited = set()
        redirect_hops = 0
        while True:
            canonical = _canonical_url(current_url)
            if canonical in visited:
                return _failure(
                    "unexpected_format",
                    "redirect loop rejected",
                    current_url,
                    context.observed_at,
                )
            visited.add(canonical)
            remaining = OVERALL_BUDGET_SECONDS - (self._monotonic() - started)
            if remaining <= 0:
                return _failure("timeout", "overall request budget exceeded", current_url, context.observed_at, True)
            parts = urlsplit(current_url)
            try:
                addresses = resolve_public_addresses_bounded(
                    parts.hostname or "",
                    parts.port or 443,
                    resolver=self._resolver,
                    timeout=min(self._resolver_timeout_seconds, remaining),
                )
            except DNSResolutionTimeout:
                return _failure(
                    "timeout",
                    "approved source DNS resolution timed out",
                    current_url,
                    context.observed_at,
                    True,
                )
            except DNSResolutionError:
                return _failure(
                    "source_unavailable",
                    "approved source DNS resolution failed",
                    current_url,
                    context.observed_at,
                    True,
                )
            except UnsafeResolvedAddress:
                return _failure(
                    "terms_not_approved",
                    "approved source DNS returned a non-global address",
                    current_url,
                    context.observed_at,
                )
            remaining = OVERALL_BUDGET_SECONDS - (self._monotonic() - started)
            if remaining <= 0:
                return _failure(
                    "timeout",
                    "overall request budget exceeded after DNS resolution",
                    current_url,
                    context.observed_at,
                    True,
                )
            timeout = httpx.Timeout(
                min(READ_TIMEOUT_SECONDS, remaining),
                connect=min(CONNECT_TIMEOUT_SECONDS, remaining),
                read=min(READ_TIMEOUT_SECONDS, remaining),
                write=min(CONNECT_TIMEOUT_SECONDS, remaining),
                pool=min(CONNECT_TIMEOUT_SECONDS, remaining),
            )
            owns_client = self._injected_client is None
            client = self._injected_client or self._build_client(
                PinnedHTTPTransport(
                    approved_host=parts.hostname or "",
                    approved_port=parts.port or 443,
                    pinned_ip=addresses[0],
                    ssl_context=self._ssl_context,
                    network_backend=(
                        self._network_backend_factory()
                        if self._network_backend_factory is not None
                        else None
                    ),
                )
            )
            client.cookies.clear()
            try:
                # robots.txt is plain text. Some origins answer 406 to the
                # metadata Accept header, which would hide the policy behind a
                # transport error instead of resolving it.
                request_headers = (
                    {"Accept": "text/plain, */*"} if robots_path is not None else None
                )
                with client.stream(
                    "GET", current_url, timeout=timeout, headers=request_headers
                ) as response:
                    client.cookies.clear()
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location", "")
                        if not location or _contains_control_characters(location):
                            return _failure(
                                "unexpected_format",
                                "redirect Location is missing or malformed",
                                current_url,
                                context.observed_at,
                            )
                        if redirect_hops >= MAX_REDIRECT_HOPS:
                            return _failure(
                                "unexpected_format",
                                "redirect hop limit exceeded",
                                current_url,
                                context.observed_at,
                            )
                        try:
                            current_url = _validate_request_url(
                                urljoin(current_url, location), approved_origin
                            )
                        except LiveSourcePolicyError as exc:
                            return _failure(
                                exc.error_code,
                                exc.safe_message,
                                current_url,
                                context.observed_at,
                            )
                        redirect_hops += 1
                        continue
                    if robots_path is not None and response.status_code in {404, 410}:
                        return _robots_observation(
                            current_url,
                            context.observed_at,
                            allowed=True,
                            status="absent",
                        )
                    if robots_path is not None and response.status_code != 200:
                        # An unreadable robots policy is not permission. Any other
                        # status, including 4xx content negotiation failures and
                        # transient 5xx, keeps the source closed.
                        return _failure(
                            "terms_not_approved",
                            "robots policy could not be verified",
                            current_url,
                            context.observed_at,
                        )
                    status_failure = _status_failure(response.status_code)
                    if status_failure is not None:
                        code, message, retryable = status_failure
                        return _failure(code, message, current_url, context.observed_at, retryable)
                    if response.status_code != 200:
                        return _failure(
                            "http_error",
                            "HTTP response was not successful",
                            current_url,
                            context.observed_at,
                            False,
                        )
                    return self._parse_success(
                        response,
                        current_url,
                        context,
                        deadline=started + OVERALL_BUDGET_SECONDS,
                        robots_path=robots_path,
                        source_category=source_category,
                    )
            except httpx.InvalidURL:
                return _failure(
                    "unexpected_format",
                    "redirect or request URL is malformed",
                    current_url,
                    context.observed_at,
                )
            except (httpx.TimeoutException, httpcore.TimeoutException):
                return _failure("timeout", "HTTP request timed out", current_url, context.observed_at, True)
            except (
                httpx.NetworkError,
                httpx.ProtocolError,
                httpcore.NetworkError,
                httpcore.ProtocolError,
            ):
                return _failure(
                    "source_unavailable",
                    "HTTP transport failed",
                    current_url,
                    context.observed_at,
                    True,
                )
            except (
                httpx.HTTPError,
                httpcore.ConnectionNotAvailable,
                httpcore.ProxyError,
                httpcore.UnsupportedProtocol,
            ):
                return _failure("http_error", "HTTP request failed", current_url, context.observed_at)
            finally:
                if owns_client:
                    client.close()

    def _parse_success(
        self,
        response: httpx.Response,
        source_url: str,
        context: LiveSourceContext,
        *,
        deadline: float,
        robots_path: Optional[str] = None,
        source_category: Optional[str] = None,
    ) -> ObservationResult:
        content_type_header = response.headers.get("content-type", "")
        media_type, charset = _parse_content_type(content_type_header)
        allowed_media = {"text/plain"} if robots_path is not None else {"text/html", "application/json"}
        if media_type not in allowed_media:
            return _failure(
                "unexpected_format",
                "response Content-Type is not approved",
                source_url,
                context.observed_at,
            )
        declared_length = _parse_content_length(response.headers.get("content-length"))
        if declared_length is False:
            return _failure(
                "unexpected_format",
                "response Content-Length is invalid",
                source_url,
                context.observed_at,
            )
        if isinstance(declared_length, int) and declared_length > MAX_RESPONSE_BYTES:
            return _failure(
                "unexpected_format",
                "response exceeds the byte limit",
                source_url,
                context.observed_at,
            )
        body = bytearray()
        try:
            chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
            for chunk in chunks:
                if self._monotonic() >= deadline:
                    return _failure(
                        "timeout",
                        "overall request budget exceeded",
                        source_url,
                        context.observed_at,
                        True,
                    )
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    return _failure(
                        "unexpected_format",
                        "response exceeds the byte limit",
                        source_url,
                        context.observed_at,
                    )
            if self._monotonic() >= deadline:
                return _failure(
                    "timeout",
                    "overall request budget exceeded",
                    source_url,
                    context.observed_at,
                    True,
                )
        except (httpx.TimeoutException, httpcore.TimeoutException):
            return _failure("timeout", "HTTP response read timed out", source_url, context.observed_at, True)
        except (
            httpx.HTTPError,
            httpcore.ConnectionNotAvailable,
            httpcore.ProxyError,
            httpcore.UnsupportedProtocol,
        ):
            return _failure(
                "source_unavailable",
                "HTTP response stream failed",
                source_url,
                context.observed_at,
                True,
            )
        if not body:
            return _failure("parse_error", "response body is empty", source_url, context.observed_at)
        try:
            text = _decode_body(bytes(body), charset, media_type)
            if robots_path is not None:
                parser = RobotFileParser()
                parser.parse(text.splitlines())
                return _robots_observation(
                    source_url,
                    context.observed_at,
                    allowed=parser.can_fetch("EarningsResearchSystem-Monitor", robots_path),
                    status="present",
                    content_length=len(body),
                    etag=_optional_header(response.headers.get("etag")),
                    last_modified=_optional_header(response.headers.get("last-modified")),
                )
            # The TDnet index provider answers with text/html even for the JSON
            # formats, so the Human-declared category decides the parser first.
            if source_category == _TDNET_INDEX_CATEGORY:
                parsed = _parse_json(
                    text,
                    source_category=source_category,
                    observed_at=context.observed_at,
                )
            elif source_category == _EARNINGS_CALENDAR_CATEGORY:
                parsed = _parse_ir_calendar_html(text, media_type)
            else:
                parsed = (
                    _parse_html(text)
                    if media_type == "text/html"
                    else _parse_json(text, source_category=source_category)
                )
        except UnicodeError:
            return _failure("parse_error", "response charset decoding failed", source_url, context.observed_at)
        except TimestampError:
            return _failure(
                "timestamp_parse_error",
                "published timestamp is invalid or timezone-ambiguous",
                source_url,
                context.observed_at,
            )
        except (ValueError, json.JSONDecodeError):
            return _failure("parse_error", "response metadata parsing failed", source_url, context.observed_at)

        actual_length = len(body)
        # Generic pages keep only a digest for later comparisons. Disclosure
        # lists fingerprint their latest-item metadata instead; raw content is
        # never part of the persisted monitoring bundle.
        if source_category not in (_TDNET_INDEX_CATEGORY, _EARNINGS_CALENDAR_CATEGORY):
            parsed["stable_metadata"]["page_content_sha256"] = hashlib.sha256(bytes(body)).hexdigest()
        length_mismatch = isinstance(declared_length, int) and declared_length != actual_length
        previous = context.previous_checkpoint
        etag = _optional_header(response.headers.get("etag"))
        last_modified = _optional_header(response.headers.get("last-modified"))
        replacement_suspected = bool(parsed["replacement_suspected"] or length_mismatch)
        replacement_suspected = replacement_suspected or _prior_header_changed(
            previous.get("observed_etag", ""), etag
        )
        replacement_suspected = replacement_suspected or _prior_header_changed(
            previous.get("observed_last_modified", ""), last_modified
        )
        prior_length = previous.get("observed_content_length", "")
        if prior_length and prior_length != str(actual_length):
            replacement_suspected = True
        return SourceObservation(
            source_url=_canonical_url(source_url),
            title=parsed["title"],
            document_id=parsed["document_id"],
            published_at=parsed["published_at"],
            etag=etag,
            last_modified=last_modified,
            content_length=actual_length,
            replacement_suspected=replacement_suspected,
            observed_at=context.observed_at,
            stable_metadata=parsed["stable_metadata"],
            response_date=_optional_header(response.headers.get("date")),
            content_type=media_type,
        )

    @staticmethod
    def _require_approval(target: Mapping[str, str]) -> None:
        if (
            target.get("enabled", "").lower() != "true"
            or target.get("automated_access_permitted", "").lower() != "true"
            or target.get("monitoring_level") != "level_2"
            or target.get("terms_review_state") != "candidate_specific_review_completed"
            or not is_activation_authorizer(target.get("automation_approved_by", ""))
            or target.get("activation_state") != "activated"
            or not is_activation_authorizer(target.get("activation_approved_by", ""))
        ):
            raise LiveSourcePolicyError(
                "terms_not_approved",
                "live source access is not authorized and activated",
            )


class TimestampError(ValueError):
    pass


def _validate_initial_target_url(url: str) -> Tuple[str, Tuple[str, str, int]]:
    parts = _validated_url_parts(url)
    origin = (parts.scheme.lower(), parts.hostname.lower(), parts.port or 443)
    return _canonical_url(url), origin


def _validate_request_url(url: str, approved_origin: Tuple[str, str, int]) -> str:
    parts = _validated_url_parts(url)
    origin = (parts.scheme.lower(), parts.hostname.lower(), parts.port or 443)
    if origin != approved_origin:
        raise LiveSourcePolicyError("terms_not_approved", "request origin is not Human-approved")
    return _canonical_url(url)


def _validated_url_parts(url: str):
    if (
        not isinstance(url, str)
        or not url
        or _contains_control_characters(url)
        or any(character.isspace() for character in url)
    ):
        raise LiveSourcePolicyError("unexpected_format", "source URL is malformed")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise LiveSourcePolicyError("unexpected_format", "source URL is malformed") from exc
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise LiveSourcePolicyError("terms_not_approved", "source URL must use HTTPS")
    if parts.username is not None or parts.password is not None:
        raise LiveSourcePolicyError("terms_not_approved", "source URL userinfo is forbidden")
    if port not in (None, 443):
        raise LiveSourcePolicyError("terms_not_approved", "source URL port is not approved")
    hostname = parts.hostname.lower().rstrip(".")
    if _is_local_or_private_literal(hostname):
        raise LiveSourcePolicyError("terms_not_approved", "local or private source address is forbidden")
    for key, _value in parse_qsl(parts.query, keep_blank_values=True):
        normalized_key = key.strip().lower().replace("-", "_")
        if normalized_key in _SECRET_QUERY_KEYS:
            raise LiveSourcePolicyError("terms_not_approved", "secret-bearing query parameter is forbidden")
    return parts


def _is_local_or_private_literal(hostname: str) -> bool:
    if (
        hostname in {"localhost", "localhost.localdomain", "instance-data"}
        or hostname.endswith((".localhost", ".local", ".internal"))
    ):
        return True
    try:
        address = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return bool(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9.]+)", hostname))
    return not is_safe_public_address(address)


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    hostname = (parts.hostname or "").lower().rstrip(".")
    authority = "[%s]" % hostname if ":" in hostname else hostname
    netloc = authority if parts.port in (None, 443) else "%s:%s" % (authority, parts.port)
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def _safe_url(url: str) -> str:
    try:
        parts = urlsplit(str(url))
        hostname = (parts.hostname or "unavailable").lower()
        authority = "[%s]" % hostname if ":" in hostname else hostname
        port = "" if parts.port in (None, 443) else ":%s" % parts.port
        return urlunsplit((parts.scheme.lower() or "https", authority + port, parts.path or "/", "", ""))
    except (TypeError, ValueError):
        return "https://unavailable/"


def _failure(
    code: str,
    message: str,
    source_url: str,
    observed_at: datetime,
    retryable: bool = False,
) -> ObservationFailure:
    return ObservationFailure(
        error_code=code,
        error_detail=message,
        observed_at=observed_at,
        retry_count=0,
        source_url=_safe_url(source_url),
        retryable=retryable,
    )


def _robots_observation(
    source_url: str,
    observed_at: datetime,
    *,
    allowed: bool,
    status: str,
    content_length: Optional[int] = None,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
) -> SourceObservation:
    return SourceObservation(
        source_url=_canonical_url(source_url),
        title="robots.txt",
        document_id=None,
        published_at=None,
        etag=etag,
        last_modified=last_modified,
        content_length=content_length,
        replacement_suspected=False,
        observed_at=observed_at,
        stable_metadata={
            "robots_allowed": "true" if allowed else "false",
            "robots_status": status,
        },
        content_type="text/plain",
    )


def _status_failure(status: int):
    if status in {401, 403}:
        return "authentication_required", "public source requires authentication", False
    if status == 429:
        return "rate_limited", "public source rate limit was reached", True
    if status == 408:
        return "timeout", "public source request timed out", True
    if status == 404:
        return "source_unavailable", "public source was not found", False
    if 500 <= status <= 599:
        return "source_unavailable", "public source server was unavailable", True
    return None


def _parse_content_type(value: str) -> Tuple[str, Optional[str]]:
    message = Message()
    message["content-type"] = value
    return message.get_content_type().lower(), message.get_content_charset()


def _parse_content_length(value: Optional[str]):
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        return False
    return int(value)


def _decode_body(body: bytes, charset: Optional[str], media_type: str) -> str:
    requested = charset or "utf-8"
    if requested.lower() == "windows-31j":
        requested = "cp932"
    try:
        canonical = codecs.lookup(requested).name
    except LookupError as exc:
        raise UnicodeError("unsupported charset") from exc
    if canonical not in _ALLOWED_CHARSETS:
        raise UnicodeError("unsupported charset")
    if media_type == "application/json" and canonical != "utf-8":
        raise UnicodeError("JSON must use UTF-8")
    text = body.decode(canonical, errors="strict")
    if "\ufffd" in text:
        raise UnicodeError("replacement character rejected")
    return text


def _parse_html(text: str) -> Dict:
    if "\x00" in text:
        raise ValueError("NUL in HTML")
    parser = _GenericHTMLParser()
    parser.feed(text)
    parser.close()
    if not parser.title_closed:
        raise ValueError("unclosed title")
    title = parser.title
    if title is not None and not _is_meaningful_text(title):
        raise ValueError("invalid title")
    document_id = _first_metadata(
        parser.metadata,
        "document_id",
        "document-id",
        "citation_doi",
        "og:id",
    )
    document_id = _validated_optional_metadata(document_id, "document ID")
    published_value = _first_metadata(
        parser.metadata,
        "published_at",
        "article:published_time",
        "date",
        "dc.date",
    )
    published_at = _parse_published_at(published_value)
    corrected = _first_metadata(parser.metadata, "corrected", "updated", "article:modified_time")
    if title is None and document_id is None and published_at is None:
        raise ValueError("no generic metadata")
    stable_metadata = {}
    if parser.metadata.get("og:type"):
        stable_metadata["og_type"] = parser.metadata["og:type"]
    return {
        "title": title,
        "document_id": document_id,
        "published_at": published_at,
        "replacement_suspected": _truthy(corrected),
        "stable_metadata": stable_metadata,
    }


# A row reads "2026年11月13日 2027年3月期第2四半期決算発表". The label between the
# date and 決算発表 carries its own digits, so the date is matched first and the
# label is read from a bounded window that stops at the next date.
# 期 in "2027年3月期第2四半期" looks like a date tail, so only a day number or a
# named part of the month counts as one.
_SCHEDULE_DATE = re.compile(
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(?:(\d{1,2})\s*日|(上旬|中旬|下旬|初旬|末))"
)
_SCHEDULE_LABEL_WINDOW = 40


def _parse_ir_calendar_html(text: str, media_type: str = "text/html") -> Dict:
    """Fingerprint the published earnings schedule, not the whole page.

    The page digest moves on any unrelated edit, which turns a schedule watch
    into noise. Only the announced dates are compared, so a change means the
    company moved a date or added a quarter.
    """
    if media_type != "text/html":
        raise ValueError("earnings calendar must be served as HTML")
    generic = _parse_html(text)
    parser = _VisibleTextHTMLParser()
    parser.feed(text)
    parser.close()
    segments = parser.segments
    exact = []
    approximate = []
    for index, segment in enumerate(segments):
        for match in _SCHEDULE_DATE.finditer(segment):
            label = _schedule_label(segments, index, segment[match.end() :])
            if label is None:
                continue
            year, month, day, vague = match.group(1), match.group(2), match.group(3), match.group(4)
            if not day:
                # Forms such as 2027年2月中旬 name no day. The part of the month
                # is kept verbatim so a move to 下旬 is still a change, without
                # inventing a date that was never published.
                approximate.append("%s-%02d-%s=%s" % (year, int(month), vague, label))
                continue
            try:
                parsed = date(int(year), int(month), int(day))
            except ValueError as exc:
                raise ValueError("IR calendar row has an invalid date") from exc
            exact.append("%s=%s" % (parsed.isoformat(), label))
    if not exact and not approximate:
        raise ValueError("IR calendar contains no earnings announcement row")
    if len(exact) + len(approximate) > _MAX_SCHEDULE_ROWS:
        raise ValueError("IR calendar contains an implausible number of rows")
    generic["stable_metadata"] = {
        "earnings_schedule": ";".join(exact) if exact else "none",
        "approximate_schedule": ";".join(approximate) if approximate else "none",
    }
    return generic


def _schedule_label(segments, index: int, remainder: str) -> Optional[str]:
    """Return the announcement label that belongs to this date, or None.

    The label is the rest of the date's own text node, or the next one when the
    date owns a cell of its own. Reading past that would let an unrelated
    "決算発表資料はこちら" elsewhere on the page attach itself to a shareholder
    meeting date. The stored label is truncated, never the row.
    """
    candidate = remainder.strip()
    if not candidate and index + 1 < len(segments):
        candidate = segments[index + 1]
    if "決算発表" not in candidate:
        return None
    label = candidate[: candidate.index("決算発表") + len("決算発表")]
    if not _is_meaningful_text(label):
        return None
    # The cell already bounds the label. Length bounds only what is stored, so a
    # long but legitimate label keeps its row instead of vanishing in silence.
    return _clean_text(label)[:_SCHEDULE_LABEL_WINDOW]


def _parse_json(
    text: str,
    *,
    source_category: Optional[str] = None,
    observed_at: Optional[datetime] = None,
) -> Dict:
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("JSON root must be an object")
    if source_category == _TDNET_INDEX_CATEGORY:
        return _parse_tdnet_index_json(loaded, observed_at)
    recognized = {"title", "document_id", "published_at", "corrected", "updated", "stable_metadata"}
    if not recognized.intersection(loaded):
        raise ValueError("JSON has no recognized metadata")
    title = None if loaded.get("title") is None else _clean_text(str(loaded.get("title")))
    if title is not None and not _is_meaningful_text(title):
        raise ValueError("invalid title")
    document_id = _validated_optional_metadata(loaded.get("document_id"), "document ID")
    published_at = _parse_published_at(loaded.get("published_at"))
    stable_metadata = loaded.get("stable_metadata") or {}
    if not isinstance(stable_metadata, dict):
        raise ValueError("stable_metadata must be a flat object")
    filtered_metadata = {}
    for key, value in stable_metadata.items():
        normalized_key = str(key).strip().lower()
        if normalized_key not in _ALLOWED_STABLE_METADATA_KEYS:
            continue
        if isinstance(value, (dict, list)):
            raise ValueError("stable_metadata values must be scalar")
        cleaned_value = _validated_optional_metadata(value, "stable metadata")
        if cleaned_value is not None:
            filtered_metadata[normalized_key] = cleaned_value
    if title is None and document_id is None and published_at is None:
        raise ValueError("JSON has no usable metadata")
    return {
        "title": title,
        "document_id": document_id,
        "published_at": published_at,
        "replacement_suspected": _truthy(loaded.get("corrected")) or _truthy(loaded.get("updated")),
        "stable_metadata": filtered_metadata,
    }


def _parse_tdnet_index_json(loaded: Dict, observed_at: Optional[datetime] = None) -> Dict:
    items = loaded.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ValueError("TDnet index must contain a first item")
    latest = items[0]
    title = _clean_text(str(latest.get("title") or ""))
    if not _is_meaningful_text(title):
        raise ValueError("latest disclosure title is missing or invalid")
    document_id = _validated_optional_metadata(latest.get("id"), "disclosure ID")
    if document_id is None:
        raise ValueError("latest disclosure ID is missing")
    pubdate = latest.get("pubdate")
    if pubdate in (None, ""):
        raise ValueError("latest disclosure pubdate is missing")
    try:
        published_at = datetime.strptime(str(pubdate), "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise TimestampError from exc
    # The TDnet index omits a timezone from pubdate. For this source category only,
    # the documented provider timestamp is interpreted explicitly as Japan time,
    # matching the Tokyo Stock Exchange disclosure clock the provider mirrors.
    published_at = published_at.replace(tzinfo=_JST)
    # A disclosure cannot be published after it was observed. Accepting a future
    # timestamp would put a provider error straight into the research handoff.
    if observed_at is not None and published_at > observed_at + _PUBLISHED_AT_TOLERANCE:
        raise TimestampError
    document_url = _validated_optional_metadata(latest.get("document_url"), "document URL")
    if document_url is None:
        raise ValueError("latest disclosure document URL is missing")
    parts = urlsplit(document_url)
    if (
        parts.scheme.lower() != "https"
        or not parts.hostname
        # An empty userinfo is still userinfo; `or parts.username` would pass it.
        or parts.username is not None
        or parts.password is not None
    ):
        raise ValueError("latest disclosure document URL is invalid")
    total_count = latest_index_count(loaded, len(items))
    return {
        "title": title,
        "document_id": document_id,
        "published_at": published_at,
        "replacement_suspected": _is_meaningful_text(
            _clean_text(str(latest.get("update_history") or ""))
        ),
        # The index count joins the newest item in the fingerprint so that a
        # change below the first row cannot pass as an unchanged observation.
        "stable_metadata": {
            "latest_document_url": document_url,
            "index_item_count": str(total_count),
        },
    }


def latest_index_count(loaded: Dict, fallback: int) -> int:
    declared = loaded.get("total_count")
    if declared in (None, ""):
        return fallback
    try:
        return int(str(declared))
    except ValueError as exc:
        raise ValueError("TDnet index total_count is invalid") from exc


def _parse_published_at(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimestampError from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TimestampError
    return parsed


def _first_metadata(metadata: Mapping[str, str], *keys: str) -> Optional[str]:
    for key in keys:
        value = metadata.get(key)
        if value:
            return value
    return None


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _validated_optional_metadata(value, label: str) -> Optional[str]:
    if value is None:
        return None
    cleaned = _clean_text(str(value))
    if not cleaned:
        return None
    if len(cleaned) > 200 or _contains_control_characters(cleaned):
        raise ValueError("%s is invalid" % label)
    return cleaned


def _is_meaningful_text(value: str) -> bool:
    return bool(value and len(value) <= 500 and any(character.isalnum() for character in value))


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "corrected", "updated"}


def _optional_header(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = _clean_text(value)
    if not cleaned or len(cleaned) > 500 or _contains_control_characters(cleaned):
        return None
    return cleaned


def _prior_header_changed(previous: str, current: Optional[str]) -> bool:
    return bool(previous and current is not None and previous != current)


def _contains_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
