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

from datetime import date
from typing import Dict, Optional, Sequence, Tuple

SCHEMA_VERSION = "event_attributes_v1"

# 東証の立会時間。**後場の終わりは日付で変わる。**
#
# 2024-11-05 に 15:00 から 15:30 へ延びた。索引の実測で境目が出る:
# 2024-11-01 は 15:00 が36件・15:30 が11件、2024-11-05 は 15:00 が12件・
# 15:30 が46件。間に営業日は無い（11/2-3 が週末、11/4 が振替休日）。
#
# **固定値で区切ると2021〜2024年が壊れる。** 当時の15:00発表は引け後だが、
# 15:30固定では「後場の取引中」に化ける。実測では2021〜2023年の最頻時刻が
# 15:00（40〜42%）、2025〜2026年が15:30（42%）で、固定値のままだと
# `afternoon` が 58% と 22% の間で理由なく跳ねる。
MORNING_OPEN = (9, 0)
MORNING_CLOSE = (11, 30)
AFTERNOON_OPEN = (12, 30)
AFTERNOON_CLOSE_BEFORE_EXTENSION = (15, 0)
AFTERNOON_CLOSE = (15, 30)
CLOSE_EXTENDED_FROM = "2024-11-05"

SESSION_CLASSES = ("pre_open", "morning", "lunch", "afternoon", "post_close", "unknown")

# 品質の目印。**調べていないことを「無い」と書かない。**
QUALITY_STATES = ("clean", "suspect", "unknown")

# 出口。名前はセッション番号で、保有本数ではない（`lookahead.COMPARISON_AXIS`）。
EXIT_OFFSETS: Tuple[int, ...] = (3, 4, 5, 7, 12, 22)
ENTRY_OFFSET = 2
SESSIONS_HELD: Dict[int, int] = {3: 1, 4: 2, 5: 3, 7: 5, 12: 10, 22: 20}


class MalformedDay(ValueError):
    """日付が `YYYY-MM-DD` でない。黙って別の日の立会時間を使わない。"""


def _checked_day(value: object) -> date:
    """`YYYY-MM-DD` の実在する日付として読む。読めなければ落とす。

    **`\\d` で検査しない。** 正規表現の `\\d` は全角数字を通すので、
    `"2024-１1-05"` が素通りして別の境界を選んでしまう。`date.fromisoformat`
    で読んだうえで、元の文字列が正準な表記そのものかを確かめる。
    `regime.features.iso_day` と同じ規約で、両者が一致することを試験で縛る。
    """
    if not isinstance(value, str):
        raise MalformedDay(repr(value))
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MalformedDay(value) from exc
    if parsed.isoformat() != value:
        raise MalformedDay(value)
    return parsed


def afternoon_close(day: str) -> Tuple[int, int]:
    """その日の後場の終わり。`CLOSE_EXTENDED_FROM` の当日から15:30。"""
    if _checked_day(day) < _checked_day(CLOSE_EXTENDED_FROM):
        return AFTERNOON_CLOSE_BEFORE_EXTENSION
    return AFTERNOON_CLOSE


def session_class(hour: int, minute: int, day: str) -> str:
    """開示時刻がどの時間帯か。**日付が要る。**

    **引けちょうどは引け後に数える。** 2026年の台帳235件のうち128件（54.5%）が
    15:30ちょうどで、この一点の規約に分類が大きく依存する。後場側に倒すと
    「引け後でない」が 27.7% から 82% に増える。`timing/models.py::classify` が
    `local >= regular_close → post_close` としているのに合わせてある。

    **`day` を省略できるようにしない。** 既定値を置くと、2021年の15:00発表が
    黙って `afternoon` になる。呼ぶ側に日付を持たせて、境界を選ばせる。
    """
    close = afternoon_close(day)
    at = hour * 60 + minute
    if at < MORNING_OPEN[0] * 60 + MORNING_OPEN[1]:
        return "pre_open"
    if at < MORNING_CLOSE[0] * 60 + MORNING_CLOSE[1]:
        return "morning"
    if at < AFTERNOON_OPEN[0] * 60 + AFTERNOON_OPEN[1]:
        return "lunch"
    if at < close[0] * 60 + close[1]:
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
