import io
import json
import re
import shutil
import urllib.request
import zipfile
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from earnings_research.monitoring.github_api import (
    CredentialStrippingRedirectHandler,
    GitHubAPIClient,
    GitHubAPIError,
)
from earnings_research.monitoring.handoff import build_research_handoff, write_research_handoff
from earnings_research.monitoring.models import ObservationFailure, OfflineSourceInput, SourceObservation
from earnings_research.monitoring.notifications import (
    build_issue_plan,
    build_workflow_failure_plan,
    WORKFLOW_FAILURE_REASONS,
    deliver_issue_notification,
)
from earnings_research.monitoring.offline import OfflineSourceAdapter
from earnings_research.monitoring.operations import (
    StateUnavailable,
    _stale_reference,
    execute_live_run,
    execute_offline_run,
)
from earnings_research.monitoring import operational_cli
from earnings_research.monitoring.operational_cli import record_gap_acknowledgement
from earnings_research.monitoring.persistence import (
    BundleError,
    PersistenceError,
    artifact_name,
    verify_bundle,
    verify_uploaded_bundle,
    write_committed_bundle,
)
from earnings_research.monitoring.registry import (
    RegistryError,
    active_target_plan,
    load_registry,
    next_announcement_date,
    observed_event_dates,
)
from earnings_research.monitoring.runtime import MonitorRuntime, MonitorTransitionError
from earnings_research.monitoring.stale import assess_stale_gap
from earnings_research.validation.validator import ValidationIssue, ValidationReport

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]
OFFLINE = ROOT / "tests" / "fixtures" / "monitor_offline"
REGISTRY = ROOT / "tests" / "fixtures" / "monitor_operations" / "monitor_targets.csv"
WORKFLOW = ROOT / ".github" / "workflows" / "level2_monitor.yml"


def moment(hour, minute=0, day=7, month=8):
    return datetime(2026, month, day, hour, minute, tzinfo=JST)


def target():
    return load_registry(REGISTRY)[0]


def source_input(name, at):
    html = OFFLINE / (name + ".html")
    return OfflineSourceInput(
        html_path=html if html.is_file() else None,
        metadata_path=OFFLINE / (name + ".json"),
        observed_at=at,
    )


def initial_bundle(tmp_path):
    return execute_offline_run(
        target=target(),
        source_input=source_input("initial", moment(9)),
        previous_bundle=None,
        output_dir=tmp_path / "v1",
        run_id="MRUN-EXAMPLE-001",
        started_at=moment(9),
        finished_at=moment(9, 1),
    )


def next_bundle(tmp_path, previous, name, run_id, hour, output_name):
    return execute_offline_run(
        target=target(),
        source_input=source_input(name, moment(hour)),
        previous_bundle=previous,
        output_dir=tmp_path / output_name,
        run_id=run_id,
        started_at=moment(hour),
        finished_at=moment(hour, 1),
    )


def copied_bundle(tmp_path, source, name):
    destination = tmp_path / name
    shutil.copytree(source.path, destination)
    return destination


def test_committed_bundle_round_trip_and_immutable_identity(tmp_path):
    bundle = initial_bundle(tmp_path)
    reread = verify_bundle(bundle.path)

    assert reread.manifest.bundle_status == "committed"
    assert reread.manifest.checkpoint_version == 1
    assert reread.latest_run["run_result"] == "initialized"
    assert reread.validation_report.ok


def test_validation_report_is_a_persistence_hard_gate(tmp_path):
    runtime = MonitorRuntime()
    transition = runtime.transition(
        target=target(),
        previous_checkpoint=None,
        prior_runs=[],
        resolutions=[],
        observation=OfflineSourceAdapter().observe(target(), source_input("initial", moment(9))),
        run_id="MRUN-EXAMPLE-001",
        started_at=moment(9),
        finished_at=moment(9, 1),
        self_validate=False,
    )
    invalid = replace(
        transition,
        validation_report=ValidationReport(
            [ValidationIssue("monitor_checkpoint", 1, "target_state", "forced invalid test")]
        ),
    )

    with pytest.raises(BundleError, match="validation_report.ok"):
        write_committed_bundle(
            output_dir=tmp_path / "must-not-exist",
            target=target(),
            transition=invalid,
            created_at=moment(9, 1),
        )
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("checkpoint_only", "file set"),
        ("run_only", "file set"),
        ("manifest_missing", "file set"),
        ("missing_file", "file set"),
        ("extra_file", "file set"),
        ("hash_mismatch", "hash mismatch"),
        ("manifest_extra", "manifest is invalid"),
        ("version_mismatch", "checkpoint version"),
        ("previous_run_mismatch", "previous_run_id"),
    ],
)
def test_corrupt_or_partial_bundle_is_rejected(tmp_path, mutation, match):
    bundle = initial_bundle(tmp_path)
    damaged = copied_bundle(tmp_path, bundle, "damaged-" + mutation)
    if mutation == "checkpoint_only":
        for path in damaged.iterdir():
            if path.name != "checkpoint.json":
                path.unlink()
    elif mutation == "run_only":
        for path in damaged.iterdir():
            if path.name != "run.json":
                path.unlink()
    elif mutation == "manifest_missing":
        (damaged / "manifest.json").unlink()
    elif mutation == "missing_file":
        (damaged / "run.json").unlink()
    elif mutation == "extra_file":
        (damaged / "unexpected.json").write_text("{}", encoding="utf-8")
    elif mutation == "hash_mismatch":
        (damaged / "target.json").write_text("{}\n", encoding="utf-8")
    else:
        manifest_path = damaged / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "manifest_extra":
            manifest["unexpected"] = "value"
        elif mutation == "version_mismatch":
            manifest["checkpoint_version"] = 2
        else:
            manifest["previous_run_id"] = "MRUN-WRONG"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BundleError, match=match):
        verify_bundle(damaged)


def test_failed_uploaded_reread_maps_to_persistence_error(tmp_path):
    bundle = initial_bundle(tmp_path)
    damaged = copied_bundle(tmp_path, bundle, "uploaded")
    (damaged / "checkpoint.json").unlink()

    with pytest.raises(PersistenceError, match="persistence_error"):
        verify_uploaded_bundle(damaged)


def test_missing_state_only_initializes_with_exact_human_activation(tmp_path):
    bad_target = target()
    bad_target["initialization_run_id"] = "MRUN-OTHER"
    with pytest.raises(StateUnavailable, match="Human-approved initialization"):
        execute_offline_run(
            target=bad_target,
            source_input=source_input("initial", moment(9)),
            previous_bundle=None,
            output_dir=tmp_path / "invalid",
            run_id="MRUN-EXAMPLE-001",
            started_at=moment(9),
            finished_at=moment(9, 1),
        )


