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
"""

from typing import Optional

import pandas as pd

SCHEMA_VERSION = "cross_market_align_v1"


class MissingColumn(ValueError):
    """求めた列が無い。黙って空の表を返さない。"""


def returns_on_own_days(frame: pd.DataFrame, symbol: str,
                        value: str = "close") -> pd.DataFrame:
    """その銘柄が実際に値を持つ日だけで騰落率(%)を作る。

    **`fill_method=None` を明示する。** 既定に任せると、欠測を前の値で埋めた
    0.00% が本物の観測として混じる。
    """
    for column in ("symbol", "date", value):
        if column not in frame.columns:
            raise MissingColumn(column)
    rows = frame[frame["symbol"] == symbol][["date", value]].dropna()
    rows = rows.sort_values("date").drop_duplicates("date")
    out = pd.DataFrame({"date": pd.to_datetime(rows["date"].values),
                        "ret": rows[value].pct_change(fill_method=None).values * 100})
    return out.dropna().reset_index(drop=True)


def follows(jp_returns: pd.DataFrame, us_returns: pd.DataFrame) -> pd.DataFrame:
    """日本の各営業日に、**その日より前で直近の**米国の立会を当てる。

    `allow_exact_matches=False`。日本の立会は米国より先に終わるので、同じ日付の
    米国は日本の後の情報である。同日で組むと未来を見たことになる。
    """
    left = jp_returns.rename(columns={"ret": "jp"}).sort_values("date")
    right = us_returns.rename(columns={"ret": "us"}).sort_values("date")
    return pd.merge_asof(left, right, on="date", direction="backward",
                         allow_exact_matches=False).dropna().reset_index(drop=True)


def padded_zero_days(frame: pd.DataFrame, symbol: str, value: str = "close") -> int:
    """暦で並べたときに偽の0.00%が何日ぶん生まれるかを数える。

    直さずに使ってしまったときの被害を測るために置いてある。
    """
    wide = frame.pivot_table(index="date", columns="symbol", values=value).sort_index()
    if symbol not in wide.columns:
        raise MissingColumn(symbol)
    return int((wide.pct_change()[symbol] == 0).sum())


def correlation(pair: pd.DataFrame, since: Optional[str] = None) -> Optional[float]:
    """組んだ表の相関。2本に満たなければ `None`。埋めない。"""
    rows = pair if since is None else pair[pair["date"] >= pd.Timestamp(since)]
    if len(rows) < 2:
        return None
    return float(rows["jp"].corr(rows["us"]))
