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
    return {
        "entry_date": entry.get("date"),
        "entry_open": open_,
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


def quality_block(**flags) -> Dict[str, Any]:
    """この行を信用してよいかの目印。

    **調べていない項目は `"unknown"` であって `False` ではない。** `False` は
    「調べて、無かった」を意味する。`~/.ers-corpus/notes/price-anomaly-candidates.md`
    に候補の一覧があり、埋まっていないものはそこで `未確認` になっている。
    """
    known = {
        "split_in_window": "unknown",
        "dividend_in_window": "unknown",
        "limit_move_at_entry": "unknown",
        "halted_in_window": "unknown",
        "zero_volume_in_window": "unknown",
        "ticker_resolution": "unknown",
        "duplicate_of": None,
    }
    known.update(flags)
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
