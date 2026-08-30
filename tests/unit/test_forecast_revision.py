"""業績予想の修正の有無。**規則で読めるものを推測させない。**

`outlook_mention` としてモデルに尋ねていたものは、構造的に答えられなかった。
業績予想の記述は `section.py` が切り出す節の外にあり、入力に無いことを尋ねられた
モデルは決算の好調さから「上方」を作った。実測:

    LLM の答え     上方 52 / 言及なし 29 / 下方 1 / 据置 1   （83件）
    定型欄          有 30 / 無 59 / 欄なし 14                （103件）

「上方＋下方」が64%に対し、定型欄で「有」は29%。**倍以上ずれている。**
"""

from earnings_research.narrative import forecast


def test_the_standard_field_is_read_rather_than_guessed():
    assert forecast.revision_flag(
        "直近に公表されている業績予想からの修正の有無：有") == "有"
    assert forecast.revision_flag(
        "直近に公表されている業績予想からの修正の有無：無") == "無"


def test_the_field_survives_the_shapes_a_pdf_produces():
    """PDF から抜いたテキストは欄の途中で改行が入り、全半角も揺れる。"""
    for shape in (
        "直近に公表されている業績予想からの修正の有無\n：有",
        "直近に公表されている業績予想からの修正の有無 : 有",
        "直近に公表されている業績予想からの修正の有無︓有",
        "直近に公表されている業績予想からの\n修正の有無：有",
        "（注）直近に公表されている業績予想からの修正の有無：有連結業績予想の修正につきましては",
    ):
        assert forecast.revision_flag(shape) == "有", shape


def test_an_absent_field_is_not_read_as_no_revision():
    """`None` は「修正が無かった」ではなく「**欄が読めなかった**」である。
    103件中14件がこれに当たる（REIT やインフラファンドの様式、PDF抽出の破損）。"""
    assert forecast.revision_flag("") is None
    assert forecast.revision_flag("経営成績に関する説明。売上は増加しました。") is None
    assert forecast.revision_flag("業績予想の修正に関するお知らせを公表しました") is None


def test_text_near_the_label_is_not_mistaken_for_the_value():
    """**欄の近くにある無関係な文字を答えにしない。** 緩い一致で実際に拾えたもの:

        業績予想からの修正の有無（注記有）          -> 有
        業績予想からの修正の有無について、無配を継続  -> 無
        業績予想からの修正の有無 有・無             -> 有

    3つとも「欄が読めなかった」が正しい。特に `有・無` は選択肢の表示であって、
    どちらが選ばれたかを言っていない。
    """
    for misleading in (
        "業績予想からの修正の有無（注記有）",
        "業績予想からの修正の有無について、無配を継続します",
        "業績予想からの修正の有無 有・無",
        "業績予想からの修正の有無：有・無",
        "業績予想からの修正の有無、無配当の方針",
    ):
        assert forecast.revision_flag(misleading) is None, misleading


def test_the_direction_is_not_invented():
    """欄が言うのは有無だけで、上方か下方かは書かれていない。知るには数値の比較か
    参照先の開示が要る。`outlook_mention` は「上方」という向きまで答えさせていたが、
    その根拠は文書のどこにも無かった。"""
    assert forecast.REVISED == "有" and forecast.UNREVISED == "無"
    flag = forecast.revision_flag(
        "直近に公表されている業績予想からの修正の有無：有")
    assert flag in ("有", "無"), "向きを名乗る値が混じっている"
    assert not hasattr(forecast, "direction"), "向きを推測する経路を作らない"
