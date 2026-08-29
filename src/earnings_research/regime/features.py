"""ある区間の地盤を数える。判定はしない。

返すのは観測であって分類ではない。`safe_haven` のようなラベルを付けたくなるが、
TSO の SPEC-CAR-001 が非活性ゲート（clean評価30件以上・4資産以上・20日以上）を
満たすまで断定しないと決めており、ERS はまだどれも満たしていない。
"""

import math
import statistics
from typing import Dict, Mapping, Optional, Sequence, Tuple

from earnings_research.regime.series import BY_SYMBOL, DIVERGENCE, missing_roles

# 「動いた」と言える大きさ。これ未満は動いていない側に数える。
MOVE_THRESHOLD_PCT = 5.0
# 乖離を言うために、静かな側がどれだけ静かである必要があるか。
QUIET_THRESHOLD_PCT = 3.5


def window_move(closes: Mapping[str, float], start: str, end: str) -> Optional[float]:
    """区間の騰落率(%)。端が欠けていれば `None`。埋めない。"""
    a, b = closes.get(start), closes.get(end)
    if a is None or b is None:
        return None
    if not (math.isfinite(a) and math.isfinite(b)) or a == 0:
        return None
    return (b / a - 1.0) * 100.0


def realised_vol(closes: Mapping[str, float], days: Sequence[str]) -> Optional[float]:
    """日次騰落の母標準偏差(%)。2日未満なら `None`。"""
    values = [closes[d] for d in days if d in closes and math.isfinite(closes[d])]
    if len(values) < 3:
        return None
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
    got = [sym for sym, move in moves.items() if move is not None]
    missing = missing_roles(got)
    ranked = sorted(((abs(m), s, m) for s, m in moves.items() if m is not None), reverse=True)
    return {
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
