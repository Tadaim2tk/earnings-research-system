"""File boundaries for registry generation, append-only evaluation, and summaries."""

import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .evaluator import (
    evaluate_observation,
    successor_registry_problems,
    summarize_trials,
    validate_bundle_history,
)
from .models import (
    canonical_hash,
    CompletedEventObservation,
    HypothesisRegistry,
    HypothesisTrialBundle,
    HypothesisTrialBundleV1,
)
from earnings_research.market_reaction.models import MarketReactionTracking
from earnings_research.validation.validator import (
    _calculate_baseline_record_hash,
    load_spec,
    validate_dataset,
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
    bundles = []
    for item in sorted(path.glob("*.json")):
        payload = json.loads(item.read_text(encoding="utf-8"))
        version = payload.get("schema_version")
        if version == "prospective_hypothesis_trial_bundle_v1":
            bundles.append(HypothesisTrialBundleV1.model_validate(payload))
        elif version == "prospective_hypothesis_trial_bundle_v2":
            bundles.append(HypothesisTrialBundle.model_validate(payload))
        else:
            raise ValueError(f"unsupported hypothesis trial bundle schema: {version!r}")
    validate_bundle_history(bundles)
    return bundles


def _trial_keys(bundles):
    return {
        (
            trial.hypothesis_id,
            trial.hypothesis_version,
            trial.earnings_event_id,
            trial.evaluation_horizon,
        )
        for bundle in bundles
        for trial in bundle.trials
    }


def _read_dataset_table(dataset_dir, table):
    path = Path(dataset_dir) / load_spec(table).file
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _verify_authoritative_baseline(dataset_dir, observation):
    dataset_dir = Path(dataset_dir)
    report = validate_dataset(dataset_dir)
    if not report.ok:
        raise ValueError(
            "authoritative dataset validation failed: "
            + "; ".join(issue.format() for issue in report.issues)
        )
    rows = _read_dataset_table(dataset_dir, "pre_earnings_baseline")
    expected_id = observation.pre_event_features.baseline_id
    matches = [row for row in rows if row.get("baseline_id", "").strip() == expected_id]
    if len(matches) != 1:
        raise ValueError("baseline_id must resolve to exactly one authoritative row")
    row = matches[0]
    event_id = observation.earnings_event_id
    prospective_rows = [
        item for item in rows
        if item.get("earnings_event_id", "").strip() == event_id
        and item.get("baseline_status", "").strip()
    ]
    superseded_ids = {
        item.get("supersedes_baseline_id", "").strip()
        for item in prospective_rows
        if item.get("supersedes_baseline_id", "").strip()
    }
    current_tails = [
        item for item in prospective_rows
        if item.get("baseline_id", "").strip() not in superseded_ids
    ]
    if len(current_tails) != 1:
        raise ValueError("earnings event must have exactly one current prospective baseline tail")
    if current_tails[0].get("baseline_id", "").strip() != expected_id:
        raise ValueError("event observation must reference the current prospective baseline tail")
    if row.get("earnings_event_id", "").strip() != observation.earnings_event_id:
        raise ValueError("authoritative baseline belongs to a different earnings event")
    if row.get("baseline_version", "").strip() != f"v{observation.pre_event_features.baseline_version}":
        raise ValueError("authoritative baseline version does not match the event observation")
    if row.get("is_locked", "").strip().lower() != "true":
        raise ValueError("authoritative baseline must be locked")
    status = row.get("baseline_status", "").strip()
    if status != "locked":
        raise ValueError("authoritative prospective baseline must have locked status")
    try:
        locked_at = datetime.fromisoformat(row.get("locked_at", "").strip())
    except ValueError as exc:
        raise ValueError("authoritative baseline locked_at is invalid") from exc
    if locked_at != observation.pre_event_features.locked_at:
        raise ValueError("authoritative baseline lock timestamp does not match the event observation")
    if locked_at >= observation.event_occurred_at:
        raise ValueError("authoritative baseline must be locked before the event occurs")
    spec = load_spec("pre_earnings_baseline")
    canonical_hash = _calculate_baseline_record_hash(row, spec)
    declared_hash = row.get("baseline_record_hash", "").strip()
    if declared_hash != canonical_hash:
        raise ValueError("authoritative baseline hash does not match its canonical locked content")
    if observation.pre_event_features.baseline_record_hash != canonical_hash:
        raise ValueError("event observation baseline hash does not match the authoritative baseline")
    if expected_id not in observation.source_record_ids:
        raise ValueError("event observation source_record_ids must include the authoritative baseline_id")
    features = observation.pre_event_features
    recorded_rank = row.get("pre_event_grade", "").strip() or None
    if features.rank != recorded_rank:
        raise ValueError("event observation rank must match authoritative pre_event_grade")
    unsupported = {
        "narrative": features.narrative,
        "judge": features.judge,
        "risk_balance": features.risk_balance,
        "volatility_environment": features.volatility_environment,
        "dollar_environment": features.dollar_environment,
    }
    supplied = sorted(name for name, value in unsupported.items() if value is not None)
    if supplied:
        raise ValueError(
            "pre-event hypothesis fields lack an authoritative mapping: " + ", ".join(supplied)
        )

    event_rows = [
        item for item in _read_dataset_table(dataset_dir, "earnings_event")
        if item.get("earnings_event_id", "").strip() == event_id
    ]
    if len(event_rows) != 1:
        raise ValueError("earnings_event_id must resolve to exactly one authoritative event row")
    event_row = event_rows[0]
    if event_row.get("fiscal_period", "").strip() != observation.event_quarter.replace("-", ""):
        raise ValueError("event observation quarter does not match the authoritative event")
    company_rows = [
        item for item in _read_dataset_table(dataset_dir, "company_master")
        if item.get("company_id", "").strip() == event_row.get("company_id", "").strip()
    ]
    if len(company_rows) != 1:
        raise ValueError("authoritative event company must resolve to exactly one company row")
    company_row = company_rows[0]
    if (
        company_row.get("company_name", "").strip() != observation.company_name
        or company_row.get("ticker", "").strip() != observation.ticker
    ):
        raise ValueError("event observation company identity does not match the authoritative dataset")

    status_rows = [
        item for item in _read_dataset_table(dataset_dir, "event_status_history")
        if item.get("earnings_event_id", "").strip() == event_id
    ]
    superseded_status_ids = {
        item.get("supersedes_status_record_id", "").strip()
        for item in status_rows
        if item.get("supersedes_status_record_id", "").strip()
    }
    current_statuses = [
        item for item in status_rows
        if item.get("event_status_record_id", "").strip() not in superseded_status_ids
    ]
    if len(current_statuses) != 1 or current_statuses[0].get("event_status", "").strip() != "occurred":
        raise ValueError("authoritative event must have exactly one current occurred status")
    try:
        occurred_at = datetime.fromisoformat(current_statuses[0].get("occurred_at", "").strip())
    except ValueError as exc:
        raise ValueError("authoritative event occurred_at is invalid") from exc
    if occurred_at != observation.event_occurred_at:
        raise ValueError("event observation occurrence time does not match the authoritative dataset")
    return row


def _reaction_label(tracking):
    immediate = tracking.event_window_reaction.return_pct
    next_day = next(
        item for item in tracking.milestones
        if item.role == "next_business_day_close"
    ).return_from_pre_event_close_pct
    if immediate is None or next_day is None or immediate == 0:
        return None
    if immediate > 0:
        return "GU継続" if next_day >= immediate else "GU失速"
    return "GD反発" if next_day > immediate else "GD継続"


def _verify_authoritative_outcomes(dataset_dir, market_reaction_path, observation):
    tracking = MarketReactionTracking.model_validate_json(
        Path(market_reaction_path).read_text(encoding="utf-8")
    )
    if (
        tracking.earnings_event_id != observation.earnings_event_id
        or tracking.company_name != observation.company_name
        or tracking.ticker != observation.ticker
    ):
        raise ValueError("market reaction identity does not match the event observation")
    if tracking.tracking_id not in observation.source_record_ids:
        raise ValueError("event observation source_record_ids must include market reaction tracking_id")
    if observation.post_event_features.reaction_source_record_id != tracking.tracking_id:
        raise ValueError("reaction source must reference the authoritative market reaction tracking")
    if observation.post_event_features.reaction != _reaction_label(tracking):
        raise ValueError("event observation reaction does not match authoritative market reaction values")

    next_day_milestone = next(
        item for item in tracking.milestones
        if item.role == "next_business_day_close"
    )
    if observation.post_event_features.captured_at != next_day_milestone.price_datetime:
        raise ValueError("reaction captured_at does not match the authoritative next-day milestone")

    milestone_by_horizon = {
        "D1": next_day_milestone,
        "D5": next(
            item for item in tracking.milestones
            if item.role == "fifth_business_day_close"
        ),
    }
    review_rows = {
        row.get("review_id", "").strip(): row
        for row in _read_dataset_table(dataset_dir, "post_earnings_review")
    }
    for item in observation.returns:
        if item.horizon in milestone_by_horizon:
            milestone = milestone_by_horizon[item.horizon]
            expected_status = "comparable" if milestone.status == "observed" else "not_comparable"
            expected_value = (
                milestone.return_from_pre_event_close_pct / 100
                if milestone.return_from_pre_event_close_pct is not None else None
            )
            if item.source_record_id != tracking.tracking_id:
                raise ValueError(f"{item.horizon} return must reference market reaction tracking_id")
            if milestone.price_datetime != item.observed_at:
                raise ValueError(f"{item.horizon} observed_at does not match market reaction milestone")
        else:
            review = review_rows.get(item.source_record_id)
            if review is None:
                raise ValueError("D20 source_record_id must resolve to an authoritative post-event review")
            if (
                review.get("earnings_event_id", "").strip() != observation.earnings_event_id
                or review.get("baseline_id", "").strip() != observation.pre_event_features.baseline_id
            ):
                raise ValueError("D20 post-event review does not match the observation event and baseline")
            raw_value = review.get("day20_return_pct", "").strip()
            expected_status = "comparable" if raw_value else "not_comparable"
            expected_value = float(raw_value) / 100 if raw_value else None
            try:
                review_recorded_at = datetime.fromisoformat(review.get("recorded_at", "").strip())
            except ValueError as exc:
                raise ValueError("D20 post-event review recorded_at is invalid") from exc
            if review_recorded_at != item.observed_at:
                raise ValueError("D20 observed_at must match authoritative post-event review recorded_at")
        if item.status != expected_status or item.return_value != expected_value:
            raise ValueError(f"{item.horizon} return does not match its authoritative source")
        if item.source_record_id not in observation.source_record_ids:
            raise ValueError(f"source_record_ids must include the {item.horizon} return source")


def _validate_observation_chain(existing, observation):
    if any(
        isinstance(item, HypothesisTrialBundleV1)
        and item.earnings_event_id == observation.earnings_event_id
        for item in existing
    ):
        raise ValueError("a v1 event bundle cannot be extended as a staged v2 observation")
    event_bundles = sorted(
        (
            item for item in existing
            if isinstance(item, HypothesisTrialBundle)
            and item.earnings_event_id == observation.earnings_event_id
        ),
        key=lambda item: item.observation_version,
    )
    if not event_bundles:
        if observation.observation_version != 1 or observation.supersedes_observation_id is not None:
            raise ValueError("first staged observation must be version 1 without a predecessor")
        return
    versions = [item.observation_version for item in event_bundles]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError("existing staged observation versions are not contiguous")
    previous = event_bundles[-1]
    if observation.observation_version != previous.observation_version + 1:
        raise ValueError("staged observation version must increment by one")
    if observation.supersedes_observation_id != previous.observation_id:
        raise ValueError("staged observation must supersede the current event observation")
    identity = (
        observation.company_name,
        observation.ticker,
        observation.event_quarter,
        observation.event_occurred_at,
    )
    previous_identity = (
        previous.company_name,
        previous.ticker,
        previous.event_quarter,
        previous.event_occurred_at,
    )
    if identity != previous_identity:
        raise ValueError("staged observation cannot change event identity")
    if canonical_hash(observation.pre_event_features) != previous.pre_event_features_sha256:
        raise ValueError("staged observation cannot change frozen pre-event features")
    if previous.reaction is not None and observation.post_event_features.reaction != previous.reaction:
        raise ValueError("staged observation cannot change an already recorded reaction")
    order = {"D1": 1, "D5": 2, "D20": 3}
    if order[observation.observation_stage] <= order[previous.observation_stage]:
        raise ValueError("staged observation horizon must advance")
    if observation.observed_through <= previous.observed_through:
        raise ValueError("staged observation time must advance")
    current_returns = {item.horizon: item for item in observation.returns}
    for old_return in previous.return_snapshots:
        current = current_returns.get(old_return.horizon)
        if current is None or current.model_dump(mode="json") != old_return.model_dump(mode="json"):
            raise ValueError("staged observation cannot remove or change a matured return")


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


class _Unverified:
    """正本との突合を行わないことを、**呼ぶ側に明示させる**ための合図。

    `None` を既定値にすると、引数を忘れただけの呼び出しが黙って突合を飛ばす。
    合図を書かせれば、飛ばしたことがその行に残る。

    **記録する経路では使わない。** CLI の `evaluate-hypothesis-event` は
    `--dataset` と `--market-reaction` を必須にしてあるので、実際に trial を
    積む道からは到達しない。使うのは、正本と無関係な関心（規則の凍結時期など）を
    合成イベントで試す場合に限る——`data/samples` に無いイベントを正本と突き
    合わせることは原理的にできない。

    残る穴: bundle 自体には「突合していない」と書かれない。合成イベントで
    作った bundle を本物と並べる運用に移る前に、記録側へ印を足すこと。
    """

    def __repr__(self):
        return "UNVERIFIED"


UNVERIFIED = _Unverified()


def default_ledger_path(registry) -> Path:
    return Path("data/prospective_hypotheses") / LEDGER_NAME


def evaluate_observation_file(
    registry_path: Path,
    observation_path: Path,
    trials_dir: Path,
    output_path: Path,
    recorded_at: datetime,
    dataset_dir: Path,
    market_reaction_path: Path,
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
    # **「1イベントに1つのbundle」は、ここで版の連鎖へ置き換わる。**
    # main 側はイベント名で走査して2本目を拒んでいた。段階評価では D1 → D5 →
    # D20 と同じイベントに複数持つことが目的なので、その走査は使えない。
    # 代わりに `_validate_observation_chain` が版の連続と先行関係を、
    # `_trial_keys` が (仮説ID, 版, イベント, horizon) の一意性を強制する。
    # **保護は緩まず細かくなる**——同じ horizon の二重登録は今も拒む。
    # 走査を消して source-validity gate に置き換えたときに試験が緩くて
    # 気づかなかった、と main 側のコメントが記録している。ここでは置き換え先を
    # 明示し、下の2つの検査がその役を負う。
    if dataset_dir is UNVERIFIED or market_reaction_path is UNVERIFIED:
        if not (dataset_dir is UNVERIFIED and market_reaction_path is UNVERIFIED):
            raise ValueError("UNVERIFIED must be passed for both the dataset and the market reaction")
    else:
        _verify_authoritative_baseline(dataset_dir, observation)
        _verify_authoritative_outcomes(dataset_dir, market_reaction_path, observation)
    existing = load_trial_bundles(trials_dir)
    _validate_observation_chain(existing, observation)
    bundle = evaluate_observation(
        registry,
        observation,
        recorded_at,
        existing_trial_keys=_trial_keys(existing),
    )
    _write_new(output_path, _render(bundle))
    return bundle


def evaluate_observation_and_status_file(
    registry_path: Path,
    observation_path: Path,
    trials_dir: Path,
    trial_output_path: Path,
    status_output_path: Path,
    recorded_at: datetime,
    evaluated_at: datetime,
    dataset_dir: Path,
    market_reaction_path: Path,
):
    trials_dir = Path(trials_dir)
    if Path(trial_output_path).parent.resolve() != trials_dir.resolve():
        raise ValueError("trial output must be a direct child of the append-only trials directory")
    if Path(status_output_path).parent.resolve() == trials_dir.resolve():
        raise ValueError("derived status output must stay outside the trial source directory")
    if Path(trial_output_path).exists() or Path(status_output_path).exists():
        raise FileExistsError("append-only trial and status output paths must both be new")
    registry = HypothesisRegistry.model_validate_json(Path(registry_path).read_text(encoding="utf-8"))
    observation = CompletedEventObservation.model_validate_json(
        Path(observation_path).read_text(encoding="utf-8")
    )
    if dataset_dir is UNVERIFIED or market_reaction_path is UNVERIFIED:
        if not (dataset_dir is UNVERIFIED and market_reaction_path is UNVERIFIED):
            raise ValueError("UNVERIFIED must be passed for both the dataset and the market reaction")
    else:
        _verify_authoritative_baseline(dataset_dir, observation)
        _verify_authoritative_outcomes(dataset_dir, market_reaction_path, observation)
    existing = load_trial_bundles(trials_dir)
    _validate_observation_chain(existing, observation)
    bundle = evaluate_observation(
        registry,
        observation,
        recorded_at,
        existing_trial_keys=_trial_keys(existing),
    )
    snapshot = summarize_trials(registry, existing + [bundle], evaluated_at)
    _write_new(trial_output_path, _render(bundle))
    _write_new(status_output_path, _render(snapshot))
    return bundle, snapshot


def summarize_trials_file(
    registry_path: Path,
    trials_dir: Path,
    output_path: Path,
    evaluated_at: datetime,
    ledger_path: Path = None,
):
    if Path(output_path).parent.resolve() == Path(trials_dir).resolve():
        raise ValueError("derived status output must stay outside the trial source directory")
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
