"""台帳の銘柄について、窓の期間の適時開示から会社の行為を拾う。

**目録を短信で絞ったのは私だった。** `~/.ers-corpus/tdnet/` は決算短信しか持って
いないが、索引そのものは全件を持っている。増資・TOB・単元変更が「原理的に判定
できない」というのは、自分の絞り込みを源の性質と取り違えた結論だった。

    python tools/build_corporate_actions.py --start 2026-06-01 --end 2026-08-31

出力は `data/analysis/corporate_actions.jsonl`。**表題までは残すが本文は取らない。**
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.timing import corporate_actions as CA  # noqa: E402
from earnings_research.timing import tdnet_index as ix  # noqa: E402

JST = timezone(timedelta(hours=9))
LEDGER = ROOT / "data/historical_research/earnings_research_os/v1/legacy_records.jsonl"
DEFAULT_OUT = ROOT / "data/analysis/corporate_actions.jsonl"
UA = "EarningsResearchSystem-Research/1.0"
PAUSE = 0.8


def ledger_codes():
    codes = set()
    for line in LEDGER.open(encoding="utf-8"):
        code = ix.short_code(
            json.loads(line)["normalized_identity"].get("ticker_candidate"))
        if code:
            codes.add(code)
    return codes


def fetch(day, timeout=90):
    for limit in (4000, 12000):
        request = urllib.request.Request(ix.date_url(day, limit),
                                         headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            items = ix.items_from(json.loads(response.read()))
        if not ix.truncated(items, limit):
            return items
    raise RuntimeError("%s: 索引が上限に張り付いた" % day)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and not args.replace:
        print("%s は既に在る。置き換えるなら --replace を明示すること。" % out, file=sys.stderr)
        return 2

    codes = ledger_codes()
    print("台帳 %d銘柄 / %s〜%s" % (len(codes), args.start, args.end))

    rows, failed = [], []
    day = date.fromisoformat(args.start)
    stop = date.fromisoformat(args.end)
    # **その日の開示がまだ出そろっていない日を「調べて何も無かった」にしない。**
    # `--end` が当日や未来だと、空の応答を完全な被覆として manifest に書く。
    # 実際に起きた: `corporate_actions.manifest.json` が `end=2026-08-31` を
    # 名乗る一方 `fetched_at` は 2026-08-30T13:23 で、**その後に出た開示が
    # 「確かめた不在」として扱われる**状態になっていた。
    today_jst = datetime.now(JST).date()
    if stop >= today_jst:
        print("--end は %s 以前の完了した日にすること（JSTで本日は %s）。"
              "当日を含めると、まだ出ていない開示を『無かった』と記録する。"
              % (today_jst - timedelta(days=1), today_jst), file=sys.stderr)
        return 2
    while day <= stop:
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        try:
            items = fetch(day.isoformat())
        except Exception as exc:
            failed.append((str(day), str(exc)[:80]))
            day += timedelta(days=1)
            continue
        found = CA.collect(items, codes)
        rows.extend(found)
        if found:
            print("  %s  索引%5d件  該当%2d件" % (day, len(items), len(found)))
        time.sleep(PAUSE)
        day += timedelta(days=1)

    if failed:
        # 取れない日があると「その日は何も無かった」と読めてしまう。書かずに終える。
        print("\n取得できない日がある。出力は作らない:", file=sys.stderr)
        for d, why in failed:
            print("  %s %s" % (d, why), file=sys.stderr)
        return 1

    # **表題とURLをリポジトリに置かない。** ERS-ADR-0079 は、取得元が保存・
    # 再配布について何も述べていないことを受けて「リポジトリ側は manifest と
    # digest だけを持つ」と決めた。**その決定を書いた同じPRで、428行すべてに
    # 表題と本文URLを入れていた。** このリポジトリは public である。
    #
    # 照合できるようにするため、表題の digest は残す。原文は
    # `~/.ers-corpus/tdnet_full/` に在る。
    published = []
    for row in rows:
        keep = {k: v for k, v in row.items() if k not in ("title", "document_url")}
        keep["title_sha256"] = hashlib.sha256(
            (row.get("title") or "").encode("utf-8")).hexdigest()
        published.append(keep)
    rows = published
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    out.with_suffix(".manifest.json").write_text(json.dumps({
        "schema_version": "corporate_actions_v1",
        "source": ix.SOURCE,
        "note": CA.MD_NOTE,
        "start": args.start, "end": args.end,
        "tickers": len(codes), "rows": len(rows),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "fetched_at": datetime.now(JST).isoformat(),
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    import collections
    kinds = collections.Counter(k for r in rows for k in r["actions"])
    stages = collections.Counter(r["stage"] for r in rows)
    print("\n%d件 → %s" % (len(rows), out))
    print("  種別: %s" % dict(kinds.most_common()))
    print("  段階: %s" % dict(stages.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
