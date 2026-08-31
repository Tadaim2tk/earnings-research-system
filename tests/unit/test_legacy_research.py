import csv
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import jsonschema
import pytest

from earnings_research.cli.__main__ import main
from earnings_research.legacy_research.importer import EXPECTED_FIELDS, build_import
from earnings_research.legacy_research.pipeline import migrate_legacy_os, verify_legacy_migration
from earnings_research.legacy_research.importer import parse_csv_bytes
from earnings_research.legacy_research.aggregation import _open_anchored
from earnings_research.statistics.holdout import MIN_FOR_RESERVE, split_by_date
from earnings_research.legacy_research.legacy_parity import (
    render_dashboard_as_retired,
    render_note_as_retired,
    render_weekly_as_retired,
)


ROOT = Path(__file__).resolve().parents[2]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def init_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://example.invalid/{path.name}.git"], cwd=path, check=True)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def commit_all(repo, message):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    return git(repo, "rev-parse", "HEAD")


def row(code="1111", name="架空会社", event_date="2026-06-10"):
    item = {field: "" for field in EXPECTED_FIELDS}
    item.update({
        "code": code, "name": name, "date": event_date, "quarter": "1Q", "rank": "B",
        "surprise": "+1", "company_forecast": "維持", "rc1": "segment_growth",
        "narrative": "整合", "judge": "監視", "buy_condition": "legacy entry text",
        "exit_condition": "legacy exit text", "memo": "legacy memo",
    })
    return item


def source_rows(wrong_name=False):
    """The rows both stand-in repositories are built from.

    Enough of them, over enough days, that the reserve actually divides: two
    rows meant the split never fired and every migration test ran the path
    where record_count equals the source row count.
    """
    first = row(name="違う会社" if wrong_name else "架空会社")
    first.update({
        "prev_close": "100", "next_open": "102", "next_close": "103", "d5_close": "105",
        "d20_close": "110", "gap": "0.02", "ret_d1": "0.03", "ret_d5": "0.05",
        "ret_d20": "0.1", "shodo": "GU", "reaction": "GU継続",
    })
    rows = [first, row("2222", "別の架空会社")]
    for index in range(MIN_FOR_RESERVE + 6):
        extra = row("3%03d" % index, "連番%02d" % index, "2026-06-%02d" % (11 + index % 18))
        extra.update({
            "prev_close": "100", "next_open": "%d" % (100 + index % 5),
            "next_close": "%d" % (101 + index % 7), "d5_close": "%d" % (102 + index % 9),
            "d20_close": "%d" % (103 + index % 11),
            "gap": "%.4f" % ((index % 5) / 100),
            "ret_d1": "%.4f" % ((index % 7 - 3) / 100),
            "ret_d5": "%.4f" % ((index % 9 - 4) / 100),
            "ret_d20": "%.4f" % ((index % 11 - 5) / 100),
            "shodo": ("GU", "フラット", "GD")[index % 3],
            "reaction": ("GU継続", "GU失速", "GD反発", "GD継続")[index % 4],
        })
        rows.append(extra)
    return rows


def fixture_sessions(tmp_path):
    """A sessions file covering exactly the fixture's events.

    Required, not optional: the rebuild refuses a price file that does not
    account for every event in the record, because a truncated one would
    publish smaller denominators as though the observations had not occurred.
    """
    import hashlib

    rows = source_rows()
    sessions = []
    for index, row in enumerate(rows):
        opening = 100 + (index * 3) % 11
        sessions.append({
            "schema_version": "legacy_event_sessions_v1",
            "code": row["code"], "event_date": row["date"], "status": "ok",
            "ticker": row["code"] + ".T", "source": "fixture", "auto_adjust": False,
            "fetched_at": "2026-08-29T00:00:00+09:00", "first_offset": 0,
            "sessions": [
                {"offset": offset, "date": row["date"],
                 "open": round(opening * (1 + offset / 100), 4),
                 "close": round(opening * (1 + offset / 100 + 0.002), 4)}
                for offset in (0, 1, 2, 5, 7, 20, 22)
            ],
            "derived": {},
        })
    directory = tmp_path / "prices"
    directory.mkdir(parents=True, exist_ok=True)
    prices = directory / "sessions.jsonl"
    prices.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in sessions),
        encoding="utf-8",
    )
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "legacy_event_sessions_manifest_v1",
        "source": "fixture", "event_count": len(sessions), "priced_count": len(sessions),
        "sha256": hashlib.sha256(prices.read_bytes()).hexdigest(),
        "accepted_discrepancies": [],
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return prices, manifest


