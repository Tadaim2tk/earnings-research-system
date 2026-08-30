"""業績予想の修正があったかを、短信の定型欄から読む。

**モデルに聞かない。** `outlook_mention` として尋ねていたものは、構造的に答えられ
なかった。業績予想の記述は短信の「（３）連結業績予想」にあり、`section.py` が
切り出す「経営成績に関する説明」の**外**である。入力に無いことを尋ねられた
モデルは、決算の好調さから「上方」を作った——実測で83件中52件が「上方」、原文に
修正の語があるのは2件だけだった。

短信には定型の欄がある:

    直近に公表されている業績予想からの修正の有無：有

確保した103件のうち **89件（86%）** にこの欄があり、有29% / 無57%。規則で読める
ものを推測させない。

**向きは読まない。** 欄が言うのは有無だけで、上方か下方かは書かれていない。
知るには数値の比較か、参照先の開示が要る。`outlook_mention` は「上方」という
向きまで答えさせていたが、その根拠は文書のどこにも無かった。
"""

import re
import unicodedata
from typing import Optional

# 定型欄。空白・改行・全半角の揺れを吸収してから当てる。PDFから抜いたテキストは
# 欄の途中で改行が入るので、詰めてから見る。
FIELD = re.compile(r"直近に公表されている業績予想からの修正の有無[:：]?([有無])")
# 表題が省略される様式もある。定型欄の核だけで拾う。
LOOSE = re.compile(r"業績予想からの修正の有無[^有無]{0,6}([有無])")

REVISED, UNREVISED = "有", "無"


def flatten(text: str) -> str:
    """比較用に詰める。NFKC で全半角を揃え、空白と改行を落とす。"""
    return "".join(unicodedata.normalize("NFKC", text or "").split())


def revision_flag(text: str) -> Optional[str]:
    """`"有"` / `"無"` / 欄が無ければ `None`。

    `None` は「修正が無かった」ではなく「**欄が読めなかった**」である。
    確保した103件のうち14件がこれに当たり、REIT やインフラファンドの様式、
    PDF のテキスト抽出が壊れているものが含まれる。
    """
    flat = flatten(text)
    found = FIELD.search(flat) or LOOSE.search(flat)
    return found.group(1) if found else None
