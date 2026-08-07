import socket
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpcore
import httpx
import pytest

from earnings_research.monitoring.live import LiveSourceAdapter
from earnings_research.monitoring.models import LiveSourceContext, ObservationFailure, SourceObservation
from earnings_research.monitoring.network import (
    DNSResolutionError,
    DNSResolutionTimeout,
    PinnedHTTPTransport,
    UnsafeResolvedAddress,
    resolve_public_addresses,
    resolve_public_addresses_bounded,
)
from earnings_research.monitoring.registry import load_registry
from earnings_research.monitoring.runtime import MonitorRuntime

JST = timezone(timedelta(hours=9))
PUBLIC_IPV4 = "93.184.216.34"
PUBLIC_IPV6 = "2606:2800:220:1:248:1893:25c8:1946"
REGISTRY = Path(__file__).resolve().parents[1] / "fixtures" / "monitor_operations" / "monitor_targets.csv"


def moment():
    return datetime(2026, 8, 7, 9, 0, tzinfo=JST)


def target():
    row = load_registry(REGISTRY)[0]
    row["source_url"] = "https://approved.example.invalid/releases"
    return row


def html_response():
    return httpx.Response(
        200,
        content=b"<html><head><title>Approved public metadata</title></head></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )


def observe(handler, resolver, *, target_row=None, context=None, **adapter_kwargs):
    with LiveSourceAdapter(
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        **adapter_kwargs,
    ) as adapter:
        return adapter.observe(
            target_row or target(),
            context or LiveSourceContext(observed_at=moment()),
        )


def test_all_public_ipv4_and_ipv6_answers_are_accepted():
    addresses = resolve_public_addresses(
        "approved.example.invalid",
        443,
        resolver=lambda _host, _port: [PUBLIC_IPV6, PUBLIC_IPV4, PUBLIC_IPV4],
    )
    assert addresses == (PUBLIC_IPV4, PUBLIC_IPV6)

    calls = []
    result = observe(
        lambda request: calls.append(request) or html_response(),
        lambda _host, _port: [PUBLIC_IPV4, PUBLIC_IPV6],
    )
    assert isinstance(result, SourceObservation)
    assert len(calls) == 1


def test_global_ipv6_literal_keeps_brackets_in_canonical_url():
    row = target()
    row["source_url"] = "https://[%s]/releases" % PUBLIC_IPV6
    result = observe(
        lambda _request: html_response(),
        lambda _host, _port: [PUBLIC_IPV6],
        target_row=row,
    )
    assert isinstance(result, SourceObservation)
    assert result.source_url == "https://[%s]/releases" % PUBLIC_IPV6


@pytest.mark.parametrize(
    "address",
    [
        "::1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::1",
        "64:ff9b::7f00:1",
    ],
)
def test_unsafe_ipv6_literals_and_embedded_ipv4_are_rejected(address):
    row = target()
    row["source_url"] = "https://[%s]/releases" % address
    calls = []
    result = observe(
        lambda request: calls.append(request),
        lambda _host, _port: [address],
        target_row=row,
    )
    assert result.error_code == "terms_not_approved"
    assert calls == []


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "fe80::1",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
    ],
)
def test_any_non_global_dns_answer_is_rejected_before_http(address):
    calls = []
    result = observe(
        lambda request: calls.append(request) or html_response(),
        lambda _host, _port: [address],
    )
    assert isinstance(result, ObservationFailure)
    assert result.error_code == "terms_not_approved"
    assert calls == []


def test_mixed_public_and_private_dns_answers_fail_closed():
    with pytest.raises(UnsafeResolvedAddress):
        resolve_public_addresses(
            "approved.example.invalid",
            443,
            resolver=lambda _host, _port: [PUBLIC_IPV4, "10.0.0.1"],
        )

    calls = []
    result = observe(
        lambda request: calls.append(request) or html_response(),
        lambda _host, _port: [PUBLIC_IPV4, "10.0.0.1"],
    )
    assert result.error_code == "terms_not_approved"
    assert calls == []


def test_dns_failure_is_source_unavailable_without_http_request():
    calls = []

    def failed_resolver(_host, _port):
        raise socket.gaierror("private resolver detail must not leak")

    with pytest.raises(DNSResolutionError):
        resolve_public_addresses("approved.example.invalid", 443, resolver=failed_resolver)
    result = observe(lambda request: calls.append(request), failed_resolver)
    assert result.error_code == "source_unavailable"
    assert result.retryable is True
    assert "private resolver detail" not in result.error_detail
    assert calls == []


@pytest.mark.parametrize("error", [UnicodeError("bad IDNA"), ValueError("bad host"), RuntimeError("bad resolver")])
def test_unexpected_resolver_exception_is_sanitized(error):
    calls = []

    def failed_resolver(_host, _port):
        raise error

    result = observe(lambda request: calls.append(request), failed_resolver)
    assert isinstance(result, ObservationFailure)
    assert result.error_code == "source_unavailable"
    assert str(error) not in result.error_detail
    assert calls == []


