"""市場ごとの営業日で騰落を作り、「直前の相手の立会」に合わせる。

**暦の行で揃えない。** 日本と米国は営業日が違い、仮想通貨は週末も動く。全部を
1つの表に並べると、閉まっていた市場の行が空欄になる。`pandas.pct_change()` は
既定で空欄を前の値で埋めるので（2.0系まで `fill_method="pad"`）、**閉まっていた
日が「騰落0.00%」の実在する観測に化ける。**

実測でこれが起きた。20系列を `pivot_table` で並べると日付が1,382日から2,066日に
膨らみ、日経の騰落がちょうど0.00%になる行が681日ぶん混入した。日経とS&Pの
相関は 0.61 が 0.46 に薄まり、**「直近は5年の中央値より上」という結論が出た。
正しく組むと下から28%で、結論が逆になる。**

空欄を埋めないだけでは足りない。週末の行が残ったまま1日ずらすと、月曜の日経が
「日曜の米国」と組まれて落ちる。各系列を自分の営業日だけで持ち、日本の当日に
対して直前の米国の立会を当てる。

**pandas に依存しない。** `src/` は pandas を1つも使っておらず、この1本のために
本体の依存を増やすと、CI が入れない限り試験が飛ばされる。飛ばされる試験は何も
守らない。ISO日付は辞書順が日付順と一致するので、素の Python で足りる。
"""

from datetime import date, timedelta
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "cross_market_align_v1"

# **相手の立会をいつまで持ち越すか。** 米国が休むのは連続でせいぜい4日
# （木〜日の感謝祭、金〜月の連休）なので、7日を超える空きは休場ではなく
# **こちらの取得が欠けている**と見る。
#
# これは事実ではなく方針である。上限を置かないと、系列が途中で切れたときに
# 1本の古い値が何日ぶんも使い回され、**取得の欠けが休場として相関に入り込む**。
# 上限を超えた日は組まずに落とす——推測で埋めない。
MAX_CARRY_DAYS = 7


class MissingColumn(ValueError):
    """求めた欄が無い。黙って空を返さない。"""


class MalformedDay(ValueError):
    """日付が `YYYY-MM-DD` でない。黙って別の日として並べない。"""


def _checked_day(value: object) -> str:
    """`YYYY-MM-DD` の実在する日付として読む。読めなければ落とす。

    **`\\d` で検査しない。** 正規表現の `\\d` は全角数字を通すので、
    `"2026-０8-25"` が素通りし、しかも `"2026-０8-25" > "2026-12-31"` が真に
    なって並び順まで壊れる。`regime.features.iso_day` と同じ規約。
    """
    if not isinstance(value, str):
        raise MalformedDay(repr(value))
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MalformedDay(value) from exc
    if parsed.isoformat() != value:
        raise MalformedDay(value)
    return value


def _series(rows: Sequence[Mapping[str, object]], symbol: str,
            value: str) -> List[Tuple[str, float]]:
    """その銘柄の (日付, 値)。日付順、同じ日は最後の1つ。欠測は落とす。"""
    seen: Dict[str, float] = {}
    saw_symbol = saw_value = False
    for row in rows:
        if "symbol" not in row:
            raise MissingColumn("symbol")
        if "date" not in row:
            raise MissingColumn("date")
        if value not in row:
            raise MissingColumn(value)
        saw_symbol = saw_value = True
        if row["symbol"] != symbol:
            continue
        got = row[value]
        if got is None or got != got:            # None と NaN
            continue
        seen[_checked_day(row["date"])] = float(got)
    if not saw_symbol or not saw_value:
        raise MissingColumn(value)
    return [(day, seen[day]) for day in sorted(seen)]


def returns_on_own_days(rows: Sequence[Mapping[str, object]], symbol: str,
                        value: str = "close") -> Tuple[Dict[str, object], ...]:
    """その銘柄が実際に値を持つ日だけで騰落率(%)を作る。

    **隣り合う観測どうしで割る。** 暦上の隣ではないので、休みを挟めばその区間
    まるごとの騰落になる——それが「前の立会からいくら動いたか」である。
    """
    points = _series(rows, symbol, value)
    out = []
    for (_, before), (day, now) in zip(points, points[1:]):
        if before == 0:
            continue
        out.append({"date": day, "ret": 100.0 * (now / before - 1.0)})
    return tuple(out)


def follows(jp_returns: Sequence[Mapping[str, object]],
            us_returns: Sequence[Mapping[str, object]],
            max_carry_days: int = MAX_CARRY_DAYS) -> Tuple[Dict[str, object], ...]:
    """日本の各営業日に、**その日より前で直近の**米国の立会を当てる。

    同じ日付の米国は拾わない。日本の立会は米国より先に終わるので、同日の米国は
    日本の後の情報である。同日で組むと未来を見たことになる。

    休みを挟む日は、その間で最後に観測された1本が当たる。ただし
    `max_carry_days` を超えて古い値は当てない——**そこまで空くのは休場ではなく
    取得の欠けなので、組まずに落とす。**
    """
    right = sorted(({"date": _checked_day(r["date"]), "ret": float(r["ret"])}
                    for r in us_returns), key=lambda r: r["date"])
    out = []
    at = 0
    latest: Optional[Dict[str, object]] = None
    for row in sorted(jp_returns, key=lambda r: _checked_day(str(r["date"]))):
        day = _checked_day(str(row["date"]))
        while at < len(right) and right[at]["date"] < day:
            latest = right[at]
            at += 1
        if latest is None:
            continue
        # **古い値を無期限に持ち越さない。** 相手の系列が途中で切れると、1本の
        # 値が何日ぶんも使い回され、取得の欠けが休場として相関に入り込む。
        gap = date.fromisoformat(day) - date.fromisoformat(str(latest["date"]))
        if gap > timedelta(days=max_carry_days):
            continue
        out.append({"date": day, "jp": float(row["ret"]), "us": float(latest["ret"])})
    return tuple(out)


def padded_zero_days(rows: Sequence[Mapping[str, object]], symbol: str,
                     value: str = "close") -> int:
    """暦で並べたときに偽の0.00%が何日ぶん生まれるかを数える。

    直さずに使ってしまったときの被害を測るために置いてある。その銘柄が値を持つ
    最初の日より後で、他のどれかが動いていて自分が休んでいた日の数。
    """
    # **2回走査するので、先に実体化する。** generator を渡されると1回目で
    # 使い切り、2回目が空になって黙って0が返る。
    rows = list(rows)
    mine = {day for day, _ in _series(rows, symbol, value)}
    if not mine:
        raise MissingColumn(symbol)
    first = min(mine)
    everyone = {_checked_day(str(row["date"])) for row in rows}
    return sum(1 for day in everyone if day > first and day not in mine)


def correlation(pairs: Sequence[Mapping[str, object]],
                since: Optional[str] = None) -> Optional[float]:
    """組んだ表の相関。2本に満たなければ、あるいは片方が動かなければ `None`。"""
    rows = [r for r in pairs
            if since is None or _checked_day(str(r["date"])) >= _checked_day(since)]
    if len(rows) < 2:
        return None
    xs = [float(r["jp"]) for r in rows]
    ys = [float(r["us"]) for r in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5
