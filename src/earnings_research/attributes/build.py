"""イベント1件ぶんの属性を、既にある記録から組み立てる。

**新しく測らない。** 台帳・索引・セッション列・測定器の出力を、それぞれの出どころ
を保ったまま1つの行にまとめるだけである。ここで平均を取ったり判定を下したりする
と、後から「どの数字がどこから来たか」が読めなくなる。

組み立ては純粋関数にしてある。ファイルを読むのは `tools/build_event_attributes.py`。
"""

import math
from datetime import date, datetime
from typing import Any, Dict, Mapping, Optional, Sequence

from earnings_research.attributes.schema import (
    ENTRY_OFFSET,
    EXIT_OFFSETS,
    SCHEMA_VERSION,
    SESSIONS_HELD,
    decision_close_is_clean,
    session_class,
)

WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


def _weekday(day: str) -> Optional[str]:
    try:
        return WEEKDAYS[date.fromisoformat(day).weekday()]
    except (ValueError, TypeError):
        return None


def disclosure_block(timing: Optional[Mapping[str, Any]],
                     forecast_revision: Optional[str]) -> Dict[str, Any]:
    """いつ・どう公表されたか。索引から取った時刻に基づく。"""
    if not timing or timing.get("selection") != "matched":
        return {
            "announced_at": None,
            "session_class": "unknown",
            "weekday": None,
            "is_friday": None,
            # **なぜ時刻が無いのかを残す。** 「無い」で潰すと、索引の不足と
            # 台帳の日付ずれと重複行が区別できなくなる。
            "timing_status": (timing or {}).get("selection", "not_recorded"),
            "decision_close_is_clean": None,
            "forecast_revision": forecast_revision,
        }
    stamp = timing["announced_at"]
    when = datetime.fromisoformat(stamp)
    klass = session_class(when.hour, when.minute, when.strftime("%Y-%m-%d"))
    weekday = _weekday(stamp[:10])
    return {
        "announced_at": stamp,
        "session_class": klass,
        "weekday": weekday,
        "is_friday": weekday == "金" if weekday else None,
        "timing_status": "matched",
        "decision_close_is_clean": decision_close_is_clean(klass),
        "forecast_revision": forecast_revision,
        "name_agrees": timing.get("name_agrees"),
        "same_day_candidates": timing.get("same_day_candidates"),
    }


# 約定の寄りが前日終値からどれだけ飛んだか。**これが約定規約の壊れ方を測る。**
#
# 独立監査（2026-08-30）: 約定日そのものは246件すべて寄っており「約定できない」は
# 0件。壊れるのは **+1 が制限値幅で寄らないまま張り付いた8件**で、翌朝の寄りが
# 一気に窓を開ける。ギャップの中央値は 11.73%、それ以外の234件は 0.67% で**17.5倍**。
# 全246件の95パーセンタイルが 4.19% なので、8件は分布の完全な外側にある。
#
# 「+2の寄りで買う」が、この8件では**反応の大半を取り逃がした後の価格で買う**ことを
# 意味している。切って確かめられるように、値で持つ。
ENTRY_GAP_OUTLIER_PCT = 4.19


def _uncovered(entry_date: Optional[str]) -> Dict[str, Any]:
    """建てられなかった行。**部分的に取れた行と同じ形を返す。**

    `fully_covered` を省くと、`where(price__fully_covered=False)` がこの行を
    拾えない。実測で、8件の `no_session` が「覆えていない」の集計から漏れ、
    107件あるはずが99件と出ていた。**欄を落とすことは False ではない。**
    """
    return {"entry_date": entry_date, "entry_open": None, "returns": {},
            "covered": [], "prev_session_close": None, "entry_gap_pct": None,
            "entry_gap_is_outlier": None, "fully_covered": False}