def test_bounded_resolver_succeeds_within_timeout():
    addresses = resolve_public_addresses_bounded(
        "approved.example.invalid",
        443,
        resolver=lambda _host, _port: (time.sleep(0.005), [PUBLIC_IPV4])[1],
        timeout=0.1,
    )
    assert addresses == (PUBLIC_IPV4,)


def test_resolver_timeout_never_starts_http_even_after_late_completion():
    release = threading.Event()
    calls = []

    def delayed_resolver(_host, _port):
        release.wait(0.5)
        return [PUBLIC_IPV4]

    result = observe(
        lambda request: calls.append(request) or html_response(),
        delayed_resolver,
        resolver_timeout_seconds=0.01,
    )
    assert result.error_code == "timeout"
    assert result.retryable is True
    assert calls == []

    release.set()
    time.sleep(0.02)
    assert calls == []


def test_timed_out_adapter_does_not_start_additional_resolver_workers():
    release = threading.Event()
    resolver_calls = []

    def delayed_resolver(_host, _port):
        resolver_calls.append(True)
        release.wait(0.5)
        return [PUBLIC_IPV4]

    with LiveSourceAdapter(
        transport=httpx.MockTransport(lambda _request: html_response()),
        resolver=delayed_resolver,
        resolver_timeout_seconds=0.01,
    ) as adapter:
        first = adapter.observe(target(), LiveSourceContext(observed_at=moment()))
        second = adapter.observe(
            target(),
            LiveSourceContext(observed_at=moment() + timedelta(minutes=1)),
        )
    release.set()

    assert first.error_code == "timeout"
    assert second.error_code == "timeout"
    assert resolver_calls == [True]


def test_resolver_completion_rechecks_consumed_overall_deadline():
    times = iter([0.0, 0.0, 16.0])
    calls = []
    result = observe(
        lambda request: calls.append(request) or html_response(),
        lambda _host, _port: [PUBLIC_IPV4],
        monotonic=lambda: next(times),
    )
    assert result.error_code == "timeout"
    assert calls == []


def test_malformed_ipv6_url_returns_sanitized_failure_without_http():
    row = target()
    row["source_url"] = "https://[2001:db8::1/releases"
    calls = []
    result = observe(
        lambda request: calls.append(request),
        lambda _host, _port: [PUBLIC_IPV4],
        target_row=row,
    )
    assert isinstance(result, ObservationFailure)
    assert result.error_code == "unexpected_format"
    assert calls == []


def test_dns_timeout_preserves_pending_human_change():
    row = target()
    row["initialization_run_id"] = "MRUN-DNS-001"
    runtime = MonitorRuntime()
    initial_observation = SourceObservation(
        source_url=row["source_url"],
        title="Initial metadata",
        document_id="DOC-1",
        published_at=None,
        etag="etag-1",
        last_modified=None,
        content_length=10,
        replacement_suspected=False,
        observed_at=moment(),
    )
    initial = runtime.transition(
        target=row,
        previous_checkpoint=None,
        prior_runs=[],
        resolutions=[],
        observation=initial_observation,
        run_id="MRUN-DNS-001",
        started_at=moment(),
        finished_at=moment() + timedelta(minutes=1),
    )
    changed_observation = SourceObservation(
        source_url=row["source_url"],
        title="Changed metadata",
        document_id="DOC-2",
        published_at=None,
        etag="etag-2",
        last_modified=None,
        content_length=11,
        replacement_suspected=False,
        observed_at=moment() + timedelta(hours=1),
    )
    changed = runtime.transition(
        target=row,
        previous_checkpoint=initial.checkpoint_after,
        prior_runs=initial.monitor_runs,
        resolutions=[],
        observation=changed_observation,
        run_id="MRUN-DNS-002",
        started_at=moment() + timedelta(hours=1),
        finished_at=moment() + timedelta(hours=1, minutes=1),
    )
    release = threading.Event()

    def delayed_resolver(_host, _port):
        release.wait(0.5)
        return [PUBLIC_IPV4]

    failure = observe(
        lambda _request: html_response(),
        delayed_resolver,
        resolver_timeout_seconds=0.01,
        context=LiveSourceContext(
            observed_at=moment() + timedelta(hours=2),
            previous_checkpoint=changed.checkpoint_after,
        ),
    )
    timed_out = runtime.transition(
        target=row,
        previous_checkpoint=changed.checkpoint_after,
        prior_runs=changed.monitor_runs,
        resolutions=[],
        observation=failure,
        run_id="MRUN-DNS-003",
        started_at=moment() + timedelta(hours=2),
        finished_at=moment() + timedelta(hours=2, minutes=1),
    )
    release.set()

    assert changed.checkpoint_after["target_state"] == "pending_human_review"
    assert timed_out.monitor_run["error_code"] == "timeout"
    assert timed_out.checkpoint_after["target_state"] == "pending_human_review"
    assert timed_out.checkpoint_after["pending_change_run_id"] == "MRUN-DNS-002"


