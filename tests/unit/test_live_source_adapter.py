from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from earnings_research.monitoring.live import (
    MAX_REDIRECT_HOPS,
    MAX_RESPONSE_BYTES,
    LiveSourceAdapter,
)
from earnings_research.monitoring.models import (
    LiveSourceContext,
    ObservationFailure,
    SourceObservation,
)
from earnings_research.monitoring.fingerprint import build_metadata_fingerprint
from earnings_research.monitoring.registry import load_registry
from earnings_research.monitoring.runtime import MonitorRuntime

JST = timezone(timedelta(hours=9))
PUBLIC_IP = "93.184.216.34"
REGISTRY = Path(__file__).resolve().parents[1] / "fixtures" / "monitor_operations" / "monitor_targets.csv"


def moment(hour=9, minute=0):
    return datetime(2026, 8, 7, hour, minute, tzinfo=JST)


def target():
    row = load_registry(REGISTRY)[0]
    row["source_url"] = "https://ir.example.invalid/releases"
    return row


def context(*, url=None, previous=None, at=None):
    return LiveSourceContext(
        observed_at=at or moment(),
        source_url=url,
        previous_checkpoint=previous or {},
    )


def html_response(
    title="Example Results",
    *,
    etag="etag-v1",
    last_modified="Fri, 07 Aug 2026 00:00:00 GMT",
    extra_meta="",
    headers=None,
):
    body = (
        "<!doctype html><html><head><title>%s</title>"
        '<meta name="document_id" content="DOC-001">'
        '<meta name="published_at" content="2026-08-07T08:30:00+09:00">'
        "%s</head><body>Public IR metadata</body></html>" % (title, extra_meta)
    ).encode("utf-8")
    response_headers = {
        "content-type": "text/html; charset=utf-8",
        "etag": etag,
        "last-modified": last_modified,
        "date": "Fri, 07 Aug 2026 00:01:00 GMT",
    }
    response_headers.update(headers or {})
    return httpx.Response(200, content=body, headers=response_headers)


def observe_with(handler, *, target_row=None, source_context=None, resolver=None):
    resolver = resolver or (lambda _host, _port: [PUBLIC_IP])
    with LiveSourceAdapter(
        transport=httpx.MockTransport(handler),
        resolver=resolver,
    ) as adapter:
        return adapter.observe(target_row or target(), source_context or context())


def check_robots_with(handler, *, target_row=None):
    with LiveSourceAdapter(
        transport=httpx.MockTransport(handler),
        resolver=lambda _host, _port: [PUBLIC_IP],
    ) as adapter:
        return adapter.check_robots(target_row or target(), context())


@pytest.mark.parametrize(
    "field,value",
    [
        ("automated_access_permitted", "false"),
        ("automation_approved_by", ""),
        ("automation_approved_by", "workflow:ai"),
        ("enabled", "false"),
        ("monitoring_level", "level_1"),
        ("terms_review_state", "candidate_specific_review_pending"),
        ("activation_state", "not_activated"),
        ("activation_approved_by", "workflow:ai"),
    ],
)
def test_approval_gate_rejects_before_network(field, value):
    calls = []
    row = target()
    row[field] = value

    result = observe_with(lambda request: calls.append(request), target_row=row)

    assert isinstance(result, ObservationFailure)
    assert result.error_code == "terms_not_approved"
    assert calls == []


def test_system_policy_authorization_is_accepted():
    row = target()
    row["automation_approved_by"] = "system_policy:public-web-low-frequency-v1"
    row["activation_approved_by"] = "system_policy:public-web-low-frequency-v1"
    result = observe_with(lambda _request: html_response(), target_row=row)
    assert isinstance(result, SourceObservation)


def test_robots_allows_approved_ir_path():
    result = check_robots_with(
        lambda _request: httpx.Response(
            200,
            content=b"User-agent: *\nDisallow: /admin/\n",
            headers={"content-type": "text/plain; charset=utf-8"},
        )
    )
    assert result is None


