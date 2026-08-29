"""Keeping what the evidence was, so a better model can read it again.

The retired pipeline made one call that chose eight companies, searched, read,
judged and assigned a letter, and kept only the letter. Nothing here judges
anything; it keeps the first layer, which is the one that cannot be rebuilt
from the others.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from earnings_research.evidence import (
    CAPTURE_STATUSES,
    EventRef,
    EvidenceBundle,
    ExcludedEvent,
    PopulationManifest,
)
from earnings_research.evidence.models import sha256_text
from earnings_research.evidence.store import (
    append_bundles,
    read_bundles,
    read_manifest,
    verify,
    write_manifest,
)

JST = timezone(timedelta(hours=9))
DAY = datetime(2026, 9, 1, 16, tzinfo=JST)


def event(index=1):
    return EventRef(
        event_id="EV-2026-09-01-%03d" % index,
        ticker="%04d" % (1000 + index),
        company_name="架空%02d" % index,
        disclosure_kind="決算短信",
        listed_at=DAY,
    )


def manifest(included=2, excluded=1):
    return PopulationManifest(
        manifest_id="POP-2026-09-01",
        population_date="2026-09-01",
        source="fixture-roster",
        source_retrieved_at=DAY,
        inclusion_rule="当日決算短信を開示した全銘柄。ETF・REITは除外。",
        included=[event(i) for i in range(1, included + 1)],
        excluded=[
            ExcludedEvent(event=event(100 + i), rule="etf_reit", reason="REITのため対象外")
            for i in range(excluded)
        ],
        fixed_at=DAY + timedelta(minutes=5),
    )


def bundle(event_id, status="captured", text="決算短信の本文", **changes):
    payload = {
        "bundle_id": "EB-%s-1" % event_id,
        "manifest_id": "POP-2026-09-01",
        "event_id": event_id,
        "source_url": "https://example.invalid/%s.pdf" % event_id,
        "source_type": "決算短信",
        "retrieved_at": DAY + timedelta(minutes=10),
        "capture_status": status,
        "discovery_method": "roster_link",
        "fetch_implementation": "fixture/1",
    }
    if status == "captured":
        payload["content"] = text
        payload["content_sha256"] = sha256_text(text)
    payload.update(changes)
    return EvidenceBundle(**payload)


def written(tmp_path, pop=None, bundles=()):
    pop = pop or manifest()
    manifest_path = tmp_path / "population.json"
    bundles_path = tmp_path / "bundles.jsonl"
    write_manifest(manifest_path, pop)
    append_bundles(bundles_path, list(bundles))
    return manifest_path, bundles_path


# --- the population is fixed before anything is read ------------------------

def test_the_population_is_written_once_and_never_again(tmp_path):
    """A population that can be rewritten is not fixed: the events studied
    could be chosen after the results were seen."""
    path = tmp_path / "population.json"
    write_manifest(path, manifest())
    with pytest.raises(FileExistsError, match="already fixed"):
        write_manifest(path, manifest())


def test_an_excluded_event_stays_in_the_manifest_with_the_rule_that_dropped_it():
    """The retired pipeline asked a model for eight notable companies, so its
    cohorts were drawn from a group already filtered by the thing under study —
    which is why one D exists in 254 records. A company can be left out here,
    but not left out quietly.
    """
    pop = manifest(included=2, excluded=3)
    assert len(pop.included) == 2
    assert len(pop.excluded) == 3
    for item in pop.excluded:
        assert item.rule and item.reason
        assert item.event.event_id not in pop.event_ids()


def test_a_population_cannot_list_the_same_event_twice():
    pop = manifest()
    payload = pop.model_dump(mode="json")
    payload["excluded"].append({
        "event": payload["included"][0], "rule": "x", "reason": "y",
    })
    with pytest.raises(ValidationError, match="appears twice"):
        PopulationManifest.model_validate(payload)


def test_a_population_cannot_be_fixed_before_its_source_was_read():
    payload = manifest().model_dump(mode="json")
    payload["fixed_at"] = (DAY - timedelta(hours=1)).isoformat()
    with pytest.raises(ValidationError, match="cannot be fixed before"):
        PopulationManifest.model_validate(payload)


# --- a bundle says what happened to it --------------------------------------

def test_a_captured_bundle_hashes_the_text_it_carries():
    item = bundle("EV-2026-09-01-001")
    assert item.content_sha256 == sha256_text(item.content)
    payload = item.model_dump(mode="json")
    payload["content"] = payload["content"] + "…改変"
    with pytest.raises(ValidationError, match="does not hash the content"):
        EvidenceBundle.model_validate(payload)


@pytest.mark.parametrize("status", [s for s in CAPTURE_STATUSES if s != "captured"])
def test_a_bundle_that_was_not_captured_carries_nothing_in_place_of_it(status):
    """An empty string or a placeholder would read downstream as a source that
    said nothing, which is a different fact from a source nobody could read.
    The status is how the absence stays visible."""
    item = bundle("EV-2026-09-01-001", status=status)
    assert item.content is None and item.content_sha256 is None
    payload = item.model_dump(mode="json")
    payload["content"] = ""
    with pytest.raises(ValidationError, match="carries no content"):
        EvidenceBundle.model_validate(payload)


def test_a_captured_bundle_must_actually_carry_something():
    payload = bundle("EV-2026-09-01-001").model_dump(mode="json")
    payload["content"] = None
    payload["content_sha256"] = None
    with pytest.raises(ValidationError, match="has to carry what it captured"):
        EvidenceBundle.model_validate(payload)


def test_the_discovery_that_produced_a_url_is_part_of_the_record():
    """A URL with no provenance cannot be re-derived, and the order matters: a
    model reading the first three results saw a different thing from one
    reading all ten."""
    item = bundle("EV-2026-09-01-001", discovery_query="4441 決算短信", result_order=0)
    assert item.discovery_method and item.fetch_implementation
    assert item.result_order == 0
    payload = item.model_dump(mode="json")
    payload["discovery_method"] = ""
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)


# --- the ledger is appended to ----------------------------------------------

def test_reading_a_source_twice_keeps_both_reads(tmp_path):
    """A re-read is a second observation, not a correction of the first. A page
    that changed between two reads is itself a fact about the evidence."""
    path = tmp_path / "bundles.jsonl"
    first = bundle("EV-2026-09-01-001", text="初回の本文")
    append_bundles(path, [first])
    later = bundle("EV-2026-09-01-001", text="差し替え後の本文",
                   retrieved_at=DAY + timedelta(days=1))
    later = later.model_copy(update={"bundle_id": "EB-EV-2026-09-01-001-2"})
    append_bundles(path, [later])
    stored = read_bundles(path)
    assert len(stored) == 2
    assert {b.content for b in stored} == {"初回の本文", "差し替え後の本文"}
    assert stored[0].bundle_id != stored[1].bundle_id


# --- verification -----------------------------------------------------------

def test_a_verified_capture_accounts_for_every_event_in_its_population(tmp_path):
    pop = manifest(included=2)
    bundles = [bundle(e.event_id) for e in pop.included]
    result = verify(*written(tmp_path, pop, bundles))
    assert result["status"] == "verified"
    assert result["included"] == 2 and result["excluded"] == 1
    assert result["by_capture_status"] == {"captured": 2}
    assert result["events_with_content"] == 2


def test_an_event_nobody_tried_is_refused(tmp_path):
    """Different from an event whose sources could not be fetched: that one has
    a bundle saying so. This one reads downstream exactly like an event with
    nothing to find."""
    pop = manifest(included=3)
    bundles = [bundle(e.event_id) for e in pop.included[:2]]
    with pytest.raises(ValueError, match="have no bundle at all"):
        verify(*written(tmp_path, pop, bundles))


def test_an_event_that_could_not_be_fetched_still_counts_as_attempted(tmp_path):
    pop = manifest(included=2)
    bundles = [
        bundle(pop.included[0].event_id),
        bundle(pop.included[1].event_id, status="fetch_failed"),
    ]
    result = verify(*written(tmp_path, pop, bundles))
    assert result["by_capture_status"] == {"captured": 1, "fetch_failed": 1}
    # The distinction the totals would hide.
    assert result["bundles"] == 2 and result["events_with_content"] == 1


def test_evidence_for_an_event_outside_the_population_is_refused(tmp_path):
    """Reaching past the fixed population would put evidence into the record
    for events chosen after the fact."""
    pop = manifest(included=2)
    bundles = [bundle(e.event_id) for e in pop.included] + [bundle("EV-NOT-IN-POPULATION")]
    with pytest.raises(ValueError, match="outside the fixed population"):
        verify(*written(tmp_path, pop, bundles))


def test_content_edited_on_disk_is_refused(tmp_path):
    """The model validator checks this when a bundle is built. This is the case
    that matters: the file is what a future model reads."""
    pop = manifest(included=1)
    manifest_path, bundles_path = written(tmp_path, pop, [bundle(pop.included[0].event_id)])
    rows = [json.loads(line) for line in bundles_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["content"] = "書き換えられた本文"
    bundles_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="does not hash the content"):
        verify(manifest_path, bundles_path)


def test_nothing_here_extracts_a_fact_or_assigns_a_rank():
    """The scope, asserted against the models rather than against the prose.

    An earlier form of this grepped the source for "rank" and "judge", and
    failed on the docstring that explains what this module does not do — a test
    that constrained the writing instead of the behaviour. What matters is that
    nothing here has a field to put a fact or a verdict in.

    Facts and judgements can be redone from this evidence any number of times.
    The evidence cannot be redone from them, which is why the capability stops
    where it does.
    """
    fields = set(EvidenceBundle.model_fields) | set(PopulationManifest.model_fields)
    fields |= set(EventRef.model_fields) | set(ExcludedEvent.model_fields)
    for forbidden in ("rank", "surprise", "judge", "narrative", "reason_codes",
                      "score", "grade", "model", "prompt", "extracted"):
        assert not any(forbidden in name for name in fields), (forbidden, sorted(fields))
    # And the one field that could smuggle a verdict in is text with a hash
    # over it, not a category anything downstream would group on.
    assert EvidenceBundle.model_fields["content"].annotation is not None
    assert "content_sha256" in EvidenceBundle.model_fields
