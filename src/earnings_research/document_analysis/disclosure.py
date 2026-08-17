"""Analyze the disclosure document a monitor handoff already named.

Kept apart from the discovery pipeline because nothing is discovered here. The
index hands over one document URL, this reads that one document, and a handoff
that names nothing produces no analysis rather than sending the pipeline
looking for links.
"""

import json
from pathlib import Path
from typing import Dict, Optional

from earnings_research.document_analysis.acquisition import (
    handed_over_documents,
    within_run_limit,
)
from earnings_research.document_analysis.discovery import classify_document
from earnings_research.document_analysis.guarded_fetch import GuardedDocumentFetcher
from earnings_research.document_analysis.pipeline import (
    analyze_document_url,
    analyze_handoff,
    write_analysis,
)


def analyze_named_disclosure(
    *,
    handoff_path: Path,
    output_dir: Path,
    acquired_at: Optional[str] = None,
) -> Dict[str, object]:
    """Read the named document, write its analysis, and return the dispatch.

    A handoff that names no document is passed to the discovery pipeline
    unchanged, so this is the single entry point the workflow needs and the
    branch lives here rather than in shell.
    """
    payload = json.loads(Path(handoff_path).read_text(encoding="utf-8"))
    if not payload.get("last_seen_document_url"):
        return analyze_handoff(handoff_path, output_dir, acquired_at)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = handed_over_documents(payload)
    limit_reason = within_run_limit(documents)
    if limit_reason:
        raise ValueError(limit_reason)
    analyzed = []
    excluded = 0
    # The guarded fetcher re-checks every redirect hop against the approved
    # publishers, which the generic fetcher does not.
    fetcher = GuardedDocumentFetcher()
    for document in documents:
        if classify_document(document["title"], document["url"]) is None:
            excluded += 1
            continue
        result = analyze_document_url(document["url"], document["title"], acquired_at, fetcher)
        path = output_dir / (result.analysis_id + ".json")
        write_analysis(result, path)
        analyzed.append(str(path))
    dispatch = {
        "dispatch_version": "earnings_document_dispatch_v1",
        "status": "analysis_completed" if analyzed else "no_target_documents",
        "monitor_target_id": payload.get("monitor_target_id"),
        "analyzed_outputs": analyzed,
        "excluded_document_count": excluded,
        "raw_document_retained": False,
    }
    (output_dir / "dispatch_result.json").write_text(
        json.dumps(dispatch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return dispatch
