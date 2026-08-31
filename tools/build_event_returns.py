"""索引の全イベントに、建て値と出口を付ける。**測れない行も理由付きで残す。**

規約は台帳のときと同じ:
  セッション0 = 開示日（その日が休場なら次の営業日）
  建て       = セッション2の**寄り付き**（終値判断→翌々営業日寄り付き）
  出口       = セッション 3/4/5/7/12/22 の**終値**
  名前は `lookahead.COMPARISON_AXIS` に従い、保有本数で呼ぶ（+22 = 20本保有）

**落とさない。** 上場廃止で系列が終わった行を除くと、残るのは生き残った会社の
決算だけになり、リターンが上振れする。測れないものは `return_state` で理由を
書いて残す（`prices.coverage`）。

    python tools/build_event_returns.py
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.attributes import schema as SC  # noqa: E402
from earnings_research.prices import coverage as COV  # noqa: E402

EVENTS = os.path.expanduser("~/.ers-corpus/events_2021_2026.jsonl")
PRICES = os.path.expanduser("~/.ers-corpus/market_prices.parquet")
OUT = os.path.expanduser("~/.ers-corpus/event_returns_2021_2026.jsonl")
ENTRY = SC.ENTRY_OFFSET          # 2
EXITS = SC.EXIT_OFFSETS          # (3, 4, 5, 7, 12, 22)


def main():
    px = pd.read_parquet(PRICES).sort_values(["code", "date"])
    by_code = {}
    for code, g in px.groupby("code", sort=False):
        by_code[code] = (g["date"].to_numpy(), g["open"].to_numpy(),
                         g["close"].to_numpy())
    print("価格を持つ銘柄 %d" % len(by_code), flush=True)

    counts = {name: 0 for name in COV.RETURN_STATES}
    written = 0
    with open(OUT, "w", encoding="utf-8") as w:
        for line in open(EVENTS, encoding="utf-8"):
            ev = json.loads(line)
            code, day = ev["code"], ev["date"]
            series = by_code.get(code)
            if series is None:
                row = dict(ev, entry_date=None, entry_open=None, returns={},
                           return_states={name: "source_unavailable" for name in
                                          (str(x) for x in EXITS)})
                counts["source_unavailable"] += len(EXITS)
                w.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
                continue
            dates, opens, closes = series
            zero = int(np.searchsorted(dates, day, side="left"))   # 開示日以降の最初の営業日
            last_day = dates[-1] if len(dates) else None
            entry_i = zero + ENTRY
            after = len(dates) - 1 - zero                          # セッション0より後に残る本数
            entry_date = dates[entry_i] if entry_i < len(dates) else None
            entry_open = float(opens[entry_i]) if entry_i < len(dates) and not np.isnan(opens[entry_i]) else None
            rets, states = {}, {}
            for off in EXITS:
                j = zero + off
                exit_close = float(closes[j]) if j < len(dates) and not np.isnan(closes[j]) else None
                exit_date = dates[j] if j < len(dates) else None
                state = COV.return_state(
                    entry_date if entry_open is not None else None,
                    exit_date if exit_close is not None else None,
                    after, off, last_day)
                states[str(off)] = state
                counts[state] += 1
                rets[str(off)] = (round(100 * (exit_close / entry_open - 1), 6)
                                  if state == "measured" and entry_open else None)
            w.write(json.dumps(dict(ev, entry_date=entry_date, entry_open=entry_open,
                                    returns=rets, return_states=states),
                               ensure_ascii=False) + "\n")
            written += 1
            if written % 20000 == 0:
                print("  %d件" % written, flush=True)

    total = sum(counts.values())
    print("\n%d件 × %d出口 = %d の測定について" % (written, len(EXITS), total))
    for name in COV.RETURN_STATES:
        print("   %-22s %8d  %5.1f%%" % (name, counts[name], 100 * counts[name] / total))
    print("\n→ %s (%.0fMB)" % (OUT, os.path.getsize(OUT) / 1e6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
