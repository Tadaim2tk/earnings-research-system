"""地盤の層。固定値は 2026-08-29 の実測から取った。

留保期（2026-08-01〜08-25）は、株価指数を引いても四半期を揃えても説明が
つかなかった期間で、資産を横断して見たときだけ姿が見えた。その姿がこの層で
再現できることを確かめる。
"""

import pytest

from earnings_research.regime import features, series

# 実測（2026-08-01〜08-25 の騰落率）
RESERVED = {
    "XRP-USD": 35.25, "SOL-USD": 34.42, "ETH-USD": 32.53, "BTC-USD": 25.18,
    "SI=F": 19.02, "GC=F": 14.98, "^SOX": 1.38, "^N225": 3.30,
    "HG=F": 3.00, "DX-Y.NYB": -1.04, "^VIX": -2.59, "^TNX": -1.00,
}
# 実測（2026-06-10〜07-31）。同じ期間で銀は -10.85%、銅は +2.99%。
EXPLORATION = {
    "SI=F": -10.85, "GC=F": -1.44, "HG=F": 2.99, "^N225": 0.28,
    "BTC-USD": 2.22, "^VIX": -28.04, "^TNX": 4.47, "DX-Y.NYB": -0.15,
}


def test_the_silver_copper_divergence_is_what_named_the_period():
    """銀 +19.0% に対し銅 +3.0%。両方上がっていれば産業需要の話になり、
    結論が変わっていた。片方だけでは区別がつかないので、銅は
    「上がったから」ではなく上がらなかったことのために系列に入っている。"""
    found = features.divergences(RESERVED)
    assert len(found) == 1
    assert found[0]["moved"] == "SI=F" and found[0]["quiet"] == "HG=F"
    assert found[0]["moved_pct"] == 19.02 and found[0]["quiet_pct"] == 3.0


def test_a_falling_silver_is_a_move_too():
    """探索期は銀 -10.85% / 銅 +2.99%。向きは逆でも乖離は乖離で、
    絶対値で見ないと下落側の地盤を取り落とす。"""
    found = features.divergences(EXPLORATION)
    assert len(found) == 1 and found[0]["moved_pct"] == -10.85


def test_a_small_move_is_not_a_divergence():
    """**閾値の下端が一度も踏まれていなかった。** 固定値の動きが全て大きく、
    `MOVE_THRESHOLD_PCT` を 0 にしても全部通った。0 にすると、**両方とも動いて
    いない平坦な相場**が「銀が動いて銅が動かない」として報告される——
    ERS-ADR-0066 が結論の根拠にした信号そのものが、無から出る。"""
    assert features.divergences({"SI=F": 1.0, "HG=F": 0.5}) == ()
    assert features.divergences({"SI=F": 0.0, "HG=F": 0.0}) == ()
    assert features.divergences({"SI=F": features.MOVE_THRESHOLD_PCT - 0.1,
                                 "HG=F": 0.0}) == ()
    # 閾値ちょうどは動いた側に数える。
    assert len(features.divergences({"SI=F": features.MOVE_THRESHOLD_PCT,
                                     "HG=F": 0.0})) == 1


def test_a_noisy_quiet_leg_is_not_quiet():
    """静かな側が騒いでいたら乖離ではない。上端も踏む。"""
    assert features.divergences({"SI=F": 19.0,
                                 "HG=F": features.QUIET_THRESHOLD_PCT + 0.1}) == ()
    assert len(features.divergences({"SI=F": 19.0,
                                     "HG=F": features.QUIET_THRESHOLD_PCT})) == 1


def test_no_divergence_when_both_move_together():
    both = dict(RESERVED, **{"HG=F": 17.4})
    assert features.divergences(both) == ()


def test_a_missing_leg_reports_nothing_rather_than_guessing():
    assert features.divergences({"SI=F": 19.02}) == ()
    assert features.divergences({"SI=F": None, "HG=F": 3.0}) == ()