def test_robots_disallow_stops_before_source_request():
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(
            200,
            content=b"User-agent: *\nDisallow: /releases\n",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    result = check_robots_with(handler)
    assert result.error_code == "terms_not_approved"
    assert requests == ["/robots.txt"]


def test_absent_robots_file_does_not_create_an_unwritten_prohibition():
    result = check_robots_with(lambda _request: httpx.Response(404))
    assert result is None


def test_robots_transport_failure_is_not_treated_as_permission():
    result = check_robots_with(lambda _request: httpx.Response(503))
    assert result.error_code == "source_unavailable"


def test_unapproved_requested_origin_is_rejected_before_network():
    calls = []
    result = observe_with(
        lambda request: calls.append(request),
        source_context=context(url="https://other.example.invalid/releases"),
    )
    assert result.error_code == "terms_not_approved"
    assert calls == []


def test_200_html_produces_source_observation_and_safe_headers():
    requests = []

    def handler(request):
        requests.append(request)
        return html_response()

    result = observe_with(handler)

    assert isinstance(result, SourceObservation)
    assert result.title == "Example Results"
    assert result.document_id == "DOC-001"
    assert result.published_at == datetime(2026, 8, 7, 8, 30, tzinfo=JST)
    assert result.etag == "etag-v1"
    assert result.response_date == "Fri, 07 Aug 2026 00:01:00 GMT"
    assert result.content_type == "text/html"
    assert requests[0].headers["user-agent"].startswith("EarningsResearchSystem-Monitor/")
    assert "authorization" not in requests[0].headers
    assert "cookie" not in requests[0].headers


def test_200_json_uses_only_recognized_generic_metadata():
    payload = {
        "title": "Example JSON Results",
        "document_id": "DOC-JSON-1",
        "published_at": "2026-08-07T00:00:00Z",
        "stable_metadata": {"period": "FY2026", "token": "must-not-be-stored"},
    }
    result = observe_with(
        lambda _request: httpx.Response(
            200,
            json=payload,
            headers={"content-type": "application/json; charset=utf-8"},
        )
    )
    assert isinstance(result, SourceObservation)
    assert result.title == "Example JSON Results"
    assert result.stable_metadata["period"] == "FY2026"
    assert len(result.stable_metadata["page_content_sha256"]) == 64
    assert "token" not in result.stable_metadata


def disclosure_payload(title="2027年3月期第1四半期決算短信", published="2026/08/13 15:30:00"):
    return {
        "length": "1",
        "items": [
            {
                "title": title,
                "publishDate": published,
                "files": [
                    {
                        "type": "PDF-GENERAL",
                        "url": "https://contents.xj-storage.jp/xcontents/AS04527/latest.pdf",
                    }
                ],
            }
        ],
    }


def observe_disclosure_list(payload):
    row = target()
    row["source_category"] = "disclosure_list_json"
    return observe_with(
        lambda _request: httpx.Response(
            200, json=payload, headers={"content-type": "application/json"}
        ),
        target_row=row,
    )


def test_disclosure_list_fingerprint_uses_only_latest_item_metadata():
    result = observe_disclosure_list(disclosure_payload())
    assert isinstance(result, SourceObservation)
    assert result.title == "2027年3月期第1四半期決算短信"
    assert result.published_at == datetime(2026, 8, 13, 15, 30, tzinfo=JST)
    assert result.stable_metadata == {
        "latest_pdf_url": "https://contents.xj-storage.jp/xcontents/AS04527/latest.pdf"
    }
    assert len(build_metadata_fingerprint(result)) == 64


def test_disclosure_list_fingerprint_changes_when_new_item_is_prepended():
    previous_payload = disclosure_payload("Previous disclosure", "2026/08/01 15:00:00")
    current_payload = disclosure_payload()
    current_payload["items"].append(previous_payload["items"][0])
    previous = observe_disclosure_list(previous_payload)
    current = observe_disclosure_list(current_payload)
    assert build_metadata_fingerprint(previous) != build_metadata_fingerprint(current)


@pytest.mark.parametrize(
    "payload,expected_code",
    [
        ({"length": "0", "items": []}, "parse_error"),
        ({"length": "1", "items": [{"publishDate": "2026/08/13 15:30:00"}]}, "parse_error"),
        ({"length": "1", "items": [{"title": "Disclosure"}]}, "parse_error"),
        (disclosure_payload(published="not-a-timestamp"), "timestamp_parse_error"),
    ],
)
def test_disclosure_list_rejects_missing_or_invalid_latest_metadata(payload, expected_code):
    result = observe_disclosure_list(payload)
    assert isinstance(result, ObservationFailure)
    assert result.error_code == expected_code


def test_same_origin_redirect_is_followed_without_cookie_carryover():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert "cookie" not in request.headers
        if request.url.path == "/releases":
            return httpx.Response(
                302,
                headers={"location": "/releases/current", "set-cookie": "session=forbidden"},
            )
        return html_response()

    result = observe_with(handler)
    assert isinstance(result, SourceObservation)
    assert paths == ["/releases", "/releases/current"]


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example.invalid/releases",
        "http://ir.example.invalid/releases",
        "https://user:password@ir.example.invalid/releases",
        "https://ir.example.invalid:444/releases",
    ],
)
def test_unsafe_redirect_is_rejected_without_second_request(location):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": location})

    result = observe_with(handler)
    assert isinstance(result, ObservationFailure)
    assert result.error_code in {"terms_not_approved", "unexpected_format"}
    assert len(calls) == 1
    assert "password" not in result.error_detail
    assert "password" not in (result.source_url or "")


