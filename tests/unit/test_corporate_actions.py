"""会社の行為の判定。**廃止と注意喚起と解除を混ぜない。**"""

from earnings_research.timing import corporate_actions as CA

def test_a_supervision_post_is_not_a_delisting():
    """**監理銘柄は注意喚起であって廃止ではない。** 解除されて上場が続くことが
    実際に多い。実測で「上場維持基準への適合及び監理銘柄(確認中)指定解除」——
    基準を満たした良い知らせ——が上場廃止として数えられていた。この取り違えは
    生きている会社を「消えた」と記録する。"""
    assert CA.actions_in("当社株式の監理銘柄（確認中）指定に関するお知らせ") == ("listing_warning",)
    assert CA.actions_in("当社株式の上場廃止に関するお知らせ") == ("delisting",)
    assert "delisting" not in CA.actions_in("当社株式の監理銘柄（審査中）の指定に関するお知らせ")


def test_a_liquidation_post_is_a_delisting_because_it_is_already_decided():
    """整理銘柄は廃止が決まった後に付く。監理銘柄と違い、戻らない。"""
    got = CA.actions_in("当社株式の上場廃止の決定及び整理銘柄の指定に関するお知らせ")
    assert "delisting" in got


def test_releasing_a_designation_is_not_the_designation():
    """**向きが逆。** 「指定解除」を `announcement` にすると、注意喚起の解除が
    新たな注意喚起として数えられる。"""
    assert CA.stage_of("当社株式の監理銘柄（確認中）指定解除に関するお知らせ") == "released"
    assert CA.stage_of("上場維持基準への適合及び当社株式の監理銘柄(確認中)指定解除に関するお知らせ") == "released"
    assert CA.stage_of("当社株式の監理銘柄（確認中）指定に関するお知らせ") == "announcement"


def test_delisting_from_one_exchange_is_marked_as_partial():
    """**名証だけの上場廃止は、東証に残っている会社の消滅ではない。** 実測で
    「名古屋証券取引所における当社株式の上場廃止申請」が14件あった。"""
    assert CA.scope_of("名古屋証券取引所における当社株式の上場廃止申請に関するお知らせ") == "secondary_market"
    assert CA.scope_of("当社株式の上場廃止に関するお知らせ") == "unspecified"


def test_naming_tokyo_alongside_another_exchange_is_not_partial():
    """両方を名指しているものを「地方だけ」に落とさない。"""
    assert CA.scope_of("東京証券取引所及び名古屋証券取引所における上場廃止に関するお知らせ") == "unspecified"


def test_unspecified_scope_does_not_claim_a_full_delisting():
    """`unspecified` は「全面廃止だと確かめた」ではなく「市場名が表題に無い」。
    語彙の並びで、確かめた側と未確認側を混ぜない。"""
    assert set(CA.SCOPES) == {"secondary_market", "unspecified"}
    assert CA.scope_of("当社株式の上場廃止のお知らせ") == "unspecified"
