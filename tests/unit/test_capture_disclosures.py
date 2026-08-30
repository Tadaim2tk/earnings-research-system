"""日次の確保。広げないことと、身元を作らないこと。

このツールは `Disallow: /` の発行元から取る。索引が渡したURLに限った取得は
ERS-ADR-0046 で Human が承認したが、それは1社・四半期1本の文脈だった。全短信は
1日250本で30倍になる。**規模の変更は人の判断なので、既定で広がらないことを
固定する。**
"""

import ast
import importlib.util
import sys
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


# `test_capture_stores_no_pdf_and_no_score` はここにあった。書き出す辞書の
# **鍵名の一覧**を見ており、これも両方向に誤っていた——PDF本体を `"blob"`、
# 採点を `"quality_points"` という名前で保存すれば通り、無関係なローカル変数
# `_notes = {"score": "採点はしない"}` があると落ちる。実際に書かれたファイルを
# 読む `test_what_is_written_carries_the_text_and_no_document_body` に置き換えた。


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


# `test_a_shortfall_is_never_reported_as_success` はここにあった。ソースの
# `Return` ノードの形だけを見ており、**両方向に誤っていた**——
# `return 0 if (left_behind or failed) else 0` は通り、正当な早期終了
# `if args.days <= 0: return 0` は落ちる。実際に走らせて終了コードを見る
# `test_the_sweep_limit_actually_stops_the_fetching` と
# `test_a_disclosure_already_gone_is_not_a_failure_but_is_not_success_either`
# に置き換えた。


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


# ---------------------------------------------------------------------------
# ここから下は `main()` を実際に走らせる。
#
# 上の検査は AST と純粋関数だけを見ており、**`main()` を一度も実行していなかった**。
# 独立監査が変異を137本当てたところ、13本がここを素通りした——既定で全短信を取りに
# 行く、掃き出し上限を無効化する、リポジトリ内への書き込みの門を外す、取り残しが
# あっても 0 を返す、PDF本体を保存する。どれも文書が「しない」と書いている挙動である。
#
# argparse の宣言を見るだけでは足りない。`parse_args()` の直後に `args.all = True`
# を置けば、宣言は無傷のまま既定が反転する。
# ---------------------------------------------------------------------------

import contextlib
import json as _json
import shutil
import types


class _Extracted:
    def __init__(self, pages, sha):
        self.pages, self.sha256 = pages, sha


def _index_row(code, day, title="2027年3月期第1四半期決算短信〔日本基準〕", url=None):
    return {"company_code": code + "0", "company_name": "テスト",
            "pubdate": "%s 15:30:00" % day,
            "title": title,
            "document_url": url or "https://www.release.tdnet.info/inbs/%s%s.pdf" % (code, day)}


def _run(monkeypatch, tmp_path, rows, argv, fetch_raises=None):
    """索引と文書取得を差し替えて `main()` を実行し、(終了コード, 取得回数) を返す。"""
    module = tool()
    monkeypatch.setattr(module, "INDEX_PAUSE", 0.0, raising=False)
    monkeypatch.setattr(module, "DOCUMENT_PAUSE", 0.0, raising=False)
    monkeypatch.setattr(module, "fetch_index", lambda day, timeout=90: rows.get(day, []))

    fetched = []

    class _Fetcher:
        @contextlib.contextmanager
        def pdf(self, url):
            fetched.append(url)
            if fetch_raises is not None:
                raise fetch_raises
            yield tmp_path / "x.pdf"

    monkeypatch.setattr(module, "GuardedDocumentFetcher", _Fetcher)
    monkeypatch.setattr(module, "extract_pdf",
                        lambda path: _Extracted(["本文"], "a" * 64))
    monkeypatch.setattr(sys, "argv", ["capture_disclosures.py"] + argv)
    return module.main(), fetched


def test_the_default_run_fetches_only_the_ledger_companies(monkeypatch, tmp_path):
    """既定で全短信を取りに行く変異が、宣言を見るだけの検査を素通りしていた。"""
    known = sorted(tool().ledger_codes())[0]
    day = "2026-08-14"
    rows = {day: [_index_row(known, day), _index_row("9999", day)]}
    code, fetched = _run(monkeypatch, tmp_path,
                         rows, ["--store", str(tmp_path / "s"), "--days", "1", "--today", day])
    assert code == 0
    assert len(fetched) == 1, "台帳外の銘柄まで取りに行っている"
    assert known in fetched[0]


def test_the_sweep_limit_actually_stops_the_fetching(monkeypatch, tmp_path):
    """`if budget <= 0:` を無効化する変異が素通りしていた。"""
    from earnings_research.document_analysis.acquisition import MAX_DOCUMENTS_PER_SWEEP
    codes = sorted(tool().ledger_codes())[: MAX_DOCUMENTS_PER_SWEEP + 5]
    day = "2026-08-14"
    rows = {day: [_index_row(c, day) for c in codes]}
    code, fetched = _run(monkeypatch, tmp_path,
                         rows, ["--store", str(tmp_path / "s"), "--days", "1", "--today", day])
    assert len(fetched) == MAX_DOCUMENTS_PER_SWEEP, "上限を超えて取りに行っている"
    assert code == 1, "取り残しがあるのに成功として終えている"


