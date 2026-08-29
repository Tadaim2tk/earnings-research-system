"""地盤の日次系列を取る。

**適用範囲。** `PROSPECTIVE_OPERATIONS.md`「退役済み史料の研究」により、Yahoo からの
日足取得は**凍結記録に対する後知恵の集計に限って**認められる。同節が保存の形も
定めている——`data/market_prices/` に置き、日足のセッション列（日付・始値・終値）
のみとし、provider・銘柄表記・取得時刻・窓・digest を manifest に記録する。
この出力は baseline / lock / evidence / scoring / 実売買のどれにも接続しない。

    python tools/build_regime_daily.py --start 2026-05-01 --end 2026-09-01

**上書きしない。** 走らせるたびに新しい版を作る。Yahoo が過去を書き換えることが
あり、上書きすると「そのとき何が見えていたか」が消える。取得時刻を記録する意味も
無くなる。

系列ごとに開いている日が違う（暗号資産は土日も動き、先物は休みが別）ので、欠けた
日を埋めない。埋めると、動かなかったのか観測しなかったのかが後から区別できない。
"""

import argparse
import hashlib
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
DEFAULT_OUT = ROOT / "data/market_prices/regime_sessions"
SCHEMA = "regime_sessions_v1"


def next_snapshot(directory: Path, start: str, end: str) -> Path:
    """まだ使われていない版のパス。既存には触れない。"""
    stem = "%s_%s" % (start.replace("-", ""), end.replace("-", ""))
    for revision in range(1, 1000):
        candidate = directory / ("%s_r%d.jsonl" % (stem, revision))
        if not candidate.exists():
            return candidate
    raise RuntimeError("版が尽きた: %s" % stem)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    try:
        import yfinance as yf
    except ImportError:
        print('yfinance が無い。`pip install -e ".[research]"` で入る。', file=sys.stderr)
        return 2

    sessions, fetched, failed = {}, [], []
    for s in SERIES:
        try:
            h = yf.Ticker(s.symbol).history(start=args.start, end=args.end, auto_adjust=False)
        except Exception as exc:
            failed.append({"symbol": s.symbol, "reason": str(exc)[:120]}); continue
        rows = {}
        for day, row in zip(h.index, h.itertuples()):
            o, c = float(row.Open), float(row.Close)
            if o == o and c == c:                       # NaN を落とす
                rows[str(day.date())] = {"open": o, "close": c}
        if not rows:
            failed.append({"symbol": s.symbol, "reason": "空"}); continue
        sessions[s.symbol] = rows
        fetched.append(s.symbol)
        print("  %-10s %-12s %4d日  %s..%s" %
              (s.symbol, s.name, len(rows), min(rows), max(rows)))

    missing = missing_roles(fetched)
    if missing:
        # 役割が1つでも空なら地盤を名乗らせない。株だけ見て説明を外したのが
        # そもそもの発端である。
        print("\n役割が埋まっていない: %s — 出力を作らない。" % ", ".join(missing), file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = next_snapshot(out, args.start, args.end)

    days = sorted({d for rows in sessions.values() for d in rows})
    lines = []
    for day in days:
        got = {sym: rows[day] for sym, rows in sessions.items() if day in rows}
        lines.append(json.dumps({"date": day, "sessions": got, "observed": len(got)},
                                ensure_ascii=False, sort_keys=True))
    body = "\n".join(lines) + "\n"
    snapshot.write_text(body, encoding="utf-8")

    manifest = snapshot.with_suffix(".manifest.json")
    manifest.write_text(json.dumps({
        "schema_version": SCHEMA,
        "scope": "退役済み史料の研究。baseline/lock/evidence/scoring/実売買に接続しない",
        "source": "yfinance",
        "auto_adjust": False,
        "ticker_convention": "Yahoo Finance のシンボル表記をそのまま使う",
        "window": "%s 以上 %s 未満（要求値。実際の観測日は系列ごとに異なる）" % (args.start, args.end),
        "requested_start": args.start,
        "requested_end": args.end,
        "fetched_at": datetime.now(JST).isoformat(),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "series_fetched": sorted(fetched),
        "series_failed": failed,
        "unavailable_axes": UNAVAILABLE,
        "days": len(days),
        "snapshot": snapshot.name,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("\n%d系列 / %d日 → %s" % (len(fetched), len(days), snapshot.name))
    print("digest %s" % hashlib.sha256(body.encode("utf-8")).hexdigest()[:16])
    if failed:
        print("取れなかった系列:")
        for f in failed:
            print("  %-10s %s" % (f["symbol"], f["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
