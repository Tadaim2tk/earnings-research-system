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
    EvidenceBody,
    EvidenceBundle,
    ExcludedEvent,
    PopulationManifest,
    body_matches,
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
        payload["content_sha256"] = sha256_text(text)
    payload.update(changes)
    return EvidenceBundle(**payload)


def body(event_id, text="決算短信の本文"):
    """What goes to the private store, never to this repository."""
    return EvidenceBody(
        bundle_id="EB-%s-1" % event_id, content=text, content_sha256=sha256_text(text)
    )


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

def test_the_public_record_has_nowhere_to_put_a_body():
    """A rule saying "do not commit the body" is a rule somebody has to keep.
    A record with no field for one keeps it by construction.

    This repository is public, and the terms that permit fetching a disclosure
    for one's own analysis do not permit redistributing it — so a body
    committed here would be redistributed the moment it landed, contract or
    not.
    """
    assert "content" not in EvidenceBundle.model_fields
    assert "content_sha256" in EvidenceBundle.model_fields
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(
            {**bundle("EV-2026-09-01-001").model_dump(mode="json"), "content": "本文"}
        )


def test_a_captured_bundle_carries_the_hash_that_ties_it_to_its_body():
    item, text = bundle("EV-2026-09-01-001"), "決算短信の本文"
    assert item.content_sha256 == sha256_text(text)
    assert body_matches(item, body("EV-2026-09-01-001"))
    # A body from elsewhere, or one that was edited, does not match.
    assert not body_matches(item, body("EV-2026-09-01-001", "書き換えられた本文"))
    assert not body_matches(item, body("EV-2026-09-01-002"))


def test_a_body_that_does_not_hash_to_its_own_digest_is_refused():
    with pytest.raises(ValidationError, match="does not hash the content"):
        EvidenceBody(
            bundle_id="EB-1", content="本文", content_sha256=sha256_text("違う本文")
        )


@pytest.mark.parametrize("status", [s for s in CAPTURE_STATUSES if s != "captured"])
def test_a_bundle_that_was_not_captured_claims_no_body(status):
    """A hash would claim a body exists in the private store, and downstream
    that reads as a source that was read — a different fact from a source
    nobody could read. The status is how the absence stays visible."""
    item = bundle("EV-2026-09-01-001", status=status)
    assert item.content_sha256 is None
    payload = item.model_dump(mode="json")
    payload["content_sha256"] = sha256_text("何か")
    with pytest.raises(ValidationError, match="no body to hash"):
        EvidenceBundle.model_validate(payload)


def test_a_captured_bundle_must_say_what_it_captured():
    payload = bundle("EV-2026-09-01-001").model_dump(mode="json")
    payload["content_sha256"] = None
    with pytest.raises(ValidationError, match="hash of what it captured"):
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
    append_bundles(path, [bundle("EV-2026-09-01-001", text="初回の本文")])
    later = bundle("EV-2026-09-01-001", text="差し替え後の本文",
                   retrieved_at=DAY + timedelta(days=1))
    append_bundles(path, [later.model_copy(update={"bundle_id": "EB-EV-2026-09-01-001-2"})])
    stored = read_bundles(path)
    assert len(stored) == 2
    # The hashes differ, which is how the change is visible without either text
    # ever being committed.
    assert stored[0].content_sha256 != stored[1].content_sha256
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


def test_a_captured_row_with_its_hash_stripped_on_disk_is_refused(tmp_path):
    """The model validator checks this when a bundle is built. This is the case
    that matters: the file is what a future reader has, and it is edited by
    whatever touches the file. Without the hash the row can never be matched to
    a body in the private store.
    """
    pop = manifest(included=1)
    manifest_path, bundles_path = written(tmp_path, pop, [bundle(pop.included[0].event_id)])
    rows = [json.loads(line) for line in bundles_path.read_text(encoding="utf-8").splitlines()]
    rows[0].pop("content_sha256")
    bundles_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="hash of what it captured"):
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
    fields |= set(EvidenceBody.model_fields)
    for forbidden in ("rank", "surprise", "judge", "narrative", "reason_codes",
                      "score", "grade", "model", "prompt", "extracted"):
        assert not any(forbidden in name for name in fields), (forbidden, sorted(fields))
    # And the one field that could smuggle a verdict in is text with a hash
    # over it, not a category anything downstream would group on.
    assert "content_sha256" in EvidenceBundle.model_fields


def test_evidence_read_before_the_population_was_fixed_is_refused(tmp_path):
    """The property this capability exists for, and the one it did not enforce.

    Fixing the population first only prevents selection if nothing was read
    first. Evidence retrieved before `fixed_at` could have been seen while
    deciding which events to include — the retired pipeline's "eight notable
    companies" arriving by another route.

    The manifest checked that it was not fixed before its own roster was read,
    and each bundle checked its own consistency. The one comparison between
    them, which carries the guarantee, was missing until a review found it.
    """
    pop = manifest(included=1)
    event_id = pop.included[0].event_id
    early = bundle(event_id, retrieved_at=pop.fixed_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="read before the population was fixed"):
        verify(*written(tmp_path, pop, [early]))


def test_evidence_read_at_the_moment_the_population_was_fixed_is_allowed(tmp_path):
    """The boundary is inclusive: a capture that starts the instant the
    population closes has not seen anything the population was chosen from."""
    pop = manifest(included=1)
    at_the_moment = bundle(pop.included[0].event_id, retrieved_at=pop.fixed_at)
    assert verify(*written(tmp_path, pop, [at_the_moment]))["status"] == "verified"


def test_a_bundle_naming_another_population_is_refused(tmp_path):
    """Membership by event id is not lineage. A stale or mistyped manifest_id
    passes an event-id check whenever two populations share an event, and the
    capture is then certified under the wrong population."""
    pop = manifest(included=2)
    stray = bundle(pop.included[1].event_id).model_copy(
        update={"manifest_id": "POP-2026-08-31"}
    )
    with pytest.raises(ValueError, match="belong to another population"):
        verify(*written(tmp_path, pop, [bundle(pop.included[0].event_id), stray]))
