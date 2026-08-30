"""イベント1件を、後から条件で切れる形にまとめる。

**なぜ要るか。** 価格系列が壊れうる原因を1つずつ潰していくと、潰すたびに全部を
やり直すことになる。分割を調べ、次に配当を調べ、次にストップ高を調べる——その
たびに「では分割の無い銘柄だけで測り直すと」と全件を回すのでは進まない。

**候補を属性として持たせておけば、切るだけで済む。** 「金曜の決算だけ」「場中に
出たものだけ」「ストップ高でない日に約定できたものだけ」を、後から組み合わせて
確かめられる。

**階層で持つ。** 平たい辞書に30個並べると、どれが観測でどれが導出かが読めなく
なる。出どころごとに分ける:

    identity      誰の、いつのイベントか
    disclosure    いつ・どう公表されたか（索引から）
    ledger        当時の人の判断（旧OSの台帳から）
    narrative     文書から抜いた事実（測定器から。版を明記）
    price         約定と出口（セッション列から）
    regime        その期間の地盤（20系列から）
    quality       この行を信用してよいかの目印

**`quality` は空欄を許さない。** 調べていない項目は `"unknown"` であって
`false` ではない。`false` は「調べて、無かった」を意味する。
"""

from typing import Dict, Optional, Sequence, Tuple

SCHEMA_VERSION = "event_attributes_v1"

# 東証の立会時間。2024年11月から後場は15:30まで。開示時刻をここで区切る。
# `timing/models.py::classify` は日付ごとの実際の時間を使うが、こちらは
# 台帳の窓（2026年6〜8月）に限った集計なので固定値で足りる。変えるときは
# 両方を動かすこと。
MORNING_OPEN = (9, 0)
MORNING_CLOSE = (11, 30)
AFTERNOON_OPEN = (12, 30)
AFTERNOON_CLOSE = (15, 30)

SESSION_CLASSES = ("pre_open", "morning", "lunch", "afternoon", "post_close", "unknown")

# 品質の目印。**調べていないことを「無い」と書かない。**
QUALITY_STATES = ("clean", "suspect", "unknown")

# 出口。名前はセッション番号で、保有本数ではない（`lookahead.COMPARISON_AXIS`）。
EXIT_OFFSETS: Tuple[int, ...] = (3, 4, 5, 7, 12, 22)
ENTRY_OFFSET = 2
SESSIONS_HELD: Dict[int, int] = {3: 1, 4: 2, 5: 3, 7: 5, 12: 10, 22: 20}


def session_class(hour: int, minute: int) -> str:
    """開示時刻がどの時間帯か。

    **引けちょうど（15:30）は引け後に数える。** 235件のうち128件（54.5%）が
    15:30ちょうどで、この一点の規約に分類が大きく依存する。後場側に倒すと
    「引け後でない」が 27.7% から 82% に増える。`timing/models.py::classify` が
    `local >= regular_close → post_close` としているのに合わせてある。
    """
    at = hour * 60 + minute
    if at < MORNING_OPEN[0] * 60 + MORNING_OPEN[1]:
        return "pre_open"
    if at < MORNING_CLOSE[0] * 60 + MORNING_CLOSE[1]:
        return "morning"
    if at < AFTERNOON_OPEN[0] * 60 + AFTERNOON_OPEN[1]:
        return "lunch"
    if at < AFTERNOON_CLOSE[0] * 60 + AFTERNOON_CLOSE[1]:
        return "afternoon"
    return "post_close"


def decision_close_is_clean(klass: str) -> Optional[bool]:
    """「決算日の終値を見てから判断する」が成り立つか。

    引け後に出たものだけが成り立つ。場中や昼休みに出たものは、**その日の終値に
    もう反応が入っている**ので、終値を見て判断したことにならない。実測で27.7%が
    これに当たる。`None` は時刻が取れなかったことを表す。
    """
    if klass == "unknown":
        return None
    return klass == "post_close"
