"""適時開示の表題から、価格を動かす会社の行為を拾う。

**「索引からは判定できない」は誤りだった。** 目録を作るとき短信で絞ったのは私で
（`keep = [i for i in items if is_tanshin(...)]`）、索引そのものは全件を持っている。
実測（2026-08-04、1日ぶん）:

    総345件 = 決算短信97件 + 適時開示248件
      公開買付/TOB 5 / 新株予約権 6 / 第三者割当 3 / 株式併合 1
      株式分割 3 / 単元株式数 1 / 株主優待 4 / 業績予想の修正 18

しかもその日の開示に「サツドラＨＤに対する公開買付けの結果」があり、サツドラＨＤは
独立監査が「2026-06-22・06-23 に連続2日ストップ高で寄らず」と特定した銘柄である。
**値動きの理由が索引に書いてあった。**

**表題だけで判定する。** 本文は取りに行かない（31日で消えるうえ、種別を知るには
表題で足りる）。表題は種別を言うが、**中身は言わない**——「株式分割に関するお知らせ」
は分割比率を言わないし、「公開買付けの開始」は成立するかを言わない。だから
**種別のフラグとして持ち、値としては使わない。**
"""

import re
import unicodedata
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# 種別と、表題に現れる語。**訂正・中止・結果は別扱いにする**——「公開買付けの中止」を
# 「TOBがあった」と数えると、値動きの説明が逆になる。
ACTIONS: Dict[str, str] = {
    "tender_offer": r"公開買付|ＴＯＢ",
    "share_consolidation": r"株式併合",
    "share_split": r"株式分割",
    "warrant": r"新株予約権|ストックオプション",
    "third_party_allotment": r"第三者割当",
    "public_offering": r"公募|売出",
    "merger_or_exchange": r"株式交換|株式移転|吸収合併|合併契約",
    "board_lot_change": r"単元株式数",
    "shareholder_benefit": r"株主優待",
    "treasury_stock": r"自己株式",
    "forecast_revision": r"業績予想.{0,8}修正|配当予想.{0,8}修正",
    "delisting": r"上場廃止|監理銘柄|整理銘柄",
}

# 表題の性質。**同じ「公開買付」でも、開始と中止では値動きの向きが逆になる。**
STAGES: Dict[str, str] = {
    "correction": r"^[（(【]?訂正",
    "withdrawal": r"中止|撤回|不成立|延期",
    "result": r"結果|完了|終了|払込",
}

MD_NOTE = "表題だけで判定している。種別は言うが中身（比率・成否）は言わない"


def normalise(title: str) -> str:
    return "".join(unicodedata.normalize("NFKC", title or "").split())


def stage_of(title: str) -> str:
    """開示が何の段階か。`announcement` が既定。"""
    flat = normalise(title)
    for stage, pattern in STAGES.items():
        if re.search(pattern, flat):
            return stage
    return "announcement"


def actions_in(title: str) -> Tuple[str, ...]:
    """表題に現れる種別。**1つの表題が複数を持つことがある**——
    「株式分割、定款の一部変更及び配当予想の修正」のような複合表題は実在する。"""
    flat = normalise(title)
    return tuple(sorted(name for name, pattern in ACTIONS.items()
                        if re.search(pattern, flat)))


def collect(items: Sequence[Mapping[str, object]],
            codes: Optional[Iterable[str]] = None) -> List[dict]:
    """索引1日ぶんから、会社の行為を拾う。

    `codes` を渡すとその銘柄だけに絞る。**決算短信は除く**——短信そのものは
    コーポレートアクションではないし、既に別の経路で扱っている。
    """
    from earnings_research.timing.tdnet_index import is_tanshin, short_code, unwrap_url

    wanted = {short_code(c) for c in codes} if codes else None
    out = []
    for item in items:
        title = str(item.get("title") or "")
        if is_tanshin(title):
            continue
        kinds = actions_in(title)
        if not kinds:
            continue
        code = short_code(str(item.get("company_code") or ""))
        if code is None or (wanted is not None and code not in wanted):
            continue
        out.append({
            "ticker": code,
            "pubdate": item.get("pubdate"),
            "actions": list(kinds),
            "stage": stage_of(title),
            "title": title,
            "document_url": unwrap_url(str(item.get("document_url") or "")),
        })
    return out