def test_an_empty_axis_is_stated_not_silently_zero():
    """株だけ見て地盤を語らない。今回それをやって説明を外した。"""
    equity_only = {"^N225": {"2026-08-01": 100.0, "2026-08-25": 103.3}}
    got = features.summarise(equity_only, "2026-08-01", "2026-08-25")
    assert got["insufficient_axes"] is True
    for role in ("precious", "crypto", "volatility", "rate", "fx", "industrial"):
        assert role in got["missing_roles"]
    assert got["moves_pct"]["^N225"] == 3.3


def test_a_gap_in_the_series_is_not_filled():
    # 日付は `YYYY-MM-DD` でしか渡せなくなったので、固定値も実データの形にする。
    assert features.window_move({}, "2026-08-01", "2026-08-25") is None
    assert features.window_move({"2026-08-03": 0.0, "2026-08-25": 5.0},
                                "2026-08-01", "2026-08-25") is None, "0で割らない"
    assert features.window_move({"2026-09-01": 5.0}, "2026-08-01", "2026-08-25") is None
    assert features.window_move({"2026-07-01": 5.0}, "2026-08-01", "2026-08-25") is None


def test_a_weekend_boundary_does_not_erase_the_series():
    """要求した 2026-08-01 は土曜。日付をそのまま引くと、その日に値を持つ
    暗号資産以外の全系列が消え、銀と銅の乖離も出なくなる。実測でこれを踏んだ——
    しかも検証には出荷していない補助関数を使っていたので、出荷したAPIでは
    本文に書いた窓が再現できなかった。"""
    tokyo = {"2026-08-03": 100.0, "2026-08-04": 101.0, "2026-08-25": 103.3}
    assert features.resolve_endpoints(tokyo, "2026-08-01", "2026-08-25") == \
        ("2026-08-03", "2026-08-25")
    assert features.window_move(tokyo, "2026-08-01", "2026-08-25") == pytest.approx(3.3)

    crypto = {"2026-08-01": 100.0, "2026-08-02": 101.0, "2026-08-25": 125.2}
    assert features.resolve_endpoints(crypto, "2026-08-01", "2026-08-25")[0] == "2026-08-01"


def test_resolution_never_reaches_outside_the_requested_window():
    """寄せるのは内側だけ。外へ広げると窓の外の値が混ざる。"""
    closes = {"2026-07-25": 90.0, "2026-08-03": 100.0,
              "2026-08-25": 103.0, "2026-09-05": 120.0}
    assert features.resolve_endpoints(closes, "2026-08-01", "2026-08-26") == \
        ("2026-08-03", "2026-08-25")


def test_the_summary_says_which_days_it_actually_measured():
    """寄せた結果を黙って要求どおりに見せない。"""
    got = features.summarise(
        {"^N225": {"2026-08-03": 100.0, "2026-08-25": 103.3}},
        "2026-08-01", "2026-08-25")
    assert got["requested_start"] == "2026-08-01"
    assert got["resolved"]["^N225"] == {"start": "2026-08-03", "end": "2026-08-25"}


def test_volatility_needs_enough_days_to_mean_anything():
    """境界を1つずつ踏む。`days[:2]` だけだと、値の数の下限と差分の数の下限が
    同時に効いてしまい、**どちらも固定できていなかった**（両方の変異が生きた）。"""
    days = ["d%d" % i for i in range(6)]
    closes = {d: 100.0 + i for i, d in enumerate(days)}
    assert features.realised_vol(closes, days) is not None
    assert features.realised_vol(closes, days[:3]) is not None, "3点は測れる"
    assert features.realised_vol(closes, days[:2]) is None, "2点では測らない"
    assert features.realised_vol(closes, days[:1]) is None
    assert features.realised_vol({}, days) is None


def test_every_role_has_a_series_and_the_missing_one_is_named():
    assert series.missing_roles([s.symbol for s in series.SERIES]) == ()
    # 日経VI が無いことは記録に残す。埋まっていない軸を空欄にしておかない。
    assert "日経VI" in series.UNAVAILABLE
    assert "^JNIV" in series.UNAVAILABLE["日経VI"]