def test_redirect_loop_is_rejected():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        location = "/next" if request.url.path == "/releases" else "/releases"
        return httpx.Response(302, headers={"location": location})

    result = observe_with(handler)
    assert result.error_code == "unexpected_format"
    assert calls == ["/releases", "/next"]


def test_redirect_hop_limit_is_bounded():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        index = len(calls)
        return httpx.Response(302, headers={"location": "/hop-%s" % index})

    result = observe_with(handler)
    assert result.error_code == "unexpected_format"
    assert len(calls) == MAX_REDIRECT_HOPS + 1


@pytest.mark.parametrize(
    "url",
    [
        "https://user@ir.example.invalid/releases",
        "https://user:password@ir.example.invalid/releases",
        "https://ir.example.invalid/releases?token=secret-value",
        "https://ir.example.invalid/releases?api-key=secret-value",
    ],
)
def test_userinfo_and_secret_query_are_rejected_before_network(url):
    calls = []
    result = observe_with(lambda request: calls.append(request), source_context=context(url=url))
    assert result.error_code == "terms_not_approved"
    assert calls == []
    assert "secret-value" not in result.error_detail
    assert "secret-value" not in (result.source_url or "")


@pytest.mark.parametrize(
    "source_url",
    [
        "https://localhost/releases",
        "https://127.0.0.1/releases",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.1/releases",
        "https://127.1/releases",
        "https://2130706433/releases",
        "https://0177.0.0.1/releases",
        "https://0x7f000001/releases",
        "https://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_local_and_private_target_addresses_are_rejected(source_url):
    calls = []
    row = target()
    row["source_url"] = source_url
    result = observe_with(lambda request: calls.append(request), target_row=row)
    assert result.error_code == "terms_not_approved"
    assert calls == []


def test_timeout_is_sanitized_and_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("token=must-not-leak", request=request)

    result = observe_with(handler)
    assert result.error_code == "timeout"
    assert result.retryable is True
    assert "must-not-leak" not in result.error_detail
    assert len(calls) == 1


def test_overall_budget_is_checked_while_reading_the_response():
    times = iter([0.0, 0.0, 16.0])
    with LiveSourceAdapter(
        transport=httpx.MockTransport(lambda _request: html_response()),
        resolver=lambda _host, _port: [PUBLIC_IP],
        monotonic=lambda: next(times),
    ) as adapter:
        result = adapter.observe(target(), context())
    assert result.error_code == "timeout"
    assert result.retryable is True


@pytest.mark.parametrize(
    "status,expected,retryable",
    [
        (401, "authentication_required", False),
        (403, "authentication_required", False),
        (408, "timeout", True),
        (404, "source_unavailable", False),
        (429, "rate_limited", True),
        (418, "http_error", False),
        (500, "source_unavailable", True),
    ],
)
def test_http_status_mapping_is_fail_safe_and_single_attempt(status, expected, retryable):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    result = observe_with(handler)
    assert result.error_code == expected
    assert result.retryable is retryable
    assert len(calls) == 1


def test_declared_and_streamed_response_size_limits():
    declared = observe_with(
        lambda _request: httpx.Response(
            200,
            content=b"",
            headers={
                "content-type": "text/html",
                "content-length": str(MAX_RESPONSE_BYTES + 1),
            },
        )
    )
    streamed = observe_with(
        lambda _request: httpx.Response(
            200,
            content=b"x" * (MAX_RESPONSE_BYTES + 1),
            headers={"content-type": "text/html"},
        )
    )
    assert declared.error_code == "unexpected_format"
    assert streamed.error_code == "unexpected_format"


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "application/pdf"},
        {"content-type": "text/html", "content-length": "not-a-number"},
    ],
)
def test_wrong_content_contract_is_rejected(headers):
    result = observe_with(lambda _request: httpx.Response(200, content=b"content", headers=headers))
    assert result.error_code == "unexpected_format"