def price_block(sessions: Optional[Mapping[int, Mapping[str, Any]]]) -> Dict[str, Any]:
    """約定と出口。**リターンは計算するが、集計はしない。**"""
    if not sessions or ENTRY_OFFSET not in sessions:
        return _uncovered(None)
    entry = sessions[ENTRY_OFFSET]
    open_ = entry.get("open")
    if not open_ or not math.isfinite(open_):
        return _uncovered(entry.get("date"))
    returns, covered = {}, []
    for offset in EXIT_OFFSETS:
        leg = sessions.get(offset)
        close = (leg or {}).get("close")
        if close and math.isfinite(close):
            held = SESSIONS_HELD[offset]
            returns["held_%d" % held] = round((close / open_ - 1.0) * 100, 4)
            covered.append(held)
    previous = sessions.get(ENTRY_OFFSET - 1) or {}
    prev_close = previous.get("close")
    gap = None
    if prev_close and math.isfinite(prev_close):
        gap = round((open_ / prev_close - 1.0) * 100, 4)
    return {
        "entry_date": entry.get("date"),
        "entry_open": open_,
        "prev_session_close": prev_close if prev_close and math.isfinite(prev_close) else None,
        # 約定の寄りが前日終値からどれだけ飛んだか。
        "entry_gap_pct": gap,
        # 分布の外側か。**閾値は全246件の95パーセンタイル**であって、
        # ストップ高安の判定ではない（それには高値安値が要る）。
        "entry_gap_is_outlier": (abs(gap) > ENTRY_GAP_OUTLIER_PCT) if gap is not None else None,
        # 名前は**保有本数**にする。`+5` はセッション番号で3本保有であり、
        # 「保有+5」と書いて5本と読まれた（公開したダッシュボードの誤り）。
        "returns": returns,
        "covered": covered,
        "fully_covered": len(covered) == len(EXIT_OFFSETS),
    }


def ledger_block(classifications: Mapping[str, Any]) -> Dict[str, Any]:
    """当時の人の判断。**ここは観測ではなく、比較の相手である。**"""
    return {
        "rank": classifications.get("legacy_rank"),
        "surprise": classifications.get("legacy_surprise"),
        "narrative": classifications.get("legacy_narrative"),
        "quarter": classifications.get("quarter"),
        "initial_reaction": classifications.get("initial_reaction"),
        "judge": classifications.get("legacy_judge"),
        "company_forecast": classifications.get("company_forecast_label"),
        "reason_codes": list(classifications.get("reason_codes") or []),
    }


