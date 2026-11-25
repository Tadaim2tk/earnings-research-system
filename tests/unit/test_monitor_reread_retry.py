"""Level 2 Monitor: 上げた直後の state 成果物の再取得を、上限つきでやり直す（ERS-ADR-0085）。

2026-11-23 と 2026-11-24 の夜、monitor job（ICECO_TDNET_INDEX）の「Re-download uploaded artifact」が
`Unable to download artifact(s): Artifact not found for name: ...` で落ちた。成果物はその 0.1〜0.4 秒前に
上げ終わっていて、あとから一覧を見れば在る。再取得が落ちると、続く通知は束を読めずに止まり、
「Preserve notification receipt」と「Surface exhausted notification retry」も赤になる。

再取得は GitHub Actions の step の条件（`if`・`continue-on-error`・`outcome`）で組んであり、手元では
動かせない。ここでは monitor job の step を workflow からそのまま読み、GitHub の文書にある step の規則だけを
小さく写した模型の上で、場面ごとに「どの step が走り、job がどう終わるか」を確かめる。

模型が写している規則:

- `if` に状態の関数（`always()`・`failure()`・`success()`・`cancelled()`）が無ければ、先頭に `success()` が付く。
- `success()` は、それまでの step が1つも job を失敗させていないこと。`failure()` はその逆。
- `continue-on-error: true` の step は、失敗しても job を失敗させない。`steps.<id>.outcome` には、その扱いを
  する前の結果（`failure`）が残る。
- 走らなかった step の `outcome` は `skipped`。

模型は本物の runner ではない。規則の読み違いが無いことは、直す前の形に戻した job に 11/24 の場面を当て、
実際の run 45419480723 と同じ3つの step が赤になることで確かめている（下の「模型の検算」）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "level2_monitor.yml"
DOWNLOAD = "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
REREAD_DIR = ".monitor/reread"
STATUS_FUNCTIONS = ("always()", "failure()", "success()", "cancelled()")

# 1回の再取得の結果。
FOUND = "found"            # 取れた（束が全部そろう）
NOT_FOUND = "not_found"    # 一覧に出ていない（何も書かれない）。11/23・11/24 に起きた形
PARTIAL = "partial"        # 途中まで書いて落ちた


def monitor_steps() -> List[dict]:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return parsed["jobs"]["monitor"]["steps"]


def key(step: dict) -> str:
    return step.get("id") or step.get("name") or step.get("uses") or step["run"]


def _to_python(expression: str) -> str:
    text = expression.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    text = re.sub(r"steps\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)", r"output('\1', '\2')", text)
    text = re.sub(r"steps\.([A-Za-z0-9_-]+)\.outcome", r"outcome('\1')", text)
    text = text.replace("always()", "True").replace("failure()", "failed")
    text = text.replace("success()", "(not failed)").replace("cancelled()", "False")
    return text.replace("&&", " and ").replace("||", " or ")


class Job:
    """monitor job を1回ぶん走らせた結果。"""

    def __init__(
        self,
        steps: List[dict],
        *,
        downloads: Iterable[str] = (),
        due: str = "true",
        upload_ok: bool = True,
        run_monitor_ok: bool = True,
    ):
        self.steps = steps
        self.downloads = list(downloads)
        self.due = due
        self.upload_ok = upload_ok
        self.run_monitor_ok = run_monitor_ok
        self.failed = False
        self.outcomes: Dict[str, str] = {}
        self.outputs: Dict[tuple, str] = {}
        self.ran: List[str] = []
        self.red: List[str] = []          # outcome が failure の step（continue-on-error を含む）
        self.reread: Optional[str] = None  # .monitor/reread の中身: None / FOUND / PARTIAL
        self.receipt = False
        self.download_attempts = 0
        self.waited: List[int] = []
        self.reason = ""
        for step in steps:
            self._step(step)

    # ---- GitHub Actions の規則
    def evaluate(self, expression: str):
        names = {
            "failed": self.failed,
            "True": True,
            "False": False,
            "output": lambda step_id, name: self.outputs.get((step_id, name), ""),
            "outcome": lambda step_id: self.outcomes.get(step_id, ""),
        }
        # 模型が知らない書き方（needs.・github.・関数）が条件に入ったら、ここで NameError になる。
        # そのときは模型を直す（黙って True や False に倒さない）。
        return eval(_to_python(expression), {"__builtins__": {}}, names)  # この workflow の条件式だけを評価する

    def _should_run(self, step: dict) -> bool:
        condition = step.get("if")
        if condition is None:
            return not self.failed
        result = bool(self.evaluate(str(condition)))
        if not any(function in str(condition) for function in STATUS_FUNCTIONS):
            result = (not self.failed) and result
        return result

    def _step(self, step: dict) -> None:
        name = key(step)
        if not self._should_run(step):
            outcome = "skipped"
        else:
            self.ran.append(name)
            outcome = "success" if self._effect(step) else "failure"
            if outcome == "failure":
                self.red.append(name)
                if not step.get("continue-on-error"):
                    self.failed = True
        if step.get("id"):
            self.outcomes[step["id"]] = outcome

    # ---- この job の step が、何に依存して成功・失敗するか
    def _effect(self, step: dict) -> bool:
        run = str(step.get("run", ""))
        uses = str(step.get("uses", ""))
        step_id = step.get("id", "")
        if step_id == "recheck":
            self.outputs[("recheck", "due")] = self.due
            return True
        if step_id == "run-monitor":
            return self.run_monitor_ok
        if step_id == "upload":
            return self.upload_ok
        if uses.startswith("actions/download-artifact@"):
            result = self.downloads[self.download_attempts] if self.download_attempts < len(self.downloads) else FOUND
            self.download_attempts += 1
            if result == FOUND:
                self.reread = FOUND
            elif result == PARTIAL:
                self.reread = PARTIAL
            return result == FOUND
        if "rm -rf " + REREAD_DIR in run:
            self.reread = None
        for seconds in re.findall(r"^\s*sleep (\d+)\s*$", run, flags=re.MULTILINE):
            self.waited.append(int(seconds))
        if run.strip() == "exit 1":
            return False
        if step_id == "handoff":
            self.outputs[("handoff", "required")] = "false"
            return self.reread == FOUND
        if step_id == "notify":
            # 束を読めなければ通知は組み立てられない（monitor state bundle directory is unavailable）。
            self.receipt = self.reread == FOUND
            return self.receipt
        if step.get("name") == "Preserve notification receipt":
            return self.receipt  # if-no-files-found: error
        if step_id == "failure-notice":
            self.reason = str(self.evaluate(step["env"]["REASON"]))
            return True
        if "monitor-verify-bundle " + REREAD_DIR in run:
            return self.reread == FOUND
        return True


def attempts(steps: List[dict]) -> List[dict]:
    return [step for step in steps if str(step.get("uses", "")).startswith("actions/download-artifact@")]


def waits(steps: List[dict]) -> List[dict]:
    return [step for step in steps if re.search(r"^\s*sleep \d+\s*$", str(step.get("run", "")), flags=re.MULTILINE)]


def without_retry(steps: List[dict]) -> List[dict]:
    """直す前の形: 再取得は1回だけで、落ちたら job が落ちる。"""
    first, *later = attempts(steps)
    removed = {id(step) for step in later} | {id(step) for step in waits(steps)}
    restored = []
    for step in steps:
        if id(step) in removed:
            continue
        if step is first:
            step = {name: value for name, value in step.items() if name not in ("id", "continue-on-error")}
        restored.append(step)
    return restored


# --------------------------------------------------------------------------- 模型の検算
def test_the_model_reproduces_the_run_that_failed_on_2026_11_24():
    """直す前の形に 11/24 の場面（上げ終えた直後に探して、見つからない）を当てる。

    実際の run 45419480723 で赤になった step は、Re-download uploaded artifact・Preserve notification
    receipt・Surface exhausted notification retry の3つで、通知の step は失敗（continue-on-error）、
    workflow failure の理由は notification_failed だった。模型が同じ結果を出すことを確かめる。
    """
    job = Job(without_retry(monitor_steps()), downloads=[NOT_FOUND])
    assert job.failed
    assert job.red == [
        "Re-download uploaded artifact",
        "notify",
        "Preserve notification receipt",
        "Surface exhausted notification retry",
    ]
    assert job.outcomes["notify"] == "failure"
    assert "Verify re-downloaded committed state" not in job.ran
    assert "failure-notice" in job.ran and job.reason == "notification_failed"


def test_before_the_change_a_listing_that_was_not_ready_was_never_asked_again():
    job = Job(without_retry(monitor_steps()), downloads=[NOT_FOUND, FOUND])
    assert job.download_attempts == 1 and job.failed


# --------------------------------------------------------------------------- やり直し
def test_a_first_attempt_that_finds_the_artifact_waits_for_nothing():
    job = Job(monitor_steps(), downloads=[FOUND])
    assert not job.failed and job.red == []
    assert job.download_attempts == 1 and job.waited == []
    assert "Verify re-downloaded committed state" in job.ran
    assert job.outcomes["notify"] == "success" and "failure-notice" not in job.ran


def test_a_listing_that_is_not_ready_yet_is_asked_again_and_the_run_goes_on():
    """11/23・11/24 の形。1回目は見つからず、待ってからの2回目で取れる。job は落ちず、通知まで進む。"""
    job = Job(monitor_steps(), downloads=[NOT_FOUND, FOUND])
    assert not job.failed
    assert job.download_attempts == 2 and job.waited == [10]
    assert job.red == ["reread"]                     # 1回目が赤だったことは、実行の記録に残る
    assert "Verify re-downloaded committed state" in job.ran
    assert job.outcomes["notify"] == "success"
    assert "Surface exhausted notification retry" not in job.ran
    assert "failure-notice" not in job.ran


def test_a_second_miss_gets_one_more_attempt_after_a_longer_wait():
    job = Job(monitor_steps(), downloads=[NOT_FOUND, NOT_FOUND, FOUND])
    assert not job.failed
    assert job.download_attempts == 3 and job.waited == [10, 30]
    assert job.outcomes["notify"] == "success" and "failure-notice" not in job.ran


def test_three_misses_end_the_job_the_way_one_miss_used_to():
    """上限まで取れなければ、今までどおり赤。束を読めないので通知は出ず、workflow failure の通知が代わりに出る。"""
    job = Job(monitor_steps(), downloads=[NOT_FOUND, NOT_FOUND, NOT_FOUND, FOUND])
    assert job.failed
    assert job.download_attempts == 3                # 4回目は無い
    assert job.waited == [10, 30]
    assert "Verify re-downloaded committed state" not in job.ran
    assert "handoff" not in job.ran
    assert job.outcomes["notify"] == "failure"
    assert job.red[-3:] == ["notify", "Preserve notification receipt", "Surface exhausted notification retry"]
    # 直す前と同じ理由で届く。「Issue 配信が3回失敗した」という文面は、この場面には合っていない
    # （配信は試みていない）。文面は変えていない。docs/OPEN_QUESTIONS.md に残した。
    assert "failure-notice" in job.ran and job.reason == "notification_failed"
    before = Job(without_retry(monitor_steps()), downloads=[NOT_FOUND])
    assert job.red[-3:] == before.red[-3:] and job.reason == before.reason


def test_a_download_that_stopped_halfway_does_not_stand_in_for_the_bundle():
    """途中まで落ちた試行のあと、次の試行で取れれば進む。最後まで取れなければ、残りものでは進まない。"""
    recovered = Job(monitor_steps(), downloads=[PARTIAL, FOUND])
    assert not recovered.failed and recovered.outcomes["notify"] == "success"
    exhausted = Job(monitor_steps(), downloads=[PARTIAL, NOT_FOUND, NOT_FOUND])
    assert exhausted.failed and exhausted.outcomes["notify"] == "failure"
    assert exhausted.reread is None                  # 途中まで落ちたものは、やり直す前に消している
    left_behind = Job(monitor_steps(), downloads=[NOT_FOUND, NOT_FOUND, PARTIAL])
    assert left_behind.failed and left_behind.outcomes["notify"] == "failure"


def test_an_upload_that_failed_is_not_re_downloaded():
    job = Job(monitor_steps(), upload_ok=False)
    assert job.failed and job.download_attempts == 0 and job.waited == []
    assert job.red[0] == "upload"


def test_a_target_that_is_not_due_downloads_nothing():
    job = Job(monitor_steps(), due="false")
    assert not job.failed and job.download_attempts == 0 and job.waited == []
    assert job.outcomes["notify"] == "skipped"


def test_a_monitor_step_that_failed_still_reports_no_bundle():
    """束を作る前に落ちた場合の経路は、やり直しを入れても変わらない。"""
    job = Job(monitor_steps(), run_monitor_ok=False)
    assert job.failed and job.download_attempts == 0
    assert job.outcomes["notify"] == "skipped"
    assert "failure-notice" in job.ran and job.reason == "no_bundle"


# --------------------------------------------------------------------------- workflow の形
def test_every_attempt_asks_for_the_same_artifact_with_the_same_pinned_action():
    steps = monitor_steps()
    tries = attempts(steps)
    assert [key(step) for step in tries] == [
        "reread",
        "reread-second",
        "Re-download uploaded artifact (last attempt)",
    ]
    for step in tries:
        assert step["uses"] == DOWNLOAD
        assert step["with"] == {"name": "${{ steps.run-monitor.outputs.artifact_name }}", "path": REREAD_DIR}
    assert tries[0]["name"] == "Re-download uploaded artifact"
    # 1回目と2回目は、落ちても job を落とさない。最後の試行は、落ちたらそのまま job が落ちる。
    assert [step.get("continue-on-error", False) for step in tries] == [True, True, False]
    # 1回目は、束を作る側のほかの手順と同じく due の再確認に従う。やり直しは、前の試行が落ちたときだけ。
    assert tries[0]["if"] == "steps.recheck.outputs.due == 'true'"
    assert tries[1]["if"] == "steps.reread.outcome == 'failure'"
    assert tries[2]["if"] == "steps.reread-second.outcome == 'failure'"


def test_the_waits_are_bounded_and_start_each_attempt_from_an_empty_directory():
    steps = monitor_steps()
    pauses = waits(steps)
    tries = attempts(steps)
    assert len(pauses) == 2
    assert [pause["if"] for pause in pauses] == [tries[1]["if"], tries[2]["if"]]
    seconds = [int(re.search(r"^\s*sleep (\d+)\s*$", pause["run"], flags=re.MULTILINE).group(1)) for pause in pauses]
    assert seconds == [10, 30]
    # 待ちの合計は job の制限時間（10分）よりずっと短い。target ごとの並び（concurrency）を長く塞がない。
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["monitor"]
    assert sum(seconds) <= 60 and job["timeout-minutes"] == 10
    for pause in pauses:
        lines = [line.strip() for line in pause["run"].splitlines() if line.strip()]
        assert lines.index("rm -rf " + REREAD_DIR) < lines.index([line for line in lines if line.startswith("sleep ")][0])
        assert "continue-on-error" not in pause
    # ほかの場所では待たない（待ちが増えていたら、上限の見積もりをやり直す）。
    assert len([step for step in steps if "sleep" in str(step.get("run", ""))]) == 2


def test_the_attempts_sit_between_the_upload_and_the_verification():
    order = [key(step) for step in monitor_steps()]
    sequence = [
        "upload",
        "reread",
        "Wait before the second re-download",
        "reread-second",
        "Wait before the last re-download",
        "Re-download uploaded artifact (last attempt)",
        "Verify re-downloaded committed state",
        "handoff",
    ]
    positions = [order.index(name) for name in sequence]
    assert positions == list(range(positions[0], positions[0] + len(sequence)))


def test_a_retry_leaves_a_warning_on_the_run():
    """やり直しが起きた回は緑で終わる。起きたこと自体は、実行の注記（warning）に残す。"""
    first, second = waits(monitor_steps())
    assert "::warning::" in first["run"] and "attempt 1 of 3" in first["run"]
    assert "::warning::" in second["run"] and "attempt 2 of 3" in second["run"]


def test_the_notification_steps_are_untouched():
    """通知・受領の保存・再試行の使い切りの3手順は、条件を一字も変えていない。"""
    steps = {key(step): step for step in monitor_steps()}
    assert steps["notify"]["if"] == "always() && steps.run-monitor.outcome == 'success'"
    assert steps["notify"]["continue-on-error"] is True
    assert REREAD_DIR in steps["notify"]["run"]
    assert steps["Preserve notification receipt"]["if"] == "always() && steps.notify.outcome != 'skipped'"
    assert steps["Preserve notification receipt"]["with"]["if-no-files-found"] == "error"
    assert steps["Surface exhausted notification retry"]["if"] == "always() && steps.notify.outcome == 'failure'"
    assert steps["Surface exhausted notification retry"]["run"] == "exit 1"
    assert steps["failure-notice"]["if"] == "failure() && steps.notify.outcome != 'success'"
    assert steps["Verify re-downloaded committed state"]["if"] == "steps.recheck.outputs.due == 'true'"
