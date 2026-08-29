"""254件の発表時刻を索引から確定させる。

選別は `timing.tdnet_index` にあり、ここは取得と書き出しだけを持つ。分けてある
のは、選別を網羅的にテストするためにネットワークを踏みたくないからで、混ぜると
テストのたびに索引を叩くか、叩かないために選別を飛ばすかのどちらかになる。

    python tools/build_tdnet_timing.py [--out PATH] [--sleep 1.0]

書き出すのは時刻・URL・取得時刻・索引行の指紋まで。タイトルも本文も残さない。
必要なのは「いつ発表されたか」であって開示の中身ではない。
"""

import argparse
import collections
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.timing import tdnet_index as ix  # noqa: E402

LEDGER = ROOT / "data/historical_research/earnings_research_os/v1/legacy_records.jsonl"
DEFAULT_OUT = ROOT / "data/timing/legacy_event_timing.jsonl"
UA = "EarningsResearchSystem-Research/1.0"
JST = timezone(timedelta(hours=9))


LIMITS = (1000, 4000, 12000)


def fetch(day, timeout=60):
    """上限に張り付いたら広げて取り直す。

    張り付いたまま返すと、切られた分の会社が `no_disclosure` になる——
    つまり黙って切られたものが「開示が無かった」として記録される。
    """
    items = []
    for limit in LIMITS:
        request = urllib.request.Request(ix.date_url(day, limit), headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            items = ix.items_from(json.loads(response.read()))
        if not ix.truncated(items, limit):
            return items, limit
    raise RuntimeError("%s: 索引が %d 件でも上限に張り付いた" % (day, LIMITS[-1]))


def ledger_events():
    seen = []
    for line in LEDGER.open(encoding="utf-8"):
        ident = json.loads(line)["normalized_identity"]
        code, day = ident.get("ticker_candidate"), (ident.get("legacy_event_date") or "")[:10]
        if code and day:
            seen.append((code, day, ident.get("company_name_candidate")))
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--replace", action="store_true",
                    help="既存の出力を置き換える。既定では拒否する")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and not args.replace:
        # 出力は provenance で、`source_observed_at` は「いつ見たか」の記録である。
        # 黙って上書きすると、確定済みの観測がその都度消える。
        print("%s は既に在る。置き換えるなら --replace を明示すること。" % out, file=sys.stderr)
        return 2

    events = ledger_events()
    by_day = collections.defaultdict(list)
    for code, day, name in events:
        by_day[day].append((code, name))
    print("台帳 %d件 / %d日" % (len(events), len(by_day)))

    rows, tally = [], collections.Counter()
    for n, day in enumerate(sorted(by_day), 1):
        try:
            items, used = fetch(day)
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            # 取得失敗を placeholder にして書き出すと、一度の不調で確定済みの
            # 記録が消える。1日でも取れなければ何も書かずに終える。
            print("  %s 取得失敗: %s" % (day, exc), file=sys.stderr)
            print("\n取得できない日があったので、出力は作らない。", file=sys.stderr)
            return 1
        observed = datetime.now(JST).isoformat()
        seen_today = collections.Counter()
        for code, name in by_day[day]:
            got = ix.select(items, code, day, expect_name=name)
            seen_today[got.status] += 1
            tally[got.status] += 1
            row = {
                "schema_version": "legacy_event_timing_v1",
                "ticker": code,
                "event_date": day,
                "selection": got.status,
                "source": ix.SOURCE,
                "source_url": ix.date_url(day, used),
                "source_observed_at": observed,
                "index_size": len(items),
                "same_day_candidates": got.candidates,
                "name_agrees": got.name_agrees,
                "corrections_seen": got.corrections,
            }
            if got.status == "matched":
                row["announced_at"] = got.announced_at.isoformat()
                row["document_url"] = got.document_url
                row["content_sha256"] = got.content_sha256
            rows.append(row)
        print("  [%2d/%2d] %s  索引%5d件(limit %d)  %s" %
              (n, len(by_day), day, len(items), used,
               " ".join("%s=%d" % (k, v) for k, v in sorted(seen_today.items()))))
        time.sleep(args.sleep)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print("\n=== 結果  %s" % out)
    for status, count in tally.most_common():
        print("  %-16s %3d" % (status, count))
    matched = [r for r in rows if r["selection"] == "matched"]
    print("\n確定 %d / %d 件 (%.0f%%)" % (len(matched), len(rows), 100 * len(matched) / max(1, len(rows))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
