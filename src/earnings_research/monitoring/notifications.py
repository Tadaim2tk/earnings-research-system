"""Issue planning, deduplication, and bounded delivery retry."""

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from earnings_research.monitoring.github_api import GitHubAPIClient
from earnings_research.monitoring.persistence import VerifiedMonitorBundle

MAX_NOTIFICATION_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (0, 1, 2)


@dataclass(frozen=True)
class IssueNotificationPlan:
    dedup_key: str
    title: str
    body: str
    update_body: str
    requires_human_decision: bool


@dataclass(frozen=True)
class NotificationReceipt:
    monitor_target_id: str
    monitor_run_id: str
    dedup_key: str
    status: str
    attempts: int
    issue_number: Optional[int]
    issue_url: Optional[str]
    error: Optional[str]
    recorded_at: str

    def write(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


def build_issue_plan(bundle: VerifiedMonitorBundle) -> Optional[IssueNotificationPlan]:
    """Render change/error notification; successful unchanged runs remain silent."""
    run = bundle.latest_run
    result = run.get("run_result")
    if result not in {"change_detected", "error"}:
        return None
    target = bundle.target
    target_id = run["monitor_target_id"]
    if result == "change_detected":
        episode_id = _first_unresolved_change_id(bundle)
        category = "change"
        summary = run.get("detected_change_summary") or "Metadata change requires Human review"
        recommended = "Review this run and record a monitor_resolution before closing the Issue."
    else:
        episode_id = _error_episode_id(bundle.runs)
        category = "error"
        summary = "%s: %s" % (run.get("error_code"), run.get("error_detail"))
        recommended = "Restore monitoring health; do not infer no_change from this failure."
    dedup_key = _dedup_key(target_id, category, episode_id)
    marker = "<!-- ers-monitor-dedup:%s -->" % dedup_key
    details = _issue_details(bundle, summary, recommended, dedup_key)
    title = "[ERS monitor] %s: %s" % (target_id, category)
    body = marker + "\n\n" + details
    update = "Additional monitor run in the same episode:\n\n" + details
    return IssueNotificationPlan(dedup_key, title, body, update, True)


def deliver_issue_notification(
    *,
    client: GitHubAPIClient,
    plan: IssueNotificationPlan,
    target_id: str,
    run_id: str,
    recorded_at: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> NotificationReceipt:
    """Create or append to one Issue, retrying a bounded three attempts."""
    error = None
    for attempt in range(1, MAX_NOTIFICATION_ATTEMPTS + 1):
        try:
            existing = client.find_open_issue(plan.dedup_key)
            if existing is None:
                issue = client.create_issue(plan.title, plan.body)
            else:
                client.comment_issue(int(existing["number"]), plan.update_body)
                issue = existing
            return NotificationReceipt(
                target_id,
                run_id,
                plan.dedup_key,
                "delivered",
                attempt,
                int(issue["number"]),
                issue.get("html_url"),
                None,
                recorded_at.isoformat(),
            )
        except Exception as exc:
            error = type(exc).__name__
            if attempt < MAX_NOTIFICATION_ATTEMPTS:
                sleep(RETRY_BACKOFF_SECONDS[attempt])
    return NotificationReceipt(
        target_id,
        run_id,
        plan.dedup_key,
        "failed",
        MAX_NOTIFICATION_ATTEMPTS,
        None,
        None,
        error,
        recorded_at.isoformat(),
    )


def _first_unresolved_change_id(bundle: VerifiedMonitorBundle) -> str:
    resolved = {row.get("source_monitor_run_id", "") for row in bundle.resolutions}
    pending = [
        row["monitor_run_id"]
        for row in bundle.runs
        if row.get("run_result") == "change_detected" and row.get("monitor_run_id") not in resolved
    ]
    return pending[0] if pending else bundle.latest_run["monitor_run_id"]


def _error_episode_id(runs: Sequence[Dict[str, str]]) -> str:
    latest = runs[-1]
    error_code = latest.get("error_code", "")
    episode = latest["monitor_run_id"]
    for run in reversed(runs):
        if run.get("run_result") != "error" or run.get("error_code") != error_code:
            break
        episode = run["monitor_run_id"]
    return episode


def _dedup_key(target_id: str, category: str, episode_id: str) -> str:
    raw = "%s|%s|%s" % (target_id, category, episode_id)
    return "%s-%s" % (category, hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24])


def _issue_details(
    bundle: VerifiedMonitorBundle,
    summary: str,
    recommended: str,
    dedup_key: str,
) -> str:
    run = bundle.latest_run
    checkpoint = bundle.checkpoint
    target = bundle.target
    return "\n".join(
        [
            "- monitor_target_id: `%s`" % run["monitor_target_id"],
            "- company/event: `%s` / `%s`" % (target.get("company_id") or "none", target.get("earnings_event_id") or "none"),
            "- monitor_run_id: `%s`" % run["monitor_run_id"],
            "- detected_at: `%s`" % run["finished_at"],
            "- run_result: `%s`" % run["run_result"],
            "- target_state: `%s`" % checkpoint["target_state"],
            "- what_changed_or_error: %s" % summary,
            "- source_url: %s" % target["source_url"],
            "- confidence: `metadata_only`",
            "- requires_human_decision: `true`",
            "- recommended_next_action: %s" % recommended,
            "- dedup_key: `%s`" % dedup_key,
            "",
            "This notification is not formal evidence and does not change event or baseline state.",
        ]
    )
