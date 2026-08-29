"""測定器の定義。版が動くこと、壊れた出力を通さないこと、目次を掴まないこと。"""

import json

import pytest

from earnings_research.narrative import instrument as I
from earnings_research.narrative.section import narrative_section, prose_score

GOOD = {
    "sales_direction": "増加", "profit_direction": "減少",
    "tailwinds": ["調味料セグメントの増収"], "headwinds": ["原材料コストの上昇"],
    "one_off": "無", "outlook_mention": "上方",
}

# 実測に近い形。目次が先に来て、本文は後ろにある。
TOC_FIRST = """
１．経営成績等の概況 ……………………………………………………………… 2
（１）当中間期の経営成績等の概況 ……………………………………………… 2
（２）当中間期の財政状態の概況 ………………………………………………… 3
２．要約中間連結財務諸表及び主な注記 ………………………………………… 4
当中間期の経営成績等の概況
　当中間連結会計期間における我が国経済は、緩やかな回復基調で推移したものの、
原材料価格の高騰および為替変動の影響により、先行きは不透明な状況が続いており
ます。当社グループの主力である食品卸売事業においては、業務用需要の回復により
売上高は堅調に推移いたしました。一方、仕入価格の上昇分を販売価格へ十分に転嫁
できず、売上総利益率は前年同期比で0.8ポイント低下いたしました。販売費及び一般
管理費は、物流費の増加および人件費の上昇により前年同期比6.2%増加しております。
セグメント別では、食品卸売事業の売上高は15,584百万円となりました。
　冷凍食品部門につきましては、新規取引先の獲得が進み、外食向けおよび量販店向け
のいずれも二桁の成長となりました。前期に稼働を開始した物流拠点の効果が通期で
寄与し、配送効率の改善が進んでおります。一方、常温食品部門につきましては、既存
顧客における需要の減退が続き、前年同期比で微減となりました。価格改定の交渉は
継続しておりますが、浸透には時間を要する見込みであります。
　当社グループは、引き続き商品構成の見直しと物流網の最適化に取り組むとともに、
人材への投資を継続してまいります。なお、通期の業績予想につきましては、当中間期
の進捗を踏まえ、前回発表値を据え置いております。
２．要約中間連結財務諸表及び主な注記
（１）要約中間連結財政状態計算書
"""


def test_the_table_of_contents_is_not_mistaken_for_the_body():
    """最初の一致は目次のことが多い。掴むと、そこから先の採点が全部無意味に
    なり、しかも値は出るので気づけない。"""
    got = narrative_section(TOC_FIRST)
    assert got is not None
    assert "我が国経済" in got
    assert "……" not in got, "目次を掴んでいる"
    assert "要約中間連結財政状態計算書" not in got, "財務諸表まで飲み込んでいる"


def test_prose_scores_above_a_contents_listing():
    body = "当社グループは堅調に推移いたしました。売上高は増加しております。"
    toc = "１．経営成績 …………… 2\n２．財政状態 …………… 3\n３．財務諸表 …………… 4"
    assert prose_score(body) > prose_score(toc)


def test_no_section_is_better_than_the_wrong_one():
    assert narrative_section("") is None
    assert narrative_section("目次だけ …… 2\n財務諸表 …… 4") is None
    assert narrative_section("経営成績に関する説明") is None   # 短すぎる


def test_every_part_of_the_instrument_is_in_its_version():
    """モデル・プロンプト・語彙・温度・生成長・節の規則。どれか一つでも変われば
    別の測定器で、過去の採点と混ぜてはいけない。"""
    base = I.instrument_version()
    for attribute, replacement in (
        ("MODEL", "mlx-community/other-model"),
        ("PROMPT", I.PROMPT + " 追記"),
        ("TEMPERATURE", 0.7),
        ("MAX_TOKENS", 400),
        ("ENABLE_THINKING", True),
        ("MAX_REASONS", 6),
    ):
        original = getattr(I, attribute)
        setattr(I, attribute, replacement)
        try:
            assert I.instrument_version() != base, attribute
        finally:
            setattr(I, attribute, original)
    assert I.instrument_version() == base


def test_the_version_is_stable_across_calls():
    assert I.instrument_version() == I.instrument_version() == I.INSTRUMENT_VERSION


def test_a_broken_output_is_refused_rather_than_repaired():
    """埋めて通すと、埋めた値が観測として記録される。"""
    assert I.parse("")[0] is None
    assert I.parse("すみません、判断できません")[0] is None
    assert I.parse("{壊れた")[0] is None
    assert I.parse("[1,2,3]")[0] is None

    out_of_vocab = dict(GOOD, sales_direction="やや増加")
    facts, why = I.parse(json.dumps(out_of_vocab, ensure_ascii=False))
    assert facts is None and "sales_direction" in why

    too_many = dict(GOOD, tailwinds=["a", "b", "c", "d", "e"])
    assert I.parse(json.dumps(too_many, ensure_ascii=False))[0] is None

    not_a_list = dict(GOOD, headwinds="原材料")
    assert I.parse(json.dumps(not_a_list, ensure_ascii=False))[0] is None


def test_a_preamble_around_the_json_is_tolerated():
    """出力の飾りは測定の失敗ではない。中身が語彙の中なら受ける。"""
    wrapped = "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"
    facts, why = I.parse(wrapped)
    assert why is None and facts["sales_direction"] == "増加"


def test_the_instrument_extracts_facts_and_does_not_score():
    """4層のうち Extracted Facts にあたる。点にするのは Evaluation Policy の
    仕事で、点の意味がモデルの中にしか無い状態を作らない。"""
    fields = set(I.FIELDS) | set(I.LISTS)
    for judgement in ("score", "grade", "rank", "rating", "recommendation", "点数"):
        assert judgement not in fields, judgement
    facts, _ = I.parse(json.dumps(GOOD, ensure_ascii=False))
    assert set(facts) == fields
