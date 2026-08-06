import io
import json
import shutil
import zipfile
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from earnings_research.monitoring.github_api import GitHubAPIClient, GitHubAPIError
from earnings_research.monitoring.models import OfflineSourceInput
from earnings_research.monitoring.notifications import (
    build_issue_plan,
    deliver_issue_notification,
)
from earnings_research.monitoring.offline import OfflineSourceAdapter
from earnings_research.monitoring.operations import StateUnavailable, execute_offline_run
from earnings_research.monitoring.persistence import (
    BundleError,
    PersistenceError,
    verify_bundle,
    verify_uploaded_bundle,
    write_committed_bundle,
)
from earnings_research.monitoring.registry import RegistryError, load_registry
from earnings_research.monitoring.runtime import MonitorRuntime, MonitorTransitionError
from earnings_research.monitoring.stale import assess_stale_gap
from earnings_research.validation.validator import ValidationIssue, ValidationReport

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]
OFFLINE = ROOT / "tests" / "fixtures" / "monitor_offline"
REGISTRY = ROOT / "tests" / "fixtures" / "monitor_operations" / "monitor_targets.csv"
WORKFLOW = ROOT / ".github" / "workflows" / "level2_monitor.yml"


def moment(hour, minute=0, day=7):
    return datetime(2026, 8, day, hour, minute, tzinfo=JST)


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
        reference_time=moment(10, day=8),
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
        source_input=source_input("same", moment(22, day=9)),
        previous_bundle=previous,
        output_dir=tmp_path / "stale",
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(22, day=9),
        finished_at=moment(22, 1, day=9),
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


def test_userinfo_url_is_rejected_by_read_only_registry(tmp_path):
    text = REGISTRY.read_text(encoding="utf-8")
    unsafe = tmp_path / "unsafe.csv"
    unsafe.write_text(text.replace("https://example.invalid/", "https://user:secret@example.invalid/"), encoding="utf-8")

    with pytest.raises(RegistryError, match="userinfo"):
        load_registry(unsafe)


def test_workflow_has_scoped_permissions_fixed_python_and_no_live_or_push():
    raw = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)

    assert parsed
    assert 'python-version: "3.11.9"' in raw
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
    assert "monitor-verify-bundle" in raw
    assert "tests/fixtures/monitor_operations/monitor_targets.csv" in raw
    assert "data/config/monitor_targets.csv" in raw