def fixture_as_of():
    """The last day these fixture rows cover.

    Written as a derivation because the migration now refuses an as-of that
    disagrees with the record — the two paths that produce reports have to
    reach the same date or a freshly migrated report fails the verification of
    the same reports. The fixtures used 2026-06-10, which is the *first* of
    their eighteen days.
    """
    from datetime import date as _date

    return _date.fromisoformat(max(item["date"] for item in source_rows()))


def make_source(tmp_path):
    repo = tmp_path / "old"
    init_repo(repo)
    write_csv(repo / "data/records.csv", EXPECTED_FIELDS, [row()])
    commit_all(repo, "initial")
    rows = source_rows()
    write_csv(repo / "data/records.csv", EXPECTED_FIELDS, rows)
    as_of = fixture_as_of()
    # The stand-in for the retired repository publishes what the retired
    # repository published. Writing these with the current renderer would make
    # the parity check compare ERS against itself, which no renderer change can
    # ever fail.
    (repo / "dashboard.md").write_text(
        render_dashboard_as_retired(rows, "2026-06-10 20:00"), encoding="utf-8"
    )
    (repo / "weekly_report.md").write_text(render_weekly_as_retired(rows, as_of), encoding="utf-8")
    (repo / "note_draft.md").write_text(render_note_as_retired(rows, as_of), encoding="utf-8")
    return repo, commit_all(repo, "enrich")


def make_tso(tmp_path, future=False, wrong_name=False, bad_cutoff=False, spoofed_usable=False):
    repo = tmp_path / "tso"
    init_repo(repo)
    context_fields = [
        "snapshot_id", "provenance", "context_date", "generated_at_utc", "generated_at_jst",
        "usable_from_utc", "source_run_id", "risk_on_score", "risk_off_score", "status",
        "source_artifact_id",
    ]
    # The context row always carries the snapshot's real usable-from timestamp.
    real_usable = "2026-06-10 01:00:00 UTC" if (future or spoofed_usable) else "2026-06-09 22:00:05 UTC"
    contexts = [{
        "snapshot_id": "MCTX-1", "provenance": "historical_artifact_join", "context_date": "2026-06-09",
        "generated_at_utc": "2026-06-09 22:00:00 UTC", "generated_at_jst": "2026-06-10 07:00:00 JST",
        "usable_from_utc": real_usable,
        "source_run_id": "10", "risk_on_score": "55", "risk_off_score": "45", "status": "ok",
        "source_artifact_id": "20",
    }]
    # spoofed_usable: the link claims an early usable-from time even though the
    # referenced context snapshot's real usable-from time is later (future leak).
    link_usable = "2026-06-09 22:00:05 UTC" if spoofed_usable else real_usable
    # bad_cutoff: the cutoff falls after the market opened on the event date, so
    # the context it selects can already contain the reaction. 06:00 UTC is
    # 15:00 JST, the close. The sound value is 00:00 UTC — 09:00 JST, the
    # opening bell — which is what all 254 committed records carry.
    cutoff = "2026-06-10 06:00:00 UTC" if bad_cutoff else "2026-06-10 00:00:00 UTC"
    link_fields = [
        "ers_code", "ers_name", "ers_date", "ers_quarter", "decision_cutoff_utc", "join_status",
        "snapshot_id", "provenance", "snapshot_usable_from_utc", "snapshot_generated_at_utc",
        "lag_hours", "snapshot_status", "snapshot_max_asset_staleness_days", "source_artifact_id",
        "source_run_id",
    ]
    links = []
    for item in source_rows(wrong_name=wrong_name):
        event = date.fromisoformat(item["date"])
        # Every record needs its own link, and the cutoff has to fall on a
        # calendar day before that record's event. The variants under test
        # apply to the first row only, which is the one they are asserted on.
        own_cutoff = cutoff if item["code"] == "1111" else (
            "%s 23:00:00 UTC" % (event - timedelta(days=1))
        )
        links.append({
            "ers_code": item["code"], "ers_name": item["name"], "ers_date": item["date"],
            "ers_quarter": item["quarter"],
            "decision_cutoff_utc": own_cutoff, "join_status": "ok",
            "snapshot_id": "MCTX-1", "provenance": "historical_artifact_join",
            "snapshot_usable_from_utc": link_usable,
            "snapshot_generated_at_utc": contexts[0]["generated_at_utc"], "lag_hours": "2",
            "snapshot_status": "ok", "snapshot_max_asset_staleness_days": "0",
            "source_artifact_id": "20", "source_run_id": "10",
        })
    write_csv(repo / "data/ers_legacy_context_link.csv", link_fields, links)
    write_csv(repo / "data/market_context_historical.csv", context_fields, contexts)
    return repo, commit_all(repo, "contexts")


