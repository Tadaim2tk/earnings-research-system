"""Judge frozen hypotheses against the contamination rules as they stand now.

A hypothesis is frozen so that nobody can change what it claims after seeing
the result. What it rests on is a different matter: the eight reaction
hypotheses were derived from returns measured before the reaction was known,
and nothing in the system said so until a person went looking. The rules that
name such a pairing keep growing — twice in one change — and every time they
grow, knowledge frozen earlier can stop being supportable.

So the registry stays untouched and validity lives beside it, in a ledger that
is appended to and never rewritten. A verdict is always recorded against the
digest of the rules that produced it, because "invalid" on its own cannot be
told apart from "invalid under a rule that did not exist yet", and the second
is the interesting one: it is the system noticing that its own past work does
not meet the standard it now holds.

Nothing here decides anything. It reports what the current rules say about
what was frozen, and a hypothesis whose cohort the rules do not cover comes
back as `undeclared` rather than as sound — a gap in the rules, not a finding
about the hypothesis. Only an affirmative `valid` lets prospective work
proceed: treating "we have not looked" as "go ahead" let two hypotheses
through whose labels were afterwards measured to depend on data from seventy
days after the event they describe.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from earnings_research.legacy_research.knowledge import HORIZONS
from earnings_research.statistics.lookahead import contamination, declares, rules_digest

LEDGER_NAME = "source_validity.jsonl"
SCHEMA_VERSION = "prospective_hypothesis_source_validity_v1"

VALID = "valid"
INVALID = "invalid"
UNDECLARED = "undeclared"


@dataclass(frozen=True)
class Verdict:
    """One judgement of one frozen hypothesis under one version of the rules."""

    hypothesis_id: str
    hypothesis_version: int
    registry_id: str
    registry_version: int
    dimension: str
    evaluation_horizon: str
    source_field: str
    verdict: str
    reason: Optional[str]
    contamination_rules_sha256: str
    source_fields_sha256: str
    evaluated_at: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_version": self.hypothesis_version,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "dimension": self.dimension,
            "evaluation_horizon": self.evaluation_horizon,
            "source_field": self.source_field,
            "verdict": self.verdict,
            "reason": self.reason,
            "contamination_rules_sha256": self.contamination_rules_sha256,
            "source_fields_sha256": self.source_fields_sha256,
            "evaluated_at": self.evaluated_at,
        }


def source_fields_digest() -> str:
    """SHA-256 of the horizon-to-return mapping the judgement reads.

    It decides which pairing is judged, so it belongs to the standard as much
    as the contamination rules do. Left outside, changing d5 from ret_d5 to
    open_d5 moved four of nineteen verdicts while the rules digest sat still,
    and the re-scan the capability exists to trigger never fired.
    """
    return hashlib.sha256(
        json.dumps(dict(sorted(HORIZONS.items())), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _standard() -> tuple:
    """The pair of digests a verdict is recorded against."""
    return rules_digest(), source_fields_digest()


def source_field_for(evaluation_horizon: str) -> str:
    """The return the historical analysis measured this horizon with.

    Read off knowledge.py's own declaration rather than restated here: the
    question is what the analysis that produced the hypothesis actually used,
    and a second copy of that mapping could drift from the first.
    """
    field = HORIZONS.get(evaluation_horizon.lower())
    if field is None:
        raise KeyError("no source field for horizon %r" % evaluation_horizon)
    return field


def judge(registry, evaluated_at: str) -> List[Verdict]:
    """Judge every hypothesis in a registry under the rules as they stand."""
    digest, fields_digest = _standard()
    verdicts = []
    for item in registry.hypotheses:
        field = source_field_for(item.evaluation_horizon)
        reason = contamination(item.dimension, field)
        if reason is not None:
            outcome = INVALID
        elif declares(item.dimension):
            outcome = VALID
        else:
            outcome = UNDECLARED
            reason = (
                "%s is not declared in the contamination rules, so this pairing "
                "was passed by default rather than checked" % item.dimension
            )
        verdicts.append(
            Verdict(
                hypothesis_id=item.hypothesis_id,
                hypothesis_version=item.hypothesis_version,
                registry_id=registry.registry_id,
                registry_version=registry.registry_version,
                dimension=item.dimension,
                evaluation_horizon=item.evaluation_horizon,
                source_field=field,
                verdict=outcome,
                reason=reason,
                contamination_rules_sha256=digest,
                source_fields_sha256=fields_digest,
                evaluated_at=evaluated_at,
            )
        )
    return verdicts


def read_ledger(path: Path) -> List[dict]:
    """Every judgement ever recorded, oldest first."""
    path = Path(path)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_ledger(path: Path, verdicts: Sequence[Verdict]) -> int:
    """Add judgements without touching what is already there.

    The ledger is a history, not a current-state file: the same hypothesis is
    judged again whenever the rules change, and both judgements stay. A rewrite
    would erase the only evidence of when the standard moved.
    """
    if not verdicts:
        return 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for verdict in verdicts:
            handle.write(json.dumps(verdict.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return len(verdicts)


def _latest(ledger: Sequence[dict], key_of, digest: Optional[str] = None) -> Dict[tuple, dict]:
    """The last judgement recorded under the standard as it stands, per key.

    Times are parsed before they are compared. Compared as strings, a verdict
    stamped +00:00 loses to an earlier one stamped +09:00, and the ledger would
    report the superseded answer. Where two judgements carry the same instant,
    the later line wins, because that is the order they were appended in.
    """
    rules, fields = _standard()
    rules = digest or rules
    latest: Dict[tuple, dict] = {}
    for row in ledger:
        if row.get("contamination_rules_sha256") != rules:
            continue
        if row.get("source_fields_sha256") != fields:
            continue
        key = key_of(row)
        current = latest.get(key)
        if current is None or _moment(row) >= _moment(current):
            latest[key] = row
    return latest


def _definition(row: dict) -> tuple:
    return (row["hypothesis_id"], row["hypothesis_version"])


def _freeze(row: dict) -> tuple:
    return (
        row["registry_id"],
        row["registry_version"],
        row["hypothesis_id"],
        row["hypothesis_version"],
    )


def _moment(row: dict) -> datetime:
    return datetime.fromisoformat(row["evaluated_at"])


def effective_status(ledger: Sequence[dict], digest: Optional[str] = None) -> Dict[tuple, dict]:
    """What each definition stands at now, derived rather than written down.

    The latest judgement under the standard as it stands, keyed by hypothesis
    and version. Deriving it means an invalidation cannot be recorded and then
    forgotten to be acted on: there is no second place to update.

    This answers a question about a definition. Whether a particular freeze has
    been judged is a different question, and `effective_status_by_freeze` is
    what answers it.
    """
    return _latest(ledger, _definition, digest)


def effective_status_by_freeze(
    ledger: Sequence[dict], digest: Optional[str] = None
) -> Dict[tuple, dict]:
    """The same, keyed by the freeze the judgement was recorded against.

    A definition carried unchanged into a successor registry would draw the
    same verdict, so keying coverage on the definition alone looks harmless.
    It is not: "this freeze has been judged" and "this definition has been
    judged somewhere" are different claims, and only the first is something a
    standing check can rest on. On the definition key, a successor registry
    inherited its predecessor's row — the re-scan appended nothing for the new
    freeze, the per-freeze rate had no bucket for it, and the repeated
    invalidity that rate exists to expose was invisible.
    """
    return _latest(ledger, _freeze, digest)


def unevaluated(registry, ledger: Sequence[dict], digest: Optional[str] = None) -> List[tuple]:
    """Hypotheses in this freeze with no judgement under the rules as they stand."""
    known = effective_status_by_freeze(ledger, digest)
    return [
        (item.hypothesis_id, item.hypothesis_version)
        for item in registry.hypotheses
        if (
            registry.registry_id,
            registry.registry_version,
            item.hypothesis_id,
            item.hypothesis_version,
        )
        not in known
    ]


def is_usable(
    registry_id: str,
    registry_version: int,
    hypothesis_id: str,
    hypothesis_version: int,
    ledger: Sequence[dict],
) -> bool:
    """Whether prospective work may still be recorded against this freeze.

    Only an affirmative `valid`. Unjudged is not usable — a hypothesis nobody
    has checked under the current rules is the case this capability exists for
    — and neither is `undeclared`, which says the rules have nothing to say
    about the cohort. Letting that through treated "we have not looked" as
    "go ahead", and two hypotheses whose labels were later measured to depend
    on data from after the event passed the gate on it.

    Asked of the freeze rather than of the definition, so this gate and the
    standing check refuse the same things. Asked of the definition, a successor
    registry could record trials against knowledge that was never judged in
    that freeze while `verify-source-validity` refused the same registry.
    """
    row = effective_status_by_freeze(ledger).get(
        (registry_id, registry_version, hypothesis_id, hypothesis_version)
    )
    return row is not None and row["verdict"] == VALID


def rates(registry, ledger: Sequence[dict], digest: Optional[str] = None) -> Dict[str, object]:
    """Two numbers, because one of them can be improved by doing nothing.

    The retroactive rate is the share of frozen knowledge that does not meet
    the current standard — a debt, which rises whenever a rule is added. The
    per-registry rate is the same measure taken separately for each freeze, so
    a later registry that repeats the mistakes of an earlier one is visible.
    Reporting only the first would let the numbers improve by never adding a
    rule again, which is the outcome nobody wants.

    Both are counted per freeze. Counted per definition, two registries sharing
    a hypothesis id at the same version collapse into one, and the bucket that
    disappears is the successor — the one the per-freeze rate exists to show.
    """
    status = effective_status_by_freeze(ledger, digest)
    frozen = [
        (
            registry.registry_id,
            registry.registry_version,
            item.hypothesis_id,
            item.hypothesis_version,
        )
        for item in registry.hypotheses
    ]
    judged = [status[key] for key in frozen if key in status]
    invalid = sum(1 for row in judged if row["verdict"] == INVALID)
    undeclared = sum(1 for row in judged if row["verdict"] == UNDECLARED)
    by_registry: Dict[str, Dict[str, int]] = {}
    for (registry_id, registry_version, _id, _version), row in status.items():
        bucket = by_registry.setdefault(
            "%s@v%d" % (registry_id, registry_version), {"frozen": 0, "invalid": 0}
        )
        bucket["frozen"] += 1
        bucket["invalid"] += row["verdict"] == INVALID
    return {
        "contamination_rules_sha256": digest or rules_digest(),
        "source_fields_sha256": source_fields_digest(),
        "frozen_count": len(frozen),
        "judged_count": len(judged),
        "invalid_count": invalid,
        "undeclared_count": undeclared,
        "retroactive_invalidation_rate": (
            round(invalid / len(judged), 6) if judged else None
        ),
        "by_registry": {
            name: {
                **counts,
                "invalidation_rate": round(counts["invalid"] / counts["frozen"], 6),
            }
            for name, counts in sorted(by_registry.items())
        },
    }