def narrative_block(facts: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """文書から抜いた事実。**どの版で測ったかを必ず添える。**"""
    if not facts:
        return {"status": "not_extracted", "instrument_version": None}
    block = {
        "status": facts.get("status"),
        "instrument_version": facts.get("instrument_version"),
        "section_chars": facts.get("section_chars"),
    }
    if facts.get("status") == "extracted":
        block.update(facts.get("facts") or {})
    else:
        block["reason"] = facts.get("reason")
    return block


# 台帳のコードをどう解決したか。**2値にすると対処法が混ざる。** `3977` は `.S` で
# 取れ、`34010` は4桁に直せば取れ、`…` は解決できない——この3つは全部違う。
TICKER_RESOLUTIONS = (
    "resolved",              # そのまま取れた
    "code_format_error",     # 5桁のまま渡していた。4桁に直せば取れる
    "non_tse_venue",         # 東証以外。接尾辞が違う（札証は `.S`）
    "renamed_ledger_stale",  # 社名が古い。コードは有効
    "duplicate",             # 別の行と同一の開示を指す
    "placeholder",           # そもそもイベントではない
    "unknown",
)

# 分割は調整されている（`auto_adjust=False` でも）。3091 が 2026-06-29 に 1:2
# 分割していて終値 2240→2235 に段差が無いことで確かめた。**「分割が無い」ではなく
# 「分割は調整済み」である。**
SPLIT_STATES = ("adjusted", "none_in_window", "unadjusted", "unknown")


def corporate_actions_block(actions: Optional[Sequence[Mapping[str, Any]]],
                            event_date: Optional[str],
                            entry_date: Optional[str],
                            exit_dates: Optional[Mapping[int, str]] = None) -> Dict[str, Any]:
    """窓の期間に会社が何をしたか。**いつ出たかで分ける。**

    実測（2026-08-30）で、**約定ギャップが分布の外側だった13件のうち7件が、決算と
    同じ日の別の開示で説明できた**:

        3480 ジェイ・エス・ビー +13.11%  決算と同日に TOB の開始と意見表明
        6966 三井ハイテック    +14.09%  同日に通期業績予想の上方修正
        4394 エクスモーション   +12.64%  同日に株主優待制度の導入
        3659 ネクソン         +10.82%  同日に配当予想の修正＋自己株式の消却

    **3480 の +13% は決算への反応ではない。** それを決算リターンとして測るのは誤りで
    ある。さらに `3544` サツドラHD は、約定した日の引け後（2026-06-19 17:30）に TOB の
    開始が出て、翌営業日から**連続2日ストップ高で寄らず**——保有期間のリターンが
    まるごと TOB プレミアムになっている。

    だから「窓にあったか」ではなく **「決算と同じ日か」「約定より前か」「保有中か」**
    で分ける。決算の反応を測りたいなら、同日の別材料と保有中の材料は切れなければ
    ならない。
    """
    if actions is None:
        # **調べていないことを「無かった」と書かない。** 会社の行為の成果物が
        # 無い状態で組むと、全イベントに `None` が渡る。ここで `False` を返すと
        # 「同日に別材料は出ていない」と主張したことになるが、**源を一度も見て
        # いない**。空の列（調べて該当なし）と区別する。
        return {"same_day": [], "before_entry": [], "during_hold": [],
                "contaminated": None, "coverage": "not_checked"}
    if not actions:
        return {"same_day": [], "before_entry": [], "during_hold": [],
                "contaminated": None if event_date is None else False,
                "coverage": "checked"}
    same_day, before_entry, during_hold = [], [], []
    last_exit = max(exit_dates.values()) if exit_dates else None
    for action in actions:
        when = str(action.get("pubdate") or "")[:10]
        if not when:
            continue
        kinds = list(action.get("actions") or [])
        # `scope` を落とすと、名証だけの上場廃止が全面廃止と区別できなくなる。
        # `corporate_actions.collect` がわざわざ分けているものを、ここで潰さない。
        entry = {"date": when, "actions": kinds, "stage": action.get("stage"),
                 "scope": action.get("scope")}
        if event_date and when == event_date:
            same_day.append(entry)
        elif entry_date and when < entry_date:
            before_entry.append(entry)
        elif entry_date and (last_exit is None or when <= last_exit):
            during_hold.append(entry)
    return {
        "coverage": "checked",
        "same_day": same_day,
        "before_entry": before_entry,
        "during_hold": during_hold,
        # **決算の反応として読めない状態か。** 同日の別材料か、保有中の資本異動。
        "contaminated": bool(same_day or during_hold),
    }


def quality_block(**flags) -> Dict[str, Any]:
    """この行を信用してよいかの目印。

    **調べていない項目は `"unknown"` であって `False` ではない。** `False` は
    「調べて、無かった」を意味する。`docs/PRICE_ANOMALY_CANDIDATES.md` に候補の
    一覧があり、埋まっていないものはそこで `未確認` になっている。
    """
    known = {
        "ticker_resolution": "unknown",
        "split_state": "unknown",
        "dividend_in_window": "unknown",
        "limit_move_at_entry": "unknown",
        "halted_in_window": "unknown",
        "zero_volume_in_window": "unknown",
        "event_date_is_business_day": "unknown",
        "duplicate_of": None,
        "price_source": "unknown",
    }
    unknown = set(flags) - set(known)
    if unknown:
        # 綴りの違う名前で新しい鍵が生えると、`unknown` のまま気づかない項目が
        # 増える。増やすときはここに足すこと。
        raise ValueError("知らない品質の項目: %s" % sorted(unknown))
    if flags.get("ticker_resolution") not in (None,) + TICKER_RESOLUTIONS:
        raise ValueError("ticker_resolution が語彙の外: %r" % flags["ticker_resolution"])
    if flags.get("split_state") not in (None,) + SPLIT_STATES:
        raise ValueError("split_state が語彙の外: %r" % flags["split_state"])
    known.update({k: v for k, v in flags.items() if v is not None})
    return known


def build(record: Mapping[str, Any],
          timing: Optional[Mapping[str, Any]],
          sessions: Optional[Mapping[int, Mapping[str, Any]]],
          facts: Optional[Mapping[str, Any]],
          forecast_revision: Optional[str] = None,
          regime: Optional[Mapping[str, Any]] = None,
          actions: Optional[Sequence[Mapping[str, Any]]] = None,
          **quality) -> Dict[str, Any]:
    identity = record.get("normalized_identity", {})
    event_date = (identity.get("legacy_event_date") or "")[:10] or None
    price = price_block(sessions)
    exit_dates = {}
    if sessions:
        for offset in EXIT_OFFSETS:
            leg = sessions.get(offset) or {}
            if leg.get("date"):
                exit_dates[offset] = leg["date"]
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "ticker": identity.get("ticker_candidate"),
            "company": identity.get("company_name_candidate"),
            "event_date": event_date,
            "legacy_record_id": record.get("legacy_record_id"),
        },
        "disclosure": disclosure_block(timing, forecast_revision),
        "ledger": ledger_block(record.get("normalized_classifications", {})),
        "narrative": narrative_block(facts),
        "price": price,
        "corporate_actions": corporate_actions_block(
            actions, event_date, price.get("entry_date"), exit_dates),
        "regime": dict(regime) if regime else {},
        "quality": quality_block(**quality),
    }
