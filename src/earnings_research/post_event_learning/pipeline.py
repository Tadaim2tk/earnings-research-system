"""File entry points for post-event forecast validation and learning."""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from earnings_research.earnings_evaluation.models import EarningsEvaluation
from earnings_research.market_reaction.models import MarketReactionTracking

from .models import PostEventLearningReview
from .reviewer import build_post_event_review


def review_files(
    baseline_path: Path,
    baseline_id: str,
    hypothesis_path: Path,
    evaluation_path: Path,
    reaction_path: Path,
    reviewed_at: datetime,
    previous_review_path: Optional[Path] = None,
) -> PostEventLearningReview:
    baseline_rows = _read_csv(baseline_path)
    baselines = [row for row in baseline_rows if row.get("baseline_id") == baseline_id]
    if len(baselines) != 1:
        raise ValueError("baseline_id must resolve to exactly one row")
    evaluation = EarningsEvaluation.model_validate_json(
        Path(evaluation_path).read_text(encoding="utf-8")
    )
    reaction = MarketReactionTracking.model_validate_json(
        Path(reaction_path).read_text(encoding="utf-8")
    )
    previous = None
    if previous_review_path is not None:
        previous = PostEventLearningReview.model_validate_json(
            Path(previous_review_path).read_text(encoding="utf-8")
        )
    return build_post_event_review(
        baselines[0],
        _read_csv(hypothesis_path),
        evaluation,
        reaction,
        reviewed_at,
        previous,
    )


def write_review(result: PostEventLearningReview, output_path: Path) -> None:
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError("post-event learning review already exists; append a new version path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
