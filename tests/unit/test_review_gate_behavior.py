"""Codex review gate を、実物の手順を走らせて確かめる（ERS-ADR-0084）。

`test_review_gate_workflow.py` は workflow の文字列を見る。それだけでは、二つの読み違いを
どちらも止められなかった。

- **「指摘なし」を読めていなかった。** PR を開いたときの自動レビューは、指摘が無ければ要約
  コメントを書き換えるだけで、ゲートが探していた `Reviewed commit` のコメントは付かない。
  PR #89 は Codex が1分24秒で読み終えていたのに、ゲートは20分待って `no-review PR` で通した。
- **ゲートが書く依頼は、Codex に読まれていなかった。** PR #82 で8回書いて8回とも
  「Codex のアカウントを作って接続してください」と返されている。

ここでは YAML から手順（`run`）と jq の式を取り出し、`gh` と `sleep` だけを偽物に差し替えて
そのまま bash で走らせる。偽の `gh` は、手順が渡した `--jq` の式を**そのまま**本物の jq に
通して fixture に当てるので、手順の中の述語（レビューの数え方、受領コメントの数え方、未解決
スレッドの数え方）も実際に動く。見るのは終了コードと、手順が言ったこと。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github" / "workflows" / "pr_review_gate.yml"
HEAD = "e7fea6fe653cd81a9dcb9a7b2571cc270ab1fff6"
OTHER = "f" * 40
PUSHED_AT = "2026-11-24T13:32:06Z"
CODEX = {"login": "chatgpt-codex-connector[bot]", "type": "Bot"}
OWNER = {"login": "someone", "type": "User"}
JQ = shutil.which("jq")
BASH = shutil.which("bash")



@pytest.fixture(autouse=True)
def _the_tools_these_tests_need():
    """手元に jq か bash が無ければ skip する。**CI では skip にしない。**

    CI で道具が無くなったとき、このファイルが丸ごと skip されて緑になると、下の検査は何も
    見ていないのに「通った」ことになる。
    """
    if JQ is not None and BASH is not None:
        return
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail("CI に jq か bash が無い。このファイルの検査は何も見ていない")
    pytest.skip("jq と bash が要る")


def _job() -> dict:
    return yaml.safe_load(GATE.read_text(encoding="utf-8"))["jobs"]["wait-for-codex-review"]


def _step() -> dict:
    steps = [s for s in _job()["steps"] if s.get("name", "").startswith("Wait for Codex")]
    assert len(steps) == 1
    return steps[0]


# --------------------------------------------------------------------------- fixture の形
def _summary(sha: str, status, findings, user: dict = CODEX) -> dict:
    """Codex の要約コメント（2026-11 の実物と同じ形。PR #89 のものを写した）。"""
    state = {
        "code_review": {
            "commit_sha": sha,
            "has_any_findings": findings,
            "has_unresolved_findings": findings,
            "status": status,
        },
        "security_review": {
            "commit_sha": None,
            "has_any_findings": None,
            "has_unresolved_findings": None,
            "status": None,
        },
    }
    body = (
        "<!-- codex-pull-request-review-summary -->\n"
        "<!-- codex-review-state:v1 %s -->\n\n<details>\n"
        "<summary><strong>Codex Review Summary</strong>: ✅ Completed</summary>\n\n"
        "| Review | Status | Commit | Review trigger |\n| --- | --- | --- | --- |\n"
        "| 📝 **Code Review** | ✅ **Completed** | `%s` | PR opened |\n</details>\n"
        % (json.dumps(state, separators=(",", ":")), sha[:7])
    )
    return {"user": user, "body": body, "created_at": "2026-11-17T12:23:17Z"}


def _receipt(sha: str, user: dict = CODEX) -> dict:
    """コメントで依頼したレビューが指摘なしで終わったときに付く、受領のコメント。"""
    body = (
        "<!-- codex-review-receipt:v1 -->\n\nCodex Review: Didn't find any major issues. Breezy!\n\n"
        "**Reviewed commit:** `%s`\n" % sha[:10]
    )
    return {"user": user, "body": body, "created_at": "2026-11-24T13:33:49Z"}


def _request(created_at: str, user: dict = OWNER, body: str = "@codex review", association: str = "OWNER") -> dict:
    return {"user": user, "body": body, "created_at": created_at, "author_association": association}


def _review(sha: str, login: str = CODEX["login"]) -> dict:
    return {"user": {"login": login}, "commit_id": sha, "state": "COMMENTED"}


def _thread(resolved: bool, login: str = "chatgpt-codex-connector") -> dict:
    return {"isResolved": resolved, "comments": {"nodes": [{"author": {"login": login}}]}}


def _finding_comments(threads, sha: str) -> list:
    """指摘スレッドの最初のコメントを、REST の行コメントの形で返す（Codex のものだけ。解決済みも含む）。

    Codex の指摘は、レビューした commit への行コメントとして付く。GraphQL のスレッドと REST の
    行コメントは同じものを別の口から見ているので、fixture でも片方からもう片方を作る。
    """
    return [
        {"user": {"login": CODEX["login"]}, "original_commit_id": sha}
        for thread in threads
        if thread["comments"]["nodes"][0]["author"]["login"].startswith("chatgpt-codex-connector")
    ]


