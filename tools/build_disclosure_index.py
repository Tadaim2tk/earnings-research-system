"""適時開示の索引を、日ごとに丸ごと保存する。

**集める段階で絞らない。** `~/.ers-corpus/tdnet/` は決算短信しか持っていない。
前の収集が `is_tanshin` で漉していたためで、そのせいで「増資・TOB・単元変更は
原理的に判定できない」という誤った結論を書いた。源は全件を持っている。

一度取れば、会社の行為も、上場廃止の理由も、同日に何本出たかも、取り直さずに
数え直せる。**絞るのは読む側の仕事で、集める側の仕事ではない。**

    python tools/build_disclosure_index.py --start 2021-01-01 --end 2026-08-28

出力は `~/.ers-corpus/tdnet_full/YYYY-MM-DD.json.gz`。既に在る日は飛ばすので、
途中で止めても続きから走る。**取れなかった日は書かない** — 空ファイルを置くと
「その日は何も無かった」と読めてしまう。
"""

import argparse
import gzip
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.timing import tdnet_index as ix  # noqa: E402

OUT = Path(os.path.expanduser("~/.ers-corpus/tdnet_full"))
JST = timezone(timedelta(hours=9))
UA = "EarningsResearchSystem-Research/1.0"
PAUSE = 0.8


def fetch(day, timeout=90):
    """その日の索引を全件。切り捨てられていたら上限を上げて取り直す。"""
    for limit in (4000, 12000):
        request = urllib.request.Request(ix.date_url(day, limit), headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            items = ix.items_from(json.loads(response.read().decode("utf-8")))
        if not ix.truncated(items, limit):
            return items
        time.sleep(PAUSE)
    raise RuntimeError("%s: 上限12000でも切り捨てられている" % day)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    day, stop = date.fromisoformat(args.start), date.fromisoformat(args.end)
    # **その日の開示が出そろう前に取ると、空の応答を「確かめた不在」にする。**
    # しかも一度書くと既存として飛ばすので、後から出た開示は永久に入らない。
    # `build_corporate_actions.py` と同じ検査をここにも置く。
    today_jst = datetime.now(JST).date()
    if stop >= today_jst:
        print("--end は %s 以前の完了した日にすること（JSTで本日は %s）。"
              "当日を含めると、まだ出ていない開示を『無かった』として固定する。"
              % (today_jst - timedelta(days=1), today_jst), file=sys.stderr)
        return 2
    fetched = skipped = 0
    failed = []
    while day <= stop:
        # **週末を飛ばさない。** 飛ばしたまま manifest が連続した範囲を名乗ると、
        # 土日に出たTOBや分割の開示が「調べて無かった」に化ける。次の立会に効く
        # 材料なので、落とすと `contaminated=false` を誤って付ける。
        path = OUT / ("%s.json.gz" % day)
        if path.exists():
            skipped += 1
            day += timedelta(days=1)
            continue
        try:
            items = fetch(day.isoformat())
        except Exception as exc:
            failed.append((str(day), "%s: %s" % (type(exc).__name__, str(exc)[:60])))
            day += timedelta(days=1)
            continue
        tmp = path.with_suffix(".part")          # 途中で死んだ断片を本番名に置かない
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False)
        tmp.rename(path)
        fetched += 1
        if fetched % 50 == 0:
            print("  取得 %d日 / 既存 %d日 / 失敗 %d日  (いま %s, 索引%d件)"
                  % (fetched, skipped, len(failed), day, len(items)), flush=True)
        time.sleep(PAUSE)
        day += timedelta(days=1)

    print("取得 %d日 / 既存を飛ばした %d日 / 取れなかった %d日" % (fetched, skipped, len(failed)))
    if failed:
        # **0 で終えない。** 束ねて回すと「成功した」と読まれ、欠けた日を持った
        # まま下流が走る。空ファイルを置かない判断と、終了コードを揃える。
        print("\n取れなかった日（空ファイルは置いていない。もう一度走らせれば拾い直す）:",
              file=sys.stderr)
        for d, why in failed[:40]:
            print("  %s %s" % (d, why), file=sys.stderr)
        if len(failed) > 40:
            print("  ほか %d日" % (len(failed) - 40), file=sys.stderr)
        return 1
    print("索引の取得終了", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
