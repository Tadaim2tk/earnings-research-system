"""測定器の定義。版が動くこと、壊れた出力を通さないこと、目次を掴まないこと。"""

import json

import pytest

from earnings_research.narrative import instrument as I
from earnings_research.narrative.section import narrative_section, prose_score

GOOD = {
    "sales_direction": "増加", "profit_direction": "減少",
    "tailwinds": ["調味料セグメントの増収"], "headwinds": ["原材料コストの上昇"],
    "one_off": "無",
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
        ("MAX_REASONS", 8),
        ("FIELDS", {"sales_direction": I.DIRECTIONS}),
        ("LISTS", ("tailwinds",)),
        ("SECTION_RULE_VERSION", "narrative_section_v9"),
        ("BODY_CHARS", 3000),
        ("MODEL_REVISION", "0" * 40),
        ("RUNTIME", {"mlx-lm": "9.9.9"}),
    ):
        original = getattr(I, attribute)
        setattr(I, attribute, replacement)
        try:
            assert I.instrument_version() != base, attribute
        finally:
            setattr(I, attribute, original)
    assert I.instrument_version() == base


def test_the_weights_are_pinned_by_commit_not_by_repository_name():
    """リポジトリ名は可変である。同じ名前が別の重みに解決されても、名前を
    hash する限り版は動かない——**「重みが固定されているから再現できる」という
    この層の前提が、そこで崩れる。**"""
    assert len(I.MODEL_REVISION) == 40 and all(c in "0123456789abcdef" for c in I.MODEL_REVISION)
    # 生成側の版も入っている。同じ重みでも runtime が変われば出力が変わりうる。
    for package in ("mlx-lm", "mlx", "transformers", "tokenizers"):
        assert package in I.RUNTIME, package


def test_a_missing_reason_list_is_not_read_as_an_empty_one():
    """**答えなかったことと「無かった」ことは別である。** 既定値で埋めると、
    モデルが黙った場合が「理由を挙げなかった」という観測として記録される。"""
    without = {k: v for k, v in GOOD.items() if k != "headwinds"}
    facts, why = I.parse(json.dumps(without, ensure_ascii=False))
    assert facts is None and "headwinds" in why

    empty = dict(GOOD, headwinds=[])
    facts, why = I.parse(json.dumps(empty, ensure_ascii=False))
    assert why is None and facts["headwinds"] == [], "本当に空なら受ける"

    coerced = dict(GOOD, tailwinds=[1, {"a": 2}])
    assert I.parse(json.dumps(coerced, ensure_ascii=False))[0] is None


# 記録された版。`docs/DECISIONS.md` の ERS-ADR-0069 がこの値で採点済みの結果を
# 指しており、`~/.ers-corpus/facts/<この値>/` に103件が入っている。
RECORDED_VERSION = "f5b1f896125fc8e8"


def test_the_recorded_version_is_the_one_this_code_produces():
    """**digest が動くことと、digest が何かは別である。**

    ここを置くまで、版の検査は「属性を差し替えたら値が変わる」ことしか見ていな
    かった。独立監査が変異を当てたところ、`TEMPERATURE` を 0.0 から 0.9 にしても、
    `MODEL_REVISION` を別の重みに向けても、digest から `section_rule` や
    `body_chars` や出力語彙を落としても、**すべて緑のまま通った**。版が変わるのに
    誰も気づかない状態で、過去の採点と混ざる。

    採点済みの103件が `RECORDED_VERSION` の名前で保存されている以上、この値は
    コードから再現できなければならない。変えるときは、この定数と ADR を同時に
    動かすことになる——それが「別の測定器になった」ということである。
    """
    assert I.INSTRUMENT_VERSION == RECORDED_VERSION, (
        "測定器が変わっている。記録済みの採点と混ぜてはいけない。"
        "意図した変更なら、この定数と ERS-ADR を同時に更新すること")


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

    # 上限は `MAX_REASONS`。超えたぶんを黙って切らない——切ると、モデルが
    # 出した観測をこちらが選んだことになる。同じ語の繰り返しは重複排除が先に
    # 落とすので、上限に当てるには別々の項目が要る。
    at_limit = dict(GOOD, tailwinds=["項目%d" % i for i in range(I.MAX_REASONS)])
    assert I.parse(json.dumps(at_limit, ensure_ascii=False))[0] is not None
    too_many = dict(GOOD, tailwinds=["項目%d" % i for i in range(I.MAX_REASONS + 1)])
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