def test_lossless_import_keeps_raw_history_and_context(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    result = migrate_legacy_os(
        source, source_commit, "source-run-1", tso, tso_commit, output, reports,
        "2026-08-26T08:00:00+09:00", fixture_as_of(), *fixture_sessions(tmp_path),
    )
    expected = len(source_rows())
    assert result["record_count"] == expected
    assert result["tso_context_link_count"] == expected
    assert result["publishing_parity"] is True
    assert (output / "source/records.csv").read_bytes() == (source / "data/records.csv").read_bytes()
    records = [json.loads(line) for line in (output / "legacy_records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(item["dataset_origin"] == "earnings-research-os" for item in records)
    assert all(item["record_mode"] == "legacy_observational" for item in records)
    assert records[0]["raw_record"]["buy_condition"] == "legacy entry text"
    assert records[0]["normalized_prices"]["legacy_d20_return"] == "0.1"
    contexts = [json.loads(line) for line in (output / "legacy_context_view.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(contexts) == expected
    assert contexts[0]["market_context"]["risk_on_score"] == "55"
    assert all(path.exists() for path in (reports / "dashboard.md", reports / "weekly_report.md", reports / "note_draft.md"))
    summary = json.loads((reports / "aggregation_summary.json").read_text(encoding="utf-8"))
    # The distinction the two-row fixture could not express: the migration
    # carries every record, and the summary counts only the explored ones.
    split = split_by_date([_open_anchored(item["raw_record"]) for item in records])
    assert split.reserved, "the fixture must actually reserve something"
    assert summary["record_count"] == len(split.exploration)
    assert summary["record_count_including_reserved"] == expected
    assert summary["market_context"]["linked_count"] == len(split.exploration)
    assert summary["prospective_records_included"] == 0
    assert verify_legacy_migration(output, reports)["record_count"] == expected


def test_same_source_is_idempotent_but_changed_output_is_not_overwritten(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    kwargs = dict(source_repo=source, source_commit=source_commit, source_run_id="source-run-1", tso_repo=tso, tso_commit=tso_commit,
                  output_root=output, reports_output=tmp_path / "reports",
                  migration_recorded_at="2026-08-26T08:00:00+09:00", as_of_date=fixture_as_of(),
                      entry_prices=fixture_sessions(tmp_path)[0], entry_manifest=fixture_sessions(tmp_path)[1])
    migrate_legacy_os(**kwargs)
    migrate_legacy_os(**kwargs)
    (output / "legacy_records.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        migrate_legacy_os(**kwargs)


def test_context_future_leak_and_identity_mismatch_are_rejected(tmp_path):
    source, source_commit = make_source(tmp_path)
    future_tso, future_commit = make_tso(tmp_path, future=True)
    with pytest.raises(ValueError, match="usable after"):
        build_import(source, source_commit, "source-run-1", future_tso, future_commit, "2026-08-26T08:00:00+09:00")
    other = tmp_path / "other"
    other.mkdir()
    bad_tso, bad_commit = make_tso(other, wrong_name=True)
    with pytest.raises(ValueError, match="identity"):
        build_import(source, source_commit, "source-run-1", bad_tso, bad_commit, "2026-08-26T08:00:00+09:00")


def test_context_cutoff_and_usable_from_are_cross_checked(tmp_path):
    source, source_commit = make_source(tmp_path)
    # The cutoff must precede the moment the market could react to the event,
    # not merely fall on an earlier calendar day in UTC. The earlier form of
    # this check compared `cutoff.date() >= event_date` and so rejected every
    # one of the 254 committed records: each carries 00:00:00 UTC on its event
    # date, which is 09:00 JST — the opening bell, six hours before the
    # earliest possible disclosure. The whole migration was blocked by a test
    # that had the rule backwards.
    other = tmp_path / "other_bad_cutoff"
    other.mkdir()
    bad_cutoff_tso, bad_cutoff_commit = make_tso(other, bad_cutoff=True)
    with pytest.raises(ValueError, match="after the market opened"):
        build_import(source, source_commit, "source-run-1", bad_cutoff_tso, bad_cutoff_commit, "2026-08-26T08:00:00+09:00")
    # snapshot_usable_from_utc on the link must match the referenced context row's own
    # usable_from_utc; a link that copies an early time while the real snapshot became
    # usable later must not be trusted.
    spoofed = tmp_path / "spoofed_usable"
    spoofed.mkdir()
    spoofed_tso, spoofed_commit = make_tso(spoofed, spoofed_usable=True)
    with pytest.raises(ValueError, match="does not match its context snapshot"):
        build_import(source, source_commit, "source-run-1", spoofed_tso, spoofed_commit, "2026-08-26T08:00:00+09:00")


def test_schema_rejects_prospective_promotion(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    files, manifest, records, _ = build_import(source, source_commit, "source-run-1", tso, tso_commit, "2026-08-26T08:00:00+09:00")
    record_schema = json.loads((ROOT / "schemas/analysis/legacy_earnings_record.schema.json").read_text(encoding="utf-8"))
    manifest_schema = json.loads((ROOT / "schemas/analysis/legacy_migration_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(records[0], record_schema)
    jsonschema.validate(manifest, manifest_schema)
    records[0]["record_mode"] = "prospective"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(records[0], record_schema)
    assert files["source/records.csv"] == (source / "data/records.csv").read_bytes()


def test_cli_completes_one_integrated_migration(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    assert main([
        "migrate-legacy-os", "--source-repo", str(source), "--source-commit", source_commit,
        "--source-run-id", "source-run-1",
        "--tso-repo", str(tso), "--tso-commit", tso_commit, "--output-root", str(output),
        "--reports-output", str(reports), "--migration-recorded-at", "2026-08-26T08:00:00+09:00",
        "--as-of-date", fixture_as_of().isoformat(),
        "--entry-prices", str(fixture_sessions(tmp_path)[0]),
        "--entry-manifest", str(fixture_sessions(tmp_path)[1]),
    ]) == 0
    assert json.loads((output / "migration_manifest.json").read_text(encoding="utf-8"))["prospective_records_created"] == 0
    assert main([
        "verify-legacy-migration", "--output-root", str(output), "--reports-output", str(reports)
    ]) == 0


def test_verifier_rejects_tampered_committed_data(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    migrate_legacy_os(source, source_commit, "source-run-1", tso, tso_commit, output, reports,
                      "2026-08-26T08:00:00+09:00", fixture_as_of(), *fixture_sessions(tmp_path))
    with (output / "legacy_records.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_legacy_migration(output, reports)


def test_verifier_rejects_tampered_report_outputs(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    migrate_legacy_os(source, source_commit, "source-run-1", tso, tso_commit, output, reports,
                      "2026-08-26T08:00:00+09:00", fixture_as_of(), *fixture_sessions(tmp_path))
    verify_legacy_migration(output, reports)
    (reports / "dashboard.md").write_text("tampered dashboard\n", encoding="utf-8")
    with pytest.raises(ValueError, match="legacy report output hash mismatch: dashboard.md"):
        verify_legacy_migration(output, reports)


def test_verifier_rejects_tampered_publishing_parity(tmp_path):
    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output = tmp_path / "migration"
    reports = tmp_path / "reports"
    migrate_legacy_os(source, source_commit, "source-run-1", tso, tso_commit, output, reports,
                      "2026-08-26T08:00:00+09:00", fixture_as_of(), *fixture_sessions(tmp_path))
    parity_path = reports / "publishing_parity.json"
    tampered = json.loads(parity_path.read_text(encoding="utf-8"))
    for item in tampered["outputs"].values():
        item["byte_equal"] = True
    parity_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="legacy report output hash mismatch: publishing_parity.json"):
        verify_legacy_migration(output, reports)


# --- 退役システムとの一致 -----------------------------------------------------

SOURCE = ROOT / "data/historical_research/earnings_research_os/v1/source"


def test_the_frozen_renderer_still_reproduces_the_retired_dashboard():
    """Real committed bytes from the retired repository, not a stand-in.

    The migration's whole claim is that nothing was lost in the reading of the
    old data. Every other parity check in this file compares ERS output against
    ERS output, so a renderer change passes them all while silently breaking
    that claim; changing what the dashboard says did exactly that, and this is
    the check that catches it.
    """
    import re

    published = SOURCE.joinpath("dashboard.md").read_bytes()
    _fields, rows = parse_csv_bytes(SOURCE.joinpath("records.csv").read_bytes())
    stamp = re.search(r"最終更新: ([0-9-]+ [0-9:]+)", published.decode("utf-8")).group(1)
    assert render_dashboard_as_retired(rows, stamp).encode("utf-8") == published


def test_the_current_reports_are_allowed_to_differ_from_the_retired_ones():
    """The two renderers answer different questions and must not be merged."""
    import re

    from earnings_research.legacy_research.publishing import render_dashboard

    published = SOURCE.joinpath("dashboard.md").read_bytes()
    _fields, rows = parse_csv_bytes(SOURCE.joinpath("records.csv").read_bytes())
    stamp = re.search(r"最終更新: ([0-9-]+ [0-9:]+)", published.decode("utf-8")).group(1)
    assert render_dashboard(rows, stamp).encode("utf-8") != published


def test_the_committed_research_outputs_are_what_their_generator_produces():
    """Stamping a provenance notice onto files knowledge.py reproduces verbatim
    turned this command red, and nothing noticed: CI did not run it and the
    other test calls it against a fixture. The notice comes from the generator
    now, so the file cannot drift from what it says about itself."""
    from earnings_research.legacy_research.knowledge import build_research_outputs

    committed = ROOT / "outputs/historical_research"
    generated = build_research_outputs(ROOT / "data/historical_research/earnings_research_os/v1")
    for name, body in generated.items():
        expected = body if isinstance(body, str) else body.decode("utf-8")
        assert committed.joinpath(name).read_text(encoding="utf-8") == expected, name
    assert "統計ガードを通っていない経路" in generated["research_report.md"]


def test_the_committed_cutoffs_are_accepted_by_the_guard():
    """Stated against the real record, because a synthetic fixture is what got
    this wrong: the guard was written, tested against a made-up value, and
    rejected all 254 committed rows without anyone running it on them."""
    import json as _json
    from datetime import date as _date
    from earnings_research.legacy_research.importer import _market_open_utc, _utc_datetime

    path = ROOT / "data/historical_research/earnings_research_os/v1/legacy_context_view.jsonl"
    rows = [_json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 254
    for row in rows:
        cutoff = _utc_datetime(row["decision_cutoff_utc"])
        opening = _market_open_utc(_date.fromisoformat(row["legacy_event_date"]))
        assert cutoff <= opening, row["legacy_record_id"]
        # And the snapshot behind it was usable before that cutoff.
        assert _utc_datetime(row["market_context"]["usable_from_utc"]) <= cutoff


def test_the_guard_still_refuses_a_cutoff_past_the_open():
    from datetime import date as _date
    from earnings_research.legacy_research.importer import _market_open_utc, _utc_datetime

    opening = _market_open_utc(_date(2026, 6, 10))
    assert _utc_datetime("2026-06-10 00:00:00 UTC") <= opening      # 09:00 JST, the bell
    assert _utc_datetime("2026-06-09 23:00:00 UTC") <= opening      # the evening before
    assert not _utc_datetime("2026-06-10 00:00:01 UTC") <= opening  # one second late
    assert not _utc_datetime("2026-06-10 06:00:00 UTC") <= opening  # 15:00 JST, the close


def test_the_published_reports_are_rebuildable_without_the_retired_repository():
    """The gap this closes.

    The reports a reader opens were produced only by `migrate-legacy-os`, which
    needs the retired repository and a TSO checkout at pinned commits. CI has
    neither, so nothing checked them: they sat committed for weeks describing a
    pipeline that had been replaced, with figures measured from the previous
    close while the code measured from the open.
    """
    from earnings_research.legacy_research.publishing import rebuild_reports, verify_reports

    root = ROOT / "data/historical_research/earnings_research_os/v1"
    reports = rebuild_reports(root)
    assert set(reports) == {
        "dashboard.md", "weekly_report.md", "note_draft.md", "aggregation_summary.json"
    }
    assert verify_reports(root, ROOT / "outputs/historical_research")["status"] == "verified"


def test_a_committed_report_that_drifted_is_refused(tmp_path):
    from earnings_research.legacy_research.publishing import rebuild_reports, verify_reports

    root = ROOT / "data/historical_research/earnings_research_os/v1"
    out = tmp_path / "outputs"
    out.mkdir()
    for name, content in rebuild_reports(root).items():
        (out / name).write_bytes(content)
    assert verify_reports(root, out)["status"] == "verified"
    (out / "dashboard.md").write_bytes(b"# something else\n")
    with pytest.raises(ValueError, match="not what the current code produces"):
        verify_reports(root, out)


def test_the_rebuild_refuses_an_input_that_does_not_match_its_manifest(tmp_path):
    """Rebuilt from the record means the record, not whatever is on disk."""
    import shutil
    from earnings_research.legacy_research.publishing import rebuild_reports

    root = tmp_path / "v1"
    shutil.copytree(ROOT / "data/historical_research/earnings_research_os/v1", root)
    assert rebuild_reports(root)
    target = root / "source/records.csv"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="input hash mismatch"):
        rebuild_reports(root)


def test_the_as_of_date_comes_from_the_record_and_not_from_the_clock():
    """A caller-supplied as-of would put a different date in the file every day
    it was rebuilt, and the drift check above would report a mismatch that
    means nothing."""
    from earnings_research.legacy_research.publishing import rebuild_reports

    reports = rebuild_reports(ROOT / "data/historical_research/earnings_research_os/v1")
    assert b"2026-08-25" in reports["weekly_report.md"]


def test_no_committed_snapshot_reaches_into_its_own_session():
    """The invariant the cutoff rule actually establishes, measured.

    Not "earnings are disclosed after 15:00" — the record has no announcement
    time and cannot support that. What holds is the chain: every snapshot was
    usable at or before its cutoff, and every cutoff is at or before the Tokyo
    open, so nothing here contains a tick of the session its event falls in.
    """
    import json as _json
    from datetime import date as _date
    from earnings_research.legacy_research.importer import _market_open_utc, _utc_datetime

    path = ROOT / "data/historical_research/earnings_research_os/v1/legacy_context_view.jsonl"
    rows = [_json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 254
    for row in rows:
        usable = _utc_datetime(row["market_context"]["usable_from_utc"])
        cutoff = _utc_datetime(row["decision_cutoff_utc"])
        opening = _market_open_utc(_date.fromisoformat(row["legacy_event_date"]))
        assert usable <= cutoff <= opening, row["legacy_record_id"]


def test_the_relaxation_is_recorded_with_what_it_costs():
    """The doc has to say the rule moved and what it gave up.

    The previous rule — no event-day snapshot at all — is one 234 of the 254
    committed links have never met. Relaxing it to the open is defensible and
    is not free: a disclosure before 08:17 JST would not be excluded. A reader
    who finds only the code should still find that stated.
    """
    doc = (ROOT / "docs/LEGACY_OS_INTEGRATION.md").read_text(encoding="utf-8")
    assert "09:00 JST" in doc
    assert "234件が発表日当日" in doc
    assert "ERS-ADR-0056" in doc
    assert "これは測定ではなく推測である" in doc


def test_how_many_committed_links_the_previous_rule_would_have_admitted():
    """Twenty. Stated as a measurement rather than a claim, because the number
    is the whole argument for changing the rule instead of enforcing it."""
    import json as _json
    from datetime import date as _date, timedelta as _td, timezone as _tz
    from earnings_research.legacy_research.importer import _utc_datetime

    jst = _tz(_td(hours=9))
    path = ROOT / "data/historical_research/earnings_research_os/v1/legacy_context_view.jsonl"
    rows = [_json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    prior_day = sum(
        _utc_datetime(row["market_context"]["usable_from_utc"]).astimezone(jst).date()
        < _date.fromisoformat(row["legacy_event_date"])
        for row in rows
    )
    assert prior_day == 20
    assert len(rows) - prior_day == 234


def test_a_migration_as_of_that_disagrees_with_the_record_is_refused(tmp_path, capsys):
    """The refusal has to actually fire somewhere.

    Every other fixture now passes the derived date, so removing this check
    broke nothing in the suite — the guard was added and never driven. The two
    report paths have to reach the same as-of or a report freshly made by the
    documented command fails the verification of the same reports.
    """
    from datetime import timedelta as _td

    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    args = [
        "migrate-legacy-os", "--source-repo", str(source), "--source-commit", source_commit,
        "--source-run-id", "source-run-1",
        "--tso-repo", str(tso), "--tso-commit", tso_commit,
        "--output-root", str(tmp_path / "out"), "--reports-output", str(tmp_path / "rep"),
        "--migration-recorded-at", "2026-08-26T08:00:00+09:00",
        "--as-of-date", (fixture_as_of() + _td(days=3)).isoformat(),
        "--entry-prices", str(fixture_sessions(tmp_path)[0]),
        "--entry-manifest", str(fixture_sessions(tmp_path)[1]),
    ]
    assert main(args) == 1
    assert "does not match the last day the record covers" in capsys.readouterr().err


def test_a_migration_and_a_rebuild_produce_the_same_reports(tmp_path):
    """The property the as-of check exists to protect, exercised end to end."""
    from earnings_research.legacy_research.publishing import verify_reports

    source, source_commit = make_source(tmp_path)
    tso, tso_commit = make_tso(tmp_path)
    output, reports = tmp_path / "out", tmp_path / "rep"
    assert main([
        "migrate-legacy-os", "--source-repo", str(source), "--source-commit", source_commit,
        "--source-run-id", "source-run-1",
        "--tso-repo", str(tso), "--tso-commit", tso_commit, "--output-root", str(output),
        "--reports-output", str(reports), "--migration-recorded-at", "2026-08-26T08:00:00+09:00",
        "--as-of-date", fixture_as_of().isoformat(),
        "--entry-prices", str(fixture_sessions(tmp_path)[0]),
        "--entry-manifest", str(fixture_sessions(tmp_path)[1]),
    ]) == 0
    assert verify_reports(output, reports, *fixture_sessions(tmp_path))["status"] == "verified"
