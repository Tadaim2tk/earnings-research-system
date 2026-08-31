"""市場をまたぐ揃え方。**暦の行で組むと結論の符号が逆になる。**"""

import pytest

from earnings_research.regime import align as A


def rows(*triples):
    return [{"symbol": s, "date": d, "close": c} for s, d, c in triples]


# 2026-01-02 は金曜、01-03 と 01-04 は週末、01-05 が月曜。
# **休みが営業日の後ろに来る形でないと事故は再現しない。** 前に置くと埋める元の
# 値が無いので 0.00% は生まれず、試験が通ってしまう。最初これを間違えた。
JP = (("^N225", "2026-01-02", 100.0), ("^N225", "2026-01-05", 101.0),
      ("^N225", "2026-01-06", 99.0))
US = (("^GSPC", "2026-01-02", 200.0), ("^GSPC", "2026-01-05", 204.0),
      ("^GSPC", "2026-01-06", 200.0))
WEEKEND = tuple(("BTC-USD", d, 1.0) for d in
                ("2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"))


def test_a_closed_market_does_not_become_a_zero_percent_day():
    """**これが実測で起きた事故。** 仮想通貨が週末も動くので日付が1,382日から
    2,066日に膨らみ、日経の騰落がちょうど0.00%になる行が681日ぶん混入した。
    相関は 0.61 が 0.46 に薄まり、「直近は中央値より上」という逆の結論が出た。"""
    mixed = rows(*(JP + WEEKEND))
    assert A.padded_zero_days(mixed, "^N225") == 2      # 土曜 1/3 と 日曜 1/4
    got = A.returns_on_own_days(mixed, "^N225")
    assert len(got) == 2                                 # 1/5 と 1/6 だけ
    assert not any(r["ret"] == 0 for r in got)


def test_returns_use_only_the_days_the_symbol_actually_traded():
    got = A.returns_on_own_days(rows(*(JP + US + WEEKEND)), "^N225")
    assert [r["date"] for r in got] == ["2026-01-05", "2026-01-06"]
    assert got[0]["ret"] == pytest.approx(1.0)
    assert got[1]["ret"] == pytest.approx(-1.9802, abs=1e-4)


def test_the_japanese_day_is_matched_to_the_previous_american_session():
    """**同じ日付の米国を拾わせない。** 日本の立会は先に終わるので、同日の
    米国は日本の後の情報である。同日で組むと未来を見たことになる。"""
    both = rows(*(JP + US))
    pair = A.follows(A.returns_on_own_days(both, "^N225"),
                     A.returns_on_own_days(both, "^GSPC"))
    assert len(pair) == 1
    assert pair[0]["date"] == "2026-01-06"
    assert pair[0]["jp"] == pytest.approx(-1.9802, abs=1e-4)   # 火曜 1/6 の日経
    assert pair[0]["us"] == pytest.approx(2.0)                 # 月曜 1/5 の米国


def test_a_holiday_on_one_side_reaches_further_back_rather_than_dropping():
    """日本が祝日で米国が開いていた日は、次の日本の立会が**最後の米国**を拾う。"""
    jp = (("^N225", "2026-01-05", 100.0), ("^N225", "2026-01-09", 102.0))
    us = (("^GSPC", "2026-01-05", 200.0), ("^GSPC", "2026-01-06", 202.0),
          ("^GSPC", "2026-01-07", 210.0), ("^GSPC", "2026-01-08", 220.0))
    data = rows(*(jp + us))
    pair = A.follows(A.returns_on_own_days(data, "^N225"),
                     A.returns_on_own_days(data, "^GSPC"))
    assert len(pair) == 1
    assert pair[0]["us"] == pytest.approx(100 * (220 - 210) / 210, abs=1e-6)


def test_a_gap_on_the_japanese_side_measures_the_whole_gap():
    """**隣り合う観測どうしで割る。** 暦上の隣ではないので、休みを挟めばその
    区間まるごとの騰落になる——それが「前の立会からいくら動いたか」である。"""
    got = A.returns_on_own_days(rows(("^N225", "2026-01-05", 100.0),
                                     ("^N225", "2026-01-13", 110.0)), "^N225")
    assert len(got) == 1
    assert got[0]["ret"] == pytest.approx(10.0)


def test_a_missing_column_stops_rather_than_returning_an_empty_frame():
    with pytest.raises(A.MissingColumn):
        A.returns_on_own_days([{"symbol": "^N225", "date": "2026-01-05"}], "^N225")
    with pytest.raises(A.MissingColumn):
        A.returns_on_own_days([{"date": "2026-01-05", "close": 1.0}], "^N225")
    with pytest.raises(A.MissingColumn):
        A.padded_zero_days(rows(*JP), "^GSPC")


def test_a_day_that_is_not_a_day_stops_rather_than_being_sorted():
    """**全角数字は弾く。** `"2026-０8-25"` は `\\d` を通り、しかも
    `"2026-０8-25" > "2026-12-31"` が真になって並び順まで壊す。"""
    for bad in ("2026-０1-05", "2026-1-5", "2026/01/05", "2026-02-30", "20260105", ""):
        with pytest.raises(A.MalformedDay):
            A.returns_on_own_days([{"symbol": "^N225", "date": bad, "close": 1.0}], "^N225")


def test_a_correlation_of_one_row_is_none_rather_than_a_number():
    """2本に満たない相関を数字で返さない。埋めない。"""
    both = rows(*(JP + US))
    pair = A.follows(A.returns_on_own_days(both, "^N225"),
                     A.returns_on_own_days(both, "^GSPC"))
    assert A.correlation(pair) is None
    assert A.correlation(pair, since="2030-01-01") is None


def test_a_flat_series_has_no_correlation_rather_than_zero():
    """片方が1本も動かない区間で 0.0 を返すと、「無関係だと測れた」に読める。"""
    pair = [{"date": "2026-01-05", "jp": 1.0, "us": 2.0},
            {"date": "2026-01-06", "jp": -1.0, "us": 2.0}]
    assert A.correlation(pair) is None


def test_a_real_correlation_comes_out_as_a_number():
    pair = [{"date": "2026-01-05", "jp": 1.0, "us": 1.0},
            {"date": "2026-01-06", "jp": 2.0, "us": 2.0},
            {"date": "2026-01-07", "jp": 3.0, "us": 3.0}]
    assert A.correlation(pair) == pytest.approx(1.0)
