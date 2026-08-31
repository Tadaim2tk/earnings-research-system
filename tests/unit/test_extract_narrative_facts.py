"""記録の組み立て。**モデルを呼ばずに、そのまま試す。**

`outlook_mention` を測定器から外したとき（ERS-ADR-0073）、規則側の
`forecast.revision_flag` を呼ぶ経路を作らなかった。**間違った値を、何も無い状態に
置き換えただけになっていた。** 同じ形は ERS-ADR-0066 の Amendment でも踏んでいる
——検証で使った関数を出荷しなかった件である。

このファイルは、その「呼んでいるか」を実際に組み立てて確かめる。
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/extract_narrative_facts.py"

DOCUMENT = {
    "ticker": "7203", "event_date": "2026-08-05",
    "announced_at": "2026-08-05 15:30:00", "text_sha256": "a" * 64,
    "text": "経営成績に関する説明。売上は増加しました。"
            "直近に公表されている業績予想からの修正の有無：有",
}
GOOD_OUTPUT = json.dumps({
    "sales_direction": "増加", "profit_direction": "増加",
    "tailwinds": ["需要の回復"], "headwinds": [], "one_off": "無",
}, ensure_ascii=False)


def tool():
    spec = importlib.util.spec_from_file_location("extract_narrative_facts", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_rule_derived_revision_is_actually_written():
    """**モジュールを作っただけでは記録に入らない。**"""
    record = tool().build_record(DOCUMENT, "節の本文", GOOD_OUTPUT, "2026-08-30T12:00:00+09:00")
    assert record["status"] == "extracted"
    assert record["forecast_revision"] == "有"
    assert record["forecast_revision_source"] == "standard_field_rule"


def test_the_model_answer_and_the_rule_answer_are_kept_apart():
    """`facts` はモデルが答えたもの、`forecast_revision` は規則で読んだもの。
    同じ辞書に混ぜると、出どころが読めなくなる。"""
    record = tool().build_record(DOCUMENT, "節の本文", GOOD_OUTPUT, "t")
    assert "forecast_revision" not in record["facts"]
    assert "outlook_mention" not in record["facts"]
    assert set(record["facts"]) == {"sales_direction", "profit_direction",
                                    "one_off", "tailwinds", "headwinds"}


def test_an_unreadable_field_is_recorded_as_unread_not_as_no_revision():
    """`None` は「修正が無かった」ではなく「欄が読めなかった」である。"""
    without = dict(DOCUMENT, text="経営成績に関する説明。売上は増加しました。")
    record = tool().build_record(without, "節の本文", GOOD_OUTPUT, "t")
    assert record["forecast_revision"] is None
    assert record["forecast_revision_source"] == "standard_field_rule"


def test_the_revision_is_read_even_when_the_model_could_not_answer():
    """節が取れなくても、定型欄は文書全体から読める。モデルの失敗に巻き込まない。"""
    no_section = tool().build_record(DOCUMENT, None, None, "t")
    assert no_section["status"] == "no_section"
    assert no_section["forecast_revision"] == "有"

    broken = tool().build_record(DOCUMENT, "節の本文", "壊れた出力", "t")
    assert broken["status"] == "unreadable"
    assert broken["forecast_revision"] == "有"
    assert broken["raw_output"] == "壊れた出力"


def test_the_record_carries_the_instrument_version():
    from earnings_research.narrative import instrument as I
    record = tool().build_record(DOCUMENT, "節の本文", GOOD_OUTPUT, "t")
    assert record["instrument_version"] == I.INSTRUMENT_VERSION
