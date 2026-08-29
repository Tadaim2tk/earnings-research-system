"""索引から発表時刻を選ぶところ。

固定値は実測から取った。2026-06-10 のトビラシステムズと pluszero は、素朴な
「決算」一致が別の書類を掴む実例で、この2件が通らない実装は使えない。
"""

import ast
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from earnings_research.timing import tdnet_index as ix

JST = timezone(timedelta(hours=9))

# 実測: 短信は昼休みの12:00、動画告知が13:00。素朴な一致は13:00を掴む。
TOBILA = [
    {"company_code": "44410", "pubdate": "2026-06-10 13:00:00",
     "title": "2026年10月期第２四半期 決算説明動画と書き起こし公開のお知らせ",
     "document_url": "https://example.invalid/a.pdf"},
    {"company_code": "44410", "pubdate": "2026-06-10 12:00:00",
     "title": "2026年10月期　第２四半期（中間期）決算短信〔日本基準〕(非連結)",
     "document_url": "https://example.invalid/b.pdf"},
    {"company_code": "44410", "pubdate": "2026-06-10 12:00:00",
     "title": "2026年10月期第２四半期 決算説明資料",
     "document_url": "https://example.invalid/c.pdf"},
]

# 実測: 同じ16:00に3件並ぶ。時刻だけでは切り分けられない。
PLUSZERO = [
    {"company_code": "51320", "pubdate": "2026-06-10 16:00:00",
     "title": "2026年10月期第２四半期決算説明資料"},
    {"company_code": "51320", "pubdate": "2026-06-10 16:00:00",
     "title": "2026年10月期第２四半期（中間期）決算短信〔日本基準〕(非連結)"},
    {"company_code": "51320", "pubdate": "2026-06-10 16:00:00",
     "title": "第７回新株予約権（有償ストック・オプション）の取得及び消却に関するお知らせ"},
]


def test_the_lunch_break_disclosure_is_not_replaced_by_the_video_notice():
    """これが外れると、昼休みの発表が後場の発表として記録される。1時間の
    ずれではなくセッションの差になる。"""
    got = ix.select(TOBILA, "4441", "2026-06-10")
    assert got.status == "matched"
    assert got.announced_at == datetime(2026, 6, 10, 12, 0, tzinfo=JST)
    assert got.document_url == "https://example.invalid/b.pdf"


def test_the_tanshin_is_picked_out_of_three_disclosures_at_the_same_instant():
    got = ix.select(PLUSZERO, "5132", "2026-06-10")
    assert got.status == "matched"
    assert got.announced_at == datetime(2026, 6, 10, 16, 0, tzinfo=JST)


def test_two_originals_on_one_day_are_not_chosen_between():
    """どちらが発表かを推測すると、その推測が時刻になる。"""
    two = [dict(PLUSZERO[1]), dict(PLUSZERO[1], pubdate="2026-06-10 15:00:00")]
    got = ix.select(two, "5132", "2026-06-10")
    assert got.status == "ambiguous"
    assert got.announced_at is None
    assert got.candidates == 2


def test_a_correction_is_counted_but_never_selected():
    only = [{"company_code": "51320", "pubdate": "2026-06-10 16:00:00",
             "title": "（訂正）「2026年10月期第２四半期決算短信」の一部訂正について"}]
    got = ix.select(only, "5132", "2026-06-10")
    assert got.status == "correction_only"
    assert got.corrections == 1
    assert got.announced_at is None

    with_original = only + [PLUSZERO[1]]
    got = ix.select(with_original, "5132", "2026-06-10")
    assert got.status == "matched"
    assert got.corrections == 1


def test_absence_says_which_kind_it_is():
    assert ix.select([], "5132", "2026-06-10").status == "no_disclosure"
    other_day = ix.select(PLUSZERO, "5132", "2026-06-11")
    assert other_day.status == "no_disclosure"
    no_tanshin = ix.select([PLUSZERO[0], PLUSZERO[2]], "5132", "2026-06-10")
    assert no_tanshin.status == "no_tanshin"
    assert no_tanshin.candidates == 2


def test_the_five_digit_index_code_matches_the_four_digit_ledger_code():
    assert ix.short_code("44410") == "4441"
    assert ix.short_code("4441") == "4441"
    # 英数字コードは末尾を落とす実装だと壊れる。
    assert ix.short_code("130A0") == "130A"


def test_a_full_width_space_inside_the_title_does_not_create_a_false_absence():
    assert ix.is_tanshin("2026年10月期　第２四半期（中間期）決算短信〔日本基準〕")
    assert ix.is_tanshin("決算短信")
    assert not ix.is_tanshin("決算説明資料")
    assert not ix.is_tanshin("決算説明動画と書き起こし公開のお知らせ")


def test_both_response_shapes_read_the_same():
    nested = {"items": [{"Tdnet": PLUSZERO[1]}]}
    flat = {"items": [PLUSZERO[1]]}
    assert ix.items_from(nested) == ix.items_from(flat) == [PLUSZERO[1]]
    assert ix.items_from([PLUSZERO[1]]) == [PLUSZERO[1]]


def test_only_a_match_carries_an_instant():
    with pytest.raises(ValueError):
        ix.Selection("no_tanshin", announced_at=datetime(2026, 6, 10, tzinfo=JST))
    with pytest.raises(ValueError):
        ix.Selection("matched")
    with pytest.raises(ValueError):
        ix.Selection("something_else")


def test_the_digest_ignores_key_order_but_not_content():
    a = ix.digest({"a": 1, "b": 2})
    assert a == ix.digest({"b": 2, "a": 1})
    assert a != ix.digest({"a": 1, "b": 3})


def test_a_full_index_is_treated_as_truncated_not_as_absence():
    """実測で踏んだ穴。limit=1000 に対して1000件返り、実際は1627件あった。
    足りない分の2社は「開示が無かった」ことにされていた。上限と不在は
    見分けがつかないので、張り付きは不在より先に判定する。"""
    assert ix.truncated([{}] * 1000, 1000) is True
    assert ix.truncated([{}] * 1627, 1000) is True
    assert ix.truncated([{}] * 999, 1000) is False
    assert ix.truncated([], 1000) is False


def test_selection_reaches_no_network():
    """選別は純粋な判断で、取得と混ざっていない。混ざると、テストのたびに
    索引を叩くか、叩かないために選別を飛ばすかのどちらかになる。"""
    module = Path(ix.__file__)
    names = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            target, parts = node.func, []
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                parts.append(target.id)
            if parts:
                names.add(".".join(reversed(parts)))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", None) or ""
            for alias in node.names:
                assert "urllib" not in (alias.name or ""), alias.name
            assert "urllib" not in mod and "http" not in mod, mod
    assert not any("urlopen" in n or "request" in n for n in names), sorted(names)
