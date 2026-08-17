"""Machine-readable transition from monitoring into earnings-document research."""

import json
from pathlib import Path
from typing import Dict, Optional

from earnings_research.monitoring.persistence import VerifiedMonitorBundle


def build_research_handoff(bundle: VerifiedMonitorBundle) -> Optional[Dict[str, object]]:
    run = bundle.latest_run
    target = bundle.target
    if (
        run.get("run_result") != "change_detected"
        or target.get("change_response") != "autonomous_research_handoff"
    ):
        return None
    checkpoint = bundle.checkpoint
    return {
        "handoff_version": "earnings_document_research_v1",
        "status": "ready_for_document_discovery",
        "monitor_target_id": target["monitor_target_id"],
        "monitor_run_id": run["monitor_run_id"],
        "company_id": target["company_id"],
        "earnings_event_id": target.get("earnings_event_id") or None,
        "source_url": target["source_url"],
        "source_category": target["source_category"],
        "detected_at": run["finished_at"],
        "change_summary": run["detected_change_summary"],
        "last_seen_title": checkpoint.get("last_seen_title") or None,
        "last_seen_document_id": checkpoint.get("last_seen_document_id") or None,
        "last_seen_published_at": checkpoint.get("last_seen_published_at") or None,
        "last_seen_document_url": checkpoint.get("last_seen_document_url") or None,
        "last_seen_schedule": checkpoint.get("last_seen_schedule") or None,
        "next_stages": [
            "document_discovery",
            "document_content_acquisition",
            "financial_metric_extraction",
            "pre_event_comparison",
            "earnings_evaluation",
            "price_reaction_tracking",
        ],
        "raw_content_included": False,
    }


def write_research_handoff(bundle: VerifiedMonitorBundle, output_path: Path) -> bool:
    payload = build_research_handoff(bundle)
    if payload is None:
        return False
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return True
