"""地盤の日次系列を取る。

**適用範囲。** `PROSPECTIVE_OPERATIONS.md` の 2026-08-29 改訂により、Yahoo からの
日次取得は**引退記録の研究に限って**許される。この出力は baseline / lock /
evidence / scoring / 売買のどれにも接続しない。説明と監査のための背景であって、
判断に使う層ではない。

    python tools/build_regime_daily.py --start 2026-05-01 --end 2026-09-01

系列ごとに取れた日が違う（暗号資産は土日も動き、先物は休みが別）ので、欠けた日を
埋めない。埋めると、動かなかったのか観測しなかったのかが後から区別できなくなる。
"""

import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.regime.series import SERIES, UNAVAILABLE, missing_roles  # noqa: E402

JST = timezone(timedelta(hours=9))
DEFAULT_OUT = ROOT / "data/regime"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    daily, manifest = out / "daily.jsonl", out / "manifest.json"
    if daily.exists() and not args.replace:
        print("%s は既に在る。置き換えるなら --replace を明示すること。" % daily, file=sys.stderr)
        return 2

    import yfinance as yf

    closes, fetched, failed = {}, [], []
    for s in SERIES:
        try:
            h = yf.Ticker(s.symbol).history(start=args.start, end=args.end, auto_adjust=False)
        except Exception as exc:
            failed.append({"symbol": s.symbol, "reason": str(exc)[:120]}); continue
        rows = {str(d.date()): float(c) for d, c in zip(h.index, h["Close"]) if c == c}
        if not rows:
            failed.append({"symbol": s.symbol, "reason": "空"}); continue
        closes[s.symbol] = rows
        fetched.append(s.symbol)
        print("  %-10s %-12s %4d日  %s..%s" %
              (s.symbol, s.name, len(rows), min(rows), max(rows)))

    missing = missing_roles(fetched)
    if missing:
        # 役割が1つでも空なら地盤を名乗らせない。株だけ見て説明を外したのが
        # そもそもの発端である。
        print("\n役割が埋まっていない: %s — 出力を作らない。" % ", ".join(missing), file=sys.stderr)
        return 1

    days = sorted({d for rows in closes.values() for d in rows})
    out.mkdir(parents=True, exist_ok=True)
    tmp = daily.with_suffix(".part")
    with tmp.open("w", encoding="utf-8") as fh:
        for day in days:
            got = {sym: rows[day] for sym, rows in closes.items() if day in rows}
            fh.write(json.dumps({"date": day, "closes": got,
                                 "observed": len(got)}, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(daily)

    manifest.write_text(json.dumps({
        "schema_version": "regime_daily_v1",
        "scope": "retired-record research only; not connected to baseline/lock/evidence/scoring",
        "source": "yfinance",
        "retrieved_at": datetime.now(JST).isoformat(),
        "start": args.start, "end": args.end,
        "series_fetched": sorted(fetched),
        "series_failed": failed,
        "unavailable_axes": UNAVAILABLE,
        "days": len(days),
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("\n%d系列 / %d日 → %s" % (len(fetched), len(days), daily))
    if failed:
        print("取れなかった系列:")
        for f in failed:
            print("  %-10s %s" % (f["symbol"], f["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