def test_inactive_target_is_rejected_before_observation(tmp_path):
    inactive = target()
    inactive["active_until"] = moment(8).isoformat()
    with pytest.raises(StateUnavailable, match="not approved and active"):
        execute_offline_run(
            target=inactive,
            source_input=source_input("initial", moment(9)),
            previous_bundle=None,
            output_dir=tmp_path / "inactive",
            run_id="MRUN-EXAMPLE-001",
            started_at=moment(9),
            finished_at=moment(9, 1),
        )


def test_stale_gap_thresholds_are_fixed_and_fail_closed():
    normal = assess_stale_gap(
        last_success_at=moment(9),
        reference_time=moment(21, day=8),
        schedule_profile="prospective_event_v1",
        event_date=date(2026, 8, 20),
    )
    event_window = assess_stale_gap(
        last_success_at=moment(9),
        reference_time=moment(10, day=10),
        schedule_profile="prospective_event_v1",
        event_date=date(2026, 8, 12),
    )
    event_day = assess_stale_gap(
        last_success_at=moment(9),
        reference_time=moment(22),
        schedule_profile="prospective_event_v1",
        event_date=date(2026, 8, 7),
    )
    unknown_event = assess_stale_gap(
        last_success_at=moment(9),
        reference_time=moment(22),
        schedule_profile="prospective_event_v1",
        event_date=None,
        event_date_required=True,
    )

    assert (normal.window, normal.is_stale) == ("normal", False)
    assert (event_window.window, event_window.is_stale) == ("event_window", True)
    assert (event_day.window, event_day.is_stale) == ("event_day", True)
    assert (unknown_event.window, unknown_event.is_stale) == ("event_day", True)


def test_stale_previous_state_produces_fatal_stopped_bundle(tmp_path):
    previous = initial_bundle(tmp_path)
    stale = execute_offline_run(
        target=target(),
        source_input=source_input("same", moment(22, day=11)),
        previous_bundle=previous,
        output_dir=tmp_path / "stale",
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(22, day=11),
        finished_at=moment(22, 1, day=11),
    )

    assert stale.latest_run["run_result"] == "error"
    assert stale.latest_run["error_code"] == "state_unavailable"
    assert stale.checkpoint["target_state"] == "stopped"


def test_multiple_pending_changes_are_preserved_and_latest_is_pointer(tmp_path):
    initial = initial_bundle(tmp_path)
    first = next_bundle(tmp_path, initial, "changed", "MRUN-EXAMPLE-002", 10, "v2")
    second = next_bundle(tmp_path, first, "initial", "MRUN-EXAMPLE-003", 11, "v3")

    unresolved = [
        row["monitor_run_id"]
        for row in second.runs
        if row["run_result"] == "change_detected"
    ]
    assert unresolved == ["MRUN-EXAMPLE-002", "MRUN-EXAMPLE-003"]
    assert second.checkpoint["pending_change_run_id"] == "MRUN-EXAMPLE-003"
    assert second.checkpoint["target_state"] == "pending_human_review"
    assert build_issue_plan(first).dedup_key == build_issue_plan(second).dedup_key


def test_resolving_latest_change_reveals_older_pending_change(tmp_path):
    initial = initial_bundle(tmp_path)
    first = next_bundle(tmp_path, initial, "changed", "MRUN-EXAMPLE-002", 10, "v2")
    second = next_bundle(tmp_path, first, "initial", "MRUN-EXAMPLE-003", 11, "v3")
    resolution = {
        "resolution_id": "MRES-EXAMPLE-003",
        "monitor_target_id": target()["monitor_target_id"],
        "source_monitor_run_id": "MRUN-EXAMPLE-003",
        "resolution_type": "acknowledged_no_formal_action",
        "resolution": "Human reviewed the latest change",
        "resolved_at": moment(11, 30).isoformat(),
        "resolved_by": "human:reviewer-alpha",
        "supersedes_resolution_id": "",
        "notes": "Older unresolved change remains open",
    }
    transition = MonitorRuntime().transition(
        target=target(),
        previous_checkpoint=second.checkpoint,
        prior_runs=second.runs,
        resolutions=[resolution],
        observation=OfflineSourceAdapter().observe(target(), source_input("initial", moment(12))),
        run_id="MRUN-EXAMPLE-004",
        started_at=moment(12),
        finished_at=moment(12, 1),
    )

    assert transition.checkpoint_after["pending_change_run_id"] == "MRUN-EXAMPLE-002"


def test_future_dated_human_resolution_is_rejected_before_transition(tmp_path):
    initial = initial_bundle(tmp_path)
    changed = next_bundle(tmp_path, initial, "changed", "MRUN-EXAMPLE-002", 10, "v2")
    resolution = {
        "resolution_id": "MRES-FUTURE",
        "monitor_target_id": target()["monitor_target_id"],
        "source_monitor_run_id": "MRUN-EXAMPLE-002",
        "resolution_type": "acknowledged_no_formal_action",
        "resolution": "Invalid future resolution",
        "resolved_at": moment(13).isoformat(),
        "resolved_by": "human:reviewer-alpha",
        "supersedes_resolution_id": "",
        "notes": "",
    }
    observation = source_input("changed", moment(12))
    with pytest.raises(MonitorTransitionError, match="timestamp"):
        MonitorRuntime().transition(
            target=target(),
            previous_checkpoint=changed.checkpoint,
            prior_runs=changed.runs,
            resolutions=[resolution],
            observation=OfflineSourceAdapter().observe(target(), observation),
            run_id="MRUN-EXAMPLE-003",
            started_at=moment(12),
            finished_at=moment(12, 1),
        )


class FakeIssueClient:
    def __init__(self, failures=0, existing=None):
        self.failures = failures
        self.existing = existing
        self.calls = 0
        self.comments = []

    def find_open_issue(self, _dedup_key):
        self.calls += 1
        if self.calls <= self.failures:
            raise GitHubAPIError("simulated")
        return self.existing

    def create_issue(self, _title, _body):
        return {"number": 7, "html_url": "https://example.invalid/issues/7"}

    def comment_issue(self, number, body):
        self.comments.append((number, body))
        return {"id": 1}


