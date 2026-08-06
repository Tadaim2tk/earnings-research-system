from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from earnings_research.monitoring import (
    MonitorRuntime,
    MonitorTransitionError,
    ObservationFailure,
    OfflineSourceAdapter,
    OfflineSourceInput,
    SourceObservation,
    build_metadata_fingerprint,
    classify_error_state,
)
from earnings_research.monitoring.fingerprint import (
    canonicalize_datetime,
    canonicalize_title,
    canonicalize_url,
    metadata_fingerprint_payload,
)

JST = timezone(timedelta(hours=9))
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "monitor_offline"


def moment(hour, minute=0):
    return datetime(2026, 8, 7, hour, minute, tzinfo=JST)


def target(initialization_run_id="MRUN-EXAMPLE-001"):
    return {
        "monitor_target_id": "MON-EXAMPLE-CALENDAR",
        "company_id": "CMP-EXAMPLE",
        "earnings_event_id": "",
        "source_name": "Example Holdings IR Calendar",
        "source_url": "https://example.invalid/ir/calendar",
        "source_category": "company_ir_calendar",
        "monitoring_level": "level_2",
        "automated_access_permitted": "true",
        "enabled": "true",
        "schedule_profile": "prospective_event_v1",
        "timezone": "Asia/Tokyo",
        "active_from": "2026-08-07T00:00:00+09:00",
        "active_until": "2026-08-31T23:59:59+09:00",
        "terms_review_state": "candidate_specific_review_completed",
        "last_terms_review_at": "2026-08-06T10:00:00+09:00",
        "terms_review_reference": "terms-review:example-v1",
        "automation_approved_by": "human:reviewer-alpha",
        "activation_state": "activated",
        "activated_at": "2026-08-07T08:00:00+09:00",
        "activation_approved_by": "human:reviewer-alpha",
        "initialization_generation": "1",
        "initialization_run_id": initialization_run_id,
    }


def observe(name, at):
    return OfflineSourceAdapter().observe(
        target(),
        OfflineSourceInput(
            html_path=FIXTURES / (name + ".html") if (FIXTURES / (name + ".html")).exists() else None,
            metadata_path=FIXTURES / (name + ".json"),
            observed_at=at,
        ),
    )


def run_sequence():
    runtime = MonitorRuntime()
    results = {}
    initial = runtime.transition(
        target=target(),
        previous_checkpoint=None,
        prior_runs=[],
        resolutions=[],
        observation=observe("initial", moment(9)),
        run_id="MRUN-EXAMPLE-001",
        started_at=moment(9),
        finished_at=moment(9, 1),
    )
    results["initialized"] = initial

    no_change = runtime.transition(
        target=target(),
        previous_checkpoint=initial.checkpoint_after,
        prior_runs=initial.monitor_runs,
        resolutions=[],
        observation=observe("same", moment(10)),
        run_id="MRUN-EXAMPLE-002",
        started_at=moment(10),
        finished_at=moment(10, 1),
    )
    results["no_change"] = no_change

    changed = runtime.transition(
        target=target(),
        previous_checkpoint=no_change.checkpoint_after,
        prior_runs=no_change.monitor_runs,
        resolutions=[],
        observation=observe("changed", moment(11)),
        run_id="MRUN-EXAMPLE-003",
        started_at=moment(11),
        finished_at=moment(11, 1),
    )
    results["change_detected"] = changed

    pending_no_change = runtime.transition(
        target=target(),
        previous_checkpoint=changed.checkpoint_after,
        prior_runs=changed.monitor_runs,
        resolutions=[],
        observation=observe("changed", moment(12)),
        run_id="MRUN-EXAMPLE-004",
        started_at=moment(12),
        finished_at=moment(12, 1),
    )
    results["pending_no_change"] = pending_no_change

    pending_timeout = runtime.transition(
        target=target(),
        previous_checkpoint=pending_no_change.checkpoint_after,
        prior_runs=pending_no_change.monitor_runs,
        resolutions=[],
        observation=observe("timeout", moment(13)),
        run_id="MRUN-EXAMPLE-005",
        started_at=moment(13),
        finished_at=moment(13, 1),
    )
    results["pending_timeout"] = pending_timeout

    resolution = {
        "resolution_id": "MRES-EXAMPLE-001",
        "monitor_target_id": "MON-EXAMPLE-CALENDAR",
        "source_monitor_run_id": "MRUN-EXAMPLE-003",
        "resolution_type": "acknowledged_no_formal_action",
        "resolution": "Human reviewed the changed metadata",
        "resolved_at": "2026-08-07T13:30:00+09:00",
        "resolved_by": "human:reviewer-alpha",
        "supersedes_resolution_id": "",
        "notes": "Offline scenario resolution",
    }
    resolved = runtime.transition(
        target=target(),
        previous_checkpoint=pending_timeout.checkpoint_after,
        prior_runs=pending_timeout.monitor_runs,
        resolutions=[resolution],
        observation=observe("changed", moment(14)),
        run_id="MRUN-EXAMPLE-006",
        started_at=moment(14),
        finished_at=moment(14, 1),
    )
    results["human_resolution"] = resolved

    replacement = runtime.transition(
        target=target(),
        previous_checkpoint=resolved.checkpoint_after,
        prior_runs=resolved.monitor_runs,
        resolutions=[resolution],
        observation=OfflineSourceAdapter().observe(
            target(),
            OfflineSourceInput(
                html_path=FIXTURES / "changed.html",
                metadata_path=FIXTURES / "replacement.json",
                observed_at=moment(15),
            ),
        ),
        run_id="MRUN-EXAMPLE-007",
        started_at=moment(15),
        finished_at=moment(15, 1),
    )
    results["replacement_suspicion"] = replacement

    fatal = runtime.transition(
        target=target(),
        previous_checkpoint=replacement.checkpoint_after,
        prior_runs=replacement.monitor_runs,
        resolutions=[resolution],
        observation=observe("fatal", moment(16)),
        run_id="MRUN-EXAMPLE-008",
        started_at=moment(16),
        finished_at=moment(16, 1),
    )
    results["fatal_error"] = fatal
    return results


