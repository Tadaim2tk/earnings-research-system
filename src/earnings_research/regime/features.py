"""ある区間の地盤を数える。判定はしない。

返すのは観測であって分類ではない。`safe_haven` のようなラベルを付けたくなるが、
TSO の SPEC-CAR-001 が非活性ゲート（clean評価30件以上・4資産以上・20日以上）を
満たすまで断定しないと決めており、ERS はまだどれも満たしていない。
"""

import math
import statistics
from datetime import date
from typing import Dict, Mapping, Optional, Sequence, Tuple

from earnings_research.regime.series import BY_SYMBOL, DIVERGENCE, missing_roles

class MalformedWindow(ValueError):
    """窓の境界が `YYYY-MM-DD` でない。黙って別の日を測らない。"""


def iso_day(value) -> bool:
    """`YYYY-MM-DD` の実在する日付か。

    **辞書順で比べているので、書式が崩れると窓が壊れる。** 実測: `end` を
    `2026-8-25`（ゼロ埋め1つ欠け）にすると `"2026-8-25" > "2026-08-27"` が真に
    なり、要求の2日先が終端に選ばれた。銀 +19.02% → +20.40%、銅 +3.00% → +1.12%
    と、ERS-ADR-0066 が結論の根拠にした2つの数字が両方動く。

    正規表現の `\d{4}-\d{2}-\d{2}` では足りない。Python の `\d` は**全角数字を
    含む**ので `2026-０8-25` が通り、全角のゼロは ASCII の数字より後ろに並ぶため
    `"2026-０8-25" > "2026-12-31"` が真になる——塞いだはずの汚染がそのまま戻る。
    `2026-99-99` や `2026-02-30` も通ってしまう。

    暦として解釈できること、かつ**書き戻したときに同じ文字列になること**を求める。
    後者は Python 3.11 以降の `fromisoformat` が `20260825` のような別表記も
    受けるためで、辞書順の比較は表記が揃っていないと意味を持たない。
    """
    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


# 「動いた」と言える大きさ。これ未満は動いていない側に数える。
MOVE_THRESHOLD_PCT = 5.0
# 乖離を言うために、静かな側がどれだけ静かである必要があるか。
QUIET_THRESHOLD_PCT = 3.5


def resolve_endpoints(closes: Mapping[str, float], start: str, end: str
                      ) -> Optional[Tuple[str, str]]:
    """要求した境界を、その系列が実際に観測した日へ寄せる。

    系列ごとに開いている日が違う。暗号資産は土日も動き、先物は休みが別で、
    日本株は東京の休場に従う。**日付をそのまま引くと、境界が週末に落ちた瞬間に
    その系列だけ窓が消える。** 実測でこれを踏んだ——`2026-08-01` は土曜で、
    その日に値を持つのは暗号資産だけだった。株・ボラ・金利・為替・貴金属・
    産業金属が全部「観測なし」になり、銀と銅の乖離が出なくなる。

    開始は要求日**以降**の最初の観測日、終了は要求日**以前**の最後の観測日。
    外側へ広げないので、窓の外の値を混ぜない——**ただし日付が `YYYY-MM-DD` である
    限りにおいて**。比較は辞書順なので、書式が崩れると順序そのものが壊れる。
    崩れていたら測らずに `MalformedWindow` を上げる。

    同じ日に寄ってしまった場合（観測が1日しか無い）も `None` を返す。1点から
    区間の騰落は出ない。以前は `first == last` を通して 0.00% を返しており、
    **「動かなかった」と「1日しか見ていない」が区別できなかった**。
    """
    for boundary in (start, end):
        if not iso_day(boundary):
            raise MalformedWindow("窓の境界は実在する YYYY-MM-DD で渡すこと: %r" % (boundary,))
    days = sorted(d for d, c in closes.items()
                  if c is not None and math.isfinite(c) and iso_day(d))
    if not days:
        return None
    first = next((d for d in days if d >= start), None)
    last = next((d for d in reversed(days) if d <= end), None)
    if first is None or last is None or first >= last:
        return None
    return first, last