def test_redirect_destination_is_resolved_again_and_unsafe_answer_stops():
    answers = iter(([PUBLIC_IPV4], ["127.0.0.1"]))
    resolver_calls = []
    requests = []

    def resolver(host, port):
        resolver_calls.append((host, port))
        return next(answers)

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(302, headers={"location": "/next"})

    result = observe(handler, resolver)
    assert result.error_code == "terms_not_approved"
    assert requests == ["/releases"]
    assert resolver_calls == [
        ("approved.example.invalid", 443),
        ("approved.example.invalid", 443),
    ]


@pytest.mark.parametrize(
    "location",
    [
        "javascript:alert(1)",
        "mailto:test@example.invalid",
        "data:text/plain,x",
    ],
)
def test_opaque_redirect_returns_sanitized_failure_without_second_request(location):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": location})

    result = observe(handler, lambda _host, _port: [PUBLIC_IPV4])
    assert isinstance(result, ObservationFailure)
    assert result.error_code == "unexpected_format"
    assert len(calls) == 1
    assert location not in result.error_detail
    assert location not in (result.source_url or "")


class RecordingStream(httpcore.NetworkStream):
    def __init__(self):
        body = b"<html><head><title>Pinned adapter metadata</title></head></html>"
        self._reads = [
            (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                + str(len(body)).encode("ascii")
                + b"\r\n\r\n"
                + body
            ),
            b"",
        ]
        self.server_hostname = None
        self.ssl_context = None
        self.writes = []

    def read(self, max_bytes, timeout=None):
        return self._reads.pop(0)

    def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    def close(self):
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.ssl_context = ssl_context
        self.server_hostname = server_hostname
        return self

    def get_extra_info(self, info):
        return None


class RecordingBackend(httpcore.NetworkBackend):
    def __init__(self):
        self.connected_hosts = []
        self.stream = RecordingStream()

    def connect_tcp(
        self,
        host,
        port,
        timeout=None,
        local_address=None,
        socket_options=None,
    ):
        self.connected_hosts.append((host, port))
        return self.stream


def test_pinned_transport_connects_checked_ip_but_keeps_tls_hostname():
    backend = RecordingBackend()
    transport = PinnedHTTPTransport(
        approved_host="approved.example.invalid",
        pinned_ip=PUBLIC_IPV4,
        ssl_context=ssl.create_default_context(),
        network_backend=backend,
    )
    with httpx.Client(transport=transport) as client:
        response = client.get("https://approved.example.invalid/releases")

    assert response.status_code == 200
    assert backend.connected_hosts == [(PUBLIC_IPV4, 443)]
    assert backend.stream.server_hostname == "approved.example.invalid"
    assert backend.stream.ssl_context.check_hostname is True
    assert backend.stream.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert b"Host: approved.example.invalid" in b"".join(backend.stream.writes)


def test_live_adapter_wires_resolved_ip_to_pinned_transport_and_tls_hostname():
    backend = RecordingBackend()
    with LiveSourceAdapter(
        resolver=lambda _host, _port: [PUBLIC_IPV4],
        network_backend_factory=lambda: backend,
    ) as adapter:
        result = adapter.observe(target(), LiveSourceContext(observed_at=moment()))

    assert isinstance(result, SourceObservation)
    assert backend.connected_hosts == [(PUBLIC_IPV4, 443)]
    assert backend.stream.server_hostname == "approved.example.invalid"
    assert b"Host: approved.example.invalid" in b"".join(backend.stream.writes)


def test_rebinding_resolver_is_not_called_again_by_pinned_connection():
    resolver_calls = []

    def rebinding_resolver(_host, _port):
        resolver_calls.append(True)
        return [PUBLIC_IPV4] if len(resolver_calls) == 1 else ["127.0.0.1"]

    pinned_ip = resolve_public_addresses(
        "approved.example.invalid",
        443,
        resolver=rebinding_resolver,
    )[0]
    backend = RecordingBackend()
    transport = PinnedHTTPTransport(
        approved_host="approved.example.invalid",
        pinned_ip=pinned_ip,
        ssl_context=ssl.create_default_context(),
        network_backend=backend,
    )
    with httpx.Client(transport=transport) as client:
        client.get("https://approved.example.invalid/releases")

    assert len(resolver_calls) == 1
    assert backend.connected_hosts == [(PUBLIC_IPV4, 443)]


def test_mocked_paths_do_not_use_system_dns_or_real_http(monkeypatch):
    def forbidden_dns(*_args, **_kwargs):
        raise AssertionError("system DNS must not be used by hardening tests")

    def forbidden_http(*_args, **_kwargs):
        raise AssertionError("default HTTP transport must not be used by hardening tests")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_dns)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden_http)
    result = observe(
        lambda _request: html_response(),
        lambda _host, _port: [PUBLIC_IPV4],
    )
    assert isinstance(result, SourceObservation)
