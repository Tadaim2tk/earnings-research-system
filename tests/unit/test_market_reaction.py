import csv
import json

import pytest
from pydantic import ValidationError

from earnings_research.cli.__main__ import main
from earnings_research.earnings_evaluation.models import EarningsEvaluation
from earnings_research.market_reaction.models import MarketReactionObservationBundle
from earnings_research.market_reaction.pipeline import _validate_dataset_context
from earnings_research.market_reaction.tracker import track_market_reaction


def evaluation():
    return EarningsEvaluation.model_validate({
        "evaluation_id": "EE-FICTIONAL-001",
        "earnings_event_id": "EVT-FICTIONAL-001",
        "baseline_id": "BASE-FICTIONAL-001",
        "analysis_id": "EDA-FICTIONAL-001",
        "company_name": "架空食品株式会社",
        "ticker": "9999",
        "expectation_period_scope": "full_year",
        "evaluated_at": "2027-05-10T17:00:00+09:00",
        "status": "evaluated",
        "baseline_unit_multiplier": 1_000_000,
        "overall_assessment": "positive",
        "overall_explanation": "架空の評価です。",
        "next_stage": "ready_for_market_reaction_tracking",
    })


def observation(role, price, timestamp, kind, observation_id=None, bar_interval=None):
    return {
        "observation_id": observation_id or "PX-" + role.upper(),
        "role": role,
        "price": price,
        "currency": "JPY",
        "price_datetime": timestamp,
        "trading_date": timestamp[:10],
        "price_kind": kind,
        "selection_rule": "事前に固定したroleに対応する公式価格を使用",
        "bar_interval_minutes": bar_interval,
        "is_unadjusted": True,
        "source": {
            "source_name": "Approved Manual Price Display",
            "source_url_or_identifier": "screen://fictional/9999",
            "source_checked_at": "2027-05-17T16:30:00+09:00",
            "recorded_by": "system_policy:test-fixture",
            "terms_status": "manual_fallback",
            "terms_basis": "架空fixtureの手入力検証",
        },
        "raw_data_retained": False,
    }


def bundle_payload(session="before_open"):
    announcement = {
        "before_open": "2027-05-10T08:00:00+09:00",
        "intraday": "2027-05-10T12:30:00+09:00",
        "after_close": "2027-05-10T16:00:00+09:00",
    }[session]
    pre_close_date = "2027-05-10" if session == "after_close" else "2027-05-07"
    pre_close_time = "2027-05-10T15:30:00+09:00" if session == "after_close" else "2027-05-07T15:30:00+09:00"
    immediate_time = {
        "before_open": "2027-05-10T09:00:00+09:00",
        "intraday": "2027-05-10T12:31:00+09:00",
        "after_close": "2027-05-11T09:00:00+09:00",
    }[session]
    immediate_kind = "minute_bar_close" if session == "intraday" else "official_open"
    observations = [
        observation("pre_event_close", 100, pre_close_time, "official_close"),
        observation(
            "immediate_post_announcement",
            105,
            immediate_time,
            immediate_kind,
            bar_interval=1 if session == "intraday" else None,
        ),
        observation("next_business_day_close", 104, "2027-05-11T15:30:00+09:00", "official_close"),
        observation("fifth_business_day_close", 110, "2027-05-17T15:30:00+09:00", "official_close"),
    ]
    if session == "intraday":
        observations.insert(1, observation(
            "pre_announcement_reference",
            102,
            "2027-05-10T12:29:00+09:00",
            "minute_bar_close",
            bar_interval=1,
        ))
    return {
        "tracking_id": "MR-FICTIONAL-001",
        "earnings_event_id": "EVT-FICTIONAL-001",
        "evaluation_id": "EE-FICTIONAL-001",
        "company_name": "架空食品株式会社",
        "ticker": "9999",
        "announcement_datetime": announcement,
        "announcement_session": session,
        "market_timezone": "Asia/Tokyo",
        "calendar_name": "JPX-fictional-calendar",
        "pre_event_close_date": pre_close_date,
        "next_five_session_dates": [
            "2027-05-11", "2027-05-12", "2027-05-13", "2027-05-14", "2027-05-17"
        ],
        "corporate_action_status": "none_detected",
        "observations": observations,
        "recorded_at": "2027-05-17T17:00:00+09:00",
    }


def bundle(session="before_open"):
    return MarketReactionObservationBundle.model_validate(bundle_payload(session))


def milestone(result, role):
    return next(item for item in result.milestones if item.role == role)


