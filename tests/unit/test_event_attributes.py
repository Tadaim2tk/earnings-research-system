"""イベントの属性。**「調べていない」と「無い」を混ぜない。**

価格系列が壊れうる原因を1つずつ潰すと、潰すたびに全部やり直すことになる。候補を
属性として持たせておけば、切るだけで済む——それがこの層の目的である。
候補の一覧は `~/.ers-corpus/notes/price-anomaly-candidates.md`。
"""

import pytest

from earnings_research.attributes import build as B
from earnings_research.attributes import slice as S
from earnings_research.attributes import schema

RECORD = {
    "legacy_record_id": "L1",
    "normalized_identity": {"ticker_candidate": "7203", "company_name_candidate": "トヨタ",
                            "legacy_event_date": "2026-08-07"},
    "normalized_classifications": {"legacy_rank": "A", "quarter": "Q1",
                                   "reason_codes": ["theme_ai"]},
}
SESSIONS = {2: {"date": "2026-08-11", "open": 100.0},
            3: {"date": "2026-08-12", "close": 101.0},
            4: {"date": "2026-08-13", "close": 102.0},
            5: {"date": "2026-08-14", "close": 103.0},
            7: {"date": "2026-08-18", "close": 105.0},
            12: {"date": "2026-08-25", "close": 110.0},
            22: {"date": "2026-09-08", "close": 120.0}}


def matched(stamp, **extra):
    return dict({"selection": "matched", "announced_at": stamp}, **extra)


def test_the_close_of_the_disclosure_day_is_only_clean_after_the_bell():
    """場中や昼休みに出たものは、**その日の終値にもう反応が入っている**ので
    「終値を見て判断した」ことにならない。実測で27.7%がこれに当たる。"""
    for stamp, klass, clean in (
        ("2026-08-07T08:30:00+09:00", "pre_open", False),
        ("2026-08-07T10:00:00+09:00", "morning", False),
        ("2026-08-07T12:00:00+09:00", "lunch", False),
        ("2026-08-07T13:00:00+09:00", "afternoon", False),
        ("2026-08-07T15:30:00+09:00", "post_close", True),
        ("2026-08-07T19:00:00+09:00", "post_close", True),
    ):
        got = B.build(RECORD, matched(stamp), SESSIONS, None)["disclosure"]
        assert got["session_class"] == klass, stamp
        assert got["decision_close_is_clean"] is clean, stamp


def test_the_bell_itself_counts_as_after_the_bell():
    """235件のうち128件（54.5%）が15:30ちょうどで、**この一点の規約に分類が
    大きく依存する**。後場側に倒すと「引け後でない」が 27.7% から 82% に増える。
    `timing/models.py::classify` の `>= regular_close` に合わせてある。"""
    assert schema.session_class(15, 29, "2026-08-25") == "afternoon"
    assert schema.session_class(15, 30, "2026-08-25") == "post_close"


def test_the_bell_moved_in_2024_and_the_boundary_moves_with_it():
    """**後場の終わりは 2024-11-05 に 15:00 から 15:30 へ延びた。**

    固定値で区切ると、2021〜2024年の15:00発表が「後場の取引中」に化ける。
    実際にはその日の引け後で、終値を見てから判断できた開示である。索引の実測で
    最頻時刻は 2021〜2023年が 15:00（40〜42%）、2025〜2026年が 15:30（42%）。
    """
    # 延長前。15:00 はその日の引け。
    assert schema.session_class(14, 59, "2024-11-01") == "afternoon"
    assert schema.session_class(15, 0, "2024-11-01") == "post_close"
    assert schema.session_class(15, 29, "2024-11-01") == "post_close"
    # 延長後。同じ 15:00 が取引中になる。
    assert schema.session_class(15, 0, "2024-11-05") == "afternoon"
    assert schema.session_class(15, 29, "2024-11-05") == "afternoon"
    assert schema.session_class(15, 30, "2024-11-05") == "post_close"


def test_the_switch_day_is_the_first_day_with_the_longer_session():
    """境目は索引から出した。2024-11-01 は 15:00 が36件・15:30 が11件、
    2024-11-05 は 15:00 が12件・15:30 が46件。間に営業日は無い
    （11/2-3 が週末、11/4 が振替休日）。"""
    assert schema.afternoon_close("2024-11-01") == (15, 0)
    assert schema.afternoon_close("2024-11-04") == (15, 0)
    assert schema.afternoon_close(schema.CLOSE_EXTENDED_FROM) == (15, 30)
    assert schema.afternoon_close("2024-11-05") == (15, 30)


