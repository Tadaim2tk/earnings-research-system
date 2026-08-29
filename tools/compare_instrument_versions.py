"""2つの測定器の版を、同じ文書で比べる。

版を変えたら測り直す、だけでは足りない。**変えた結果が良くなったのか悪く
なったのかを見ないと、劣化した版を採用してしまう。** 実際に一度やった——
「無ければ空配列」という一文を足した版で、理由の列挙が壊れた。

    python tools/compare_instrument_versions.py <旧版> <新版>

**成否の移り変わりを先に出す。** 新しいプロンプトで `unreadable` になった文書を
比較から外すと、悪くなったぶんが消えて「変わっていない」ように見える——この
ツールが防ぐはずの失敗そのものである。実際に一度やった: v2→v3 で読めない文書が
4件から7件へ増えていたのに、生き残りだけで統計を出していた。

**項目の集合も版に含まれる。** 版が項目を足したり外したりすれば、古い記録に
その鍵は無い。現在のモジュールの定義で両方を引くと落ちるので、共通する項目だけ
比べ、増えた項目と消えた項目は別に挙げる。

方向のような閉じた語彙は一致率で、理由の列挙は0件率と平均件数で見る。
どちらが正しいかはここでは決めない——差が出た文書を挙げるので、原文と
突き合わせるのは人の仕事である。
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.narrative import instrument as I  # noqa: E402

FACTS = Path.home() / ".ers-corpus/facts"


def load(directory: Path):
    out = {}
    for path in sorted(directory.glob("*.json")):
        out[path.name] = json.loads(path.read_text(encoding="utf-8"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--facts", default=str(FACTS))
    ap.add_argument("--show", type=int, default=5)
    args = ap.parse_args()

    root = Path(args.facts)
    a, b = load(root / args.before), load(root / args.after)
    if not a or not b:
        print("版が見つからない", file=sys.stderr)
        return 2

    common = [k for k in sorted(a) if k in b]
    print("%s → %s" % (args.before, args.after))
    print("両版にある文書: %d件\n" % len(common))
    if not common:
        return 1

    # 成否の移り変わりを先に。生き残りだけを比べると、劣化が消える。
    print("成否（全文書）")
    before_ok = sum(1 for k in common if a[k]["status"] == "extracted")
    after_ok = sum(1 for k in common if b[k]["status"] == "extracted")
    print("  抽出できた   %3d → %3d  (%+d)" % (before_ok, after_ok, after_ok - before_ok))
    moves = {}
    for k in common:
        before, after = a[k]["status"], b[k]["status"]
        if before != after:
            moves.setdefault((before, after), []).append(k)
    if moves:
        for (before, after), keys in sorted(moves.items()):
            print("  %-12s → %-12s %3d件" % (before, after, len(keys)))
            for key in keys[:args.show]:
                reason = b[key].get("reason") or a[key].get("reason") or ""
                print("     %-22s %s" % (key[:-5], reason[:40]))
    else:
        print("  移動なし")

    shared = [k for k in common if a[k]["status"] == "extracted" == b[k]["status"]]
    if not shared:
        print("\n両版で抽出できた文書が無い。")
        return 1
    print("\n両版で抽出できた %d件について:" % len(shared))

    # 項目の集合も版に含まれる。共通するものだけ比べ、差は別に挙げる。
    fields_a = set().union(*(set(a[k]["facts"]) for k in shared))
    fields_b = set().union(*(set(b[k]["facts"]) for k in shared))
    added, removed = sorted(fields_b - fields_a), sorted(fields_a - fields_b)
    if added or removed:
        print("  項目の変化: 増えた %s / 消えた %s" % (added or "なし", removed or "なし"))
    shared_fields = fields_a & fields_b

    print("\n閉じた語彙（一致率）")
    for field in sorted(f for f in I.FIELDS if f in shared_fields):
        same = sum(1 for k in shared if a[k]["facts"][field] == b[k]["facts"][field])
        print("  %-18s %3d/%3d (%3.0f%%)" % (field, same, len(shared), 100 * same / len(shared)))

    print("\n理由の列挙（0件率と平均件数）")
    for field in (f for f in I.LISTS if f in shared_fields):
        za = sum(1 for k in shared if not a[k]["facts"][field])
        zb = sum(1 for k in shared if not b[k]["facts"][field])
        ma = statistics.mean(len(a[k]["facts"][field]) for k in shared)
        mb = statistics.mean(len(b[k]["facts"][field]) for k in shared)
        lost = [k for k in shared if a[k]["facts"][field] and not b[k]["facts"][field]]
        gained = [k for k in shared if not a[k]["facts"][field] and b[k]["facts"][field]]
        print("  %-10s 0件 %3d→%3d   平均 %.2f→%.2f   失った%3d件 / 得た%3d件"
              % (field, za, zb, ma, mb, len(lost), len(gained)))
        for key in lost[:args.show]:
            print("     失: %-22s %s" % (key[:-5], a[key]["facts"][field][:2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