def _apply(filter_name: str, pages, **args: str) -> str:
    """job の env にある jq の式を、実物の文字列のまま jq に渡す。pages はページごとの配列。"""
    stdin = "\n".join(json.dumps(page) for page in pages)
    command = [JQ, "-rs"]
    for key, value in args.items():
        command += ["--arg", key, value]
    out = subprocess.run(
        command + [_job()["env"][filter_name]], input=stdin, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


# --------------------------------------------------------------------------- 要約コメントの読み方
def test_summary_for_the_current_head_is_read_as_clean_findings_or_running():
    def state(pages):
        return _apply("SUMMARY_FILTER", pages, head=HEAD)

    assert state([[_summary(HEAD, "completed", False)]]) == "clean"
    assert state([[_summary(HEAD, "completed", True)]]) == "findings"
    assert state([[_summary(HEAD, "running", None)]]) == "running"
    assert state([[_summary(HEAD, "queued", None)]]) == "running"
    # 結論が無いものを clean にしない
    assert state([[_summary(HEAD, "completed", None)]]) == "running"
    assert state([[_summary(HEAD, "failed", False)]]) == "running"


def test_summary_that_does_not_speak_for_this_head_or_this_bot_is_none():
    def state(pages):
        return _apply("SUMMARY_FILTER", pages, head=HEAD)

    assert state([[]]) == "none"
    assert state([]) == "none"  # コメントが1ページも無い
    assert state([[_summary(OTHER, "completed", False)]]) == "none"  # 別の commit のレビュー
    assert state([[_summary(HEAD[:7], "completed", False)]]) == "none"  # 短い SHA は一致としない
    # Bot の login を名乗る人のアカウント、別の Bot。どちらも Codex の結論ではない。
    person = {"login": "chatgpt-codex-connector[bot]", "type": "User"}
    assert state([[_summary(HEAD, "completed", False, user=person)]]) == "none"
    actions = {"login": "github-actions[bot]", "type": "Bot"}
    assert state([[_summary(HEAD, "completed", False, user=actions)]]) == "none"
    # 目印の無いコメント、JSON が壊れた要約、JSON の形が違う要約
    quoted = {
        "user": CODEX,
        "body": 'codex-review-state:v1 {"code_review":{"commit_sha":"%s","has_any_findings":false,'
        '"status":"completed"}} -->' % HEAD,
    }
    assert state([[quoted]]) == "none"
    broken = {
        "user": CODEX,
        "body": '<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 {"code_review": -->',
    }
    assert state([[broken]]) == "none"
    odd = {
        "user": CODEX,
        "body": "<!-- codex-pull-request-review-summary -->\n"
        '<!-- codex-review-state:v1 {"code_review":"completed"} -->',
    }
    assert state([[odd]]) == "none"
    assert state([[{"user": None, "body": None}]]) == "none"


def test_summary_is_found_on_a_later_page_and_findings_win_over_clean():
    def state(pages):
        return _apply("SUMMARY_FILTER", pages, head=HEAD)

    filler = [{"user": OWNER, "body": "x"}] * 3
    assert state([filler, [_summary(HEAD, "completed", False)]]) == "clean"
    both = [[_summary(HEAD, "completed", False)], [_summary(HEAD, "completed", True)]]
    assert state(both) == "findings"


# --------------------------------------------------------------------------- 依頼の数え方
def test_only_a_request_a_person_wrote_after_the_push_counts():
    def count(pages):
        return _apply("REQUEST_FILTER", pages, since=PUSHED_AT)

    assert count([[_request("2026-11-24T13:32:10Z")]]) == "1"
    assert count([[_request(PUSHED_AT)]]) == "1"  # push と同じ秒は、push より後として数える
    assert count([[_request("2026-11-24T13:32:10Z", body="  @Codex   Review please")]]) == "1"
    assert count([[_request("2026-11-24T13:32:05Z")]]) == "0"  # push より前。前の head への依頼
    # このゲートがかつて書いていた依頼。Codex は読まないので、頼んだことにしない。
    actions = {"login": "github-actions[bot]", "type": "Bot"}
    assert count([[_request("2026-11-24T13:32:10Z", user=actions)]]) == "0"
    # 文中で触れただけのもの、依頼ではない Codex 宛ての指示
    mention = "説明の中で @codex review に触れただけ"
    assert count([[_request("2026-11-24T13:32:10Z", body=mention)]]) == "0"
    assert count([[_request("2026-11-24T13:32:10Z", body="@codex fix this")]]) == "0"
    # リポジトリの外の人の依頼。public repository の PR には誰でも書ける。
    for outsider in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", ""):
        assert count([[_request("2026-11-24T13:32:10Z", association=outsider)]]) == "0", outsider
    for insider in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert count([[_request("2026-11-24T13:32:10Z", association=insider)]]) == "1", insider
    assert count([[], [_request("2026-11-24T13:40:00Z")], [_request("2026-11-24T13:41:00Z")]]) == "2"
    assert count([]) == "0"
    assert count([[{"user": None, "body": None, "created_at": None}]]) == "0"


# --------------------------------------------------------------------------- 手順をそのまま走らせる
GH_STUB = r"""# 偽の gh。答えは $GATE_FIXTURES の fixture から作る。手順が `--jq` で渡した式は、そのまま本物の
# jq（$REAL_JQ）に通す。本物の gh は --paginate のとき式をページごとに当てるので、同じようにする。
filter=""
prev=""
for a in "$@"; do
  if [ "$prev" = "--jq" ]; then filter="$a"; fi
  prev="$a"
done
args="$*"

pages() {  # $1: ページの並び（配列の配列）。式があればページごとに当て、無ければページをそのまま出す
  if [ -n "$filter" ]; then
    "$REAL_JQ" -r ".[] | ($filter)" "$1"
  else
    "$REAL_JQ" -c '.[]' "$1"
  fi
}

number() {  # $1: ファイル。中の数を返す（無ければ 0）。cat を起こさない
  n=0
  if [ -f "$1" ]; then read -r n < "$1"; fi
  echo "$n"
}

late() {  # $1: fixture の名前、$2: いま何周目か。後から変わる fixture があり、その周回に達していれば、そちらを返す
  from=$(number "$GATE_FIXTURES/$1_late_from")
  if [ "$from" -eq 0 ]; then from=$(number "$GATE_FIXTURES/late_from"); fi
  if [ "$from" -gt 0 ] && [ "$2" -ge "$from" ] && [ -f "$GATE_FIXTURES/$1_late.json" ]; then
    echo "$GATE_FIXTURES/$1_late.json"
  else
    echo "$GATE_FIXTURES/$1.json"
  fi
}

tick() {  # $1: 数える名前。呼ばれた回数（= 周回の番号）を進めて返す
  n=$(( $(number "$GATE_FIXTURES/$1.calls") + 1 ))
  echo "$n" > "$GATE_FIXTURES/$1.calls"
  echo "$n"
}

case "$args" in
  *"-f body="*|"pr comment"*|"pr review"*|"issue comment"*|*"-X POST"*|*"--method POST"*|*"-X PATCH"*|*"-X DELETE"*)
    # このゲートは PR に何も書かない。書こうとしたら、その試験を落とす。
    printf '%s\n' "$args" >> "$GATE_FIXTURES/writes.txt"
    echo "the gate must not write to the pull request: $args" >&2
    exit 9 ;;
  "api graphql"*)
    # 手順は周回の最初にレビューを数えるので、その回数がいまの周回の番号になる。
    poll=$(number "$GATE_FIXTURES/reviews.calls")
    file=$(late graphql "$poll")
    [ -f "$file" ] || exit 1
    "$REAL_JQ" -r "$filter" "$file"
    exit $? ;;
  *"/pulls/"*"/reviews"*)
    calls=$(tick reviews)
    fail_from=$(number "$GATE_FIXTURES/reviews_fail_from")
    if [ "$fail_from" -gt 0 ] && [ "$calls" -ge "$fail_from" ]; then exit 1; fi
    pages "$(late reviews "$calls")"
    exit 0 ;;
  *"/pulls/"*"/comments"*)
    # 行に付いたコメント（指摘）。issue のコメントとは別の取得口。
    calls=$(tick review_comments)
    fail_from=$(number "$GATE_FIXTURES/review_comments_fail_from")
    if [ "$fail_from" -gt 0 ] && [ "$calls" -ge "$fail_from" ]; then exit 1; fi
    fail_until=$(number "$GATE_FIXTURES/review_comments_fail_until")
    if [ "$calls" -le "$fail_until" ]; then exit 1; fi
    pages "$(late review_comments "$calls")"
    exit 0 ;;
  *"/issues/"*"/comments"*)
    # 手順は周回ごとに、式つき（受領コメントを数える）と式なし（要約を読む）を1回ずつ呼ぶ。別々に数える。
    if [ -n "$filter" ]; then kind=comments_jq; else kind=comments_raw; fi
    calls=$(tick "$kind")
    fail_from=$(number "$GATE_FIXTURES/comments_fail_from")
    if [ "$fail_from" -gt 0 ] && [ "$calls" -ge "$fail_from" ]; then exit 1; fi
    # 要約を読む側（式なし）だけが失敗する場面。受領コメントを数える側（式つき）は通る。
    fail_from=$(number "$GATE_FIXTURES/${kind}_fail_from")
    if [ "$fail_from" -gt 0 ] && [ "$calls" -ge "$fail_from" ]; then exit 1; fi
    # 最初の何回かだけ失敗して、あとから読めるようになる場面。
    fail_until=$(number "$GATE_FIXTURES/${kind}_fail_until")
    if [ "$calls" -le "$fail_until" ]; then exit 1; fi
    pages "$(late comments "$calls")"
    exit 0 ;;
esac
echo "unexpected gh call: $args" >&2
exit 9
"""


# 手順は `seq 1 40` で40回、30秒おきに見る（20分）。試験では回数を縮める。sleep を偽物にするのと同じで、
# 縮めるのは時間であって、周回の中身と、時間切れのあとの判断はそのまま走る。
POLLS = 3
SEQ_STUB = """# 偽の seq。`seq 1 40` を `seq 1 $GATE_POLLS` に縮める。ほかの呼び方は想定していない。
if [ "$*" != "1 40" ]; then echo "unexpected seq call: $*" >&2; exit 9; fi
i=1
while [ "$i" -le "$GATE_POLLS" ]; do echo "$i"; i=$((i + 1)); done
"""


class Run:
    def __init__(self, out: subprocess.CompletedProcess, fixtures: Path, summary: Path):
        self.code = out.returncode
        self.said = out.stdout + out.stderr
        self.summary = summary.read_text(encoding="utf-8") if summary.exists() else ""
        writes = fixtures / "writes.txt"
        self.writes = writes.read_text(encoding="utf-8") if writes.exists() else ""

    def polls(self) -> int:
        return self.said.count("/40)")


def _run_gate(
    where: Path,
    *,
    event: str = "opened",
    draft: bool = False,
    reviews=(),
    comments=(),
    threads=(),
    graphql_fails: bool = False,
    finding_comments=None,
    comments_fail_from: int = 0,
    summary_fail_from: int = 0,
    summary_fail_until: int = 0,
    reviews_fail_from: int = 0,
    late_from: int = 0,
    late_comments=None,
    late_reviews=None,
    late_threads=None,
    late_threads_from: int = 0,
    late_finding_comments=None,
    finding_comments_fail_until: int = 0,
    broken_jq: bool = False,
    polls: int | None = POLLS,
    head: str = HEAD,
    pushed_at: str = PUSHED_AT,
) -> Run:
    """ゲートの手順を走らせる。

    reviews / comments: API が返す中身（1ページぶん）。threads: PR の指摘スレッド。
    finding_comments: この PR の行コメント。渡さなければ、threads のうち Codex のものが、いまの head に
    付いているものとして作る。
    graphql_fails: スレッドの取得が失敗する。
    comments_fail_from=N / reviews_fail_from=N: N 回目以降の取得が失敗する（周回ごとに1回ずつ呼ぶ。
    時間切れのあとの依頼の読み取りは、コメントの polls+1 回目）。
    summary_fail_from=N: 要約を読む取得だけが N 回目以降失敗する。受領コメントを数える取得は通る。
    summary_fail_until=N: 要約を読む取得だけが N 回目まで失敗し、そのあとは読める。
    late_from=N, late_comments / late_reviews / late_threads: N 周目以降は、渡したものへ差し替える
    （Codex が読み終えた、新しい指摘が見えるようになった、などの場面）。渡さなかったものは変わらない。
    late_threads_from=M: スレッドとレビューと行コメントだけ、M 周目から差し替える（要約より先に結果が見える場面）。
    finding_comments_fail_until=N: 行コメントの取得が N 回目まで失敗する。
    broken_jq: 手順から見える jq が動かない（runner に jq が無い、に当たる）。偽の gh は本物を使う。
    polls: 周回の数。None なら seq を差し替えず、本物の40回を走らせる（1回に10秒ほどかかる）。
    """
    where.mkdir(parents=True, exist_ok=True)
    fixtures = where / "fixtures"
    fixtures.mkdir()
    def write(name: str, value) -> None:
        (fixtures / name).write_text(json.dumps(value), encoding="utf-8")

    def graphql(nodes) -> dict:
        return {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": list(nodes)}}}}}

    write("reviews.json", [list(reviews)])
    write("comments.json", [list(comments)])
    if finding_comments is None:
        finding_comments = _finding_comments(threads, head)
    write("review_comments.json", [list(finding_comments)])
    if not graphql_fails:
        write("graphql.json", graphql(threads))
    if comments_fail_from:
        (fixtures / "comments_fail_from").write_text("%d\n" % comments_fail_from, encoding="utf-8")
    if summary_fail_from:
        (fixtures / "comments_raw_fail_from").write_text("%d\n" % summary_fail_from, encoding="utf-8")
    if summary_fail_until:
        (fixtures / "comments_raw_fail_until").write_text("%d\n" % summary_fail_until, encoding="utf-8")
    if reviews_fail_from:
        (fixtures / "reviews_fail_from").write_text("%d\n" % reviews_fail_from, encoding="utf-8")
    if finding_comments_fail_until:
        (fixtures / "review_comments_fail_until").write_text("%d\n" % finding_comments_fail_until, encoding="utf-8")
    if late_threads_from:
        for name in ("reviews", "review_comments", "graphql"):
            (fixtures / ("%s_late_from" % name)).write_text("%d\n" % late_threads_from, encoding="utf-8")
    if late_from:
        (fixtures / "late_from").write_text("%d\n" % late_from, encoding="utf-8")
        if late_comments is not None:
            write("comments_late.json", [list(late_comments)])
        if late_reviews is not None:
            write("reviews_late.json", [list(late_reviews)])
        if late_threads is not None:
            write("review_comments_late.json", [_finding_comments(late_threads, head)])
            if not graphql_fails:
                write("graphql_late.json", graphql(late_threads))
        if late_finding_comments is not None:
            write("review_comments_late.json", [list(late_finding_comments)])
    bin_dir = where / "bin"
    bin_dir.mkdir()
    fakes = {"gh": GH_STUB, "sleep": "exit 0\n"}
    if broken_jq:
        fakes["jq"] = "exit 127\n"
    if polls is not None:
        fakes["seq"] = SEQ_STUB
    for name, body in fakes.items():
        path = bin_dir / name
        # `env` を挟まずに bash を直接起こす（偽物は1回の実行で数百回呼ばれる）。
        path.write_text("#!%s\n%s" % (BASH, body), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    script = where / "step.sh"
    script.write_text(_step()["run"], encoding="utf-8")
    summary = where / "step_summary.md"
    env = dict(
        os.environ,
        PATH="%s%s%s" % (bin_dir, os.pathsep, os.environ["PATH"]),
        GH_TOKEN="x",
        PR="89",
        REPO="owner/repo",
        HEAD_SHA=head,
        EVENT_ACTION=event,
        IS_DRAFT="true" if draft else "false",
        PUSHED_AT=pushed_at,
        # job の env にある jq の式は、workflow に書いてあるものをそのまま渡す。
        **{key: str(value) for key, value in (_job().get("env") or {}).items()},
        GATE_FIXTURES=str(fixtures),
        GATE_POLLS=str(polls or 0),
        REAL_JQ=JQ,
        GITHUB_STEP_SUMMARY=str(summary),
    )
    # GitHub は run の手順を `bash -e` で走らせる
    out = subprocess.run([BASH, "-e", str(script)], env=env, capture_output=True, text=True, timeout=180)
    return Run(out, fixtures, summary)


def test_the_step_receives_everything_the_script_reads():
    """手順が読む変数が、workflow から渡されていること。渡し忘れると、試験だけが通る。"""
    env = _step()["env"]
    assert env["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert env["EVENT_ACTION"] == "${{ github.event.action }}"
    assert env["IS_DRAFT"] == "${{ github.event.pull_request.draft }}"
    assert env["PUSHED_AT"] == "${{ github.event.pull_request.updated_at }}"
    assert set(_job()["env"]) == {"SUMMARY_FILTER", "REQUEST_FILTER"}


def test_the_wait_is_forty_polls_thirty_seconds_apart():
    """名前のとおり最大20分。試験が縮めているのはこの回数なので、手順の側がこの形であることを見る。"""
    run = _step()["run"]
    assert run.count("seq ") == 1 and "for i in $(seq 1 40); do" in run
    assert run.count("sleep ") == 1 and "sleep 30" in run
    assert _step()["name"].endswith("(max 20 min)")


def test_the_real_forty_polls_end_in_the_fail_open_for_a_silent_codex(tmp_path):
    """周回の数を縮めずに、本物の40回を1度走らせる。"""
    run = _run_gate(tmp_path, event="opened", polls=None)
    assert run.code == 0, run.said
    assert run.polls() == 40 and "waiting for Codex review... (40/40)" in run.said
    assert "No Codex review within 20 min — gate passes as a no-review PR." in run.said


# --- 1. 「指摘なし」を読む
def test_a_clean_automatic_review_passes_at_once(tmp_path):
    """PR #89 の形: レビューも受領コメントも無く、要約がいまの head を completed・指摘なしと言っている。

    直す前は40回待って `no-review PR` で通した。Codex は開いてから1分24秒で読み終えていた。
    """
    run = _run_gate(tmp_path, event="opened", comments=[_summary(HEAD, "completed", False)])
    assert run.code == 0, run.said
    assert "reported no findings (summary comment)" in run.said
    assert "waiting for Codex review" not in run.said and "no-review PR" not in run.said
    assert "指摘なし" in run.summary and "fail-open" not in run.summary
    assert run.writes == ""


def test_a_clean_summary_for_another_commit_is_not_a_review_of_this_head(tmp_path):
    run = _run_gate(tmp_path, comments=[_summary(OTHER, "completed", False)])
    assert run.code == 0 and run.polls() == POLLS
    assert "No Codex review within 20 min — gate passes as a no-review PR." in run.said


def test_a_review_that_finishes_while_the_gate_waits_is_picked_up(tmp_path):
    run = _run_gate(
        tmp_path,
        comments=[_summary(HEAD, "running", None)],
        late_comments=[_summary(HEAD, "completed", False)],
        late_from=3,
    )
    assert run.code == 0, run.said
    assert run.said.count("Codex is reviewing this head.") == 2 and run.polls() == 2


def test_a_clean_summary_does_not_hide_unresolved_threads_from_earlier_commits(tmp_path):
    """成功条件は「未解決の指摘スレッドがゼロ」のまま。要約が指摘なしでも、前の commit の指摘が残れば赤。"""
    run = _run_gate(tmp_path, comments=[_summary(HEAD, "completed", False)], threads=[_thread(False)])
    assert run.code == 1 and "still unresolved after 20 min" in run.said


def test_a_clean_summary_does_not_pass_when_the_threads_cannot_be_counted(tmp_path):
    run = _run_gate(tmp_path, comments=[_summary(HEAD, "completed", False)], graphql_fails=True)
    assert run.code == 1 and "unresolved finding threads: unknown" in run.said


def test_a_summary_reporting_findings_without_a_visible_review_fails_closed(tmp_path):
    """指摘があると分かっている head を、fail-open で通さない。"""
    run = _run_gate(tmp_path, comments=[_summary(HEAD, "completed", True)])
    assert run.code == 1, run.said
    assert "reports findings for this head, but no review thread could be read" in run.said
    assert "no-review PR" not in run.said


def test_findings_seen_once_are_not_forgotten_when_a_later_poll_cannot_read_them(tmp_path):
    """最後の1回だけ取得に失敗する。それまでは「指摘あり」と読めていた。見たあとで fail-open にしない。"""
    run = _run_gate(tmp_path, comments=[_summary(HEAD, "completed", True)], comments_fail_from=POLLS)
    assert run.code == 1 and "no review thread could be read" in run.said
    # 読めなかった周回も、最後に読めた内容（指摘あり）に従って待つ
    assert run.said.count("reports findings for this head, but no review is visible yet") == POLLS
    assert run.said.count("this time (unread); keeping what it last said (findings)") == 1


# --- 2. 前からある二つの形は、前と同じに数える（今回は述語を実際に動かして確かめる）
def test_a_receipt_comment_naming_this_head_still_counts(tmp_path):
    """ERS-ADR-0082 Amendment の形。要約が無い（古い書式）ときは、これが唯一の手がかり。"""
    run = _run_gate(tmp_path, comments=[_receipt(HEAD)])
    assert run.code == 0 and "Codex review arrived (1 review(s))" in run.said
    other = _run_gate(tmp_path / "other", comments=[_receipt(OTHER)])
    assert other.code == 0 and other.polls() == POLLS and "no-review PR" in other.said
    # 人が同じ文面を書いても、到着にはならない
    person = _run_gate(tmp_path / "person", comments=[_receipt(HEAD, user=OWNER)])
    assert person.polls() == POLLS and "no-review PR" in person.said


def test_a_receipt_does_not_outvote_a_summary_that_speaks_for_the_same_head(tmp_path):
    """同じ head を読み直させている最中に、前の回の受領コメントで緑にしない。"""
    findings = _run_gate(
        tmp_path / "findings", comments=[_receipt(HEAD), _summary(HEAD, "completed", True)]
    )
    assert findings.code == 1 and "no review thread could be read" in findings.said
    running = _run_gate(tmp_path / "running", comments=[_receipt(HEAD), _summary(HEAD, "running", None)])
    assert running.polls() == POLLS and "did not finish within 20 min" in running.said
    # 指摘コメントは見えているが、その指摘を運ぶレビューとスレッドがまだ見えない。受領コメントを
    # 到着に数えると、スレッドが空なので未解決ゼロになり、通ってしまう。
    half_visible = _run_gate(
        tmp_path / "half",
        comments=[_receipt(HEAD), _summary(HEAD, "completed", True)],
        finding_comments=_finding_comments([_thread(False)], HEAD),
    )
    assert half_visible.code == 1 and "Codex review arrived" not in half_visible.said
    assert half_visible.said.count("no review is visible yet") == POLLS


def test_a_receipt_stays_outvoted_when_the_summary_cannot_be_read_again(tmp_path):
    """要約が「指摘あり」と言った次の周回で、要約の取得だけが失敗する（PR #92 Codex P2）。

    今の周回で読めなかっただけの none を「要約は何も言っていない」と読むと、同じ head への古い
    受領コメントが数え直され、指摘のスレッドがまだ見えないうちに緑で通る。直す前は2周目で通った。
    """
    comments = [_receipt(HEAD), _summary(HEAD, "completed", True)]
    findings = _run_gate(tmp_path / "findings", comments=comments, summary_fail_from=2)
    assert findings.code == 1, findings.said
    assert "Codex review arrived" not in findings.said
    assert "no review thread could be read" in findings.said
    # 読み直させている最中に読めなくなった場合も、前の回の受領コメントでは通さない
    comments = [_receipt(HEAD), _summary(HEAD, "running", None)]
    running = _run_gate(tmp_path / "running", comments=comments, summary_fail_from=2)
    assert "Codex review arrived" not in running.said and running.polls() == POLLS
    assert "did not finish within 20 min" in running.said
    # 要約が最初から一度も読めなければ、手がかりは受領コメントだけである（前からの数え方のまま）
    never = _run_gate(tmp_path / "never", comments=[_receipt(HEAD)], summary_fail_from=1)
    assert never.code == 0 and "Codex review arrived (1 review(s))" in never.said


def test_nothing_passes_while_codex_is_still_reading_this_head(tmp_path):
    """同じ head を読み直させている最中。前の回のレビュー（指摘は解決済み）で先に通さない。

    先に通すと、いま読んでいるレビューはマージの後に届く（ERS #48 と同じ形）。
    """
    older = dict(reviews=[_review(HEAD)], comments=[_summary(HEAD, "running", None)])
    waiting = _run_gate(tmp_path / "waiting", threads=[_thread(True)], **older)
    assert waiting.polls() == POLLS and "Codex review arrived" not in waiting.said
    # Codex 側が終わらなかったので、fail-open の対象である
    assert waiting.code == 0 and "did not finish within 20 min" in waiting.said
    clean = _run_gate(
        tmp_path / "clean",
        threads=[_thread(True)],
        late_comments=[_summary(HEAD, "completed", False)],
        late_from=3,
        **older,
    )
    assert clean.code == 0 and clean.polls() == 2
    # 読み直しが「指摘あり」で終わり、新しい指摘スレッドが見えるようになった
    findings = _run_gate(
        tmp_path / "findings",
        threads=[_thread(True)],
        late_comments=[_summary(HEAD, "completed", True)],
        late_threads=[_thread(True), _thread(False)],
        late_from=3,
        **older,
    )
    assert findings.code == 1 and "unresolved finding threads: 1" in findings.said
    assert "still unresolved after 20 min" in findings.said
    # 読んでいる最中だと分かったあとで要約が読めなくなっても、前の回のレビューでは通さない
    unreadable = _run_gate(tmp_path / "unreadable", threads=[_thread(True)], summary_fail_from=2, **older)
    assert unreadable.polls() == POLLS and "Codex review arrived" not in unreadable.said
    assert "keeping what it last said (running)" in unreadable.said


def test_unresolved_findings_are_not_waved_through_when_a_rereview_stalls(tmp_path):
    """この head へのレビューに未解決の指摘が残っている。読み直しを頼んだが、終わらなかった（PR #92 Codex P2）。

    読み直しの最中は通さずに待つ。だが、未解決を数えるのまでやめると、時間切れのときに
    「読み始めたが終わらなかった」の fail-open で、未解決の指摘が残ったまま通る。直す前はそう通った。
    """
    run = _run_gate(
        tmp_path, reviews=[_review(HEAD)], threads=[_thread(False)], comments=[_summary(HEAD, "running", None)]
    )
    assert run.code == 1, run.said
    assert run.polls() == POLLS and "still unresolved after 20 min" in run.said
    assert "did not finish within 20 min" not in run.said


def test_an_older_review_does_not_stand_in_for_findings_that_are_not_visible_yet(tmp_path):
    """要約は「いまの head に指摘あり」と言う。見えているのは、同じ head への前の回のレビューだけ（PR #92 Codex P2）。

    前の回の指摘は解決済みなので、未解決はゼロである。それで通すと、新しい指摘が見える前に緑になる。
    """
    found = [_summary(HEAD, "completed", True)]
    # 1) この head への Codex の指摘コメントが1つも見えない
    nothing = _run_gate(tmp_path / "nothing", reviews=[_review(HEAD)], threads=[], comments=found)
    assert nothing.code == 1, nothing.said
    assert nothing.said.count("the comments that carry them are not visible yet") == POLLS
    assert "no review thread could be read" in nothing.said
    # 2) 読み直しを見ていた実行。要約が「指摘あり」に変わっても、指摘コメントは前の回の1つのまま
    rereview = dict(
        reviews=[_review(HEAD)],
        threads=[_thread(True)],
        comments=[_summary(HEAD, "running", None)],
        late_comments=found,
        late_from=3,
    )
    stale = _run_gate(tmp_path / "stale", **rereview)
    assert stale.code == 1 and "Codex review arrived" not in stale.said
    assert "the comments that carry them are not visible yet. (3/40)" in stale.said
    # 3) 新しい指摘が見えるようになり、それも解決した。ここで初めて通る
    settled = _run_gate(tmp_path / "settled", late_threads=[_thread(True), _thread(True)], **rereview)
    assert settled.code == 0 and "Codex review arrived (1 review(s))" in settled.said
    # Codex は結果を先に置き、数秒あとで要約を書き換える（PR #92 で2回ともそうだった）。その数秒に当たった
    # 周回は、要約がまだ「読んでいる最中」なのに新しい指摘をもう数えている。それを「前の姿」に数えると、
    # 要約が変わったときに「増えていない」と読んで、resolve しても通らなくなる。
    early = _run_gate(
        tmp_path / "early",
        late_reviews=[_review(HEAD)],
        late_threads=[_thread(True), _thread(True)],
        late_threads_from=2,
        **rereview,
    )
    assert early.code == 0 and early.polls() == 2, early.said
    # 行コメントを数えられなかった周回は、「前は無かった」の根拠にしない
    blind = _run_gate(tmp_path / "blind", finding_comments_fail_until=2, **rereview)
    assert blind.code == 1 and "Codex review arrived" not in blind.said
    # 4) 増えたのが、前の回のスレッドへの Codex の返信や、別の commit への指摘だけなら、まだ通さない
    first = _finding_comments([_thread(True)], HEAD)
    reply = {"user": {"login": CODEX["login"]}, "original_commit_id": HEAD, "in_reply_to_id": 1}
    elsewhere = {"user": {"login": CODEX["login"]}, "original_commit_id": OTHER}
    person = {"user": {"login": "someone"}, "original_commit_id": HEAD}
    noise = _run_gate(tmp_path / "noise", late_finding_comments=first + [reply, elsewhere, person], **rereview)
    assert noise.code == 1 and "Codex review arrived" not in noise.said


def test_resolving_the_threads_still_turns_a_reviewed_head_green(tmp_path):
    """要約が「指摘あり」のままでも、指摘スレッドを全部 resolve すれば通る（前からの手順）。"""
    found = [_summary(HEAD, "completed", True)]
    run = _run_gate(tmp_path / "rerun", reviews=[_review(HEAD)], threads=[_thread(True)], comments=found)
    assert run.code == 0 and "Codex review arrived (1 review(s))" in run.said
    # 待っている最中に resolve した場合（PR #92 で実際にそうなった）
    waiting = _run_gate(
        tmp_path / "waiting",
        reviews=[_review(HEAD)],
        threads=[_thread(False)],
        comments=found,
        late_threads=[_thread(True)],
        late_from=3,
    )
    assert waiting.code == 0 and waiting.polls() == 2
    # 最初の周回だけ要約が読めなかった場合。読めなかった周回の姿を「指摘ありと言う前の姿」に数えると、
    # 指摘コメントが増えていないという理由で、resolve しても通らなくなる。
    late_read = _run_gate(
        tmp_path / "late_read",
        reviews=[_review(HEAD)],
        threads=[_thread(False)],
        comments=found,
        summary_fail_until=1,
        late_threads=[_thread(True)],
        late_from=2,
    )
    assert late_read.code == 0 and late_read.polls() == 1, late_read.said


def test_a_review_of_this_head_passes_only_with_zero_unresolved_codex_threads(tmp_path):
    ok = _run_gate(tmp_path / "ok", reviews=[_review(HEAD)], threads=[_thread(True)])
    assert ok.code == 0 and "Codex review arrived (1 review(s))" in ok.said
    bad = _run_gate(tmp_path / "bad", reviews=[_review(HEAD)], threads=[_thread(True), _thread(False)])
    assert bad.code == 1 and "unresolved finding threads: 1" in bad.said
    assert "still unresolved after 20 min" in bad.said
    # 人が残した未解決スレッドは、このゲートの対象ではない
    human = _run_gate(tmp_path / "human", reviews=[_review(HEAD)], threads=[_thread(False, login="someone")])
    assert human.code == 0


def test_a_review_of_an_earlier_commit_or_by_someone_else_is_not_an_arrival(tmp_path):
    old = _run_gate(tmp_path / "old", reviews=[_review(OTHER)])
    assert old.polls() == POLLS and "no-review PR" in old.said
    person = _run_gate(tmp_path / "person", reviews=[_review(HEAD, login="someone")])
    assert person.polls() == POLLS and "no-review PR" in person.said


def test_a_review_seen_once_stays_red_when_later_polls_cannot_count_it(tmp_path):
    """1周目に未解決の指摘を見た。2周目からレビューの取得が失敗しても、fail-open へ流れない。"""
    run = _run_gate(tmp_path, reviews=[_review(HEAD)], threads=[_thread(False)], reviews_fail_from=2)
    assert run.code == 1 and "still unresolved after 20 min" in run.said
    assert "no-review PR" not in run.said


# --- 3. Codex が動くはずの場面で来ない: fail-open のまま
def test_a_silent_codex_still_does_not_block_a_pull_request_it_should_have_reviewed(tmp_path):
    for event in ("opened", "reopened", "ready_for_review"):
        run = _run_gate(tmp_path / event, event=event)
        assert run.code == 0 and run.polls() == POLLS, event
        assert "No Codex review within 20 min — gate passes as a no-review PR." in run.said, event
        assert "fail-open" in run.summary and run.writes == "", event


def test_a_review_that_started_but_never_finished_passes_and_says_so(tmp_path):
    for event in ("opened", "synchronize"):
        run = _run_gate(tmp_path / event, event=event, comments=[_summary(HEAD, "running", None)])
        assert run.code == 0, event + run.said
        assert "started reviewing this head but did not finish within 20 min" in run.said, event
        assert "No one asked" not in run.said, event
        assert "読み始めたが" in run.summary, event


# --- 4. push された head: 誰も頼んでいなければ、来なかったのではなく、求めていない
def test_a_pushed_head_nobody_asked_about_does_not_pass_as_a_no_review_pr(tmp_path):
    """**push では Codex は動かない。** 頼めていない回を fail-open で通さない（ERS-ADR-0082 Amendment）。

    直す前は、ゲートが依頼を書いたことで「頼んだ」ことになり、20分後に通っていた。
    その依頼は Codex に読まれていなかった。
    """
    run = _run_gate(tmp_path, event="synchronize")
    assert run.code == 1, run.said
    assert "event=synchronize draft=false head=%s pushed_at=%s" % (HEAD, PUSHED_AT) in run.said
    assert "No one asked Codex to review this pushed head" in run.said
    assert "no request at or after %s" % PUSHED_AT in run.said  # いつの push を基準にしたか
    assert "re-run this check" in run.said  # 人が何をすればよいかを、その場で言う
    assert "no-review PR" not in run.said
    assert "誰もレビューに出していない" in run.summary and HEAD[:10] in run.summary
    assert run.writes == ""  # 自分では頼まない。頼んでも読まれない


def test_requests_that_do_not_count_leave_a_pushed_head_unrequested(tmp_path):
    actions = {"login": "github-actions[bot]", "type": "Bot"}
    cases = {
        "earlier": [_request("2026-11-24T13:30:00Z")],  # 前の head への依頼
        "bot": [_request("2026-11-24T13:32:20Z", user=actions)],  # このゲートがかつて書いた形
        "mention": [_request("2026-11-24T13:32:20Z", body="説明の中で @codex review に触れただけ")],
        "outsider": [_request("2026-11-24T13:32:20Z", association="NONE")],  # 通りすがりの1行で通さない
    }
    for name, comments in cases.items():
        run = _run_gate(tmp_path / name, event="synchronize", comments=comments)
        assert run.code == 1 and "No one asked Codex" in run.said, name


def test_a_pushed_head_someone_asked_about_keeps_the_fail_open_for_a_silent_codex(tmp_path):
    """人が頼んだのに来なかった。こちらは Codex 側の停止なので、今までどおり通す。"""
    run = _run_gate(tmp_path, event="synchronize", comments=[_request("2026-11-24T13:32:10Z")])
    assert run.code == 0, run.said
    assert "review requests by people since the push: 1" in run.said
    assert "No Codex review within 20 min — gate passes as a no-review PR." in run.said


def test_a_pushed_head_with_a_clean_review_passes_at_once(tmp_path):
    comments = [_request("2026-11-24T13:32:10Z"), _receipt(HEAD), _summary(HEAD, "completed", False)]
    run = _run_gate(tmp_path, event="synchronize", comments=comments)
    assert run.code == 0 and run.polls() == 0 and "No one asked" not in run.said


def test_a_pushed_head_is_not_called_unrequested_when_the_requests_cannot_be_read(tmp_path):
    """依頼があったかを読めなかった。「誰も頼んでいない」とも「頼んであった」とも言わず、赤で止める。"""
    run = _run_gate(tmp_path, event="synchronize", comments_fail_from=POLLS + 1)
    assert run.code == 1, run.said
    assert "Could not read this pull request's comments" in run.said
    assert "No one asked" not in run.said and "no-review PR" not in run.said


def test_a_pushed_draft_is_left_alone(tmp_path):
    """書きかけへの push のたびに赤くしない。draft を見てもらう場所は ready_for_review で、Codex が自分で動く。"""
    run = _run_gate(tmp_path, event="synchronize", draft=True)
    assert run.code == 0 and run.polls() == POLLS
    assert "event=synchronize draft=true" in run.said
    assert "No Codex review within 20 min — gate passes as a no-review PR." in run.said
    assert "No one asked" not in run.said


# --- 5. 読む道具が無いとき
def test_without_jq_the_gate_reads_less_but_never_reads_more_than_is_there(tmp_path):
    """jq が動かなければ、要約も依頼も読めない。読めないものを、指摘なしや依頼ありにしない。"""
    clean = [_summary(HEAD, "completed", False)]
    opened = _run_gate(tmp_path / "opened", event="opened", comments=clean, broken_jq=True)
    assert opened.code == 0 and opened.polls() == POLLS and "no-review PR" in opened.said
    asked = [_request("2026-11-24T13:32:10Z")]
    pushed = _run_gate(tmp_path / "pushed", event="synchronize", comments=asked, broken_jq=True)
    assert pushed.code == 1 and "Could not read this pull request's comments" in pushed.said
    # レビューと受領コメントは gh が数えるので、jq が無くても前と同じに通る
    receipt = _run_gate(tmp_path / "receipt", event="synchronize", comments=[_receipt(HEAD)], broken_jq=True)
    assert receipt.code == 0 and "Codex review arrived (1 review(s))" in receipt.said