def test_notifications_are_silent_for_no_change_and_bounded_for_change(tmp_path):
    initial = initial_bundle(tmp_path)
    unchanged = next_bundle(tmp_path, initial, "same", "MRUN-EXAMPLE-002", 10, "v2")
    changed = next_bundle(tmp_path, unchanged, "changed", "MRUN-EXAMPLE-003", 11, "v3")

    assert build_issue_plan(unchanged) is None
    plan = build_issue_plan(changed)
    sleeps = []
    receipt = deliver_issue_notification(
        client=FakeIssueClient(failures=2),
        plan=plan,
        target_id=changed.manifest.monitor_target_id,
        run_id=changed.manifest.monitor_run_id,
        recorded_at=moment(12),
        sleep=sleeps.append,
    )
    assert receipt.status == "delivered"
    assert receipt.attempts == 3
    assert sleeps == [1, 2]


def test_notification_failure_does_not_clear_pending_state(tmp_path):
    initial = initial_bundle(tmp_path)
    changed = next_bundle(tmp_path, initial, "changed", "MRUN-EXAMPLE-002", 10, "v2")
    receipt = deliver_issue_notification(
        client=FakeIssueClient(failures=10),
        plan=build_issue_plan(changed),
        target_id=changed.manifest.monitor_target_id,
        run_id=changed.manifest.monitor_run_id,
        recorded_at=moment(11),
        sleep=lambda _seconds: None,
    )

    assert receipt.status == "failed"
    assert receipt.attempts == 3
    assert changed.checkpoint["target_state"] == "pending_human_review"
    assert changed.latest_run["notification_status"] == "pending"


def test_error_issue_is_deduplicated_across_same_error_episode(tmp_path):
    initial = initial_bundle(tmp_path)
    first = execute_offline_run(
        target=target(),
        source_input=source_input("fatal", moment(10)),
        previous_bundle=initial,
        output_dir=tmp_path / "error-v2",
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(10),
        finished_at=moment(10, 1),
    )
    second = execute_offline_run(
        target=target(),
        source_input=source_input("fatal", moment(11)),
        previous_bundle=first,
        output_dir=tmp_path / "error-v3",
        run_id="MRUN-EXAMPLE-003",
        started_at=moment(11),
        finished_at=moment(11, 1),
    )

    first_plan = build_issue_plan(first)
    second_plan = build_issue_plan(second)
    assert first_plan.dedup_key == second_plan.dedup_key
    for field in (
        "monitor_target_id",
        "company/event",
        "monitor_run_id",
        "detected_at",
        "run_result",
        "target_state",
        "what_changed_or_error",
        "source_url",
        "confidence",
        "requires_human_decision",
        "recommended_next_action",
        "dedup_key",
    ):
        assert field in second_plan.body
    client = FakeIssueClient(existing={"number": 7, "html_url": "https://example.invalid/issues/7"})
    receipt = deliver_issue_notification(
        client=client,
        plan=second_plan,
        target_id=second.manifest.monitor_target_id,
        run_id=second.manifest.monitor_run_id,
        recorded_at=moment(12),
        sleep=lambda _seconds: None,
    )
    assert receipt.issue_number == 7
    assert len(client.comments) == 1


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_github_artifact_lookup_uses_injected_transport_only(tmp_path):
    requests = []

    def opener(request):
        requests.append(request)
        return FakeHTTPResponse(b'{"artifacts":[]}')

    client = GitHubAPIClient(repository="owner/repository", token="secret-token", opener=opener)
    assert client.fetch_previous_bundle(
        monitor_target_id="MON-EXAMPLE-CALENDAR", output_dir=tmp_path / "download"
    ) is None
    assert len(requests) == 1
    assert requests[0].full_url.startswith("https://api.github.com/repos/owner/repository/actions/artifacts")
    assert "secret-token" not in requests[0].full_url


def redirected_request(new_url, original_url="https://api.github.com/repos/owner/repository/actions/artifacts/1/zip"):
    original = urllib.request.Request(
        original_url,
        method="GET",
        headers={"Authorization": "Bearer secret-token", "Accept": "application/vnd.github+json"},
    )
    handler = CredentialStrippingRedirectHandler()
    return handler.redirect_request(original, io.BytesIO(b""), 302, "Found", {}, new_url)


def test_artifact_download_drops_the_credential_when_redirected_off_github():
    redirected = redirected_request("https://productionresultssa0.blob.core.windows.net/actions-results/abc?sig=xyz")
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Accept") == "application/vnd.github+json"


def test_artifact_download_keeps_the_credential_on_the_same_host():
    redirected = redirected_request("https://api.github.com/repos/owner/repository/actions/artifacts/2/zip")
    assert redirected is not None
    assert redirected.get_header("Authorization") == "Bearer secret-token"


def test_github_artifact_lookup_selects_and_verifies_highest_main_bundle(tmp_path):
    bundle = initial_bundle(tmp_path)
    archive_io = io.BytesIO()
    with zipfile.ZipFile(archive_io, "w") as archive:
        for path in bundle.path.iterdir():
            archive.write(path, path.name)
    listing = {
        "artifacts": [
            {
                "id": 10,
                "name": "ers-monitor-state-MON-EXAMPLE-CALENDAR-v1-MRUN-EXAMPLE-001",
                "expired": False,
                "workflow_run": {"head_branch": "feature/not-trusted"},
            },
            {
                "id": 11,
                "name": "ers-monitor-state-MON-EXAMPLE-CALENDAR-v1-MRUN-EXAMPLE-001",
                "expired": False,
                "workflow_run": {"head_branch": "main"},
            },
        ]
    }

    def opener(request):
        if request.full_url.endswith("/zip"):
            return FakeHTTPResponse(archive_io.getvalue())
        return FakeHTTPResponse(json.dumps(listing).encode("utf-8"))

    restored = GitHubAPIClient(
        repository="owner/repository", token="secret-token", opener=opener
    ).fetch_previous_bundle(
        monitor_target_id="MON-EXAMPLE-CALENDAR", output_dir=tmp_path / "restored"
    )
    assert restored.manifest.monitor_run_id == "MRUN-EXAMPLE-001"
    assert restored.validation_report.ok


