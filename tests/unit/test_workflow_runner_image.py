"""patch まで固定した Python を入れる job は、runner image も固定していること（ERS-ADR-0083）。

`ubuntu-latest` は GitHub が指す先を変える名前である。2026-11-15 に 24.04 から 26.04 へ移り、
固定していた Python 3.11.9 のビルドが 26.04 向けに無かったため、level2_monitor.yml の全 job が
setup-python で止まった。失敗を Issue に書く job も同じ場所で止まり、何も書かれなかった。

interpreter を patch まで固定するなら、それが載る image も固定する。片方だけの固定は、
もう片方が動いたときに外れる。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# 3.11.9 のビルドがあると確かめた image。上げるときは、上げた先に固定した patch があることを
# 確かめ、無ければ patch と一緒に上げて、ここも直す。
PINNED_IMAGE = "ubuntu-24.04"


def _jobs_installing_an_exact_python() -> list[tuple[str, str, object, str]]:
    found = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in parsed["jobs"].items():
            for step in job.get("steps", []):
                if "actions/setup-python@" not in str(step.get("uses", "")):
                    continue
                version = str((step.get("with") or {}).get("python-version", ""))
                if EXACT_VERSION.match(version):
                    found.append((path.name, job_name, job.get("runs-on"), version))
    return found


def test_the_check_below_is_looking_at_something():
    # 該当する job が見つからなければ、下の検査は何も見ずに通る。workflow の書き方が変わって
    # 走査から漏れたときに、緑のまま無意味になるのを防ぐ。
    found = {(workflow, job) for workflow, job, _, _ in _jobs_installing_an_exact_python()}
    assert found == {
        ("checks.yml", "checks"),
        ("level2_monitor.yml", "plan"),
        ("level2_monitor.yml", "monitor"),
        ("level2_monitor.yml", "report-pipeline-failure"),
    }


def test_a_job_that_installs_an_exact_python_runs_on_a_pinned_image():
    for workflow, job, runs_on, version in _jobs_installing_an_exact_python():
        where = f"{workflow}:{job} (python {version})"
        assert isinstance(runs_on, str), f"{where}: runs-on は1つの名前で書く ({runs_on!r})"
        assert not runs_on.endswith("-latest"), f"{where}: {runs_on} は GitHub が指す先を変える"
        assert runs_on == PINNED_IMAGE, f"{where}: {runs_on}"