def test_the_summary_ranks_by_size_not_by_sign():
    # 実測の固定値は大きい動きが全て正で、符号順と絶対値順が一致してしまう。
    # 大きく下げた系列を1つ足さないと、この2つを区別できない。
    A, B = "2026-08-03", "2026-08-25"
    closes = {s: {A: 100.0, B: 100.0 + v} for s, v in RESERVED.items()}
    closes["^SOX"] = {A: 100.0, B: 40.0}              # -60%
    got = features.summarise(closes, A, B)
    tops = [m["symbol"] for m in got["largest_moves"]]
    assert tops[0] == "^SOX", "絶対値ではなく符号で並べている"
    assert "XRP-USD" in tops
    # 実測で使った系列は7つの役割を全部埋めていた。株だけ見ていたときは
    # 埋まっていなかった軸に、答えがあった。
    assert got["insufficient_axes"] is False
    assert got["missing_roles"] == []
    assert got["divergences"][0]["moved"] == "SI=F"


def test_a_malformed_boundary_is_refused_rather_than_silently_reaching_further():
    """**辞書順で比べているので、書式が崩れると窓が壊れる。**

    実測: `end` を `2026-8-25`（ゼロ埋めが1つ欠けただけ）にすると
    `"2026-8-25" > "2026-08-27"` が真になり、要求の2日先が終端に選ばれた。
    ERS-ADR-0066 が結論の根拠にした銀と銅の数字が、両方とも動く
    （銀 +19.02% → +20.40%、銅 +3.00% → +1.12%）。黙って別の日を測らせない。
    """
    closes = {"2026-08-03": 100.0, "2026-08-25": 119.0, "2026-08-27": 120.4}
    assert features.resolve_endpoints(closes, "2026-08-01", "2026-08-25") == \
        ("2026-08-03", "2026-08-25")
    for broken in ("2026-8-25", "2026/08/25", "20260825", "", None, "2026-08"):
        with pytest.raises(features.MalformedWindow):
            features.resolve_endpoints(closes, "2026-08-01", broken)
        with pytest.raises(features.MalformedWindow):
            features.resolve_endpoints(closes, broken, "2026-08-25")


def test_a_stray_key_in_the_series_cannot_become_the_endpoint():
    """境界を検査しても、**系列の側に日付でないキーが混じれば順序は壊れる**。
    ASCII では `"a" > "2026-08-25"` なので、そのキーが終端に選ばれる。
    実データは索引由来なので現状は起きないが、境界だけ守っても片手落ちである。"""
    # `"2026-08-010"` は辞書順で **窓の内側**（`"2026-08-01"` 以降・`"2026-08-03"` の
    # 手前）に落ちる。窓の外に落ちるキー（`"a"` など）は `<=` の比較で自然に外れる
    # ので、ガードを踏まない——最初に書いた固定値がそれで、変異が生き残った。
    closes = {"2026-08-03": 100.0, "2026-08-25": 119.0,
              "2026-08-010": 50.0, "a": 999.0, "": 1.0}
    assert features.resolve_endpoints(closes, "2026-08-01", "2026-08-25") == \
        ("2026-08-03", "2026-08-25")
    assert features.window_move(closes, "2026-08-01", "2026-08-25") == pytest.approx(19.0)


def test_one_observation_is_not_a_zero_percent_move():
    """1点から区間の騰落は出ない。以前は 0.00% を返しており、**「動かなかった」と
    「1日しか見ていない」が区別できなかった**。7つの役割すべてを1点観測の系列で
    埋めると、`insufficient_axes` は False のまま全系列が +0.00% になった。"""
    one = {"2026-08-12": 100.0}
    assert features.resolve_endpoints(one, "2026-08-01", "2026-08-25") is None
    assert features.window_move(one, "2026-08-01", "2026-08-25") is None

    filled = {sym: dict(one) for sym in
              ("^N225", "^VIX", "^TNX", "JPY=X", "GC=F", "BTC-USD", "HG=F")}
    got = features.summarise(filled, "2026-08-01", "2026-08-25")
    assert got["moves_pct"] == {}, "1点しか無いのに動きを報告している"
    assert got["insufficient_axes"] is True
    assert sorted(got["unobserved"]) == sorted(filled)
