"""被覆と欠測の理由。**落とさないための型を縛る。**"""

import pytest

from earnings_research.prices import coverage as C

WINDOW = ("2021-01-04", "2026-08-28")


def test_a_series_that_stops_early_is_not_the_same_as_one_never_fetched():
    """**取得の失敗を上場廃止に化けさせない。**

    実測で、バッチ取得に失敗した336銘柄のうち118銘柄は2026年も決算を出して
    いた。個別に取り直せば取れる。ここを混ぜると、生きている会社が「窓の途中で
    消えた」と記録され、生存バイアスを直すつもりで別の嘘を入れることになる。
    """
    assert C.coverage_state("2021-01-04", "2023-03-10", *WINDOW) == "ends_before_window"
    assert C.coverage_state(None, None, *WINDOW) == "source_unavailable"
    assert C.coverage_state("2021-01-04", "2023-03-10", *WINDOW) != C.coverage_state(None, None, *WINDOW)


def test_an_empty_series_is_not_read_as_a_late_listing():
    """`None` を「窓の外で上場した」と読み替えない。片方でも欠ければ
    `source_unavailable` で、上場時期の話に流用しない。"""
    assert C.coverage_state(None, "2026-08-28", *WINDOW) == "source_unavailable"
    assert C.coverage_state("2021-01-04", None, *WINDOW) == "source_unavailable"


def test_the_four_shapes_of_partial_coverage_stay_apart():
    assert C.coverage_state("2021-01-04", "2026-08-28", *WINDOW) == "covered"
    assert C.coverage_state("2022-06-01", "2026-08-28", *WINDOW) == "starts_after_window"
    assert C.coverage_state("2021-01-04", "2023-03-10", *WINDOW) == "ends_before_window"
    assert C.coverage_state("2022-06-01", "2023-03-10", *WINDOW) == "partial_both_ends"


def test_running_out_of_sessions_is_not_a_gap():
    """**出口はセッション番号で決まる。** 最終日と建て日を比べるだけでは、
    建てた2日後に系列が終わった行を「出口の日だけ抜けている」と誤判定する。
    残っている本数を数えて分ける。
    """
    ended = C.return_state("2023-03-08", None, 2, 20, "2023-03-10")
    gap = C.return_state("2023-01-05", None, 300, 20, "2026-08-28")
    assert ended == "ended_before_exit"
    assert gap == "gap_at_exit"


def test_the_boundary_is_exactly_the_sessions_needed():
    """ちょうど足りる本数は測れる側に置く。1本足りなければ終了扱い。"""
    assert C.return_state("2023-03-08", None, 20, 20, "2026-08-28") == "gap_at_exit"
    assert C.return_state("2023-03-08", None, 19, 20, "2023-04-05") == "ended_before_exit"


def test_a_measured_exit_wins_over_every_other_reason():
    """値が取れているなら、他の目印が何であれ `measured`。"""
    assert C.return_state("2023-03-08", "2023-04-05", 1, 20, "2023-04-05") == "measured"


def test_no_entry_price_is_reported_before_anything_about_the_exit():
    """建てられなかった行を、出口の理由で説明しない。"""
    assert C.return_state(None, None, 300, 20, "2026-08-28") == "no_price_at_entry"


def test_a_state_that_is_not_defined_stops_rather_than_being_written():
    with pytest.raises(C.UnknownState):
        C.check("delisted", C.COVERAGE_STATES)
    with pytest.raises(C.UnknownState):
        C.check("", C.RETURN_STATES)
    assert C.check("covered", C.COVERAGE_STATES) == "covered"


def test_the_shape_names_every_bucket_even_when_empty():
    """**除いた件数を数えずに「全体で測った」と言わないため。** 0件の欄も
    消さずに並べる。"""
    shape = C.survivorship_shape({"1301": "covered", "1302": "ends_before_window",
                                  "1303": "covered", "1304": "source_unavailable"})
    assert dict(shape) == {"covered": 2, "starts_after_window": 0,
                           "ends_before_window": 1, "partial_both_ends": 0,
                           "source_unavailable": 1}
    assert [name for name, _ in shape] == list(C.COVERAGE_STATES)


def test_the_shape_refuses_a_state_it_does_not_know():
    with pytest.raises(C.UnknownState):
        C.survivorship_shape({"1301": "ok"})


def test_absence_reasons_separate_checked_from_unchecked():
    """`none` は「調べて、該当する開示が無かった」。`unknown` は「調べて
    いない」。この2つを同じにすると、調べていない行が「無かった」になる。"""
    assert "none" in C.END_REASONS and "unknown" in C.END_REASONS
    assert C.check("none", C.END_REASONS) != C.check("unknown", C.END_REASONS)
