"""254件を、後から条件で切れる1行ずつにまとめる。

**新しく測らない。** 台帳・索引・セッション列・測定器の出力を、出どころを保った
まま束ねるだけである。

    python tools/build_event_attributes.py --facts-version <測定器の版>

出力は `data/analysis/event_attributes.jsonl`。文書の本文もタイトルも入らない
（`~/.ers-corpus/` に置いてある。このリポジトリは public である）。

**`--facts-version` を省いたまま既定の出力先へは書かない。** 省くと narrative は
空になり、記録済みの102件の測定が `not_extracted` で置き換わる。ふつうの作り直しの
つもりで歴史的記録を消すことになるので、断る。測定器なしで組みたいときは
`--out` で別の宛先を明示すること。
"""

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.attributes import build as B  # noqa: E402
from earnings_research.attributes.schema import SCHEMA_VERSION  # noqa: E402

LEDGER = ROOT / "data/historical_research/earnings_research_os/v1/legacy_records.jsonl"
TIMING = ROOT / "data/timing/legacy_event_timing.jsonl"
SESSIONS = ROOT / "data/market_prices/legacy_event_sessions.jsonl"
# 取りこぼしを別ファイルで補う（`tools/recover_missing_sessions.py`）。既存の
# 記録は上書きしないので、読む側で束ねる。
RECOVERED = ROOT / "data/market_prices/recovered_sessions.jsonl"

# 回収ファイルは**なぜ落ちたか**を具体的に書く（`five_digit_tdnet_form`）。属性は
# **どう扱うか**の閉じた語彙で持つ（`code_format_error`）。粒度が違うので、変換を
# ここに明示する。黙って通すと、綴りの違う値が `unknown` のまま溜まる。
ACTIONS = ROOT / "data/analysis/corporate_actions.jsonl"

RECOVERY_TO_RESOLUTION = {
    "five_digit_tdnet_form": "code_format_error",
    "non_tse_venue": "non_tse_venue",
}
FACTS = Path.home() / ".ers-corpus/facts"
DEFAULT_OUT = ROOT / "data/analysis/event_attributes.jsonl"


def load_facts(version: str):
    """指定した版の抽出結果。版を跨いで混ぜない。"""
    out = {}
    for path in glob.glob(str(FACTS / version / "*.json")):
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        key = (record.get("ticker"), record.get("event_date"))
        out[key] = record
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts-version", default=None,
                    help="測定器の版。省略すると narrative は空になる")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    # **測定器の版を指定せずに、記録済みの出力先を上書きしない。**
    # 版を省くと narrative が全件 `not_extracted` になる。既定の宛先には
    # 102件の測定が入っているので、ふつうの作り直しのつもりで歴史的記録を
    # 消すことになる（AGENTS.md「記録・確定値・決定・訂正・取消・レビューを
    # 上書きしない」）。測定器なしで組みたいなら宛先を明示させる。
    if not args.facts_version and Path(args.out).resolve() == DEFAULT_OUT.resolve():
        print("--facts-version が要る。省くと narrative が空になり、%s の"
              "測定が消える。測定器なしで組むなら --out で別の宛先を指定すること。"
              % DEFAULT_OUT.relative_to(ROOT), file=sys.stderr)
        return 2

    timing = {}
    for line in TIMING.open(encoding="utf-8"):
        row = json.loads(line)
        timing[(row["ticker"], row["event_date"])] = row

    sessions, price_source, ticker_fix = {}, {}, {}
    for line in SESSIONS.open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("sessions"):
            key = (row["code"], row["event_date"])
            sessions[key] = {s["offset"]: s for s in row["sessions"]}
            price_source[key] = "original"
    if RECOVERED.exists():
        for line in RECOVERED.open(encoding="utf-8"):
            row = json.loads(line)
            key = (row["code"], row["event_date"])
            sessions[key] = {s["offset"]: s for s in row["sessions"]}
            price_source[key] = "recovered"
            ticker_fix[key] = row.get("recovery_reason")

    actions = {}
    if ACTIONS.exists():
        for line in ACTIONS.open(encoding="utf-8"):
            row = json.loads(line)
            actions.setdefault(row["ticker"], []).append(row)

    facts = load_facts(args.facts_version) if args.facts_version else {}
    if args.facts_version and not facts:
        print("版 %s の抽出結果が無い" % args.facts_version, file=sys.stderr)
        return 2

    rows = []
    for line in LEDGER.open(encoding="utf-8"):
        record = json.loads(line)
        identity = record.get("normalized_identity", {})
        key = (identity.get("ticker_candidate"),
               (identity.get("legacy_event_date") or "")[:10])
        found = facts.get(key)
        timing_row = timing.get(key)
        reason = ticker_fix.get(key)
        resolution = RECOVERY_TO_RESOLUTION[reason] if reason else None
        if resolution is None:
            selection = (timing_row or {}).get("selection")
            if selection == "unresolved_code":
                resolution = "placeholder"
            elif key[0] == "80310":
                resolution = "duplicate"
            elif key in sessions:
                resolution = "resolved"
        rows.append(B.build(
            record, timing_row, sessions.get(key), found,
            forecast_revision=(found or {}).get("forecast_revision"),
            actions=actions.get((key[0] or "")[:4]),
            ticker_resolution=resolution,
            price_source=price_source.get(key),
            # 分割は調整されている。3091 が 2026-06-29 に 1:2 分割していて
            # 終値 2240→2235 に段差が無いことで確かめた（独立監査、2026-08-30）。
            split_state="adjusted" if key in sessions else None,
            # セッション列に土日・祝日は無く、窓内の営業日の抜けも0件だった。
            event_date_is_business_day=True if key in sessions else None,
            duplicate_of="8031@2026-08-04" if key[0] in ("80310", "80310_dup") else None))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    import collections
    print("%s  %d件 → %s" % (SCHEMA_VERSION, len(rows), out))
    for path, label in (("disclosure.session_class", "開示の時間帯"),
                        ("disclosure.timing_status", "時刻の状態"),
                        ("narrative.status", "抽出の状態")):
        counts = collections.Counter()
        for row in rows:
            cursor = row
            for step in path.split("."):
                cursor = (cursor or {}).get(step) if isinstance(cursor, dict) else None
            counts[cursor] += 1
        print("  %s: %s" % (label, dict(counts.most_common())))
    covered = collections.Counter(len(r["price"]["covered"]) for r in rows)
    print("  価格の揃い方（出口の本数）: %s" % dict(sorted(covered.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
