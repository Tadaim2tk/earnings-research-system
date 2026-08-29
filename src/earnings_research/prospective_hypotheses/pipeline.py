"""File boundaries for registry generation, append-only evaluation, and summaries."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .evaluator import evaluate_observation, successor_registry_problems, summarize_trials
from .models import (
    CompletedEventObservation,
    HypothesisRegistry,
    HypothesisTrialBundle,
)
from .freeze import evaluation_started_at, rule_freeze_violations
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


def verify_successor_registry(previous_path: Path, current_path: Path):
    """Refuse a successor registry that quietly retires what it inherited.

    Separate from registry verification because that call re-derives the file
    from the frozen research and so only ever sees one version. This is the
    check a version bump has to pass, and it is a command rather than an
    argument so CI can require it on any change to the registry directory.

    It no longer asks whether a rule was tightened or loosened. Any change to
    a stop rule under an unchanged hypothesis version is refused, because a
    rule that moves under trials already recorded scores those trials against
    a rule that no longer exists. Whether trials actually exist is a question
    about the record, not about two files, and `verify-rule-freeze` is what
    asks it.
    """
    previous = HypothesisRegistry.model_validate_json(
        Path(previous_path).read_text(encoding="utf-8")
    )
    current = HypothesisRegistry.model_validate_json(
        Path(current_path).read_text(encoding="utf-8")
    )
    problems = successor_registry_problems(previous, current)
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


def verify_rule_freeze_files(registry_dir: Path, trials_dir: Path):
    """Refuse any definition whose decision rules moved after evidence began.

    Reads every registry in the directory rather than a named pair: a rule can
    be changed by freezing a third registry, and a pairwise check sees only the
    pair it was handed. Finding no registry is an error — a renamed directory
    must not turn this into a check that passes because it looked at nothing.
    """
    registries = []
    for path in sorted(Path(registry_dir).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not {"registry_id", "hypotheses"} <= set(payload):
            continue
        registries.append(HypothesisRegistry.model_validate(payload))
    if not registries:
        raise ValueError("no hypothesis registry found under %s" % registry_dir)
    bundles = load_trial_bundles(trials_dir)
    problems = rule_freeze_violations(registries, bundles)
    if problems:
        raise ValueError("; ".join(problems))
    started = {}
    for registry in registries:
        for definition in registry.hypotheses:
            key = (definition.hypothesis_id, definition.hypothesis_version)
            since = evaluation_started_at(key, bundles)
            if since is not None:
                started["%s v%d" % key] = since.isoformat()
    return {
        "status": "rules_frozen",
        "registries": len(registries),
        # Whether the directory is there at all, not just how many bundles were
        # in it. A mistyped path returns zero bundles and every rule reads as
        # still changeable, which is the same shape of silence as a check that
        # verified one hard-coded registry while a second went unjudged.
        "trials_dir_present": Path(trials_dir).exists(),
        "trial_bundles": len(bundles),
        # Named rather than counted. "0 started" and "12 frozen definitions,
        # none of which has ever received a trial" read the same as a number
        # and mean different things to whoever is looking at CI.
        "evaluation_started": dict(sorted(started.items())),
    }


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
        if not is_usable(
            registry.registry_id,
            registry.registry_version,
            item.hypothesis_id,
            item.hypothesis_version,
            ledger,
        )
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
    if any(
        bundle.earnings_event_id == observation.earnings_event_id
        for bundle in load_trial_bundles(trials_dir)
    ):
        # Scanned by event rather than by pathname. `_write_new` refuses the
        # same output file, which is not the same protection: the same event
        # written under a different name passed straight through, put a second
        # bundle into an append-only record, and made `summarize_trials` fail
        # afterwards on its duplicate-identity check. This branch dropped the
        # scan while replacing it with the source-validity gate, and the suite
        # stayed green because the test that named this behaviour reused one
        # output path and accepted either error.
        raise ValueError("this earnings event already has an append-only hypothesis trial bundle")
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
