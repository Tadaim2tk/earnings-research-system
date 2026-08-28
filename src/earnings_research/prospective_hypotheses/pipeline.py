"""File boundaries for registry generation, append-only evaluation, and summaries."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .evaluator import evaluate_observation, stop_rule_relaxations, summarize_trials
from .models import (
    CompletedEventObservation,
    HypothesisRegistry,
    HypothesisTrialBundle,
)
from .registry import build_registry, load_knowledge
from earnings_research.statistics.lookahead import rules_digest
from .source_validity import (
    LEDGER_NAME,
    append_ledger,
    is_usable,
    judge,
    rates,
    read_ledger,
    unevaluated,
)


def _render(model):
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_new(path: Path, text: str):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_registry_file(knowledge_path: Path, output_path: Path, frozen_at: datetime):
    knowledge_path = Path(knowledge_path)
    knowledge, source_hash = load_knowledge(knowledge_path)
    registry = build_registry(knowledge, str(knowledge_path), source_hash, frozen_at)
    _write_new(output_path, _render(registry))
    return registry


def verify_stop_rules_only_tightened(previous_path: Path, current_path: Path):
    """Refuse a successor registry that widened any inherited stop rule.

    Separate from registry verification because that call re-derives the file
    from the frozen research and so only ever sees one version. This is the
    check a version bump has to pass, and it is a command rather than an
    argument so CI can require it on any change to the registry directory.
    """
    previous = HypothesisRegistry.model_validate_json(
        Path(previous_path).read_text(encoding="utf-8")
    )
    current = HypothesisRegistry.model_validate_json(
        Path(current_path).read_text(encoding="utf-8")
    )
    problems = stop_rule_relaxations(previous, current)
    if problems:
        raise ValueError("; ".join(problems))
    return current


def verify_registry_file(knowledge_path: Path, registry_path: Path):
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    recorded_source = Path(registry.source_research_path)
    if not recorded_source.is_absolute():
        recorded_source = Path.cwd() / recorded_source
    if recorded_source.resolve() != Path(knowledge_path).resolve():
        raise ValueError("registry source path does not match the supplied legacy research file")
    knowledge, source_hash = load_knowledge(Path(knowledge_path))
    expected = build_registry(
        knowledge,
        registry.source_research_path,
        source_hash,
        registry.frozen_at,
    )
    if _render(expected) != Path(registry_path).read_text(encoding="utf-8"):
        raise ValueError("committed hypothesis registry does not match its frozen source")
    return registry


def evaluate_source_validity_file(registry_path: Path, ledger_path: Path, evaluated_at: datetime):
    """Judge every frozen hypothesis under the rules as they stand, and append.

    Deliberately a command rather than something CI does on its own: the
    verdicts land in a file that is committed, so a change of standard shows up
    as a diff somebody reviews. CI's job is to notice that the judgement is
    missing, not to write it.
    """
    registry = HypothesisRegistry.model_validate_json(
        Path(registry_path).read_text(encoding="utf-8")
    )
    ledger = read_ledger(ledger_path)
    pending = {key for key in unevaluated(registry, ledger)}
    verdicts = [
        verdict
        for verdict in judge(registry, evaluated_at.isoformat())
        if (verdict.hypothesis_id, verdict.hypothesis_version) in pending
    ]
    append_ledger(ledger_path, verdicts)
    return {
        "appended": len(verdicts),
        "already_judged": len(registry.hypotheses) - len(verdicts),
        **rates(registry, read_ledger(ledger_path)),
    }


def verify_source_validity_file(registry_path: Path, ledger_path: Path):
    """Refuse a registry that has not been judged under the current standard.

    One check, not two. No verdict under the current digests means the rules
    moved and nobody looked again — the situation where knowledge frozen
    earlier silently stops being supportable. Whether an invalid hypothesis is
    still gathering evidence is a question about trials, which this call has no
    argument for and cannot see; the trial commands refuse that themselves.
    """
    registry = HypothesisRegistry.model_validate_json(
        Path(registry_path).read_text(encoding="utf-8")
    )
    ledger = read_ledger(ledger_path)
    missing = unevaluated(registry, ledger)
    if missing:
        raise ValueError(
            "%d hypotheses have no source-validity verdict under the current "
            "contamination rules (%s): %s"
            % (
                len(missing),
                rules_digest()[:12],
                ", ".join("%s v%d" % key for key in missing[:5]),
            )
        )
    return {"status": "judged", **rates(registry, ledger)}


def load_trial_bundles(trials_dir: Path):
    path = Path(trials_dir)
    if not path.exists():
        return []
    return [
        HypothesisTrialBundle.model_validate_json(item.read_text(encoding="utf-8"))
        for item in sorted(path.glob("*.json"))
    ]


def usable_hypotheses(registry, ledger_path: Path = None):
    """The hypotheses prospective work may still be recorded against.

    Reading the ledger rather than the registry, because the registry is frozen
    and cannot say this. A hypothesis the current rules condemn is not
    evidence-gathering material, and neither is one nobody has judged under
    them — an unjudged definition is exactly the case this check exists for.
    """
    ledger = read_ledger(ledger_path or default_ledger_path(registry))
    refused = [
        item
        for item in registry.hypotheses
        if not is_usable(item.hypothesis_id, item.hypothesis_version, ledger)
    ]
    return [item for item in registry.hypotheses if item not in refused], refused


def default_ledger_path(registry) -> Path:
    return Path("data/prospective_hypotheses") / LEDGER_NAME


def evaluate_observation_file(
    registry_path: Path,
    observation_path: Path,
    trials_dir: Path,
    output_path: Path,
    recorded_at: datetime,
    ledger_path: Path = None,
):
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    observation = CompletedEventObservation.model_validate_json(
        Path(observation_path).read_text(encoding="utf-8")
    )
    _usable, refused = usable_hypotheses(
        registry, ledger_path or Path(registry_path).parent / LEDGER_NAME
    )
    if refused:
        # Refused rather than skipped. Quietly recording trials for the rest
        # would leave a registry half of which is gathering evidence and half
        # of which is not, with nothing in the output saying which.
        raise ValueError(
            "%d of %d hypotheses have no usable source-validity verdict under the "
            "current contamination rules (%s); run evaluate-source-validity and "
            "retire the invalid ones before recording more trials"
            % (len(refused), len(registry.hypotheses), ", ".join(
                item.hypothesis_id for item in refused[:3]
            ) + ("…" if len(refused) > 3 else ""))
        )
    bundle = evaluate_observation(registry, observation, recorded_at)
    _write_new(output_path, _render(bundle))
    return bundle


def summarize_trials_file(
    registry_path: Path,
    trials_dir: Path,
    output_path: Path,
    evaluated_at: datetime,
    ledger_path: Path = None,
):
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    _usable, refused = usable_hypotheses(
        registry, ledger_path or Path(registry_path).parent / LEDGER_NAME
    )
    if refused:
        raise ValueError(
            "%d of %d hypotheses have no usable source-validity verdict under the "
            "current contamination rules; a status snapshot over them would read "
            "as evidence about knowledge the rules no longer support"
            % (len(refused), len(registry.hypotheses))
        )
    snapshot = summarize_trials(registry, load_trial_bundles(trials_dir), evaluated_at)
    _write_new(output_path, _render(snapshot))
    return snapshot