def test_artifact_identity_includes_run_attempt_and_latest_attempt_wins(tmp_path):
    bundle = initial_bundle(tmp_path)
    assert artifact_name(bundle.manifest, run_attempt=2).endswith(
        "-v1-a2-MRUN-EXAMPLE-001"
    )
    with pytest.raises(BundleError, match="positive integer"):
        artifact_name(bundle.manifest, run_attempt=0)

    archive_io = io.BytesIO()
    with zipfile.ZipFile(archive_io, "w") as archive:
        for path in bundle.path.iterdir():
            archive.write(path, path.name)
    listing = {
        "artifacts": [
            {
                "id": 20,
                "name": "ers-monitor-state-MON-EXAMPLE-CALENDAR-v1-a1-MRUN-EXAMPLE-001",
                "expired": False,
                "workflow_run": {"head_branch": "main"},
            },
            {
                "id": 21,
                "name": "ers-monitor-state-MON-EXAMPLE-CALENDAR-v1-a2-MRUN-EXAMPLE-001",
                "expired": False,
                "workflow_run": {"head_branch": "main"},
            },
        ]
    }
    downloaded = []

    def opener(request):
        if request.full_url.endswith("/zip"):
            downloaded.append(request.full_url)
            return FakeHTTPResponse(archive_io.getvalue())
        return FakeHTTPResponse(json.dumps(listing).encode("utf-8"))

    GitHubAPIClient(
        repository="owner/repository", token="secret-token", opener=opener
    ).fetch_previous_bundle(
        monitor_target_id="MON-EXAMPLE-CALENDAR", output_dir=tmp_path / "attempt-restored"
    )
    assert downloaded == [
        "https://api.github.com/repos/owner/repository/actions/artifacts/21/zip"
    ]


def test_userinfo_url_is_rejected_by_read_only_registry(tmp_path):
    text = REGISTRY.read_text(encoding="utf-8")
    unsafe = tmp_path / "unsafe.csv"
    unsafe.write_text(text.replace("https://example.invalid/", "https://user:secret@example.invalid/"), encoding="utf-8")

    with pytest.raises(RegistryError, match="userinfo"):
        load_registry(unsafe)


def test_workflow_failure_plan_is_one_issue_per_target_per_day():
    same_day = [
        build_workflow_failure_plan(
            target_id="ICECO_TDNET_INDEX",
            workflow_run_url="https://example.invalid/run/%s" % index,
            occurred_at=moment(hour, day=17),
        )
        for index, hour in enumerate((1, 21))
    ]
    other_day = build_workflow_failure_plan(
        target_id="ICECO_TDNET_INDEX",
        workflow_run_url="https://example.invalid/run/3",
        occurred_at=moment(1, day=18),
    )
    other_target = build_workflow_failure_plan(
        target_id="OTHER_TARGET",
        workflow_run_url="https://example.invalid/run/4",
        occurred_at=moment(1, day=17),
    )
    assert same_day[0].dedup_key == same_day[1].dedup_key
    assert other_day.dedup_key != same_day[0].dedup_key
    assert other_target.dedup_key != same_day[0].dedup_key


def test_workflow_failure_day_is_japan_time_not_runner_utc():
    """The runner records UTC; the dedup day must still be a JST calendar day."""
    utc = timezone.utc
    before = build_workflow_failure_plan(
        target_id="T", workflow_run_url="", occurred_at=datetime(2026, 8, 17, 14, 59, 59, tzinfo=utc)
    )
    after = build_workflow_failure_plan(
        target_id="T", workflow_run_url="", occurred_at=datetime(2026, 8, 17, 15, 0, 0, tzinfo=utc)
    )
    same_jst_day = build_workflow_failure_plan(
        target_id="T", workflow_run_url="", occurred_at=datetime(2026, 8, 18, 14, 0, 0, tzinfo=utc)
    )
    assert before.dedup_key != after.dedup_key
    assert after.dedup_key == same_jst_day.dedup_key


@pytest.mark.parametrize("reason", WORKFLOW_FAILURE_REASONS)
def test_every_workflow_failure_reason_forbids_a_no_change_reading(reason):
    plan = build_workflow_failure_plan(
        target_id="T", workflow_run_url="", occurred_at=moment(9, day=17), reason=reason
    )
    assert plan.requires_human_decision is True
    assert "Do not read it as no_change" in plan.body


def test_delivery_failure_does_not_claim_the_run_observed_nothing():
    """The bundle exists when only Issue delivery failed."""
    plan = build_workflow_failure_plan(
        target_id="T", workflow_run_url="", occurred_at=moment(9, day=17),
        reason="notification_failed",
    )
    assert "run_result: `recorded_but_not_notified`" in plan.body
    assert "not_recorded" not in plan.body
    assert "observed nothing" not in plan.body
    assert "artifacts" in plan.body


def test_unknown_workflow_failure_reason_is_rejected():
    with pytest.raises(ValueError, match="reason"):
        build_workflow_failure_plan(
            target_id="T", workflow_run_url="", occurred_at=moment(9, day=17), reason="made_up"
        )


def test_monitor_job_and_pipeline_report_agree_on_an_empty_plan():
    """The same empty matrix must skip the monitor job and stay silent."""
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    monitor_condition = " ".join(parsed["jobs"]["monitor"]["if"].split())
    report_condition = " ".join(parsed["jobs"]["report-pipeline-failure"]["if"].split())
    assert monitor_condition == "needs.plan.outputs.matrix != '[]'"
    assert "needs.plan.outputs.matrix != '[]'" in report_condition


def test_pipeline_failure_job_covers_what_the_in_job_report_cannot():
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = parsed["jobs"]["report-pipeline-failure"]
    condition = " ".join(job["if"].split())
    assert job["needs"] == ["plan", "monitor"]
    assert "needs.plan.result != 'success'" in condition
    assert "needs.monitor.result == 'cancelled'" in condition
    # Nothing being due is the ordinary outcome on a day outside the window, so
    # a skipped monitor job only counts when the plan actually produced targets.
    assert "needs.monitor.result == 'skipped' && needs.plan.outputs.matrix != '[]'" in condition
    assert "needs.monitor.result == 'skipped')" not in condition
    # A failed monitor job already reports itself, so covering it here would
    # deliver two Issues for one failure.
    assert "needs.monitor.result == 'failure'" not in condition
    assert job["permissions"]["issues"] == "write"
    assert any("--reason pipeline" in str(step.get("run", "")) for step in job["steps"])


def test_workflow_failure_plan_refuses_to_read_as_no_change():
    plan = build_workflow_failure_plan(
        target_id="ICECO_TDNET_INDEX",
        workflow_run_url="https://example.invalid/run/1",
        occurred_at=moment(9, day=17),
    )
    assert plan.requires_human_decision is True
    assert "run_result: `not_recorded`" in plan.body
    assert "Do not read it as no_change" in plan.body
    assert "https://example.invalid/run/1" in plan.body
    assert plan.dedup_key in plan.body


