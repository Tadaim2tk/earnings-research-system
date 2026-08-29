"""地盤を測る系列と、そこから読む診断。

**なぜ株価指数だけでは足りないか。** 254件の探索期と留保期で、超過リターンに
+1.17pp の差があった。株価指数を引くと差は**広がった**（+1.48pp）。四半期構成を
Q1に揃えても +2.24pp 残った。指数に出ていない何かが動いていた。

資産を横断して見ると答えははっきりしていた。留保期（2026-08-01〜08-25）の実測:

    XRP +35.3%  ソラナ +34.4%  ETH +32.5%  BTC +25.2%
    銀  +19.0%  金    +15.0%
    銅  + 3.0%  日経225 +3.3%   ドル指数 -1.0%

**銅が動かず銀だけ +19%** というのが決定的だった。銀は産業金属でも貴金属でもある
ので、銅と一緒に上がれば産業需要、銅を置いて上がれば通貨側の話になる。暗号資産の
同時上昇とドル安が揃っていて、株は脇役だった。

だから系列には貴金属と暗号資産を含める。銅は「上がったから」ではなく
**上がらなかったことに意味がある**ので外せない。

この層は説明と監査のためのもので、判断には使わない。TSO の SPEC-CAR-001 が同じ
分類器を `draft — deferred / inactive` で止めており、理由も同じ——clean な評価が
足りないうちに判断器を作ると、データが無いのにそれっぽい答えを出す。
"""

from typing import Dict, NamedTuple, Optional, Sequence, Tuple


class Series(NamedTuple):
    symbol: str
    name: str
    role: str


# 役割は分類のためではなく、どの軸が欠けているかを見るためにある。
ROLES = ("equity", "volatility", "rate", "fx", "precious", "crypto", "industrial")

SERIES: Tuple[Series, ...] = (
    Series("^N225", "日経225", "equity"),
    Series("1306.T", "TOPIX ETF", "equity"),
    Series("^GSPC", "S&P500", "equity"),
    Series("^IXIC", "NASDAQ", "equity"),
    Series("^SOX", "半導体", "equity"),
    Series("1343.T", "J-REIT", "equity"),
    Series("^VIX", "VIX", "volatility"),
    Series("^FVX", "米5年金利", "rate"),
    Series("^TNX", "米10年金利", "rate"),
    Series("^TYX", "米30年金利", "rate"),
    Series("JPY=X", "ドル円", "fx"),
    Series("DX-Y.NYB", "ドル指数", "fx"),
    Series("GC=F", "金", "precious"),
    Series("SI=F", "銀", "precious"),
    Series("BTC-USD", "ビットコイン", "crypto"),
    Series("ETH-USD", "イーサリアム", "crypto"),
    Series("XRP-USD", "XRP", "crypto"),
    Series("SOL-USD", "ソラナ", "crypto"),
    Series("HG=F", "銅", "industrial"),
    Series("CL=F", "原油", "industrial"),
)

BY_SYMBOL: Dict[str, Series] = {s.symbol: s for s in SERIES}

# 日経VI は Yahoo に無い（`^JNIV` は404）。日本のボラは米VIXで代理しており、
# 代理であることを記録に残す。埋まっていない軸を空欄にしておかない。
UNAVAILABLE: Dict[str, str] = {
    "日経VI": "Yahoo Finance に系列が無い（^JNIV は 404）。米VIXで代理している",
}

# 「動かなかったこと」に意味がある組。銀が動いて銅が動かなければ通貨側、
# 揃って動けば産業側。片方だけでは区別がつかない。
DIVERGENCE: Tuple[Tuple[str, str, str], ...] = (
    ("SI=F", "HG=F", "銀が動いて銅が動かないのは、産業需要ではなく通貨側の動き"),
)


def roles_present(symbols: Sequence[str]) -> Dict[str, int]:
    """役割ごとに何系列あるか。欠けた軸を数えるために使う。"""
    counts = {role: 0 for role in ROLES}
    for symbol in symbols:
        series = BY_SYMBOL.get(symbol)
        if series is not None:
            counts[series.role] += 1
    return counts


def missing_roles(symbols: Sequence[str]) -> Tuple[str, ...]:
    """1系列も無い役割。ここが空のまま地盤を語らない。"""
    counts = roles_present(symbols)
    return tuple(role for role in ROLES if counts[role] == 0)
