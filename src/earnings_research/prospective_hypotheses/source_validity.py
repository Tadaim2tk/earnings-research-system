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
back as `undeclared` rather than as sound, so the gap is visible rather than
counted as a pass.
"""

import json
from dataclasses import dataclass
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
            "evaluated_at": self.evaluated_at,
        }


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
    digest = rules_digest()
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


def effective_status(ledger: Sequence[dict], digest: Optional[str] = None) -> Dict[tuple, dict]:
    """What each hypothesis stands at now, derived rather than written down.

    The latest judgement under the current rules, keyed by hypothesis and
    version. Deriving it means an invalidation cannot be recorded and then
    forgotten to be acted on: there is no second place to update.
    """
    digest = digest or rules_digest()
    latest: Dict[tuple, dict] = {}
    for row in ledger:
        if row.get("contamination_rules_sha256") != digest:
            continue
        key = (row["hypothesis_id"], row["hypothesis_version"])
        current = latest.get(key)
        if current is None or row["evaluated_at"] >= current["evaluated_at"]:
            latest[key] = row
    return latest


def unevaluated(registry, ledger: Sequence[dict], digest: Optional[str] = None) -> List[tuple]:
    """Hypotheses with no judgement under the rules as they stand."""
    known = effective_status(ledger, digest)
    return [
        (item.hypothesis_id, item.hypothesis_version)
        for item in registry.hypotheses
        if (item.hypothesis_id, item.hypothesis_version) not in known
    ]


def is_usable(hypothesis_id: str, hypothesis_version: int, ledger: Sequence[dict]) -> bool:
    """Whether prospective work may still be recorded against this hypothesis.

    Unjudged is not usable either. A hypothesis nobody has checked under the
    current rules is exactly the case this capability exists for.
    """
    row = effective_status(ledger).get((hypothesis_id, hypothesis_version))
    return row is not None and row["verdict"] != INVALID


def rates(registry, ledger: Sequence[dict], digest: Optional[str] = None) -> Dict[str, object]:
    """Two numbers, because one of them can be improved by doing nothing.

    The retroactive rate is the share of frozen knowledge that does not meet
    the current standard — a debt, which rises whenever a rule is added. The
    per-registry rate is the same measure taken separately for each freeze, so
    a later registry that repeats the mistakes of an earlier one is visible.
    Reporting only the first would let the numbers improve by never adding a
    rule again, which is the outcome nobody wants.
    """
    status = effective_status(ledger, digest)
    frozen = [(item.hypothesis_id, item.hypothesis_version) for item in registry.hypotheses]
    judged = [status[key] for key in frozen if key in status]
    invalid = sum(1 for row in judged if row["verdict"] == INVALID)
    undeclared = sum(1 for row in judged if row["verdict"] == UNDECLARED)
    by_registry: Dict[str, Dict[str, int]] = {}
    for row in status.values():
        bucket = by_registry.setdefault(
            "%s@v%d" % (row["registry_id"], row["registry_version"]),
            {"frozen": 0, "invalid": 0},
        )
        bucket["frozen"] += 1
        bucket["invalid"] += row["verdict"] == INVALID
    return {
        "contamination_rules_sha256": digest or rules_digest(),
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
