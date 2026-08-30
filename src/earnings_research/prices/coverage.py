"""価格系列がどこまで在るかと、測れなかったときの理由。

**落とさない。** 上場廃止になった銘柄を外すと、残るのは生き残った会社だけに
なる。5年で消えた会社の決算を除いて測ったリターンは、必ず上振れする。
2021年に決算を出して2023年に消えた会社も、決算を出した事実は変わらない。

**「取れなかった」と「無い」を分ける。** バッチ取得の取りこぼしを
`source_unavailable` ではなく「系列が終わった」と書くと、生きている会社が
上場廃止に化ける。実測で、取得に失敗した336銘柄のうち118銘柄は2026年も決算を
出していた。個別に取り直せば取れる。

**出口の前に系列が終わったことは、欠測ではなく結果である。** 保有中に上場廃止に
なれば、その建玉は予定した本数では手仕舞えていない。これを「測れなかった」と
して除くと、消えた側の損益が丸ごと落ちる。理由を付けて残す。
"""

from typing import Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "price_coverage_v1"

# 銘柄ごとの被覆。**`source_unavailable` は「その会社の株価が存在しない」では
# ない。** 取りに行って取れなかった、という取得側の事情である。
COVERAGE_STATES = (
    "covered",              # 窓の端から端まで在る
    "starts_after_window",  # 窓の途中から始まる（新規上場の候補）
    "ends_before_window",   # 窓の途中で終わる（上場廃止の候補）
    "partial_both_ends",    # 始まりも終わりも窓の内側
    "source_unavailable",   # 取り直しても取れなかった
)

# イベント1件・出口1つごとの測定の可否。
RETURN_STATES = (
    "measured",
    "no_price_at_entry",        # 建てる日の値が無い
    "ended_before_exit",        # 出口の前に系列が終わった（保有中に消えた）
    "gap_at_exit",              # 系列は続いているが出口の日だけ無い
    "source_unavailable",       # そもそも系列を取れていない
)

# 系列が終わった理由。索引の適時開示から引く。**分からないときは `unknown`。**
# `none` は「調べて、該当する開示が無かった」を意味する。
END_REASONS = ("tender_offer", "delisting", "merger_or_exchange", "none", "unknown")


class UnknownState(ValueError):
    """定義していない状態名を書こうとした。黙って通さない。"""


def coverage_state(first: Optional[str], last: Optional[str],
                   window_first: str, window_last: str) -> str:
    """銘柄の系列が窓をどこまで覆っているか。

    `first`/`last` が `None` は取得できていない場合で、**空の系列を
    「窓の外で上場した」と読み替えない。**
    """
    if first is None or last is None:
        return "source_unavailable"
    late = first > window_first
    early = last < window_last
    if late and early:
        return "partial_both_ends"
    if late:
        return "starts_after_window"
    if early:
        return "ends_before_window"
    return "covered"


def return_state(entry_day: Optional[str], exit_day: Optional[str],
                 sessions_after_entry: Optional[int], sessions_needed: int,
                 series_last: Optional[str]) -> str:
    """1つの出口について、測れたか・測れないならなぜか。

    `entry_day` / `exit_day` は系列上で実際に値が取れた日で、取れなければ
    `None`。`sessions_after_entry` は建てた日より後に系列が持っている営業日数。

    **「系列が終わった」は最終日との比較では出せない。** 出口はセッション番号で
    決まるので、必要な本数が系列に残っているかを数える。建てた日が最終日より
    前でも、残りが3本しか無ければ20本の出口には届かない。
    """
    if series_last is None:
        return "source_unavailable"
    if entry_day is None:
        return "no_price_at_entry"
    if exit_day is not None:
        return "measured"
    if sessions_after_entry is None:
        return "source_unavailable"
    if sessions_after_entry < sessions_needed:
        return "ended_before_exit"
    return "gap_at_exit"


def check(state: str, allowed: Sequence[str]) -> str:
    """状態名を検査して返す。綴り違いを黙って書き込ませない。"""
    if state not in allowed:
        raise UnknownState(state)
    return state


def survivorship_shape(states: Mapping[str, str]) -> Tuple[Tuple[str, int], ...]:
    """被覆の内訳。**除いた件数を数えずに「全体で測った」と言わないため。**"""
    counts = {name: 0 for name in COVERAGE_STATES}
    for value in states.values():
        counts[check(value, COVERAGE_STATES)] += 1
    return tuple((name, counts[name]) for name in COVERAGE_STATES)
