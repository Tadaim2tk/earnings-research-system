"""launchd が呼ぶ wrapper。**失敗が launchd まで伝わることを確かめる。**

中括弧の終了コードは最後のコマンド（`echo`）のものになる。そのままだと、
取り残しや失敗があっても launchd は成功として記録し、31日で消える開示が
取られないまま誰にも見えない。

最初の修正は `status=$?` と書いていた。**`status` は zsh の読み取り専用変数
（`$?` の別名）なので代入が黙って失敗し、直したつもりで直っていなかった。**
文言ではなく、実際に走らせて確かめる。
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "tools/launchd/capture.sh"


def run_wrapper(tmp_path, exit_code):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "x"],
                   cwd=repo, check=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    stub = tmp_path / "stub.py"
    stub.write_text("import sys\nprint('stub')\nsys.exit(%d)\n" % exit_code, encoding="utf-8")
    result = subprocess.run(
        [shutil.which("zsh") or "/bin/zsh", str(WRAPPER)],
        capture_output=True, text=True,
        env={**os.environ,
             "ERS_REPO": str(repo),
             "ERS_LOG": str(tmp_path / "capture.log"),
             "ERS_PYTHON": shutil.which("python3") or "python3",
             "ERS_CAPTURE": str(stub)})
    return result, tmp_path / "capture.log"


@pytest.mark.parametrize("code", [0, 1, 3])
def test_the_capture_status_reaches_the_scheduler(tmp_path, code):
    """緑は「全部取れた」以外を意味してはいけない。"""
    result, log = run_wrapper(tmp_path, code)
    assert result.returncode == code, result.stderr
    assert "exit=%d" % code in log.read_text(encoding="utf-8")


def test_the_wrapper_does_not_assign_to_a_read_only_shell_variable(tmp_path):
    """`status` への代入は zsh で失敗する。走らせれば stderr に出る。"""
    result, _ = run_wrapper(tmp_path, 0)
    assert "read-only variable" not in result.stderr, result.stderr


def test_a_missing_clone_is_reported_and_not_silently_skipped(tmp_path):
    result = subprocess.run(
        [shutil.which("zsh") or "/bin/zsh", str(WRAPPER)],
        capture_output=True, text=True,
        env={**os.environ,
             "ERS_REPO": str(tmp_path / "absent"),
             "ERS_LOG": str(tmp_path / "capture.log"),
             "ERS_PYTHON": shutil.which("python3") or "python3",
             "ERS_CAPTURE": str(tmp_path / "absent/x.py")})
    assert result.returncode != 0
    assert "clone が無い" in (tmp_path / "capture.log").read_text(encoding="utf-8")
