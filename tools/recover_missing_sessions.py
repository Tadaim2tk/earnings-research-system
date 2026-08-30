"""価格が取れていなかったイベントを回収する。

**既存の記録は上書きしない。** `legacy_event_sessions.jsonl` は取得済みの史料で、
`AGENTS.md` が上書きを禁じている。補遺として別ファイルに書き、どのイベントを
なぜ取り直したかを一緒に残す。

回収できたのは2種類の取りこぼしである（2026-08-30、独立監査が発見）:

**5桁のまま渡していた4件。** `34010` 帝人 / `52010` AGC / `64400` JUKI /
`67410` 日本信号。台帳に4桁形が存在しないので、`80310`（三井物産、`8031` と重複）
と違って**重複ではなく、単に価格取得から落ちていた**。5件すべてがソース行番号
#186〜#190 の連続ブロックで、5つのタイプミスではなく**TDnetの5桁表記が一度に
紛れ込んだ一箇所の事故**である。

**東証以外に上場している1件。** `3977` フュージョンは札証アンビシャス単独
（`markets_string: 札`、索引の表示名は `Ａ－フュージョン`）。`{code}.T` の規約が
当たらない。`3977.S` で取れる。

    python tools/recover_missing_sessions.py --out data/market_prices/recovered_sessions.jsonl

回収できないものは残る: `…`（社名も `…` のプレースホルダ）と `80310_dup`
（重複行の目印。`8031` と同一開示・同一 digest）。**どちらも「取れなかった」のでは
なく「そもそもイベントではない」ので、回収の対象にしない。**
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

JST = timezone(timedelta(hours=9))
SESSIONS = ROOT / "data/market_prices/legacy_event_sessions.jsonl"
LEDGER = ROOT / "data/historical_research/earnings_research_os/v1/legacy_records.jsonl"
DEFAULT_OUT = ROOT / "data/market_prices/recovered_sessions.jsonl"

# 台帳のコードと、実際に取りに行くシンボル。**なぜそう直すのかを一緒に持つ。**
RECOVERY = {
    "34010": ("3401.T", "five_digit_tdnet_form", "帝人"),
    "52010": ("5201.T", "five_digit_tdnet_form", "AGC"),
    "64400": ("6440.T", "five_digit_tdnet_form", "JUKI"),
    "67410": ("6741.T", "five_digit_tdnet_form", "日本信号"),
    "3977": ("3977.S", "non_tse_venue", "フュージョン（札証アンビシャス単独）"),
}
# 回収しないもの。**取れなかったのではなく、イベントではない。**
NOT_AN_EVENT = {
    "…": "社名もコードもプレースホルダ",
    "80310_dup": "重複行の目印。8031 と同一開示・同一 content_sha256",
    "80310": "8031 と同一開示。重複計上になるので取らない",
}

FIRST_OFFSET, LAST_OFFSET = -1, 45


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and not args.replace:
        print("%s は既に在る。置き換えるなら --replace を明示すること。" % out, file=sys.stderr)
        return 2

    have = set()
    for line in SESSIONS.open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("sessions"):
            have.add((row["code"], row["event_date"]))

    wanted = []
    for line in LEDGER.open(encoding="utf-8"):
        identity = json.loads(line)["normalized_identity"]
        code = identity.get("ticker_candidate")
        day = (identity.get("legacy_event_date") or "")[:10]
        if code and day and (code, day) not in have:
            wanted.append((code, day))

    import yfinance as yf

    rows, skipped = [], []
    for code, day in wanted:
        if code in NOT_AN_EVENT:
            skipped.append((code, day, NOT_AN_EVENT[code]))
            continue
        if code not in RECOVERY:
            skipped.append((code, day, "回収の仕方が分からない"))
            continue
        symbol, reason, label = RECOVERY[code]
        start = (datetime.fromisoformat(day) - timedelta(days=14)).date()
        end = (datetime.fromisoformat(day) + timedelta(days=95)).date()
        frame = yf.Ticker(symbol).history(start=str(start), end=str(end), auto_adjust=False)
        days = [(str(d.date()), row) for d, row in zip(frame.index, frame.itertuples())]
        anchor = next((n for n, (d, _) in enumerate(days) if d >= day), None)
        if anchor is None:
            skipped.append((code, day, "%s で該当日が取れない" % symbol))
            continue
        sessions = []
        for n, (d, row) in enumerate(days):
            offset = n - anchor
            if FIRST_OFFSET <= offset <= LAST_OFFSET:
                o, c = float(row.Open), float(row.Close)
                if o == o and c == c:
                    sessions.append({"offset": offset, "date": d,
                                     "open": o, "close": c})
        if not sessions:
            skipped.append((code, day, "%s の窓に値が無い" % symbol))
            continue
        by = {s["offset"]: s for s in sessions}
        rows.append({
            "schema_version": "recovered_event_sessions_v1",
            "code": code, "ticker": symbol, "event_date": day,
            "auto_adjust": False, "source": "yfinance",
            "status": "recovered",
            # **なぜ最初に落ちたのかを残す。** 直した事実だけでは、次に同じ形が
            # 来たときに気づけない。
            "recovery_reason": reason,
            "recovery_note": label,
            "first_offset": min(by), "sessions": sessions,
            "derived": {
                "prev_close": by.get(-1, {}).get("close"),
                "next_open": by.get(1, {}).get("open"),
                "next_close": by.get(1, {}).get("close"),
                "d5_close": by.get(5, {}).get("close"),
                "d20_close": by.get(20, {}).get("close"),
            },
            "fetched_at": datetime.now(JST).isoformat(),
        })
        print("  回収 %-10s %-12s %s  セッション%d本 (%s..%s)" %
              (code, symbol, day, len(sessions), sessions[0]["date"], sessions[-1]["date"]))

    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    out.with_suffix(".manifest.json").write_text(json.dumps({
        "schema_version": "recovered_event_sessions_manifest_v1",
        "supplements": SESSIONS.name,
        "note": "既存の記録は上書きしない。取りこぼしを別ファイルで補う",
        "source": "yfinance", "auto_adjust": False,
        "recovered": len(rows),
        "not_recovered": [{"code": c, "event_date": d, "why": w} for c, d, w in skipped],
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "fetched_at": datetime.now(JST).isoformat(),
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("\n回収 %d件 → %s" % (len(rows), out))
    print("回収しない %d件:" % len(skipped))
    for c, d, w in skipped:
        print("  %-10s %s  %s" % (c, d, w))
    return 0


if __name__ == "__main__":
    sys.exit(main())