def test_workflow_reports_a_job_that_never_produced_a_bundle():
    raw = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    steps = parsed["jobs"]["monitor"]["steps"]
    notice = [step for step in steps if step.get("id") == "failure-notice"]
    assert len(notice) == 1
    assert notice[0]["if"] == "failure() && steps.notify.outcome != 'success'"
    assert "monitor-notify-workflow-failure" in notice[0]["run"]
    assert notice[0]["continue-on-error"] is True
    assert "--workflow-run-url" in notice[0]["run"]
    # A delivery-only failure must not be reported as an unobserved run.
    assert "notification_failed" in notice[0]["env"]["REASON"]
    # It must come after the steps that turn an internal failure into a job
    # failure, otherwise failure() is still false when it is evaluated.
    order = [step.get("id") or step.get("name") for step in steps]
    assert order.index("failure-notice") > order.index("Surface failed earnings analysis")
    assert order.index("failure-notice") > order.index("Surface exhausted notification retry")


def test_workflow_has_scoped_permissions_fixed_python_and_no_live_or_push():
    raw = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)

    assert parsed
    assert 'python-version: "3.11.9"' in raw
    assert parsed["jobs"]["plan"]["timeout-minutes"] == 10
    assert parsed["jobs"]["monitor"]["timeout-minutes"] == 10
    assert "actions: read" in raw
    assert "issues: write" in raw
    assert "contents: write" not in raw
    assert "pull-requests: write" not in raw
    assert "actions: write" not in raw
    assert "git push" not in raw
    assert "curl " not in raw
    assert "wget " not in raw
    assert "retention-days: 14" in raw
    assert "cancel-in-progress: false" in raw
    assert raw.count("group: ers-level2-monitor-${{ matrix.monitor_target_id }}") == 1
    assert "\n  notify:" not in raw
    assert "python -m earnings_research.cli monitor-notify" in raw
    assert ".monitor/reread" in raw
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in raw
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in raw
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in raw
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in raw
    assert not re.search(r"uses:\s+actions/[^@]+@v[0-9]+", raw)
    assert "monitor-verify-bundle" in raw
    assert "tests/fixtures/monitor_operations/monitor_targets.csv" in raw
    assert "data/config/monitor_targets.csv" in raw
    assert "monitor-run-live" in raw
    dispatch_inputs = parsed[True]["workflow_dispatch"]["inputs"]
    assert "gap_acknowledgement" in dispatch_inputs
    assert "github.event_name == 'workflow_dispatch'" in raw
    assert "GAP_ACKNOWLEDGEMENT" in raw
    assert 'gap_acknowledgement_args=(--gap-acknowledgement .monitor/gap_acknowledgement.json)' in raw
    assert '"${gap_acknowledgement_args[@]}"' in raw
    assert "monitor-build-handoff" in raw
    assert 'cron: "17 0,4,8,12,16,20 * * *"' in raw


def test_schedule_uses_six_slots_in_event_window_and_on_event_day():
    row = target()
    row["event_date"] = "2026-08-13"
    for day in (12, 13):
        for hour in (1, 5, 9, 13, 17, 21):
            assert active_target_plan([row], planned_at=moment(hour, 17, day=day)) == [row]


@pytest.mark.parametrize("hour,minute", [(9, 17), (11, 37), (14, 59)])
def test_delayed_morning_run_is_still_due(hour, minute):
    row = target()
    row["event_date"] = "2026-08-13"
    assert active_target_plan([row], planned_at=moment(hour, minute, day=12)) == [row]


SCHEDULE = "2026-05-13=決算発表;2026-08-13=第1四半期決算発表;2026-11-13=第2四半期決算発表 | 2027-02-中旬=第3四半期決算発表"


@pytest.mark.parametrize(
    "today,expected",
    [
        ("2026-08-17", "2026-11-13"),
        ("2026-11-13", "2026-11-13"),
        ("2026-11-14", None),
        ("2026-05-01", "2026-05-13"),
    ],
)
def test_next_announcement_date_takes_the_first_date_not_yet_passed(today, expected):
    assert next_announcement_date(SCHEDULE, date.fromisoformat(today)) == expected


def test_undated_rows_never_open_a_window():
    """A window cannot be opened on 2027年2月中旬; no day was published."""
    assert next_announcement_date("none | 2027-02-中旬=第3四半期決算発表", date(2026, 12, 1)) is None


@pytest.mark.parametrize("schedule", ["", "none", "not-a-date=x", "2026-13-99=x"])
def test_unusable_schedule_falls_back_instead_of_guessing(schedule):
    assert next_announcement_date(schedule, date(2026, 8, 17)) is None


def test_observed_schedule_overrides_the_registry_event_date():
    row = target()
    row["event_date"] = "2026-08-13"
    row["schedule_source_target_id"] = "MON-SCHEDULE"
    resolved = observed_event_dates([row], {"MON-SCHEDULE": SCHEDULE}, date(2026, 8, 17))
    assert resolved == {row["monitor_target_id"]: "2026-11-13"}
    planned = active_target_plan(
        [row], planned_at=moment(9, day=10, month=11), observed_event_dates=resolved
    )
    # 2026-11-10 is three business days before the observed date, so the event
    # window is open even though the registry still names August.
    assert [item["event_date"] for item in planned] == ["2026-11-13"]
    assert active_target_plan([row], planned_at=moment(9, day=10, month=11)) == []


def test_missing_schedule_leaves_the_registry_event_date_in_place():
    row = target()
    row["event_date"] = "2026-08-13"
    row["schedule_source_target_id"] = "MON-SCHEDULE"
    assert observed_event_dates([row], {}, date(2026, 8, 17)) == {}
    planned = active_target_plan([row], planned_at=moment(9, day=13), observed_event_dates={})
    assert [item["event_date"] for item in planned] == ["2026-08-13"]


@pytest.mark.parametrize("hour", [1, 5, 9, 13, 17, 21])
def test_normal_day_more_than_five_business_days_before_event_uses_one_slot(hour):
    row = target()
    row["event_date"] = "2026-08-21"
    expected = [row] if hour == 17 else []
    assert active_target_plan([row], planned_at=moment(hour, day=12)) == expected


@pytest.mark.parametrize("hour", [1, 5, 9, 13, 17, 21])
def test_target_without_event_date_uses_one_after_close_slot(hour):
    """The TDnet index target carries no event date and must stay at one check per day."""
    row = target()
    row["event_date"] = ""
    expected = [row] if hour == 17 else []
    assert active_target_plan([row], planned_at=moment(hour, day=12)) == expected