def test_common_japanese_charset_is_strictly_decoded():
    body = (
        "<html><head><title>決算情報</title>"
        '<meta name="document_id" content="DOC-JP"></head></html>'
    ).encode("cp932")
    result = observe_with(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=windows-31j"},
        )
    )
    assert isinstance(result, SourceObservation)
    assert result.title == "決算情報"


def test_decode_failure_and_replacement_character_are_parse_errors():
    invalid = observe_with(
        lambda _request: httpx.Response(
            200,
            content=b"<html><title>\x81</title></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    replacement = observe_with(
        lambda _request: httpx.Response(
            200,
            content="<html><title>Bad \ufffd title</title></html>".encode("utf-8"),
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    assert invalid.error_code == "parse_error"
    assert replacement.error_code == "parse_error"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            content=b"<html><head><title>Unclosed",
            headers={"content-type": "text/html"},
        ),
        httpx.Response(
            200,
            content=b"not-json",
            headers={"content-type": "application/json"},
        ),
        httpx.Response(
            200,
            json={"unrecognized": "value"},
            headers={"content-type": "application/json"},
        ),
    ],
)
def test_malformed_html_and_json_are_parse_errors(response):
    result = observe_with(lambda _request: response)
    assert result.error_code == "parse_error"


def test_timezone_ambiguous_timestamp_is_not_inferred():
    result = observe_with(
        lambda _request: httpx.Response(
            200,
            json={"title": "Results", "published_at": "2026-08-07T09:00:00"},
            headers={"content-type": "application/json"},
        )
    )
    assert result.error_code == "timestamp_parse_error"


@pytest.mark.parametrize("header", ["etag", "last-modified"])
def test_changed_response_indicator_sets_replacement_suspicion(header):
    previous = {"observed_etag": "", "observed_last_modified": "", "observed_content_length": ""}
    previous["observed_etag" if header == "etag" else "observed_last_modified"] = "old-value"
    result = observe_with(
        lambda _request: html_response(),
        source_context=context(previous=previous),
    )
    assert isinstance(result, SourceObservation)
    assert result.replacement_suspected is True


def test_content_length_inconsistency_sets_replacement_suspicion():
    response = html_response(headers={"content-length": "1"})
    result = observe_with(lambda _request: response)
    assert isinstance(result, SourceObservation)
    assert result.replacement_suspected is True


def test_corrected_marker_sets_replacement_suspicion():
    result = observe_with(
        lambda _request: html_response(extra_meta='<meta name="corrected" content="true">')
    )
    assert result.replacement_suspected is True


