"""Codex review gate の契約。

**待つだけのゲートは、直すほど効かなくなる。** Codex が動くのは「PRを開いた」
「draftをreadyにした」「@codex review と書いた」の3つで、push は入っていない。
指摘を直して push すると、レビューは来ず、20分後の fail-open で緑になる。
2026-09-06 に PR #80 / #81 の両方で実測した。

ゲート自身がレビューを呼ぶこと、そして呼ぶのが synchronize のときだけである
ことを固定する。
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github" / "workflows" / "pr_review_gate.yml"


def gate():
    raw = GATE.read_text(encoding="utf-8")
    return raw, yaml.safe_load(raw)


def request_step(parsed):
    steps = parsed["jobs"]["wait-for-codex-review"]["steps"]
    matches = [step for step in steps if step.get("name", "").startswith("Ask Codex")]
    assert len(matches) == 1
    return matches[0]


def test_the_gate_asks_for_the_review_it_waits_for():
    """呼ばなければ来ないレビューを待っていた。呼ぶ側をゲートに持たせる。"""
    raw, parsed = gate()
    step = request_step(parsed)
    assert "@codex review" in step["run"]
    # 待つ側より先に置く。後に置くと、待ち終わってから呼ぶことになる。
    steps = parsed["jobs"]["wait-for-codex-review"]["steps"]
    assert steps.index(step) < next(
        i for i, s in enumerate(steps) if s.get("name", "").startswith("Wait for Codex")
    )
    assert "No Codex review within 20 min" in raw


def test_the_gate_only_asks_on_a_push():
    """opened / reopened / ready_for_review は Codex 自身の発火条件である。

    重ねて呼ぶと同じ head を二度レビューさせ、限りのある利用枠を余計に使う。
    """
    step = request_step(gate()[1])
    assert "github.event.action == 'synchronize'" in step["if"]


def test_asking_is_allowed_to_fail_without_failing_the_gate():
    """上限に当たって呼べなくても、待つ側は動く。ここで赤くしない。"""
    step = request_step(gate()[1])
    assert step["continue-on-error"] is True


def test_the_gate_can_write_a_comment_and_nothing_else():
    """コメントを書くだけの権限に留める。"""
    parsed = gate()[1]
    job = parsed["jobs"]["wait-for-codex-review"]
    assert job["permissions"] == {"pull-requests": "write"}
    assert parsed["permissions"] == {"pull-requests": "read"}
    raw = gate()[0]
    assert "contents: write" not in raw
    assert "git push" not in raw


def test_the_gate_still_runs_on_every_pull_request_event_it_did_before():
    """発火条件そのものは変えていない。"""
    parsed = gate()[1]
    # `on` は YAML では真偽値 True として読まれる。
    triggers = parsed[True]["pull_request"]["types"]
    assert triggers == ["opened", "reopened", "synchronize", "ready_for_review"]


def test_a_clean_review_counts_as_arrived():
    """**指摘が無いとき、Codexはレビューではなく普通のコメントで返す。**

    2026-09-06 実測: PR #82 は `Codex Review: Didn't find any major issues.` を
    issue comment として投稿し、`pulls/N/reviews` には何も現れなかった。
    レビューだけを数えると**きれいなPRは必ず「レビュー未着」になり fail-open で
    通る。**「Codexが止まっている」と「見て問題なかった」が区別できない。
    """
    raw, parsed = gate()
    wait = [
        step
        for step in parsed["jobs"]["wait-for-codex-review"]["steps"]
        if step.get("name", "").startswith("Wait for Codex")
    ][0]["run"]
    assert 'issues/$PR/comments' in wait
    assert "Reviewed commit" in wait
    # コメント側も現在の head を名指すものだけ数える。古い回の文言で即グリーンに
    # しないため、レビュー側と同じ条件にそろえる。
    assert 'short="${HEAD_SHA:0:10}"' in raw
    assert 'contains(\\"$short\\")' in wait
    assert "n=$((n + c))" in wait


def test_the_unresolved_finding_check_still_decides_the_outcome():
    """到着の数え方を広げても、成功条件は「未解決スレッドがゼロ」のまま。"""
    wait = [
        step
        for step in gate()[1]["jobs"]["wait-for-codex-review"]["steps"]
        if step.get("name", "").startswith("Wait for Codex")
    ][0]["run"]
    assert 'if [ "$unresolved" = "0" ]; then' in wait
    assert "Codex findings are still unresolved after 20 min" in wait


def test_a_request_we_could_not_send_does_not_pass_as_a_no_review_pr():
    """**呼べなかった回は「レビューが来なかった」ではない。**

    fork や Dependabot からのPRでは `GITHUB_TOKEN` が job 単位の permissions に
    よらず読み取り専用になり、依頼の POST が 403 で落ちる。push では Codex は
    動かないので、呼べていないなら誰も見ていない。fail-open は Codex 側の停止の
    ための逃げ道であって、**こちらの手が届かなかった場合に使うものではない。**
    """
    raw, parsed = gate()
    steps = parsed["jobs"]["wait-for-codex-review"]["steps"]
    ask = [s for s in steps if s.get("name", "").startswith("Ask Codex")][0]
    wait = [s for s in steps if s.get("name", "").startswith("Wait for Codex")][0]
    # 依頼の成否を、待つ側が読めるようにしてある。
    assert ask.get("id") == "ask"
    assert wait["env"]["ASK_OUTCOME"] == "${{ steps.ask.outcome }}"
    assert 'if [ "$ASK_OUTCOME" = "failure" ]; then' in wait["run"]
    # 人が何をすればよいかを、その場で言う。
    assert "@codex review" in wait["run"]
    assert "re-run this check" in wait["run"]


def test_the_fail_open_path_still_exists_for_a_silent_codex():
    """Codex 側が止まっているときは、今までどおり通す。"""
    wait = [
        s
        for s in gate()[1]["jobs"]["wait-for-codex-review"]["steps"]
        if s.get("name", "").startswith("Wait for Codex")
    ][0]["run"]
    assert "No Codex review within 20 min — gate passes as a no-review PR." in wait


def test_only_one_gate_run_per_pull_request_stays_alive():
    """**重なった古い実行は、満たされない待ちを続けるだけ。**

    続けて push すると `synchronize` の実行が重なる。古い方は自分の head SHA への
    レビューを待つが、Codexが見るのは常に最新の head なので満たされない。
    20分の fail-open を消費し、依頼を投げる側になった今は限りある枠まで使う。
    """
    parsed = gate()[1]
    assert parsed["concurrency"] == {
        "group": "codex-review-gate-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }


def test_a_stale_run_does_not_request_a_review_of_someone_elses_head():
    """依頼のコメントは commit を名指さない。**古い実行が投げると最新の head が
    レビューされ、その実行は自分の SHA を待ち続ける。**

    **突き合わせは投げる直前でなければ意味がない。** 既にレビュー済みかを見る
    走査はページを跨ぐので時間がかかり、その間に新しい push が入りうる。
    最初の確認と、投稿の直前の確認と、二度要る。
    """
    ask = [
        s
        for s in gate()[1]["jobs"]["wait-for-codex-review"]["steps"]
        if s.get("name", "").startswith("Ask Codex")
    ][0]
    assert ask["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    run = ask["run"]
    assert run.count('live=$(gh api "repos/$REPO/pulls/$PR" --jq') == 2
    assert run.count('if [ "$live" != "$HEAD_SHA" ]; then') == 2
    post = run.index("-f body='@codex review'")
    # 二度目の突き合わせが、既レビュー判定より後、投稿より前にある。
    assert run.index('"$seen" -gt 0') < run.rindex('"$live" != "$HEAD_SHA"') < post


def test_a_draft_pull_request_is_not_sent_for_review():
    """**書きかけへの push も `synchronize` である。**

    条件を event だけにすると、draft の更新のたびに未完成の内容をレビューさせ、
    限りある枠を使い切る。draft を見てもらう場所は `ready_for_review` で、
    そこは Codex 自身が発火する。
    """
    ask = [
        s
        for s in gate()[1]["jobs"]["wait-for-codex-review"]["steps"]
        if s.get("name", "").startswith("Ask Codex")
    ][0]
    assert "github.event.pull_request.draft == false" in ask["if"]
    assert "github.event.action == 'synchronize'" in ask["if"]


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


def test_a_rerun_does_not_ask_for_a_review_of_an_already_reviewed_head():
    """**チェックの再実行は `synchronize` の event をそのまま持ち回る。**

    指摘を resolve して再実行する手順を、待つ側が案内している。毎回頼むと、
    待つ側は既にある方のレビューを見てすぐ緑になり、**新しく頼んだレビューは
    マージの後に届く。** ERS #48（マージ4分後にP1指摘が2件着き main の負債に
    なった）と同じ形で、このゲートはそれを防ぐために在る。
    """
    ask = [
        s
        for s in gate()[1]["jobs"]["wait-for-codex-review"]["steps"]
        if s.get("name", "").startswith("Ask Codex")
    ][0]["run"]
    assert 'if [ "$seen" -gt 0 ]; then' in ask
    assert "not asking again" in ask
    # 判定は投稿より前にある。後ろでは意味がない。
    assert ask.index('"$seen" -gt 0') < ask.index("-f body='@codex review'")


def test_asking_and_waiting_count_a_review_the_same_way():
    """片方だけ変えると、**頼むかどうかと通すかどうかが食い違う。**

    どちらも「現在の head に対するレビュー」と「現在の head を名指すボットの
    コメント」を数える。同じ二つの述語を持っていることを見る。
    """
    steps = gate()[1]["jobs"]["wait-for-codex-review"]["steps"]
    ask = [s for s in steps if s.get("name", "").startswith("Ask Codex")][0]["run"]
    wait = [s for s in steps if s.get("name", "").startswith("Wait for Codex")][0]["run"]
    for predicate in (
        'select(.user.login==\\"chatgpt-codex-connector[bot]\\" and .commit_id==\\"$HEAD_SHA\\")',
        'select(.body | contains(\\"Reviewed commit\\"))',
        'select(.body | contains(\\"$short\\"))',
    ):
        assert predicate in ask, "依頼側に無い: %s" % predicate
        assert predicate in wait, "待機側に無い: %s" % predicate
