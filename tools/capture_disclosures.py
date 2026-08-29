"""公開された短信の本文を、消える前に確保する。

**なぜ毎日走らせるのか。** `www.release.tdnet.info` は文書を約31日で落とす
（2026-08-29 実測: 16日前は 200、46日前は 404、1年前も 404）。索引は2019年まで
遡れるのに本文は残らないので、**後から集めることはできない**。実際、254件の台帳の
うち132件は気づいた時点で既に失われていた。1日あたり約8件である。

    python tools/capture_disclosures.py --days 3

**既定は台帳にある銘柄だけ。** `release.tdnet.info` の robots は `Disallow: /` で、
索引が渡したURLに限った取得は ERS-ADR-0046 で Human が明示的に承認したが、それは
1社・四半期1本の文脈だった。全短信は1日250本で30倍になる。規模の変更は人の判断
なので、`--all` を明示しない限り広げない。

保存するのは抽出テキストと sha256 まで。PDF本体は残さない
（`raw_document_retained: false`）。採点はしない——ここは確保だけで、
評価は凍結した scoring_version の仕事である。
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.document_analysis.guarded_fetch import GuardedDocumentFetcher  # noqa: E402
from earnings_research.document_analysis.pdf import extract_pdf  # noqa: E402
from earnings_research.timing import tdnet_index as ix  # noqa: E402

LEDGER = ROOT / "data/historical_research/earnings_research_os/v1/legacy_records.jsonl"
DEFAULT_STORE = Path.home() / ".ers-corpus/documents"
UA = "EarningsResearchSystem-Research/1.0"
# 索引は取得側の礼儀として間を置く。文書取得も同様。
INDEX_PAUSE = 0.8
DOCUMENT_PAUSE = 1.2


def ledger_codes():
    codes = set()
    for line in LEDGER.open(encoding="utf-8"):
        code = json.loads(line)["normalized_identity"].get("ticker_candidate")
        resolved = ix.short_code(code)
        if resolved:
            codes.add(resolved)
    return codes


def fetch_index(day, timeout=90):
    import urllib.request
    for limit in (1000, 4000, 12000):
        request = urllib.request.Request(ix.date_url(day, limit), headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            items = ix.items_from(json.loads(response.read()))
        if not ix.truncated(items, limit):
            return items
    raise RuntimeError("%s: 索引が上限に張り付いた" % day)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3,
                    help="今日から何日ぶん遡るか。週末と一度の失敗を吸収する")
    ap.add_argument("--all", action="store_true",
                    help="台帳の銘柄に限らず全短信を取る。規模が30倍になる")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--today", default=None, help="基準日（試験用）")
    args = ap.parse_args()

    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)
    universe = None if args.all else ledger_codes()
    today = date.fromisoformat(args.today) if args.today else date.today()
    print("基準 %s / %d日ぶん / 対象 %s" %
          (today, args.days, "全短信" if universe is None else "台帳の%d銘柄" % len(universe)))

    fetcher = GuardedDocumentFetcher()
    saved = skipped = expired = failed = 0
    for back in range(args.days):
        day = (today - timedelta(days=back)).isoformat()
        try:
            items = fetch_index(day)
        except Exception as exc:
            print("  %s 索引が取れない: %s" % (day, str(exc)[:80]), file=sys.stderr)
            failed += 1
            continue
        time.sleep(INDEX_PAUSE)

        wanted = []
        for item in items:
            if not ix.is_tanshin(item.get("title", "")) or ix.is_correction(item.get("title", "")):
                continue
            code = ix.short_code(item.get("company_code", ""))
            if code is None or (universe is not None and code not in universe):
                continue
            url = ix.unwrap_url(item.get("document_url"))
            if url:
                wanted.append((code, url, item))
        print("  %s  索引%5d件  対象%3d件" % (day, len(items), len(wanted)))

        for code, url, item in wanted:
            stamp = (item.get("pubdate") or "")[:10] or day
            path = store / ("%s_%s.json" % (code, stamp))
            if path.exists():
                skipped += 1
                continue
            try:
                with fetcher.pdf(url) as pdf_path:
                    extracted = extract_pdf(pdf_path)
            except Exception as exc:
                message = str(exc)
                if "404" in message:
                    expired += 1        # 窓の外。取り返せないので数えるだけ。
                else:
                    failed += 1
                    print("    失敗 %s %s: %s" % (code, stamp, message[:80]), file=sys.stderr)
                time.sleep(DOCUMENT_PAUSE)
                continue
            text = "\n".join(extracted.pages)
            tmp = path.with_suffix(".part")
            tmp.write_text(json.dumps({
                "ticker": code,
                "event_date": stamp,
                "announced_at": item.get("pubdate"),
                "document_url": url,
                "pdf_sha256": extracted.sha256,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "pages": len(extracted.pages),
                "chars": len(text),
                "captured_at": datetime.now().astimezone().isoformat(),
                "text": text,
            }, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            saved += 1
            time.sleep(DOCUMENT_PAUSE)

    print("\n確保 %d / 既存 %d / 窓の外 %d / 失敗 %d" % (saved, skipped, expired, failed))
    # 失敗しても 0 で終える。1日取り逃しても翌日 --days が拾い直す。
    return 0


if __name__ == "__main__":
    sys.exit(main())