def test_before_open_tracks_all_four_price_points_and_returns():
    result = track_market_reaction(bundle(), evaluation())
    assert result.status == "complete"
    assert result.currency == "JPY"
    assert result.event_window_reaction.reference_role == "pre_event_close"
    assert result.event_window_reaction.return_pct == 5.0
    assert milestone(result, "next_business_day_close").return_from_pre_event_close_pct == 4.0
    assert milestone(result, "fifth_business_day_close").return_from_pre_event_close_pct == 10.0
    assert result.summary.reaction_path == "extended"
    assert milestone(result, "immediate_post_announcement").source.source_name == "Approved Manual Price Display"
    assert result.completed_at.isoformat() == "2027-05-17T17:00:00+09:00"
    assert result.next_stage == "ready_for_post_event_validation"
    assert result.trade_decision_included is False


def test_intraday_uses_strict_pre_announcement_minute_reference():
    result = track_market_reaction(bundle("intraday"), evaluation())
    assert result.event_window_reaction.reference_role == "pre_announcement_reference"
    assert result.event_window_reaction.return_pct == pytest.approx(2.9412)
    assert milestone(result, "immediate_post_announcement").return_from_pre_event_close_pct == 5.0


def test_after_close_uses_next_open_as_immediate_observation():
    result = track_market_reaction(bundle("after_close"), evaluation())
    immediate = milestone(result, "immediate_post_announcement")
    assert immediate.expected_trading_date.isoformat() == "2027-05-11"
    assert immediate.return_from_pre_event_close_pct == 5.0


def test_missing_fifth_day_remains_tracking_without_losing_prior_results():
    payload = bundle_payload()
    payload["observations"] = [
        item for item in payload["observations"] if item["role"] != "fifth_business_day_close"
    ]
    result = track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())
    assert result.status == "tracking"
    assert milestone(result, "immediate_post_announcement").status == "observed"
    assert milestone(result, "fifth_business_day_close").status == "pending"
    assert result.summary.reaction_path == "pending"


@pytest.mark.parametrize("corporate_status", ["present", "unknown"])
def test_unresolved_corporate_action_keeps_prices_but_blocks_returns(corporate_status):
    payload = bundle_payload()
    payload["corporate_action_status"] = corporate_status
    result = track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())
    assert result.status == "not_comparable"
    assert milestone(result, "immediate_post_announcement").price == 105
    assert milestone(result, "immediate_post_announcement").return_from_pre_event_close_pct is None
    assert result.next_stage == "manual_review_required"


def test_reaction_reversal_is_identified():
    payload = bundle_payload()
    fifth = next(item for item in payload["observations"] if item["role"] == "fifth_business_day_close")
    fifth["price"] = 95
    result = track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())
    assert result.summary.immediate_direction == "positive"
    assert result.summary.fifth_business_day_direction == "negative"
    assert result.summary.reaction_path == "reversed"


@pytest.mark.parametrize("field", ["evaluation_id", "earnings_event_id", "ticker", "company_name"])
def test_identity_mismatch_is_rejected(field):
    payload = bundle_payload()
    payload[field] = "wrong"
    with pytest.raises(ValueError, match=field):
        track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())


@pytest.mark.parametrize(
    ("target", "field", "value", "message"),
    [
        ("event", "announcement_session", "after_close", "announcement_session"),
        ("status", "occurred_at", "2027-05-10T08:01:00+09:00", "occurred_at"),
        ("company", "ticker", "0000", "ticker"),
        ("company", "company_name", "別会社", "company_name"),
    ],
)
def test_dataset_truth_mismatch_is_rejected(target, field, value, message):
    rows = {
        "event": [{
            "earnings_event_id": "EVT-FICTIONAL-001",
            "company_id": "CMP-FICTIONAL",
            "announcement_session": "before_open",
        }],
        "status": [{
            "event_status_record_id": "EVST-FICTIONAL-OCCURRED",
            "earnings_event_id": "EVT-FICTIONAL-001",
            "event_status": "occurred",
            "occurred_at": "2027-05-10T08:00:00+09:00",
        }],
        "company": [{
            "company_id": "CMP-FICTIONAL",
            "ticker": "9999",
            "company_name": "架空食品株式会社",
            "primary_currency": "JPY",
        }],
    }
    rows[target][0][field] = value
    with pytest.raises(ValueError, match=message):
        _validate_dataset_context(bundle(), rows["event"], rows["status"], rows["company"])


def test_occurred_status_must_remain_the_current_tail():
    events = [{
        "earnings_event_id": "EVT-FICTIONAL-001",
        "company_id": "CMP-FICTIONAL",
        "announcement_session": "before_open",
    }]
    status_history = [
        {
            "event_status_record_id": "EVST-FICTIONAL-OCCURRED",
            "earnings_event_id": "EVT-FICTIONAL-001",
            "event_status": "occurred",
            "occurred_at": "2027-05-10T08:00:00+09:00",
        },
        {
            "event_status_record_id": "EVST-FICTIONAL-CORRECTION",
            "earnings_event_id": "EVT-FICTIONAL-001",
            "event_status": "scheduled",
            "supersedes_status_record_id": "EVST-FICTIONAL-OCCURRED",
        },
    ]
    companies = [{
        "company_id": "CMP-FICTIONAL",
        "ticker": "9999",
        "company_name": "架空食品株式会社",
        "primary_currency": "JPY",
    }]
    with pytest.raises(ValueError, match="current status tail"):
        _validate_dataset_context(bundle(), events, status_history, companies)