def test_a_day_that_is_not_a_day_stops_rather_than_picking_a_boundary():
    """**全角数字は弾く。** `\\d` で検査すると `"2024-１1-05"` が通り、境界を
    黙って取り違える。`regime.features.iso_day` で同じ穴を踏んで直した。"""
    for bad in ("2024-１1-05", "2024-11-5", "2024/11/05", "2024-02-30",
                "20241105", "", None, 20241105, "2024-11-05 15:30"):
        with pytest.raises(schema.MalformedDay):
            schema.afternoon_close(bad)
        with pytest.raises(schema.MalformedDay):
            schema.session_class(15, 0, bad)


def test_the_day_check_agrees_with_the_one_in_regime():
    """同じ規約が2箇所にある。**片方だけ直る事故を試験で塞ぐ。**"""
    from earnings_research.regime import features as F
    for value in ("2024-11-05", "2026-08-25", "2024-１1-05", "2024-11-5",
                  "2024/11/05", "2024-02-30", "20241105", "", "2000-01-01"):
        accepted_here = True
        try:
            schema._checked_day(value)
        except schema.MalformedDay:
            accepted_here = False
        assert accepted_here is F.iso_day(value), value


def test_a_missing_time_says_why_rather_than_going_quiet():
    """「無い」で潰すと、索引の不足と台帳の日付ずれと重複行が区別できない。"""
    for selection in ("no_disclosure", "ambiguous", "unresolved_code", "no_tanshin"):
        got = B.build(RECORD, {"selection": selection}, SESSIONS, None)["disclosure"]
        assert got["timing_status"] == selection
        assert got["session_class"] == "unknown"
        assert got["decision_close_is_clean"] is None
    absent = B.build(RECORD, None, SESSIONS, None)["disclosure"]
    assert absent["timing_status"] == "not_recorded"


def test_returns_are_named_by_sessions_held_not_by_offset():
    """`+5` はセッション番号で**3本保有**である。公開したダッシュボードは
    「保有 +5」と書き、5本と読まれた。"""
    price = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None)["price"]
    assert set(price["returns"]) == {"held_1", "held_2", "held_3", "held_5",
                                     "held_10", "held_20"}
    assert price["returns"]["held_3"] == pytest.approx(3.0)
    assert price["returns"]["held_20"] == pytest.approx(20.0)
    assert price["fully_covered"] is True


def test_a_partial_price_series_is_marked_not_padded():
    """長い保有ほど直近のイベントが落ちる。**行ごとに母集団が違う**ことが、
    ここで読めなければならない。"""
    short = {k: v for k, v in SESSIONS.items() if k in (2, 3, 4, 5)}
    price = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), short, None)["price"]
    assert price["covered"] == [1, 2, 3]
    assert price["fully_covered"] is False
    assert "held_20" not in price["returns"]


def test_unchecked_quality_is_unknown_not_false():
    """`False` は「調べて、無かった」を意味する。**調べていないものに書かない。**"""
    quality = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None)["quality"]
    for flag in ("split_state", "dividend_in_window", "limit_move_at_entry",
                 "halted_in_window", "zero_volume_in_window", "ticker_resolution",
                 "event_date_is_business_day", "price_source"):
        assert quality[flag] == "unknown", flag
    checked = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None,
                      dividend_in_window=False)["quality"]
    assert checked["dividend_in_window"] is False
    assert checked["split_state"] == "unknown", "他の項目を巻き込まない"


def test_the_narrative_always_says_which_instrument_measured_it():
    """版を書かずに数字だけ残すと、後から混ざる。"""
    none = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None)["narrative"]
    assert none["status"] == "not_extracted" and none["instrument_version"] is None
    with_facts = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS,
                         {"status": "extracted", "instrument_version": "abc123",
                          "facts": {"sales_direction": "増加"}})["narrative"]
    assert with_facts["instrument_version"] == "abc123"
    assert with_facts["sales_direction"] == "増加"


def test_slicing_reports_what_each_condition_dropped():
    """**条件を重ねると母集団が変わる。** 変わったことに気づかないまま数字を
    比べたのが、公開したダッシュボードの誤りだった。"""
    rows = [
        B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None),   # 金
        B.build(RECORD, matched("2026-08-06T13:00:00+09:00"), SESSIONS, None),   # 木・場中
        B.build(RECORD, matched("2026-08-05T15:30:00+09:00"), SESSIONS, None),   # 水
    ]
    kept, dropped = S.where(rows, disclosure__session_class="post_close")
    assert len(kept) == 2 and dropped["disclosure__session_class"] == 1
    kept, dropped = S.where(rows, disclosure__is_friday=True)
    assert len(kept) == 1 and dropped["disclosure__is_friday"] == 2
    kept, dropped = S.where(rows, disclosure__session_class={"post_close", "afternoon"})
    assert len(kept) == 3