def test_canonicalization_preserves_contract_boundaries():
    assert canonicalize_url("HTTPS://Example.INVALID/Case/Path?B=2#fragment") == "https://example.invalid/Case/Path?B=2"
    assert canonicalize_title("  ＡＢＣ\n  Results  ") == "ABC Results"
    assert canonicalize_datetime(datetime(2026, 8, 7, 9, tzinfo=JST)) == "2026-08-07T00:00:00+00:00"


def test_fingerprint_is_deterministic_and_keeps_null_distinct_from_empty():
    base = SourceObservation(
        source_url="HTTPS://EXAMPLE.INVALID/IR#top",
        title="Example  Results",
        document_id=None,
        published_at=moment(9),
        etag=None,
        last_modified=None,
        content_length=None,
        replacement_suspected=False,
        observed_at=moment(9),
        stable_metadata={"period": "FY2026"},
    )
    equivalent = SourceObservation(**{**base.__dict__, "source_url": "https://example.invalid/IR", "title": "Example Results"})
    empty_id = SourceObservation(**{**base.__dict__, "document_id": ""})

    assert build_metadata_fingerprint(base) == build_metadata_fingerprint(equivalent)
    assert build_metadata_fingerprint(base) != build_metadata_fingerprint(empty_id)
    assert metadata_fingerprint_payload(base)[2] == ["document_id", None]


