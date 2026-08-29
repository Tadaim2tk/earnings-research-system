"""版の比較。**劣化が見えること自体を検査する。**

このツールは「悪くなった版を採用しない」ために置いた。最初の実装は、新しい版で
`unreadable` に落ちた文書を比較から外しており、**劣化したぶんが消えて「変わって
いない」ように見えた**——防ぐはずの失敗をツール自身がやっていた。実測で v2→v3 は
読めない文書が4件から7件へ増えていたのに、生き残りだけで統計を出していた。
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/compare_instrument_versions.py"

FACTS = {
    "sales_direction": "増加", "profit_direction": "増加", "one_off": "無",
    "outlook_mention": "上方", "tailwinds": ["a"], "headwinds": ["b"],
}


def write(root, version, name, status, facts=None, reason=None):
    directory = root / version
    directory.mkdir(parents=True, exist_ok=True)
    record = {"status": status, "ticker": name}
    if facts is not None:
        record["facts"] = facts
    if reason is not None:
        record["reason"] = reason
    (directory / (name + ".json")).write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8")


def run(root, before="old", after="new"):
    result = subprocess.run(
        [sys.executable, str(TOOL), before, after, "--facts", str(root)],
        capture_output=True, text=True)
    return result.stdout + result.stderr


def test_a_document_that_became_unreadable_is_not_filtered_out(tmp_path):
    """生き残りだけを比べると、劣化が消える。"""
    for name in ("x", "y"):
        write(tmp_path, "old", name, "extracted", FACTS)
    write(tmp_path, "new", "x", "extracted", FACTS)
    write(tmp_path, "new", "y", "unreadable", reason="壊れた")

    out = run(tmp_path)
    assert "両版にある文書: 2件" in out, "全文書を数えていない"
    assert "(-1)" in out, "抽出数の減少が出ていない"
    assert "unreadable" in out, "成否の移動が出ていない"


def test_an_improvement_in_coverage_is_shown_too(tmp_path):
    write(tmp_path, "old", "x", "extracted", FACTS)
    write(tmp_path, "old", "y", "unreadable", reason="壊れた")
    for name in ("x", "y"):
        write(tmp_path, "new", name, "extracted", FACTS)
    out = run(tmp_path)
    assert "(+1)" in out


def test_a_changed_field_set_is_reported_rather_than_crashing(tmp_path):
    """項目の集合も版に含まれる。版が項目を足せば古い記録にその鍵は無い。
    現在の定義で両方を引くと落ちる。"""
    write(tmp_path, "old", "x", "extracted",
          {k: v for k, v in FACTS.items() if k != "one_off"})
    write(tmp_path, "new", "x", "extracted", FACTS)
    out = run(tmp_path)
    assert "Traceback" not in out and "KeyError" not in out, out
    assert "項目の変化" in out
    assert "one_off" in out


def test_nothing_in_common_is_said_plainly(tmp_path):
    write(tmp_path, "old", "x", "no_section")
    write(tmp_path, "new", "x", "no_section")
    out = run(tmp_path)
    assert "Traceback" not in out, out
    assert "両版で抽出できた文書が無い" in out
