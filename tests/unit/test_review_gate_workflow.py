"""Codex review gate の契約（workflow の形）。

**待つだけのゲートは、直すほど効かなくなる。** Codex が動くのは「PRを開いた」
「draftをreadyにした」「@codex review と書いた」の3つで、push は入っていない。
指摘を直して push すると、レビューは来ず、20分後の fail-open で緑になる。
2026-09-06 に PR #80 / #81 の両方で実測した。

ERS-ADR-0082 は、だからゲート自身が依頼を書くことにした。**その依頼は読まれていなかった。**
Codex は github-actions[bot] の依頼に「Codex のアカウントを作って GitHub に接続してください」と
返すだけで、PR #82 で8回書いて8回ともそうだった（ERS-ADR-0084）。このファイルは長い間、
「依頼の手順があること」を文字列で確かめて緑になっていた。**手順が在ることと、働くことは別である。**

動きは `test_review_gate_behavior.py` が手順を走らせて確かめる。ここで見るのは、走らせても
分からない形の側: 発火条件、権限、並行実行の畳み方、ゲートが PR に何も書かないこと。
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github" / "workflows" / "pr_review_gate.yml"


def gate():
    raw = GATE.read_text(encoding="utf-8")
    return raw, yaml.safe_load(raw)


def wait_step(parsed):
    steps = parsed["jobs"]["wait-for-codex-review"]["steps"]
    matches = [step for step in steps if step.get("name", "").startswith("Wait for Codex")]
    assert len(matches) == 1
    return matches[0]


def test_the_gate_does_not_ask_for_reviews_itself():
    """**読まれない依頼を書かない。**

    ゲートが書いた依頼は Codex に読まれず、書くたびに「頼んだ」ことになって、push された head が
    20分後に `no-review PR` として通っていた。依頼の手順が戻ってきたら、ここで落ちる。
    戻すなら、Codex が実際に応えることを PR の上で確かめてからにする（ERS-ADR-0084）。
    """
    raw, parsed = gate()
    steps = parsed["jobs"]["wait-for-codex-review"]["steps"]
    assert [step.get("name", "") for step in steps] == [wait_step(parsed)["name"]]
    for step in steps:
        run = step.get("run", "")
        for writing in ("-f body=", "gh pr comment", "gh issue comment", "gh pr review", "-X POST", "--method POST"):
            assert writing not in run, "ゲートが PR に書こうとしている: %s" % writing
    assert "steps.ask" not in raw and "ASK_OUTCOME" not in raw


def test_the_gate_only_reads():
    """書く手順が無くなったので、書く権限も持たない。"""
    raw, parsed = gate()
    assert parsed["permissions"] == {"pull-requests": "read"}
    job = parsed["jobs"]["wait-for-codex-review"]
    # job 単位で権限を広げていない（ERS-ADR-0082 は依頼を書くために write にしていた）。
    assert job.get("permissions", {"pull-requests": "read"}) == {"pull-requests": "read"}
    for widened in ("pull-requests: write", "contents: write", "issues: write", "git push"):
        assert widened not in raw


def test_the_gate_still_runs_on_every_pull_request_event_it_did_before():
    """発火条件そのものは変えていない。"""
    parsed = gate()[1]
    # `on` は YAML では真偽値 True として読まれる。
    triggers = parsed[True]["pull_request"]["types"]
    assert triggers == ["opened", "reopened", "synchronize", "ready_for_review"]


def test_a_clean_review_counts_as_arrived():
    """**指摘が無いとき、Codexはレビューを作らない。** 形は二つある。

    コメントで依頼したレビューは、`Reviewed commit: <sha>` を持つ普通のコメントで返る
    （2026-09-06 実測: PR #82）。PR を開いたときの自動レビューは、要約コメントを書き換えるだけで、
    そのコメントも付かない（2026-11-17 実測: PR #89）。レビューだけを数えると、きれいなPRは必ず
    「レビュー未着」になる。「Codexが止まっている」と「見て問題なかった」が区別できない。
    """
    raw, parsed = gate()
    wait = wait_step(parsed)["run"]
    assert 'issues/$PR/comments' in wait
    assert "Reviewed commit" in wait
    # コメント側も現在の head を名指すものだけ数える。古い回の文言で即グリーンに
    # しないため、レビュー側と同じ条件にそろえる。
    assert 'short="${HEAD_SHA:0:10}"' in raw
    assert 'contains(\\"$short\\")' in wait
    # 要約は、いまの head を40桁で名指すものだけを読む。
    summary = parsed["jobs"]["wait-for-codex-review"]["env"]["SUMMARY_FILTER"]
    assert "codex-review-state:v1" in summary and ".commit_sha == $head" in summary
    assert '--arg head "$HEAD_SHA" "$SUMMARY_FILTER"' in wait
    assert '[ "$n" -gt 0 ] || [ "$c" -gt 0 ] || [ "$summary_state" = "clean" ]' in wait


def test_the_unresolved_finding_check_still_decides_the_outcome():
    """到着の数え方を広げても、成功条件は「未解決スレッドがゼロ」のまま。"""
    wait = wait_step(gate()[1])["run"]
    assert 'if [ "$unresolved" = "0" ]; then' in wait
    assert "Codex findings are still unresolved after 20 min" in wait
    # 通る道は一つだけで、未解決スレッドを数えたあとにある。
    passing = wait.index('if [ "$unresolved" = "0" ]; then')
    assert wait.index("reviewThreads") < passing
    assert wait.count("exit 0") == 3  # 指摘なしを確かめた通過、読み始めて終わらなかった fail-open、最後の fail-open
    assert wait.index("exit 0") > passing


def test_the_fail_open_path_still_exists_for_a_silent_codex():
    """Codex 側が止まっているときは、今までどおり通す。"""
    wait = wait_step(gate()[1])["run"]
    assert "No Codex review within 20 min — gate passes as a no-review PR." in wait


def test_an_unrequested_push_is_decided_before_the_fail_open():
    """**頼んでいない回は「レビューが来なかった」ではない。**

    push では Codex は動かない。push のあとに人が頼んでいなければ、誰も見ていない。
    fail-open は Codex 側の停止のための逃げ道であって、**こちらが頼んでいない場合に使うもの
    ではない**（ERS-ADR-0082 Amendment）。その判断が、fail-open より前に置かれていること。
    """
    wait = wait_step(gate()[1])["run"]
    asked = wait.index('if [ "${EVENT_ACTION:-}" = "synchronize" ] && [ "${IS_DRAFT:-}" != "true" ]; then')
    refused = wait.index("No one asked Codex to review this pushed head")
    fail_open = wait.index("No Codex review within 20 min — gate passes as a no-review PR.")
    assert asked < refused < fail_open
    # 人が何をすればよいかを、その場で言う。
    assert "@codex review" in wait and "re-run this check" in wait


def test_only_one_gate_run_per_pull_request_stays_alive():
    """**重なった古い実行は、満たされない待ちを続けるだけ。**

    続けて push すると `synchronize` の実行が重なる。古い方は自分の head SHA への
    レビューを待つが、Codexが見るのは常に最新の head なので満たされない。
    20分を消費して、古い head について結論を出すだけになる。
    """
    parsed = gate()[1]
    assert parsed["concurrency"] == {
        "group": "codex-review-gate-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }


DECISIONS = ROOT / "docs" / "DECISIONS.md"


def test_no_decision_record_is_swallowed_by_the_next_heading():
    """**見出しだけの ADR を残さない。**

    rebase の衝突を「両方残す」で機械的に畳んだとき、`## ERS-ADR-0082` の見出しが
    `## ERS-ADR-0081` の見出しと `Date:` の間に割り込み、**0081 の全文が 0082 の
    中身として読まれる**状態を作った。0082 の本文は見出しを失って `Approval:` から
    始まっていた。どちらの ADR も、読む側からは別のものに見える。

    見出しの前置きの形は歴史的にばらついている（`Date:` 58本、`Title:` 20本、他）。
    **見るのは「見出しの次に本文がある」ことだけで、その形は見ない。**
    """
    lines = DECISIONS.read_text(encoding="utf-8").split("\n")
    headings = [i for i, line in enumerate(lines) if line.startswith("## ERS-ADR-")]
    assert len(headings) > 50, "ADR の見出しが数えられていない"
    for i in headings:
        following = [line for line in lines[i + 1 :] if line.strip()]
        assert following, "%s の後に何も無い" % lines[i]
        assert not following[0].startswith("## ERS-ADR-"), (
            "%s が中身を持たないまま %s に飲み込まれている" % (lines[i], following[0])
        )


def test_each_decision_record_number_appears_once():
    """同じ番号が二度現れたら、畳み方を間違えている。"""
    lines = DECISIONS.read_text(encoding="utf-8").split("\n")
    numbers = [line.strip() for line in lines if line.startswith("## ERS-ADR-")]
    duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
    assert not duplicated, "番号が重複している: %s" % ", ".join(duplicated)


def test_no_conflict_markers_survive_in_the_decision_log():
    """衝突マーカーを一度そのまま commit した。二度目を機械で止める。"""
    text = DECISIONS.read_text(encoding="utf-8")
    for marker in ("<<<<<<< ", ">>>>>>> "):
        assert marker not in text, "衝突マーカーが残っている: %s" % marker