def test_the_forecast_revision_is_not_asked_of_the_model():
    """業績予想の記述は `section.py` が切り出す節の**外**にある。入力に無いことを
    尋ねると、モデルは決算の好調さから答えを作る——実測で83件中52件が「上方」、
    原文に修正の語があるのは2件だけだった。定型欄から規則で読む
    （`forecast.revision_flag`、86%の文書で読める）。"""
    assert "outlook_mention" not in I.FIELDS
    assert "outlook" not in I.PROMPT
    assert "上方" not in I.PROMPT and "下方" not in I.PROMPT
    assert not hasattr(I, "OUTLOOK")


def test_the_prompt_still_forbids_guessing():
    """**縛っていたのは文字列2つだけだった。**

    独立監査が「書かれていないことは推測せず"不明"とすること」を
    「推測して補ってください。分からなければ適当に埋めてよい」に置き換えたところ、
    テストは通った。空配列を誘う言い回しは塞いだのに、**測定器の中核の指示を
    正反対にする変更が素通り**していた。

    ここは事実の抽出であって推測ではない、という一点を固定する。
    """
    assert "推測せず" in I.PROMPT
    assert "不明" in I.PROMPT
    for inviting_a_guess in ("推測して", "補ってください", "適当に", "想像"):
        assert inviting_a_guess not in I.PROMPT, inviting_a_guess


def test_the_prompt_does_not_invite_the_empty_answer():
    """実測: 「無ければ空配列」を足した版（`5f986834218c05b5`）を同じ103件に
    当てると、追い風が0件の文書が 21/74 → **51/74** に増え、平均件数が
    1.85 → 1.41 に落ちた。旧版で理由を挙げていた32件が0件になり、逆は2件。
    方向の項目は動かず（売上100%・利益99%）、**理由の列挙だけが壊れた**。

    スキーマを丁寧に書いたつもりがモデルを空の答えへ寄せていた。文言を戻した
    ことをここで固定する——同じ「明確化」をまた入れないため。"""
    assert "無ければ空配列" not in I.PROMPT
    assert "空配列" not in I.PROMPT


def test_the_direction_vocabulary_stayed_closed():
    """方向は版をまたいで安定していた（売上100%・利益99%）。語彙を開くと
    その安定が失われるので、閉じたままにする。"""
    assert I.DIRECTIONS == ("増加", "減少", "横ばい", "不明")
    assert "不明" in I.DIRECTIONS, "答えられないことを言える語が要る"
    # **答えられないことを言える語を全項目に置く。** `outlook_mention` にだけ
    # それが無く、根拠が構造的に存在しない項目で推測を強いていた。
    for name, vocabulary in I.FIELDS.items():
        assert "不明" in vocabulary, name
    for vocabulary in I.FIELDS.values():
        assert len(vocabulary) == len(set(vocabulary))
        assert all(isinstance(v, str) and v for v in vocabulary)


def test_repetition_is_removed_before_the_count_is_checked():
    """上限6で落ちた5件を実際に見たところ、4件は 8〜10 個の別々の逆風
    （中東情勢／物価上昇／インフレ再燃…）を挙げた正当な列挙で、暴走していたのは
    1件だけだった——「黒字化」が3回繰り返されていた。**反復を潰すのは重複排除の
    仕事で、件数上限の仕事ではない。** 上限だけで両方を捌こうとすると、正当な
    列挙を捨てるか暴走を通すかになる。"""
    repeated = dict(GOOD, tailwinds=["黒字化", "黒字化", "黒字化", "成長"])
    facts, why = I.parse(json.dumps(repeated, ensure_ascii=False))
    assert why is None
    assert facts["tailwinds"] == ["黒字化", "成長"], "重複を落として順序は保つ"

    # 実測に近い、正当な長い列挙。上限で捨てない。
    genuine = dict(GOOD, headwinds=[
        "中東情勢の緊迫化", "金融資本市場の変動", "物価上昇の継続", "価格競争の激化",
        "需要の鈍化", "前年の大型案件の反動減", "工事計画見直し", "投資意欲の減退"])
    facts, why = I.parse(json.dumps(genuine, ensure_ascii=False))
    assert why is None and len(facts["headwinds"]) == 8

    runaway = dict(GOOD, tailwinds=["項目%d" % i for i in range(I.MAX_REASONS + 1)])
    assert I.parse(json.dumps(runaway, ensure_ascii=False))[0] is None
