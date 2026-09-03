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

from datetime import date
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
    "not_yet_observable",       # **まだその日が来ていない。** 終わったのではない
    "end_unconfirmed",          # 系列が端より前で切れているが、終了の証拠は無い
    "ended_before_exit",        # 出口の前に系列が終わった（保有中に消えた）
    "gap_at_exit",              # 系列は続いているが出口の日だけ無い
    "source_unavailable",       # そもそも系列を取れていない
)

# 系列が終わった理由。索引の適時開示から引く。**分からないときは `unknown`。**
# `none` は「調べて、該当する開示が無かった」を意味する。
END_REASONS = ("tender_offer", "delisting", "merger_or_exchange", "none", "unknown")


class UnknownState(ValueError):
    """定義していない状態名を書こうとした。黙って通さない。"""


class MalformedDay(ValueError):
    """日付が `YYYY-MM-DD` でない。黙って辞書順で比べない。"""


def _checked_day(value: object) -> str:
    """`YYYY-MM-DD` の実在する日付として読む。読めなければ落とす。

    **辞書順の比較の前に検査する。** `"2026-8-28"` は `"2026-08-28"` より後ろに
    並ぶので、窓の内側の日が `starts_after_window` に化ける。`\d` では全角数字も
    通ってしまうので、`date.fromisoformat` で読んだうえで正準な表記かを確かめる。
    `regime.align._checked_day` と同じ規約。
    """
    if not isinstance(value, str):
        raise MalformedDay(repr(value))
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MalformedDay(value) from exc
    if parsed.isoformat() != value:
        raise MalformedDay(value)
    return value


def coverage_state(first: Optional[str], last: Optional[str],
                   window_first: str, window_last: str) -> str:
    """銘柄の系列が窓をどこまで覆っているか。

    `first`/`last` が `None` は取得できていない場合で、**空の系列を
    「窓の外で上場した」と読み替えない。**
    """
    # **窓の検査を先にする。** 取れなかった銘柄の早期returnを先に置くと、
    # 壊れた窓（逆順・不正な表記）でも「取得できなかった」ともっともらしく
    # 返ってしまい、**設定の誤りが銘柄ごとのデータの有無に左右される**。
    window_first = _checked_day(window_first)
    window_last = _checked_day(window_last)
    if window_first > window_last:
        raise MalformedDay("%s..%s" % (window_first, window_last))
    if first is None or last is None:
        return "source_unavailable"
    first = _checked_day(first)
    last = _checked_day(last)
    if first > last:
        raise MalformedDay("%s..%s" % (first, last))
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
                 series_last: Optional[str],
                 observed_through: Optional[str] = None,
                 series_ended: Optional[bool] = None,
                 ended_on: Optional[str] = None,
                 series_complete: Optional[bool] = None) -> str:
    """1つの出口について、測れたか・測れないならなぜか。

    `entry_day` / `exit_day` は系列上で実際に値が取れた日で、取れなければ
    `None`。`sessions_after_entry` は建てた日より後に系列が持っている営業日数。
    `observed_through` は**データ全体が届いている最後の日**（個々の銘柄ではなく、
    取得した集合の端）。

    **「系列が終わった」は最終日との比較では出せない。** 出口はセッション番号で
    決まるので、必要な本数が系列に残っているかを数える。建てた日が最終日より
    前でも、残りが3本しか無ければ20本の出口には届かない。

    **本数が足りない理由は2つあり、混ぜてはいけない。**

        まだその日が来ていない   → `not_yet_observable`（待てば埋まる）
        系列が途中で終わった     → `ended_before_exit`（待っても埋まらない）

    直近の決算は、20営業日ぶんの将来がまだ存在しないというだけで、上場は
    続いている。これを「保有中に消えた」と記録すると、**新しいイベントほど
    廃止されたように見える**。`observed_through` を渡さなければ区別を主張せず、
    従来どおり `ended_before_exit` を返す——**推測で埋めない。**

    **端より前で切れていることも、終了の証拠ではない。** 休場・売買停止・その
    銘柄だけの取得の欠けが同じ形を作る。`series_ended=True`（上場廃止の開示など
    外から確かめた事実）が無ければ `end_unconfirmed` に留める。証拠なしに
    「終わった」と書くと、上場が続いている銘柄が消えた側のコホートに入り、
    直そうとした生存バイアスを逆向きに入れることになる。

    **「終わった」と「この出口より前に終わった」は別の主張である。**
    `series_ended=True` が示すのは前者だけで、後者は本数の数え方に依存する。
    系列に内部の欠けがあると `sessions_after_entry` は実際より少なく出るので、
    出口を越えて売買していた銘柄でも本数が足りなく見える。時点を主張するには
    次のどちらかが要る。

    `ended_on`        確かめた最終立会。系列の最終日と一致すれば、末尾は欠けて
                      いない。
    `series_complete` この窓で系列に欠けが無いことを確認済み。

    どちらも無ければ `end_unconfirmed` に留める。**数えた本数が少ないことを、
    終わった時点の証拠に流用しない。**
    """
    if series_last is None:
        return "source_unavailable"
    if entry_day is None:
        return "no_price_at_entry"
    _checked_day(entry_day)
    if exit_day is not None:
        # **`measured` の経路でも日付を検査する。** ここを素通りさせると、
        # `"2026-02-30"` や出口が建てより前の行が、もっともらしいコホートへ
        # そのまま入る。
        entry_checked = _checked_day(entry_day)
        exit_checked = _checked_day(exit_day)
        if exit_checked < entry_checked:
            raise MalformedDay("%s..%s" % (entry_checked, exit_checked))
        return "measured"
    if sessions_after_entry is None:
        return "source_unavailable"
    if sessions_after_entry < sessions_needed:
        # **確かめた終了を先に見る。** 端の比較を先にすると、確定した最終立会が
        # たまたまデータの端と同じ日だった銘柄が「まだ来ていない」側に入る。
        # 実際には出口へ届かない。
        if series_ended is True:
            # 終わったことは分かっても、この出口より前かは本数の数え方に依存する。
            # 欠けが無いと確かめられた場合だけ、時点を主張する。
            if series_complete is True:
                return "ended_before_exit"
            if ended_on is not None and \
                    _checked_day(series_last) == _checked_day(ended_on):
                return "ended_before_exit"
            return "end_unconfirmed"
        if observed_through is None:
            return "ended_before_exit"
        if _checked_day(series_last) >= _checked_day(observed_through):
            return "not_yet_observable"
        # **端より前で切れていることは、終了の証拠ではない。**
        # 休場・売買停止・その銘柄だけの取得の欠けが、同じ形を作る。証拠なしに
        # `ended_before_exit` と書くと、上場が続いている銘柄が「消えた」側の
        # コホートに入り、**直そうとした生存バイアスを逆向きに入れる**。
        return "end_unconfirmed"
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
