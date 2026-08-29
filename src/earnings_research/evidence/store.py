"""Reading and writing the capture, with the parts that must not be lost.

Two files per population: the manifest, written once, and a bundle ledger that
is only ever appended to. Neither is rewritten. A source read twice produces
two bundles, and which one a later reader uses is a question about their
timestamps rather than about which one overwrote the other.
"""

import json
from pathlib import Path
from typing import Dict, List, Sequence

from .models import EvidenceBundle, PopulationManifest, sha256_text

MANIFEST_NAME = "population.json"
BUNDLES_NAME = "bundles.jsonl"


def write_manifest(path: Path, manifest: PopulationManifest) -> Path:
    """Write the population once. A fixed population that can be rewritten is
    not fixed: the events studied could be chosen after the results were seen."""
    path = Path(path)
    if path.exists():
        raise FileExistsError("the population is already fixed: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def read_manifest(path: Path) -> PopulationManifest:
    return PopulationManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def append_bundles(path: Path, bundles: Sequence[EvidenceBundle]) -> int:
    """Add captures without touching what is there.

    Appended rather than replaced because a re-read is a second observation,
    not a correction of the first. A page that changed between two reads is
    itself a fact about the evidence, and overwriting would erase it.
    """
    if not bundles:
        return 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for bundle in bundles:
            handle.write(
                json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            )
    return len(bundles)


def read_bundles(path: Path) -> List[EvidenceBundle]:
    path = Path(path)
    if not path.exists():
        return []
    return [
        EvidenceBundle.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def unattempted(manifest: PopulationManifest, bundles: Sequence[EvidenceBundle]) -> List[str]:
    """Events in the population that no bundle accounts for.

    Different from an event whose sources could not be fetched: that one has a
    bundle saying so. This is an event nobody tried, and without the check it
    reads downstream exactly like an event with nothing to find.
    """
    seen = {bundle.event_id for bundle in bundles}
    return [event_id for event_id in manifest.event_ids() if event_id not in seen]


def foreign(manifest: PopulationManifest, bundles: Sequence[EvidenceBundle]) -> List[str]:
    """Bundles for events the fixed population does not contain.

    A capture run that reached past its own population would put evidence into
    the record for events chosen after the fact, which is the selection the
    manifest exists to prevent.
    """
    allowed = set(manifest.event_ids())
    return sorted(
        {bundle.event_id for bundle in bundles if bundle.event_id not in allowed}
    )


def tampered(bundles: Sequence[EvidenceBundle]) -> List[str]:
    """Bundles whose stored text no longer hashes to the hash beside it.

    The model validator checks this when a bundle is built. This checks it
    again over what is on disk, which is the case that matters: the file is the
    thing a future model reads, and it is edited by whatever touches the file.
    """
    return [
        bundle.bundle_id
        for bundle in bundles
        if bundle.capture_status == "captured"
        and bundle.content is not None
        and bundle.content_sha256 != sha256_text(bundle.content)
    ]


def verify(manifest_path: Path, bundles_path: Path) -> Dict[str, object]:
    """Refuse a capture that has lost a property it cannot get back.

    Not a summary with warnings. A missing event, a foreign one, or altered
    content each mean the record no longer supports the replay it exists for,
    and each is easier to fix now than after the sources have changed.
    """
    manifest = read_manifest(manifest_path)
    bundles = read_bundles(bundles_path)
    problems = []
    missing = unattempted(manifest, bundles)
    if missing:
        problems.append(
            "%d events in the population have no bundle at all: %s"
            % (len(missing), ", ".join(missing[:5]))
        )
    outside = foreign(manifest, bundles)
    if outside:
        problems.append(
            "%d bundles are for events outside the fixed population: %s"
            % (len(outside), ", ".join(outside[:5]))
        )
    altered = tampered(bundles)
    if altered:
        problems.append(
            "%d bundles no longer hash to their own content: %s"
            % (len(altered), ", ".join(altered[:5]))
        )
    if problems:
        raise ValueError("; ".join(problems))
    counts: Dict[str, int] = {}
    for bundle in bundles:
        counts[bundle.capture_status] = counts.get(bundle.capture_status, 0) + 1
    return {
        "status": "verified",
        "manifest_id": manifest.manifest_id,
        "population_date": manifest.population_date,
        "included": len(manifest.included),
        "excluded": len(manifest.excluded),
        "bundles": len(bundles),
        # Named per status rather than totalled. "40 bundles" over a population
        # of 40 reads as complete whether or not any of them holds text.
        "by_capture_status": dict(sorted(counts.items())),
        "events_with_content": len(
            {b.event_id for b in bundles if b.capture_status == "captured"}
        ),
    }
