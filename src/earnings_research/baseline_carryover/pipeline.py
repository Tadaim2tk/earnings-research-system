"""File entry points for baseline carryover preparation."""

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from earnings_research.post_event_learning.models import PostEventLearningReview

from .builder import build_baseline_carryover, canonical_json_sha256
from .models import BaselineCarryoverContext


def prepare_files(
    review_paths: Iterable[Path], target_event_id: str, prepared_at: datetime
) -> BaselineCarryoverContext:
    reviews = []
    for path in review_paths:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        review = PostEventLearningReview.model_validate(raw)
        reviews.append((review, canonical_json_sha256(raw)))
    return build_baseline_carryover(reviews, target_event_id, prepared_at)


def write_carryover(result: BaselineCarryoverContext, output_path: Path) -> None:
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError("baseline carryover context already exists; choose a new output path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