def window_move(closes: Mapping[str, float], start: str, end: str) -> Optional[float]:
    """区間の騰落率(%)。観測日へ寄せて測る。欠けていれば `None`。埋めない。"""
    resolved = resolve_endpoints(closes, start, end)
    if resolved is None:
        return None
    a, b = closes[resolved[0]], closes[resolved[1]]
    if a == 0:
        return None
    return (b / a - 1.0) * 100.0


def realised_vol(closes: Mapping[str, float], days: Sequence[str]) -> Optional[float]:
    """日次騰落の母標準偏差(%)。差分が2本に満たなければ `None`。

    以前は値の数（3点未満）でも弾いていたが、**その条件は到達しない**。n個の値
    から作れる差分は多くてもn−1本なので、値が3点未満なら差分は必ず2本未満になり、
    下の条件が先に効く。docstring も「2日未満」と書いており、コードの3点とも
    食い違っていた。数えているのは差分の本数である。
    """
    values = [closes[d] for d in days if d in closes and math.isfinite(closes[d])]
    steps = [(values[i] / values[i - 1] - 1.0) * 100.0
             for i in range(1, len(values)) if values[i - 1]]
    return statistics.pstdev(steps) if len(steps) >= 2 else None


def divergences(moves: Mapping[str, Optional[float]]) -> Tuple[Dict[str, object], ...]:
    """片方が動いて片方が動かなかった組。

    今日この判定が答えを決めた——銀 +19.0% に対し銅 +3.0%。両方上がっていれば
    産業需要の話になり、結論が変わっていた。
    """
    found = []
    for moved_symbol, quiet_symbol, meaning in DIVERGENCE:
        moved, quiet = moves.get(moved_symbol), moves.get(quiet_symbol)
        if moved is None or quiet is None:
            continue
        if abs(moved) >= MOVE_THRESHOLD_PCT and abs(quiet) <= QUIET_THRESHOLD_PCT:
            found.append({
                "moved": moved_symbol, "moved_pct": round(moved, 2),
                "quiet": quiet_symbol, "quiet_pct": round(quiet, 2),
                "meaning": meaning,
            })
    return tuple(found)


def summarise(closes_by_symbol: Mapping[str, Mapping[str, float]],
              start: str, end: str) -> Dict[str, object]:
    """区間の地盤。分類名は付けない。

    `insufficient_axes` は正直な既定値で、どれかの役割が1系列も無ければ立つ。
    埋まっていない軸を黙って0として扱わない。
    """
    moves = {sym: window_move(closes, start, end)
             for sym, closes in closes_by_symbol.items()}
    # どの系列をどの日で測ったか。要求した境界と一緒に残す——寄せた結果を
    # 黙って要求どおりに見せない。
    resolved = {sym: resolve_endpoints(closes, start, end)
                for sym, closes in closes_by_symbol.items()}
    got = [sym for sym, move in moves.items() if move is not None]
    missing = missing_roles(got)
    ranked = sorted(((abs(m), s, m) for s, m in moves.items() if m is not None), reverse=True)
    return {
        "requested_start": start, "requested_end": end,
        "resolved": {sym: {"start": r[0], "end": r[1]}
                     for sym, r in sorted(resolved.items()) if r is not None},
        "start": start, "end": end,
        "series_observed": len(got),
        "missing_roles": list(missing),
        "insufficient_axes": bool(missing),
        "moves_pct": {s: round(m, 2) for s, m in sorted(moves.items()) if m is not None},
        "unobserved": sorted(s for s, m in moves.items() if m is None),
        "largest_moves": [{"symbol": s, "name": BY_SYMBOL[s].name if s in BY_SYMBOL else s,
                           "pct": round(m, 2)} for _, s, m in ranked[:5]],
        "divergences": list(divergences(moves)),
    }
