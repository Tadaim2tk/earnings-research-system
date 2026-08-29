"""日次の確保。広げないことと、身元を作らないこと。

このツールは `Disallow: /` の発行元から取る。索引が渡したURLに限った取得は
ERS-ADR-0046 で Human が承認したが、それは1社・四半期1本の文脈だった。全短信は
1日250本で30倍になる。**規模の変更は人の判断なので、既定で広がらないことを
固定する。**
"""

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/capture_disclosures.py"


def tool():
    spec = importlib.util.spec_from_file_location("capture_disclosures", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_universe_never_widens_without_being_asked():
    """`--all` は `store_true` で、既定は False。既定値を True にした版が
    通ってはいけない。"""
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    widened = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add_argument":
            continue
        names = [a.value for a in node.args if isinstance(a, ast.Constant)]
        if "--all" not in names:
            continue
        kwargs = {k.arg: k.value for k in node.keywords}
        assert isinstance(kwargs.get("action"), ast.Constant)
        assert kwargs["action"].value == "store_true", ast.dump(node)
        # 既定値を明示していたら False でなければならない。
        default = kwargs.get("default")
        if default is not None:
            assert isinstance(default, ast.Constant) and default.value is False
        widened.append(names)
    assert widened, "--all が見つからない"


def test_the_ledger_universe_contains_no_invented_identities():
    """台帳には `80310_dup`（重複行の目印）と `…` が入っている。素朴に4文字で
    切ると `8031` が宇宙に混ざり、三井物産の開示を勝手に拾う対象になる。"""
    codes = tool().ledger_codes()
    assert codes, "台帳から銘柄が取れていない"
    for code in codes:
        assert len(code) == 4, code
        assert code.isalnum(), code
    assert "…" not in codes and "8031" in codes
    # `80310_dup` は解決できないので宇宙に入らない。`80310` は正当な5桁表記
    # なので `8031` として入る——両方が同じ4桁へ落ちるが、入り口は1つだけ。
    assert not any("_" in code for code in codes)


def test_capture_stores_no_pdf_and_no_score():
    """残すのは抽出テキストと sha256 まで。採点はここではしない——評価は
    凍結した scoring_version の仕事で、確保の副作用にしない。"""
    source = TOOL.read_text(encoding="utf-8")
    tree = ast.parse(source)
    written = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            written |= {k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert {"text", "text_sha256", "pdf_sha256", "captured_at"} <= written
    for forbidden in ("score", "scoring_version", "pdf_bytes", "raw_pdf", "grade"):
        assert forbidden not in written, forbidden


def test_the_sweep_limit_comes_from_the_contract_and_is_not_the_handoff_bound():
    """2つの上限は別の問いに答えている。`MAX_DOCUMENTS_PER_RUN` は「1つの開示に
    対する handoff が壊れていないか」（1開示=1文書+補足なので4）、
    `MAX_DOCUMENTS_PER_SWEEP` は「1回の実行でいくつの開示を見るか」。
    **流用すると、掃き出しの上限を上げたときに handoff の壊れ検査まで緩む。**"""
    from earnings_research.document_analysis import acquisition as A
    assert A.MAX_DOCUMENTS_PER_RUN == 4, "handoff の壊れ検査は動かさない"
    assert A.MAX_DOCUMENTS_PER_SWEEP >= 9, "多い日の9社を捌けない上限は意味が無い"

    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    imported = any(
        isinstance(n, ast.ImportFrom) and "acquisition" in (n.module or "")
        and any(a.name == "MAX_DOCUMENTS_PER_SWEEP" for a in n.names)
        for n in ast.walk(tree))
    assert imported, "上限を自前の定数で持ち直していない"
    assert A.MAX_DOCUMENTS_PER_SWEEP == tool().MAX_DOCUMENTS_PER_SWEEP


def test_a_shortfall_is_never_reported_as_success():
    """無人で走らせたとき、緑は「全部取れた」以外を意味してはいけない。
    取り残しと失敗のどちらでも 0 以外で終える。"""
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return) and n.value is not None]
    conditional = [n for n in returns if isinstance(n.value, ast.IfExp)]
    assert conditional, "取り残し/失敗で終了コードを分ける分岐が無い"
    # `return 0` が無条件で最後に来ていない。`False == 0` が真なので、
    # bool を除いてから比べる——これを外して `return False` に引っかかった。
    plain_zero = [n for n in returns
                  if isinstance(n.value, ast.Constant)
                  and isinstance(n.value.value, int)
                  and not isinstance(n.value.value, bool)
                  and n.value.value == 0]
    assert not plain_zero, "無条件の return 0 が残っている"


def test_two_disclosures_on_one_day_do_not_share_a_filename():
    """1社が同じ日に2本出すと、`<code>_<date>` だけでは2本目が「既にある」と
    見なされて黙って消える。`select()` が同じ状況を `ambiguous` として扱って
    いる以上、起こりうる前提で名前を付ける。"""
    key = tool().storage_key
    a = key("7203", "2026-08-13", "https://example.invalid/a.pdf")
    b = key("7203", "2026-08-13", "https://example.invalid/b.pdf")
    assert a != b
    assert a.startswith("7203_2026-08-13_")
    assert key("7203", "2026-08-13", "https://example.invalid/a.pdf") == a


def test_the_corpus_may_not_live_inside_the_public_checkout():
    """`--store` にリポジトリ内のパスを渡すと第三者の開示本文が public な
    チェックアウトに書かれる。source-eligibility 検査は
    `data/evidence/*/bundles.jsonl` しか見ないので素通りする。"""
    outside = tool().outside_repository
    assert outside(Path.home() / ".ers-corpus/documents") is True
    assert outside(Path("/tmp/somewhere")) is True
    assert outside(ROOT / "data/corpus") is False
    assert outside(ROOT) is False
    assert outside(ROOT / "docs/../data/x") is False