def test_normal_threshold_absorbs_one_missed_business_day():
    """One skipped day must recover on its own; two in a row must stop."""
    last_success = datetime(2026, 8, 14, 17, 17, tzinfo=JST)
    one_missed = assess_stale_gap(
        last_success_at=last_success,
        reference_time=datetime(2026, 8, 18, 17, 17, tzinfo=JST),
        schedule_profile="prospective_event_v1",
        event_date=None,
    )
    two_missed = assess_stale_gap(
        last_success_at=last_success,
        reference_time=datetime(2026, 8, 19, 17, 17, tzinfo=JST),
        schedule_profile="prospective_event_v1",
        event_date=None,
    )
    assert one_missed.is_stale is False
    assert two_missed.is_stale is True


@pytest.mark.parametrize(
    "gap,expected_stale",
    [(timedelta(hours=60), False), (timedelta(hours=60, seconds=1), True)],
)
def test_normal_threshold_boundary_is_exactly_sixty_business_hours(gap, expected_stale):
    """Pins the value itself; the absorb-one-day test alone allows 48h..60h."""
    last_success = datetime(2026, 8, 17, 0, 0, tzinfo=JST)
    assessment = assess_stale_gap(
        last_success_at=last_success,
        reference_time=last_success + gap,
        schedule_profile="prospective_event_v1",
        event_date=None,
    )
    assert assessment.threshold == timedelta(hours=60)
    assert assessment.is_stale is expected_stale


def test_stale_elapsed_excludes_weekend_but_preserves_weekday_hours():
    weekend = assess_stale_gap(
        last_success_at=datetime(2026, 8, 7, 9, tzinfo=JST),
        reference_time=datetime(2026, 8, 10, 9, tzinfo=JST),
        schedule_profile="prospective_event_v1",
        event_date=date(2026, 8, 13),
    )
    weekday = assess_stale_gap(
        last_success_at=datetime(2026, 8, 10, 9, tzinfo=JST),
        reference_time=datetime(2026, 8, 11, 10, tzinfo=JST),
        schedule_profile="prospective_event_v1",
        event_date=date(2026, 8, 13),
    )
    assert weekend.age == timedelta(hours=24)
    assert weekend.is_stale is False
    assert weekday.age == timedelta(hours=25)
    assert weekday.is_stale is True


@pytest.mark.parametrize(
    ("event_date", "last_success", "reference", "delay_minutes"),
    [
        (date(2026, 8, 13), moment(9, 17, day=10), moment(9, 17, day=11), 0),
        (date(2026, 8, 13), moment(9, 17, day=10), moment(9, 18, day=11), 1),
        (date(2026, 8, 13), moment(9, 17, day=10), moment(10, 17, day=11), 60),
        (date(2026, 8, 11), moment(21, 17, day=10), moment(9, 17, day=11), 0),
        (date(2026, 8, 11), moment(21, 17, day=10), moment(9, 18, day=11), 1),
        (date(2026, 8, 11), moment(21, 17, day=10), moment(10, 17, day=11), 60),
    ],
)
def test_event_window_and_event_day_morning_stale_delay_boundary(
    event_date, last_success, reference, delay_minutes
):
    assessment = assess_stale_gap(
        last_success_at=last_success,
        reference_time=reference,
        schedule_profile="prospective_event_v1",
        event_date=event_date,
    )
    assert assessment.is_stale is (delay_minutes > 0)


@pytest.mark.parametrize("hour,minute", [(9, 17), (11, 37), (15, 17), (17, 5), (21, 17), (23, 30)])
def test_delayed_event_day_runs_are_due(hour, minute):
    row = target()
    row["event_date"] = "2026-08-13"
    assert active_target_plan([row], planned_at=moment(hour, minute, day=13)) == [row]


def test_event_day_eight_hour_cron_delay_remains_within_stale_threshold():
    assessment = assess_stale_gap(
        last_success_at=moment(21, 17, day=12),
        reference_time=moment(9, 17, day=13),
        schedule_profile="prospective_event_v1",
        event_date=date(2026, 8, 13),
    )
    assert assessment.age == timedelta(hours=12)
    assert assessment.is_stale is False


class StubLiveAdapter:
    def __init__(self, observation, robots_failure=None):
        self.observation = observation
        self.robots_failure = robots_failure
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def check_robots(self, _target, _context):
        self.calls.append("robots")
        return self.robots_failure

    def observe(self, _target, _context):
        self.calls.append("source")
        return self.observation


def test_live_operation_checks_robots_and_commits_valid_initial_state(tmp_path):
    row = target()
    row["automation_approved_by"] = "system_policy:public-web-low-frequency-v1"
    row["activation_approved_by"] = "system_policy:public-web-low-frequency-v1"
    observation = SourceObservation(
        source_url=row["source_url"],
        title="Initial live metadata",
        document_id=None,
        published_at=None,
        etag="etag-live-1",
        last_modified=None,
        content_length=100,
        replacement_suspected=False,
        observed_at=moment(9),
    )
    adapter = StubLiveAdapter(observation)
    bundle = execute_live_run(
        target=row,
        previous_bundle=None,
        output_dir=tmp_path / "live-v1",
        run_id="MRUN-EXAMPLE-001",
        started_at=moment(9),
        finished_at=moment(9, 1),
        adapter_factory=lambda: adapter,
    )
    assert adapter.calls == ["robots", "source"]
    assert bundle.latest_run["run_result"] == "initialized"
    assert bundle.validation_report.ok


def test_live_operation_does_not_fetch_source_when_robots_check_fails(tmp_path):
    row = target()
    failure = ObservationFailure(
        error_code="terms_not_approved",
        error_detail="robots policy disallows the approved source path",
        observed_at=moment(9),
    )
    adapter = StubLiveAdapter(None, failure)
    with pytest.raises(MonitorTransitionError, match="initialization requires a successful"):
        execute_live_run(
            target=row,
            previous_bundle=None,
            output_dir=tmp_path / "blocked",
            run_id="MRUN-EXAMPLE-001",
            started_at=moment(9),
            finished_at=moment(9, 1),
            adapter_factory=lambda: adapter,
        )
    assert adapter.calls == ["robots"]


