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
    assert schema.session_class(15, 29) == "afternoon"
    assert schema.session_class(15, 30) == "post_close"


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