def test_fingerprint_rejects_naive_datetime():
    observation = SourceObservation(
        source_url="https://example.invalid",
        title=None,
        document_id=None,
        published_at=datetime(2026, 8, 7, 9),
        etag=None,
        last_modified=None,
        content_length=None,
        replacement_suspected=False,
        observed_at=moment(9),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        build_metadata_fingerprint(observation)


def test_offline_adapter_extracts_html_and_metadata_without_network():
    observation = observe("initial", moment(9))
    assert isinstance(observation, SourceObservation)
    assert observation.source_url == "https://example.invalid/ir/calendar"
    assert observation.document_id == "DOC-EXAMPLE-001"
    assert observation.etag == "etag-example-1"
    assert observation.content_length == 1024


def test_initialization_requires_matching_human_activation():
    with pytest.raises(MonitorTransitionError, match="Human-owned activation"):
        MonitorRuntime().transition(
            target=target("MRUN-WRONG"),
            previous_checkpoint=None,
            prior_runs=[],
            resolutions=[],
            observation=observe("initial", moment(9)),
            run_id="MRUN-EXAMPLE-001",
            started_at=moment(9),
            finished_at=moment(9, 1),
        )


def test_missing_checkpoint_does_not_reinitialize_existing_lineage():
    prior = run_sequence()["initialized"].monitor_runs
    with pytest.raises(MonitorTransitionError, match="must not reinitialize"):
        MonitorRuntime().transition(
            target=target("MRUN-EXAMPLE-009"),
            previous_checkpoint=None,
            prior_runs=prior,
            resolutions=[],
            observation=observe("initial", moment(17)),
            run_id="MRUN-EXAMPLE-009",
            started_at=moment(17),
            finished_at=moment(17, 1),
        )


@pytest.mark.parametrize(
    ("scenario", "run_result", "target_state"),
    [
        ("initialized", "initialized", "healthy"),
        ("no_change", "no_change", "healthy"),
        ("change_detected", "change_detected", "pending_human_review"),
        ("pending_no_change", "no_change", "pending_human_review"),
        ("pending_timeout", "error", "pending_human_review"),
        ("human_resolution", "no_change", "healthy"),
        ("replacement_suspicion", "error", "degraded"),
        ("fatal_error", "error", "stopped"),
    ],
)
def test_offline_scenarios_generate_expected_valid_bundle(scenario, run_result, target_state):
    result = run_sequence()[scenario]
    assert result.monitor_run["run_result"] == run_result
    assert result.checkpoint_after["target_state"] == target_state
    assert result.validation_report.ok


def test_pending_pointer_survives_no_change_and_timeout():
    results = run_sequence()
    source_id = results["change_detected"].monitor_run["monitor_run_id"]
    assert results["pending_no_change"].checkpoint_after["pending_change_run_id"] == source_id
    assert results["pending_timeout"].checkpoint_after["pending_change_run_id"] == source_id
    assert results["pending_timeout"].checkpoint_after["last_error_code"] == "timeout"


def test_human_resolution_is_required_to_clear_pending_state():
    result = run_sequence()["human_resolution"]
    assert result.checkpoint_after["pending_change_run_id"] == ""
    assert result.checkpoint_after["resolution_applied_id"] == "MRES-EXAMPLE-001"


def test_replacement_suspicion_never_becomes_no_change():
    result = run_sequence()["replacement_suspicion"]
    assert result.monitor_run["run_result"] == "error"
    assert result.monitor_run["error_code"] == "content_ambiguous"
    assert result.monitor_run["notification_status"] == "pending"


def test_etag_conflict_without_explicit_flag_is_content_ambiguous():
    resolved = run_sequence()["human_resolution"]
    observation = observe("changed", moment(15))
    assert isinstance(observation, SourceObservation)
    observation = replace(observation, etag="etag-example-conflict", replacement_suspected=False)
    result = MonitorRuntime().transition(
        target=target(),
        previous_checkpoint=resolved.checkpoint_after,
        prior_runs=resolved.monitor_runs,
        resolutions=resolved.monitor_resolutions,
        observation=observation,
        run_id="MRUN-EXAMPLE-007B",
        started_at=moment(15),
        finished_at=moment(15, 1),
    )
    assert result.monitor_run["run_result"] == "error"
    assert result.monitor_run["error_code"] == "content_ambiguous"
    assert result.checkpoint_after["target_state"] == "degraded"


def test_fatal_error_never_claims_healthy_and_positive_bundle_passes():
    result = run_sequence()["fatal_error"]
    assert result.monitor_run["error_code"] == "state_unavailable"
    assert result.checkpoint_after["target_state"] == "stopped"
    assert result.validation_report.ok


def test_fatal_error_stops_target_without_discarding_pending_change():
    changed = run_sequence()["change_detected"]
    result = MonitorRuntime().transition(
        target=target(),
        previous_checkpoint=changed.checkpoint_after,
        prior_runs=changed.monitor_runs,
        resolutions=[],
        observation=observe("fatal", moment(12)),
        run_id="MRUN-EXAMPLE-004F",
        started_at=moment(12),
        finished_at=moment(12, 1),
    )
    assert result.checkpoint_after["target_state"] == "stopped"
    assert result.checkpoint_after["pending_change_run_id"] == "MRUN-EXAMPLE-003"
    assert result.checkpoint_after["last_error_code"] == "state_unavailable"
    assert result.validation_report.ok


def test_persistence_error_is_not_falsely_committed_by_offline_core():
    initial = run_sequence()["initialized"]
    with pytest.raises(MonitorTransitionError, match="PR D persistence boundary"):
        MonitorRuntime().transition(
            target=target(),
            previous_checkpoint=initial.checkpoint_after,
            prior_runs=initial.monitor_runs,
            resolutions=[],
            observation=ObservationFailure("persistence_error", "write failed", moment(10)),
            run_id="MRUN-EXAMPLE-009",
            started_at=moment(10),
            finished_at=moment(10, 1),
        )


def test_persistence_error_is_classified_as_fatal_even_before_pr_d_persistence():
    assert classify_error_state("persistence_error", False) == "stopped"
    assert classify_error_state("persistence_error", True) == "stopped"


def test_invalid_human_resolution_is_rejected_before_state_recovery():
    changed = run_sequence()["change_detected"]
    invalid_resolution = {
        "resolution_id": "MRES-EXAMPLE-AI",
        "monitor_target_id": "MON-EXAMPLE-CALENDAR",
        "source_monitor_run_id": "MRUN-EXAMPLE-003",
        "resolution_type": "acknowledged_no_formal_action",
        "resolution": "AI attempted resolution",
        "resolved_at": "2026-08-07T11:30:00+09:00",
        "resolved_by": "workflow:monitor-v1",
        "supersedes_resolution_id": "",
        "notes": "invalid",
    }
    with pytest.raises(MonitorTransitionError, match="valid Human resolution"):
        MonitorRuntime().transition(
            target=target(),
            previous_checkpoint=changed.checkpoint_after,
            prior_runs=changed.monitor_runs,
            resolutions=[invalid_resolution],
            observation=observe("changed", moment(12)),
            run_id="MRUN-EXAMPLE-004",
            started_at=moment(12),
            finished_at=moment(12, 1),
        )
