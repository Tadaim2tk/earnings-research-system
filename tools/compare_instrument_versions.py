"""2つの測定器の版を、同じ文書で比べる。

版を変えたら測り直す、だけでは足りない。**変えた結果が良くなったのか悪く
なったのかを見ないと、劣化した版を採用してしまう。** 実際に一度やった——
「無ければ空配列」という一文を足した版で、理由の列挙が壊れた。

    python tools/compare_instrument_versions.py <旧版> <新版>

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

    shared = [k for k in sorted(a)
              if k in b and a[k]["status"] == "extracted" == b[k]["status"]]
    print("%s → %s" % (args.before, args.after))
    print("両版で抽出できた文書: %d件\n" % len(shared))
    if not shared:
        return 1

    print("閉じた語彙（一致率）")
    for field in sorted(I.FIELDS):
        same = sum(1 for k in shared if a[k]["facts"][field] == b[k]["facts"][field])
        print("  %-18s %3d/%3d (%3.0f%%)" % (field, same, len(shared), 100 * same / len(shared)))

    print("\n理由の列挙（0件率と平均件数）")
    for field in I.LISTS:
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
