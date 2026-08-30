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
    klass = session_class(when.hour, when.minute)
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


def price_block(sessions: Optional[Mapping[int, Mapping[str, Any]]]) -> Dict[str, Any]:
    """約定と出口。**リターンは計算するが、集計はしない。**"""
    if not sessions or ENTRY_OFFSET not in sessions:
        return {"entry_date": None, "entry_open": None, "returns": {}, "covered": []}
    entry = sessions[ENTRY_OFFSET]
    open_ = entry.get("open")
    if not open_ or not math.isfinite(open_):
        return {"entry_date": entry.get("date"), "entry_open": None,
                "returns": {}, "covered": []}
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
          **quality) -> Dict[str, Any]:
    identity = record.get("normalized_identity", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "ticker": identity.get("ticker_candidate"),
            "company": identity.get("company_name_candidate"),
            "event_date": (identity.get("legacy_event_date") or "")[:10] or None,
            "legacy_record_id": record.get("legacy_record_id"),
        },
        "disclosure": disclosure_block(timing, forecast_revision),
        "ledger": ledger_block(record.get("normalized_classifications", {})),
        "narrative": narrative_block(facts),
        "price": price_block(sessions),
        "regime": dict(regime) if regime else {},
        "quality": quality_block(**quality),
    }
