"""短信から定性情報の本文を取り出す。目次を掴まない。

見出しの最初の一致は**目次**のことが多い。目次は点線とページ番号の列で、本文は
散文である。実測でこれを踏んだ——「経営成績等の概況」の最初の一致が目次の行で、
そこから600字を取ると章立てと数字だけが並んだ。

だから位置ではなく**中身**で選ぶ。見出しの後ろを見て、句点が多く数字と点線が
少ないものを本文とみなす。見つからなければ `None` を返す。埋めない——目次を
本文として渡すと、そこから先の採点が全部無意味になり、しかも値は出るので
気づけない。
"""

import re
from typing import Optional

HEADINGS = (
    r"経営成績に関する説明",
    r"経営成績等の概況",
    r"定性的情報",
    r"当四半期.{0,6}経営成績",
    r"当中間期の経営成績",
)
HEAD_RE = re.compile("|".join(HEADINGS))

# 定性情報の後ろに来る章。ここで切らないと財務諸表の数字を読ませることになる。
STOP_RE = re.compile(
    r"(財政状態に関する説明|財政状態の概況|連結財務諸表|要約.{0,6}財務諸表|"
    r"継続企業の前提|注記事項|キャッシュ・フローの状況)"
)

# 判定に使う窓と、返す本文の上限。上限は文脈の長さと採点時間の折り合いで、
# 変えると測定器そのものが変わる（`instrument` の digest に入っている）。
PROBE_CHARS = 600
BODY_CHARS = 2600
MIN_BODY_CHARS = 300
# 切り出しの規則を変えたらここを上げる。過去の採点と混ざらないようにするため。
SECTION_RULE_VERSION = "narrative_section_v1"


def prose_score(chunk: str) -> float:
    """散文らしさ。目次は数字と点ばかりで、句点が少ない。"""
    if not chunk:
        return 0.0
    dots = chunk.count("…") + chunk.count("・・")
    digit_ratio = sum(c.isdigit() for c in chunk) / len(chunk)
    return chunk.count("。") * 3.0 - dots * 2.0 - digit_ratio * 40.0


def narrative_section(text: str) -> Optional[str]:
    """本文らしい定性情報。見つからなければ `None`。

    最も散文らしい見出しを選ぶ。同点なら先に出たものを採る。
    """
    best, best_score = None, 0.0
    for match in HEAD_RE.finditer(text or ""):
        score = prose_score(text[match.end(): match.end() + PROBE_CHARS])
        if score > best_score:
            best_score, best = score, match
    if best is None or best_score <= 0:
        return None
    body = text[best.start(): best.start() + BODY_CHARS]
    # 切った結果が最小長を割るなら切らない。割るということは、そこは本文の
    # 終わりではなく見出しの近くを掴んでいるということである。
    stop = STOP_RE.search(body, MIN_BODY_CHARS)
    if stop is not None and stop.start() >= MIN_BODY_CHARS:
        body = body[: stop.start()]
    body = body.strip()
    return body if len(body) >= MIN_BODY_CHARS else None