def test_returns_and_clusters_come_out_aligned():
    """統計にかけるとき銘柄をクラスタとして渡す。別々に取ると順序がずれる。"""
    rows = [B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None)]
    values, codes = S.returns_of(rows, 3)
    assert len(values) == len(codes) == 1
    assert codes == ["7203"]


def test_grouping_keeps_the_rows_that_have_no_value():
    """値が無い行を捨てると、欠測が見えなくなる。"""
    rows = [B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None),
            B.build(RECORD, {"selection": "no_disclosure"}, SESSIONS, None)]
    grouped = S.group(rows, "disclosure.session_class")
    assert set(grouped) == {"post_close", "unknown"}
    assert len(grouped["unknown"]) == 1


def test_the_quality_vocabulary_is_closed():
    """綴りの違う名前で鍵が生えると、`unknown` のまま気づかない項目が増える。"""
    from earnings_research.attributes.build import quality_block
    with pytest.raises(ValueError):
        quality_block(splt_in_window=False)          # 綴り違い
    with pytest.raises(ValueError):
        quality_block(ticker_resolution="たぶん取れた")
    with pytest.raises(ValueError):
        quality_block(split_state="無い")
    assert quality_block(ticker_resolution="non_tse_venue")["ticker_resolution"] == "non_tse_venue"


def test_the_ticker_resolutions_do_not_collapse_into_two_values():
    """`3977` は `.S` で取れ、`34010` は4桁に直せば取れ、`…` は解決できない。
    **この3つは対処法が全部違う。** 2値にすると混ざる。"""
    from earnings_research.attributes.build import TICKER_RESOLUTIONS
    for kind in ("code_format_error", "non_tse_venue", "placeholder",
                 "renamed_ledger_stale", "duplicate", "resolved"):
        assert kind in TICKER_RESOLUTIONS, kind


def test_a_split_that_was_adjusted_is_not_recorded_as_no_split():
    """3091 は 2026-06-29 に 1:2 分割している。終値 2240→2235 に段差が無いのは
    **調整されているから**であって、分割が無いからではない。"""
    from earnings_research.attributes.build import quality_block, SPLIT_STATES
    assert "adjusted" in SPLIT_STATES and "none_in_window" in SPLIT_STATES
    assert quality_block(split_state="adjusted")["split_state"] == "adjusted"


def test_the_entry_gap_is_measured_because_that_is_where_the_rule_breaks():
    """独立監査（2026-08-30）: 約定日そのものは246件すべて寄っており「約定できない」
    は0件。**壊れるのは +1 が寄らないまま張り付いた8件**で、翌朝の寄りが窓を開ける。
    ギャップ中央値は 11.73% と 0.67% で17.5倍、95パーセンタイル 4.19% の外側にある。

    「+2の寄りで買う」が、その8件では**反応の大半を取り逃がした後の価格で買う**
    ことを意味する。切れるように値で持つ。"""
    normal = dict(SESSIONS)
    normal[1] = {"date": "2026-08-10", "close": 100.0}
    price = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), normal, None)["price"]
    assert price["prev_session_close"] == 100.0
    assert price["entry_gap_pct"] == pytest.approx(0.0)
    assert price["entry_gap_is_outlier"] is False

    jumped = dict(SESSIONS)
    jumped[1] = {"date": "2026-08-10", "close": 88.0}   # +13.6% の窓
    price = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), jumped, None)["price"]
    assert price["entry_gap_pct"] == pytest.approx(13.6364, abs=1e-3)
    assert price["entry_gap_is_outlier"] is True

    # 前日が無ければ測らない。0 で埋めない。
    without = {k: v for k, v in SESSIONS.items() if k != 1}
    price = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), without, None)["price"]
    assert price["entry_gap_pct"] is None
    assert price["entry_gap_is_outlier"] is None


ACTIONS = [
    {"ticker": "7203", "pubdate": "2026-08-07 15:30:00",
     "actions": ["tender_offer"], "stage": "announcement"},          # 決算と同じ日
    {"ticker": "7203", "pubdate": "2026-08-03 10:00:00",
     "actions": ["treasury_stock"], "stage": "announcement"},        # 約定より前
    {"ticker": "7203", "pubdate": "2026-08-20 17:00:00",
     "actions": ["share_split"], "stage": "announcement"},           # 保有中
]


