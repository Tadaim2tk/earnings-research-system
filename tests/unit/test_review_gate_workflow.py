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
    assert step["if"] == "github.event.action == 'synchronize'"


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