def test_gap_acknowledgement_recovers_stopped_state_without_skipping_observation(tmp_path):
    previous = initial_bundle(tmp_path)
    stopped = execute_offline_run(
        target=target(),
        source_input=source_input("same", moment(22, day=11)),
        previous_bundle=previous,
        output_dir=tmp_path / "stopped",
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(22, day=11),
        finished_at=moment(22, 1, day=11),
    )
    acknowledgement = {
        "acknowledgement_id": "MGACK-EXAMPLE-001",
        "monitor_target_id": target()["monitor_target_id"],
        "acknowledged_gap_start": moment(9, day=7).isoformat(),
        "acknowledged_gap_end": moment(22, 15, day=11).isoformat(),
        "acknowledged_at": moment(22, 20, day=11).isoformat(),
        "acknowledged_by": "human:reviewer-alpha",
        "reason": "Artifact interruption reviewed; normal observation may resume",
        "supersedes_acknowledgement_id": "",
    }
    observation = SourceObservation(
        source_url=target()["source_url"],
        title="Initial fixture title",
        document_id="doc-initial",
        published_at=moment(8, day=7),
        etag="etag-initial",
        last_modified="Fri, 07 Aug 2026 00:00:00 GMT",
        content_length=100,
        replacement_suspected=False,
        observed_at=moment(23, day=11),
    )
    adapter = StubLiveAdapter(observation)
    recovered = execute_live_run(
        target=target(),
        previous_bundle=stopped,
        output_dir=tmp_path / "recovered",
        run_id="MRUN-EXAMPLE-003",
        started_at=moment(23, day=11),
        finished_at=moment(23, 1, day=11),
        adapter_factory=lambda: adapter,
        gap_acknowledgements=[acknowledgement],
    )
    assert adapter.calls == ["robots", "source"]
    assert recovered.latest_run["observation_status"] == "succeeded"
    assert recovered.checkpoint["target_state"] != "stopped"
    assert recovered.gap_acknowledgements == [acknowledgement]


def test_acknowledgement_expires_after_continued_observation_failures(tmp_path):
    previous = initial_bundle(tmp_path)
    stopped = execute_offline_run(
        target=target(), source_input=source_input("same", moment(22, day=11)),
        previous_bundle=previous, output_dir=tmp_path / "expired-stopped",
        run_id="MRUN-EXAMPLE-002", started_at=moment(22, day=11),
        finished_at=moment(22, 1, day=11),
    )
    acknowledgement = {
        "acknowledgement_id": "MGACK-EXPIRING-001",
        "monitor_target_id": target()["monitor_target_id"],
        "acknowledged_gap_start": moment(9).isoformat(),
        "acknowledged_gap_end": moment(22, 15, day=11).isoformat(),
        "acknowledged_at": moment(22, 20, day=11).isoformat(),
        "acknowledged_by": "human:reviewer-alpha",
        "reason": "Reviewed interruption before retrying observation",
        "supersedes_acknowledgement_id": "",
    }
    failure = ObservationFailure("timeout", "temporary failure", moment(23, day=11))
    first_adapter = StubLiveAdapter(failure)
    failed = execute_live_run(
        target=target(), previous_bundle=stopped, output_dir=tmp_path / "expired-failed",
        run_id="MRUN-EXAMPLE-003", started_at=moment(23, day=11),
        finished_at=moment(23, 1, day=11), adapter_factory=lambda: first_adapter,
        gap_acknowledgements=[acknowledgement],
    )
    assert first_adapter.calls == ["robots", "source"]

    stale_adapter = StubLiveAdapter(failure)
    stale = execute_live_run(
        target=target(), previous_bundle=failed, output_dir=tmp_path / "expired-again",
        run_id="MRUN-EXAMPLE-004", started_at=moment(13, day=17),
        finished_at=moment(13, 1, day=17), adapter_factory=lambda: stale_adapter,
    )
    assert stale.checkpoint["target_state"] == "stopped"
    assert stale_adapter.calls == []


def test_success_after_acknowledgement_does_not_cover_the_next_gap(tmp_path):
    previous = initial_bundle(tmp_path)
    stopped = execute_offline_run(
        target=target(), source_input=source_input("same", moment(22, day=11)),
        previous_bundle=previous, output_dir=tmp_path / "next-gap-stopped",
        run_id="MRUN-EXAMPLE-002", started_at=moment(22, day=11),
        finished_at=moment(22, 1, day=11),
    )
    acknowledgement = {
        "acknowledgement_id": "MGACK-NEXT-GAP-001",
        "monitor_target_id": target()["monitor_target_id"],
        "acknowledged_gap_start": moment(9).isoformat(),
        "acknowledged_gap_end": moment(22, 15, day=11).isoformat(),
        "acknowledged_at": moment(22, 20, day=11).isoformat(),
        "acknowledged_by": "human:reviewer-alpha",
        "reason": "Reviewed interruption before successful recovery",
        "supersedes_acknowledgement_id": "",
    }
    recovered = execute_offline_run(
        target=target(), source_input=source_input("same", moment(23, day=11)),
        previous_bundle=stopped, output_dir=tmp_path / "next-gap-recovered",
        run_id="MRUN-EXAMPLE-003", started_at=moment(23, day=11),
        finished_at=moment(23, 1, day=11), gap_acknowledgements=[acknowledgement],
    )
    next_gap = execute_offline_run(
        target=target(), source_input=source_input("same", moment(13, day=17)),
        previous_bundle=recovered, output_dir=tmp_path / "next-gap",
        run_id="MRUN-EXAMPLE-004", started_at=moment(13, day=17),
        finished_at=moment(13, 1, day=17),
    )
    assert next_gap.checkpoint["target_state"] == "stopped"


def test_stale_reference_uses_only_eligible_unsuperseded_target_tail_gap_end():
    checkpoint = {
        "monitor_target_id": "MON-TARGET",
        "last_success_at": moment(9).isoformat(),
    }
    rows = [
        {"acknowledgement_id": "OLD", "monitor_target_id": "MON-TARGET", "acknowledged_gap_end": moment(18).isoformat(), "acknowledged_at": moment(18, 1).isoformat(), "supersedes_acknowledgement_id": ""},
        {"acknowledgement_id": "TAIL", "monitor_target_id": "MON-TARGET", "acknowledged_gap_end": moment(12).isoformat(), "acknowledged_at": moment(12, 1).isoformat(), "supersedes_acknowledgement_id": "OLD"},
        {"acknowledgement_id": "OTHER", "monitor_target_id": "MON-OTHER", "acknowledged_gap_end": moment(20).isoformat(), "acknowledged_at": moment(20, 1).isoformat(), "supersedes_acknowledgement_id": ""},
        {"acknowledgement_id": "FUTURE", "monitor_target_id": "MON-TARGET", "acknowledged_gap_end": moment(21).isoformat(), "acknowledged_at": moment(23).isoformat(), "supersedes_acknowledgement_id": ""},
    ]
    assert _stale_reference(checkpoint, rows, moment(22)) == moment(12)