def test_page_content_digest_changes_without_persisting_response_body():
    first = observe_with(
        lambda _request: httpx.Response(
            200,
            text="<html><head><title>IR Library</title></head><body>old document</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    second = observe_with(
        lambda _request: httpx.Response(
            200,
            text="<html><head><title>IR Library</title></head><body>new document</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    assert first.stable_metadata["page_content_sha256"] != (
        second.stable_metadata["page_content_sha256"]
    )


def test_live_observations_flow_through_runtime_without_false_no_change():
    row = target()

    def fetch(title, etag, previous=None, at=None):
        return observe_with(
            lambda _request: html_response(title=title, etag=etag),
            target_row=row,
            source_context=context(previous=previous, at=at),
        )

    runtime = MonitorRuntime()
    initial_observation = fetch("Initial Results", "etag-v1", at=moment(9))
    initial = runtime.transition(
        target=row,
        previous_checkpoint=None,
        prior_runs=[],
        resolutions=[],
        observation=initial_observation,
        run_id="MRUN-EXAMPLE-001",
        started_at=moment(9),
        finished_at=moment(9, 1),
    )
    unchanged_observation = fetch(
        "Initial Results", "etag-v1", initial.checkpoint_after, moment(10)
    )
    unchanged = runtime.transition(
        target=row,
        previous_checkpoint=initial.checkpoint_after,
        prior_runs=initial.monitor_runs,
        resolutions=[],
        observation=unchanged_observation,
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(10),
        finished_at=moment(10, 1),
    )
    changed_observation = fetch(
        "Updated Results", "etag-v2", unchanged.checkpoint_after, moment(11)
    )
    changed = runtime.transition(
        target=row,
        previous_checkpoint=unchanged.checkpoint_after,
        prior_runs=unchanged.monitor_runs,
        resolutions=[],
        observation=changed_observation,
        run_id="MRUN-EXAMPLE-003",
        started_at=moment(11),
        finished_at=moment(11, 1),
    )
    replacement_observation = fetch(
        "Updated Results", "etag-v3", changed.checkpoint_after, moment(12)
    )
    replacement = runtime.transition(
        target=row,
        previous_checkpoint=changed.checkpoint_after,
        prior_runs=changed.monitor_runs,
        resolutions=[],
        observation=replacement_observation,
        run_id="MRUN-EXAMPLE-004",
        started_at=moment(12),
        finished_at=moment(12, 1),
    )
    parse_failure = observe_with(
        lambda _request: httpx.Response(
            200,
            content=b"<html><title>broken",
            headers={"content-type": "text/html"},
        ),
        target_row=row,
        source_context=context(previous=replacement.checkpoint_after, at=moment(13)),
    )
    failed = runtime.transition(
        target=row,
        previous_checkpoint=replacement.checkpoint_after,
        prior_runs=replacement.monitor_runs,
        resolutions=[],
        observation=parse_failure,
        run_id="MRUN-EXAMPLE-005",
        started_at=moment(13),
        finished_at=moment(13, 1),
    )

    assert initial.monitor_run["run_result"] == "initialized"
    assert unchanged.monitor_run["run_result"] == "no_change"
    assert changed.monitor_run["run_result"] == "change_detected"
    assert replacement.monitor_run["run_result"] == "error"
    assert replacement.monitor_run["error_code"] == "content_ambiguous"
    assert failed.monitor_run["run_result"] == "error"
    assert failed.monitor_run["error_code"] == "parse_error"


def test_mock_transport_does_not_fall_back_to_real_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("real network transport must not be used")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    result = observe_with(lambda _request: html_response())
    assert isinstance(result, SourceObservation)


def test_live_adapter_source_contains_no_tls_disable_or_auth_configuration():
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "earnings_research"
        / "monitoring"
        / "live.py"
    ).read_text(encoding="utf-8")
    assert "verify=False" not in source
    assert "BasicAuth" not in source
    assert "DigestAuth" not in source
    assert "Authorization" not in source
