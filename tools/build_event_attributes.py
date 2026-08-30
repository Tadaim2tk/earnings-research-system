"""254件を、後から条件で切れる1行ずつにまとめる。

**新しく測らない。** 台帳・索引・セッション列・測定器の出力を、出どころを保った
まま束ねるだけである。

    python tools/build_event_attributes.py

出力は `data/analysis/event_attributes.jsonl`。文書の本文もタイトルも入らない
（`~/.ers-corpus/` に置いてある。このリポジトリは public である）。
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

    timing = {}
    for line in TIMING.open(encoding="utf-8"):
        row = json.loads(line)
        timing[(row["ticker"], row["event_date"])] = row

    sessions = {}
    for line in SESSIONS.open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("sessions"):
            sessions[(row["code"], row["event_date"])] = {
                s["offset"]: s for s in row["sessions"]}

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
        rows.append(B.build(
            record, timing.get(key), sessions.get(key), found,
            forecast_revision=(found or {}).get("forecast_revision")))

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