@pytest.mark.parametrize("case", ["healthy", "future", "resolved"])
def test_offline_operation_rejects_invalid_direct_gap_acknowledgement(tmp_path, case):
    initial = initial_bundle(tmp_path)
    previous = initial
    started_at = moment(23, day=11)
    if case != "healthy":
        previous = execute_offline_run(
            target=target(), source_input=source_input("same", moment(22, day=11)),
            previous_bundle=initial, output_dir=tmp_path / (case + "-stopped"),
            run_id="MRUN-EXAMPLE-002", started_at=moment(22, day=11),
            finished_at=moment(22, 1, day=11),
        )
    gap_end = moment(22, 15, day=11)
    acknowledged_at = moment(22, 20, day=11)
    if case == "future":
        acknowledged_at = moment(23, 1, day=11)
    elif case == "resolved":
        gap_end = moment(8)
    acknowledgement = {
        "acknowledgement_id": "MGACK-DIRECT-" + case.upper(),
        "monitor_target_id": target()["monitor_target_id"],
        "acknowledged_gap_start": moment(7).isoformat(),
        "acknowledged_gap_end": gap_end.isoformat(),
        "acknowledged_at": acknowledged_at.isoformat(),
        "acknowledged_by": "human:reviewer-alpha",
        "reason": "Direct library boundary test",
        "supersedes_acknowledgement_id": "",
    }
    with pytest.raises(StateUnavailable):
        execute_offline_run(
            target=target(), source_input=source_input("same", started_at),
            previous_bundle=previous, output_dir=tmp_path / (case + "-rejected"),
            run_id="MRUN-EXAMPLE-003", started_at=started_at,
            finished_at=moment(23, 1, day=11), gap_acknowledgements=[acknowledgement],
        )


def test_gap_acknowledgement_does_not_clear_pending_change(tmp_path):
    initial = initial_bundle(tmp_path)
    changed = next_bundle(tmp_path, initial, "changed", "MRUN-EXAMPLE-002", 10, "changed")
    stopped = execute_offline_run(
        target=target(),
        source_input=source_input("changed", moment(22, day=12)),
        previous_bundle=changed,
        output_dir=tmp_path / "pending-stopped",
        run_id="MRUN-EXAMPLE-003",
        started_at=moment(22, day=12),
        finished_at=moment(22, 1, day=12),
    )
    acknowledgement = {
        "acknowledgement_id": "MGACK-EXAMPLE-PENDING",
        "monitor_target_id": target()["monitor_target_id"],
        "acknowledged_gap_start": moment(10, day=7).isoformat(),
        "acknowledged_gap_end": moment(22, 15, day=12).isoformat(),
        "acknowledged_at": moment(22, 20, day=12).isoformat(),
        "acknowledged_by": "system_policy:monitor-gap-recovery-v1",
        "reason": "Policy-reviewed infrastructure interruption",
        "supersedes_acknowledgement_id": "",
    }
    recovered = execute_offline_run(
        target=target(),
        source_input=source_input("changed", moment(23, day=12)),
        previous_bundle=stopped,
        output_dir=tmp_path / "pending-recovered",
        run_id="MRUN-EXAMPLE-004",
        started_at=moment(23, day=12),
        finished_at=moment(23, 1, day=12),
        gap_acknowledgements=[acknowledgement],
    )
    assert recovered.checkpoint["pending_change_run_id"] == "MRUN-EXAMPLE-002"
    assert recovered.checkpoint["target_state"] == "pending_human_review"


def test_gap_acknowledgement_cli_rejects_future_and_already_resolved_gaps(tmp_path):
    previous = initial_bundle(tmp_path)
    stopped = execute_offline_run(
        target=target(),
        source_input=source_input("same", moment(22, day=11)),
        previous_bundle=previous,
        output_dir=tmp_path / "cli-stopped",
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(22, day=11),
        finished_at=moment(22, 1, day=11),
    )
    common = {
        "previous_dir": stopped.path,
        "output_path": tmp_path / "ack.json",
        "acknowledgement_id": "MGACK-INVALID",
        "gap_start": moment(8, day=7).isoformat(),
        "acknowledged_at": moment(22, 20, day=11).isoformat(),
        "acknowledged_by": "human:reviewer-alpha",
        "reason": "Reviewed interruption",
    }
    with pytest.raises(ValueError, match="future monitoring gap"):
        record_gap_acknowledgement(
            **common,
            gap_end=moment(23, day=11).isoformat(),
        )
    with pytest.raises(ValueError, match="already resolved"):
        record_gap_acknowledgement(
            **common,
            gap_end=moment(8, 30, day=7).isoformat(),
        )


def test_gap_acknowledgement_cli_rejects_missing_last_success_clearly(tmp_path, monkeypatch):
    previous = initial_bundle(tmp_path)
    stopped = execute_offline_run(
        target=target(), source_input=source_input("same", moment(22, day=11)),
        previous_bundle=previous, output_dir=tmp_path / "missing-success-stopped",
        run_id="MRUN-EXAMPLE-002", started_at=moment(22, day=11),
        finished_at=moment(22, 1, day=11),
    )
    without_success = replace(
        stopped, checkpoint={**stopped.checkpoint, "last_success_at": ""}
    )
    monkeypatch.setattr(operational_cli, "verify_bundle", lambda _path: without_success)
    with pytest.raises(ValueError, match="last_success_at is required"):
        record_gap_acknowledgement(
            previous_dir=without_success.path,
            output_path=tmp_path / "missing-success.json",
            acknowledgement_id="MGACK-MISSING-SUCCESS",
            gap_start=moment(9).isoformat(),
            gap_end=moment(22, 15, day=11).isoformat(),
            acknowledged_at=moment(22, 20, day=11).isoformat(),
            acknowledged_by="human:reviewer-alpha",
            reason="Explicit missing timestamp error test",
        )


def test_autonomous_change_creates_machine_readable_research_handoff(tmp_path):
    row = target()
    row["change_response"] = "autonomous_research_handoff"
    initial = execute_offline_run(
        target=row,
        source_input=source_input("initial", moment(9)),
        previous_bundle=None,
        output_dir=tmp_path / "auto-v1",
        run_id="MRUN-EXAMPLE-001",
        started_at=moment(9),
        finished_at=moment(9, 1),
    )
    changed = execute_offline_run(
        target=row,
        source_input=source_input("changed", moment(10)),
        previous_bundle=initial,
        output_dir=tmp_path / "auto-v2",
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(10),
        finished_at=moment(10, 1),
    )
    payload = build_research_handoff(changed)
    assert payload["status"] == "ready_for_document_discovery"
    assert payload["raw_content_included"] is False
    output = tmp_path / "handoff.json"
    assert write_research_handoff(changed, output) is True
    assert json.loads(output.read_text())["monitor_run_id"] == "MRUN-EXAMPLE-002"