def test_intraday_requires_pre_announcement_reference():
    payload = bundle_payload("intraday")
    payload["observations"] = [
        item for item in payload["observations"] if item["role"] != "pre_announcement_reference"
    ]
    with pytest.raises(ValueError, match="requires pre-announcement"):
        track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())


def test_bundle_cannot_predate_earnings_evaluation():
    payload = bundle_payload()
    payload["recorded_at"] = "2027-05-10T16:00:00+09:00"
    for item in payload["observations"]:
        item["source"]["source_checked_at"] = min(
            item["price_datetime"], "2027-05-10T16:00:00+09:00"
        )
    # Future milestones cannot exist in a bundle recorded this early, so retain only available prices.
    payload["observations"] = [
        item for item in payload["observations"]
        if item["price_datetime"] <= "2027-05-10T16:00:00+09:00"
    ]
    with pytest.raises(ValueError, match="cannot predate"):
        track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())


def test_post_announcement_price_cannot_be_used_as_intraday_reference():
    payload = bundle_payload("intraday")
    reference = next(item for item in payload["observations"] if item["role"] == "pre_announcement_reference")
    reference["price_datetime"] = "2027-05-10T12:31:00+09:00"
    reference["trading_date"] = "2027-05-10"
    with pytest.raises(ValueError, match="strictly before"):
        track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())


def test_calendar_dates_must_be_unique_and_ordered():
    payload = bundle_payload()
    payload["next_five_session_dates"][4] = payload["next_five_session_dates"][3]
    with pytest.raises(ValidationError, match="unique ascending"):
        MarketReactionObservationBundle.model_validate(payload)


def test_wrong_fifth_business_day_is_rejected():
    payload = bundle_payload()
    fifth = next(item for item in payload["observations"] if item["role"] == "fifth_business_day_close")
    fifth["price_datetime"] = "2027-05-16T15:30:00+09:00"
    fifth["trading_date"] = "2027-05-16"
    with pytest.raises(ValueError, match="fifth-business-day"):
        track_market_reaction(MarketReactionObservationBundle.model_validate(payload), evaluation())


def test_adjusted_or_raw_retained_observation_is_rejected():
    payload = bundle_payload()
    payload["observations"][0]["is_unadjusted"] = False
    with pytest.raises(ValidationError):
        MarketReactionObservationBundle.model_validate(payload)


def test_vwap_requires_a_predefined_window():
    payload = bundle_payload("intraday")
    immediate = next(
        item for item in payload["observations"] if item["role"] == "immediate_post_announcement"
    )
    immediate["price_kind"] = "vwap_after_announcement"
    immediate["bar_interval_minutes"] = None
    with pytest.raises(ValidationError, match="requires vwap_window"):
        MarketReactionObservationBundle.model_validate(payload)
    immediate["vwap_window"] = "12:30:00-12:35:00 Asia/Tokyo, regular session"
    MarketReactionObservationBundle.model_validate(payload)
    payload = bundle_payload()
    payload["observations"][0]["raw_data_retained"] = True
    with pytest.raises(ValidationError):
        MarketReactionObservationBundle.model_validate(payload)


def test_cli_writes_tracking_result(tmp_path):
    observations_path = tmp_path / "observations.json"
    evaluation_path = tmp_path / "evaluation.json"
    output_path = tmp_path / "reaction.json"
    events_path = tmp_path / "events.csv"
    status_path = tmp_path / "event_status_history.csv"
    companies_path = tmp_path / "companies.csv"
    observations_path.write_text(json.dumps(bundle_payload(), ensure_ascii=False), encoding="utf-8")
    evaluation_path.write_text(evaluation().model_dump_json(indent=2), encoding="utf-8")
    write_csv(events_path, [{
        "earnings_event_id": "EVT-FICTIONAL-001",
        "company_id": "CMP-FICTIONAL",
        "announcement_session": "before_open",
    }])
    write_csv(status_path, [{
        "event_status_record_id": "EVST-FICTIONAL-OCCURRED",
        "earnings_event_id": "EVT-FICTIONAL-001",
        "event_status": "occurred",
        "occurred_at": "2027-05-10T08:00:00+09:00",
    }])
    write_csv(companies_path, [{
        "company_id": "CMP-FICTIONAL",
        "ticker": "9999",
        "company_name": "架空食品株式会社",
        "primary_currency": "JPY",
    }])
    exit_code = main([
        "track-market-reaction",
        "--observations", str(observations_path),
        "--evaluation", str(evaluation_path),
        "--events", str(events_path),
        "--event-status-history", str(status_path),
        "--companies", str(companies_path),
        "--output", str(output_path),
    ])
    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["summary"]["reaction_path"] == "extended"


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