def test_other_material_on_the_same_day_is_kept_apart_from_the_hold():
    """実測（2026-08-30）: 約定ギャップが分布の外側だった13件のうち**7件が、決算と
    同じ日の別の開示で説明できた**。`3480` の +13.11% は決算への反応ではなく **TOB**
    である。`3544` サツドラHD は約定した日の引け後に TOB の開始が出て、翌営業日から
    連続2日ストップ高で寄らず、**保有期間のリターンがまるごと TOB プレミアム**に
    なっている。

    「窓にあったか」では足りない。**決算と同じ日か、約定より前か、保有中か**で分ける。
    """
    got = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None,
                  actions=ACTIONS)["corporate_actions"]
    assert [a["actions"] for a in got["same_day"]] == [["tender_offer"]]
    assert [a["actions"] for a in got["before_entry"]] == [["treasury_stock"]]
    assert [a["actions"] for a in got["during_hold"]] == [["share_split"]]
    assert got["contaminated"] is True


def test_an_action_before_the_entry_does_not_contaminate():
    """約定より前の材料は、約定価格に既に入っている。**決算の反応が読めなくなる
    のは、同日の別材料と保有中の資本異動である。**"""
    before_only = [ACTIONS[1]]
    got = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None,
                  actions=before_only)["corporate_actions"]
    assert got["before_entry"] and not got["same_day"] and not got["during_hold"]
    assert got["contaminated"] is False


def test_no_actions_is_not_the_same_as_not_looked():
    """**調べていないのに「無かった」と書かない。**

    この試験は元々その名前で書かれながら、`actions=None`（＝一度も見ていない）
    に `contaminated is False`（＝見て、無かった）を要求していた。**docstring と
    assert が逆を言っていた。** 会社の行為の成果物が無い状態で組むと、全イベント
    が「同日に別材料なし」を名乗ることになる。
    """
    not_looked = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None,
                         actions=None)["corporate_actions"]
    assert not_looked["contaminated"] is None, "見ていないなら決められない"
    assert not_looked["coverage"] == "not_checked"

    searched = B.build(RECORD, matched("2026-08-07T15:30:00+09:00"), SESSIONS, None,
                       actions=[])["corporate_actions"]
    assert searched["contaminated"] is False, "見て、該当が無かったなら False"
    assert searched["coverage"] == "checked"

    blank = dict(RECORD, normalized_identity={"ticker_candidate": "7203"})
    unknown = B.build(blank, None, None, None, actions=[])["corporate_actions"]
    assert unknown["contaminated"] is None, "イベント日が無ければ決められない"


def test_a_row_with_no_price_still_says_it_is_not_fully_covered():
    """**欄を落とすことは False ではない。**

    価格が1本も無い経路だけ `fully_covered` を省いていた。すると
    `where(price__fully_covered=False)` がその行を拾えない。実測で、8件の
    `no_session` が「覆えていない」の集計から漏れ、107件あるはずが99件と
    出ていた。母数が黙って縮む。
    """
    absent = B.price_block(None)
    partial = B.price_block({schema.ENTRY_OFFSET: {"date": "2026-06-12", "open": 100.0}})
    assert absent["fully_covered"] is False
    assert partial["fully_covered"] is False
    assert sorted(absent) == sorted(partial), "取れなかった行も同じ形を返す"


def test_a_row_whose_entry_open_is_missing_returns_the_same_shape():
    """建ての寄りが無い経路も同じ。日付だけは分かるので残す。"""
    got = B.price_block({schema.ENTRY_OFFSET: {"date": "2026-06-12", "open": None}})
    assert got["entry_date"] == "2026-06-12"
    assert got["entry_open"] is None
    assert got["fully_covered"] is False
    assert got["entry_gap_is_outlier"] is None


def test_the_scope_of_a_corporate_action_survives_into_the_attributes():
    """**名証だけの上場廃止を、全面廃止と区別できなくしない。**

    `corporate_actions.collect` が `scope` をわざわざ分けているのに、属性へ
    束ねるときに落としていた。落とすと、東証に残っている会社の「消滅」として
    読めてしまう。
    """
    actions = [{"pubdate": "2026-06-10 15:00:00", "actions": ["delisting"],
                "stage": "announcement", "scope": "secondary_market"},
               {"pubdate": "2026-06-10 15:00:00", "actions": ["tender_offer"],
                "stage": "announcement", "scope": "unspecified"}]
    got = B.corporate_actions_block(actions, "2026-06-10", "2026-06-12", {})
    scopes = [entry["scope"] for entry in got["same_day"]]
    assert scopes == ["secondary_market", "unspecified"]