def test_the_budget_is_for_the_whole_run_not_per_day(monkeypatch, tmp_path):
    """日ごとに予算を戻す変異が素通りしていた。--days 倍まで取れてしまう。"""
    from earnings_research.document_analysis.acquisition import MAX_DOCUMENTS_PER_SWEEP
    codes = sorted(tool().ledger_codes())[: MAX_DOCUMENTS_PER_SWEEP]
    rows = {"2026-08-14": [_index_row(c, "2026-08-14") for c in codes],
            "2026-08-13": [_index_row(c, "2026-08-13") for c in codes]}
    _, fetched = _run(monkeypatch, tmp_path, rows,
                      ["--store", str(tmp_path / "s"), "--days", "2", "--today", "2026-08-14"])
    assert len(fetched) == MAX_DOCUMENTS_PER_SWEEP


def test_nothing_is_written_when_the_store_is_inside_the_repository(monkeypatch, tmp_path):
    """門を外す変異が素通りしていた。開示本文が public なチェックアウトに入る。"""
    day = "2026-08-14"
    known = sorted(tool().ledger_codes())[0]
    inside = ROOT / "data/__audit_should_not_exist__"
    # **門を外す変異を当てると、ここに JSON まで書かれる。** `rmdir()` は空でない
    # ディレクトリで例外を投げるので、次の実行は門を試す前に落ち、作業ツリーも
    # 汚れたままになる。前も後も、中身ごと消す。
    shutil.rmtree(inside, ignore_errors=True)
    try:
        code, fetched = _run(monkeypatch, tmp_path, {day: [_index_row(known, day)]},
                             ["--store", str(inside), "--days", "1", "--today", day])
        assert code == 2
        assert fetched == [], "拒否したのに取得しに行っている"
        assert not inside.exists(), "拒否したのにディレクトリを作っている"
    finally:
        shutil.rmtree(inside, ignore_errors=True)


def test_what_is_written_carries_the_text_and_no_document_body(monkeypatch, tmp_path):
    """PDF本体を `blob`、採点を `quality_points` という鍵名で保存する変異が、
    鍵名の一覧を見るだけの検査を素通りしていた。実際に書かれたものを読む。"""
    day = "2026-08-14"
    known = sorted(tool().ledger_codes())[0]
    store = tmp_path / "s"
    code, _ = _run(monkeypatch, tmp_path, {day: [_index_row(known, day)]},
                   ["--store", str(store), "--days", "1", "--today", day])
    assert code == 0
    written = sorted(store.glob("*.json"))
    assert len(written) == 1
    record = _json.loads(written[0].read_text(encoding="utf-8"))
    assert record["text"] == "本文"
    assert record["ticker"] == known
    assert record["announced_at"] == "%s 15:30:00" % day
    for key, value in record.items():
        assert not isinstance(value, (bytes, bytearray)), key
    forbidden = {"blob", "pdf", "pdf_bytes", "raw_pdf", "body",
                 "score", "grade", "rank", "quality_points", "scoring_version"}
    assert forbidden.isdisjoint(record), sorted(forbidden & set(record))


def test_a_disclosure_already_gone_is_not_a_failure_but_is_not_success_either(
        monkeypatch, tmp_path):
    """404 と失敗を混ぜる変異、および両方を 0 で終える変異が素通りしていた。"""
    import urllib.error
    day = "2026-08-14"
    known = sorted(tool().ledger_codes())[:2]
    rows = {day: [_index_row(c, day) for c in known]}
    gone = urllib.error.HTTPError("u", 404, "gone", {}, None)
    code, fetched = _run(monkeypatch, tmp_path, rows,
                         ["--store", str(tmp_path / "s"), "--days", "1", "--today", day],
                         fetch_raises=gone)
    assert len(fetched) == 2
    assert code == 0, "窓の外は取り返せない。失敗として扱わない"
    assert not list((tmp_path / "s").glob("*.json"))

    broken = urllib.error.URLError("boom")
    code, _ = _run(monkeypatch, tmp_path, rows,
                   ["--store", str(tmp_path / "s2"), "--days", "1", "--today", day],
                   fetch_raises=broken)
    assert code == 1, "取得に失敗したのに成功として終えている"


def test_a_correction_is_not_captured_as_the_original(monkeypatch, tmp_path):
    day = "2026-08-14"
    known = sorted(tool().ledger_codes())[0]
    rows = {day: [_index_row(known, day, title="（訂正）決算短信の一部訂正について")]}
    code, fetched = _run(monkeypatch, tmp_path, rows,
                         ["--store", str(tmp_path / "s"), "--days", "1", "--today", day])
    assert fetched == [], "訂正版を原本として確保している"
    assert code == 0
