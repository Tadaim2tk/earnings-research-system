"""Deterministic legacy dashboard, weekly report, and note-draft rendering."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from earnings_research.statistics.cohort import MIN_REPORTABLE, summarise
from earnings_research.statistics.holdout import split_by_date
from earnings_research.statistics.lookahead import prices_for

from .aggregation import build_aggregation
from .entry_prices import accepted, attach as attach_entry_prices, by_event, digest as entry_digest, disagreements, read as read_entry_prices
from .labels import cohort_label

# Long on purpose. "d5" meant a five-session hold from the previous close, four
# from the first open and three from the fill, all printed in the same table.
EXIT_EVENT_D5 = "decision_d1_close__entry_d2_open__exit_event_d5_close"
EXIT_EVENT_D20 = "decision_d1_close__entry_d2_open__exit_event_d20_close"
EXIT_PLUS5 = "decision_d1_close__entry_d2_open__exit_entry_plus5_close"
EXIT_PLUS20 = "decision_d1_close__entry_d2_open__exit_entry_plus20_close"

# Three entries into the same exit, then two holds from the same entry. The
# first group answers where to get in, the second how long to stay; a table
# that mixes them answers neither, because a difference could be either.
ENTRY_AXIS = ("open_d20", "close_d20", EXIT_EVENT_D20)
DURATION_AXIS = (EXIT_PLUS5, EXIT_PLUS20)
AXIS_HEADER = (
    "| 入口:初日寄付 | 入口:初日引け | 入口:約定 | 保有:約定+5日 | 保有:約定+20日 |"
)
AXIS_RULE = "|---|---|---|---|---|"


def _axes(rows, match) -> str:
    """One row's five cells: three entries into i0+20, two holds from the fill."""
    return " | ".join(
        _anchored(rows, match, field) for field in ENTRY_AXIS + DURATION_AXIS
    )
from .legacy_parity import (
    render_dashboard_as_retired,
    render_note_as_retired,
    render_weekly_as_retired,
)
from .importer import JUDGES, NARRATIVES, RANKS, SURPRISES, git_bytes, git_text, parse_csv_bytes, sha256_bytes


def pctf(value):
    if value in (None, ""):
        return "-"
    return f"{float(value) * 100:+.1f}%"


def statistics_scope(split) -> str:
    """One sentence saying which records the figures below were built from.

    It used to be injected by build_reports after the fact, which put it above
    the line the note tells the reader to copy from — so the published article
    carried the numbers and left the scope behind.

    It takes the split rather than two lists because it used to infer "no
    reserve was set" from the two being the same length. A caller that simply
    forgot to pass the explored set got that sentence printed over figures
    computed on everything, including the reserve: a false statement, produced
    by the safest-looking mistake available.
    """
    if split.cutoff is None:
        return "留保期間は設定されていない（%s）。以下は一覧の全%d件から。" % (
            split.reason or "理由未記録", len(split.exploration)
        )
    return (
        "統計は探索対象 %d/%d件 のみ。%s以降のレコードは一覧には出るが、"
        "この節のどの数字にも入っていない。"
        % (
            len(split.exploration),
            len(split.exploration) + len(split.reserved),
            split.cutoff.isoformat(),
        )
    )


def findings_line(aggregation) -> str:
    """State what survived the correction, in the place people read.

    This is the sentence the whole change exists to produce, and it appeared
    nowhere a reader would find it: the words for correction, p-value,
    interval and verdict occurred zero times across all three published files.
    Every table below carries a heading phrased as a question, and with no line
    saying the questions came back unanswered, the figures under them read as
    the answers.
    """
    comparisons = sum(
        family.get("comparisons", 0)
        for family in aggregation.get("multiplicity", {}).get("families", {}).values()
    )
    directional = 0
    distinguishable = 0

    def walk(node):
        nonlocal directional, distinguishable
        if isinstance(node, dict):
            if node.get("verdict") == "directional":
                directional += 1
            if node.get("distinguishable") is True:
                distinguishable += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(aggregation)
    surviving = directional + distinguishable
    if surviving == 0:
        return (
            f"**{comparisons}件の比較をBenjamini-Hochbergで補正した結果、統計的に主張できる項目は0件。**"
            "以下の表は記述であって、検証を通過した所見ではない。"
        )
    return (
        f"{comparisons}件の比較をBenjamini-Hochbergで補正し、{surviving}件が残った"
        f"(方向性 {directional} / 裾の捕捉 {distinguishable})。それ以外の数字は記述であって所見ではない。"
    )


def _cell(summary, size_note=""):
    """One published figure, with the width of what it does not settle.

    The win rate was printed alone. Forty-nine cells carried an exact interval,
    a median interval, a sign test and a verdict, and none of the four reached
    the page — twenty-seven of those cells had a mean and a middle pointing
    opposite ways and said nothing about it.
    """
    interval = summary.win_rate_interval
    span = (
        f" [{interval.low * 100:.0f}〜{interval.high * 100:.0f}%]"
        if interval.low is not None and interval.high is not None
        else ""
    )
    mark = "†" if summary.verdict == "tail_driven" else ""
    # The win rate's denominator is not n when some outcomes went neither way,
    # and printing n alone made a 25% read as one in four when it was one in
    # four out of six.
    ties = f", 引分{summary.ties}" if summary.ties else ""
    return (
        f"{summary.win_rate * 100:.0f}%{span} / {summary.median * 100:+.1f}% / "
        f"{summary.mean * 100:+.1f}% (n={summary.n}{size_note}{ties}){mark}"
    )


def _avg(rows, predicate, key="ret_d20"):
    """Win rate, median and mean, because the mean alone hides its own shape.

    One name limit-up for three days and a group that all drifted up give the
    same average. The win rate and the middle separate them, and a cohort too
    small to say anything prints its size instead of a number.

    Names, not rows: two earnings from one company are one company's evidence,
    and the aggregation beside this has counted them that way from the start.
    """
    picked = [
        (float(row[key]), row.get("code"))
        for row in rows
        if row.get(key) not in (None, "") and predicate(row)
    ]
    if not picked:
        return "-"
    summary = summarise(
        [value for value, _code in picked], clusters=[code for _value, code in picked]
    )
    if not summary.reportable:
        return f"n={summary.n}(件数不足)"
    if summary.win_rate is None:
        return f"n={summary.n}(全て横ばい)"
    names = "" if summary.n_independent == summary.n else f", {summary.n_independent}社"
    return _cell(summary, names)


def _anchored(rows, predicate, field):
    """The same figures measured between two prices actually available.

    Both prices have to be positive. Treating a zero exit as a -100% return,
    which is what happens when only the entry is checked, disagrees with the
    aggregation beside it, which drops the row.
    """
    entry_field, exit_field = prices_for(field)
    values = []
    for row in rows:
        if not predicate(row):
            continue
        try:
            start, end = float(row[entry_field]), float(row[exit_field])
        except (TypeError, ValueError, KeyError):
            continue
        if start > 0 and end > 0:
            values.append({"v": (end - start) / start, "code": row.get("code")})
    return _avg(values, lambda _row: True, "v")


def render_dashboard(rows, updated_at: str, *, aggregation=None):
    """Render the dashboard, listing every record but counting only some.

    Listing a reserved record and computing a statistic from it are different
    acts. The recent-records table enumerates what happened and is harmless;
    every aggregate below is a number a hypothesis could be shaped against, so
    it is built from the exploration set alone. Passing the reserved rows into
    both was how the holdout leaked into the one artefact a person reads.
    """
    # Split here rather than trusting the caller. The parameter version was
    # fail-open: forgetting it silently put the reserved third back into every
    # published figure and printed a sentence saying no reserve existed.
    split = split_by_date(rows)
    counted = split.exploration
    lines = ["# 決算研究OS ダッシュボード", "", f"最終更新: {updated_at} / 記録 {len(rows)}件", ""]
    pending = [row for row in rows if row.get("d20_close") not in (None, "") and not (row.get("result") or "").strip()]
    if pending:
        lines += [f"## ⏳ レビュー待ち({len(pending)}件) — CSVの result / error_type / review_note を記入", "",
                  "| 発表日 | コード | 銘柄 | ランク | 判断 | 20日 | 撤回条件(当時) |", "|---|---|---|---|---|---|---|"]
        for row in sorted(pending, key=lambda item: item.get("date", "")):
            lines.append(f"| {row.get('date','')} | {row.get('code','')} | {row.get('name','')} | {row.get('rank','')} | {row.get('judge','')} | {pctf(row.get('ret_d20'))} | {row.get('exit_condition','')} |")
        lines.append("")
    recent = sorted(rows, key=lambda item: item.get("date", ""), reverse=True)[:20]
    lines += ["## 直近の記録(最新20件)", "", "| 発表日 | コード | 銘柄 | ランク | 判断 | ナラ | ギャップ | 翌日 | 5日 | 20日 | 分類 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in recent:
        lines.append("| {date} | {code} | {name} | {rank} | {judge} | {narrative} | {gap} | {d1} | {d5} | {d20} | {rx} |".format(
            date=row.get("date", ""), code=row.get("code", ""), name=row.get("name", ""), rank=row.get("rank", ""),
            judge=row.get("judge", ""), narrative=row.get("narrative", ""), gap=pctf(row.get("gap")),
            d1=pctf(row.get("ret_d1")), d5=pctf(row.get("ret_d5")), d20=pctf(row.get("ret_d20")),
            rx=row.get("reaction", "") or "記録中"))
    lines += ["", "## 仮説検証", "",
              findings_line(aggregation if aggregation is not None else build_aggregation(rows, [], "")),
              "",
              statistics_scope(split),
              "",
              "各セルは **勝率 [95%区間] / 中央値 / 平均 (n)**。平均だけでは、1銘柄の",
              "大幅高が群を持ち上げている場合と、群全体が揃って動いた場合を区別できない。",
              "区間の幅がそのまま、この件数で言えることの狭さ。",
              "**†** は平均と中央値が食い違う群、つまり平均を担っているのが群全体ではなく",
              "両端の少数という印。`n=N(件数不足)` は5件未満で数字を出さない、",
              "`n=N(全て横ばい)` は全件が値動きゼロで勝率が定義できない、",
              "`-` は該当する観測が1件も無いという意味。同一銘柄が複数回現れる群では",
              "件数のうしろに社数を添える。",
              "",
              "**すべて約定起点で並べている。** 開示は大引け後に出る。初日が反応し、",
              "その引けを見て判断し、注文は翌日の寄り付きで約定する。その寄り付き",
              "(発表日を i0 として i0+2)が、これらの数字の起点である。",
              "",
              "これまでは寄り付き(i0+1)起点で並べていた。汚染はされていないが、",
              "**ギャップに飛び乗る前提**の数字であり、実際に執行する地点ではない。",
              "翌日終値(i0+1)起点も同様に、反応分類を決めるまさにその値段で約定する",
              "前提になる。約定起点だけが、どのラベルよりも後に存在する価格である。",
              "",
              "表は二つに分かれている。**出口固定**は発表から5・20営業日後の引けに",
              "出口を固定してあるので、起点を変えても比べられる — 動くのは入口だけで、",
              "答えるのは「いつ入るのがよいか」。**保有固定**は約定から5・20営業日",
              "持った場合で、入口は同じまま出口だけが動く — 答えるのは「何日持つのが",
              "よいか」。",
              "",
              "この二つを混ぜると、差が入口のせいか保有期間のせいか区別できなくなる。",
              "発表起点の「5日」は、前日終値からなら5営業日、初日の寄り付きからなら",
              "4営業日、約定からなら3営業日で、同じ表に並べると別物を比べることになる。",
              "",
              "### ランク別 リターン(仮説: AI事前評価に予測力はあるか)",
              "| ランク " + AXIS_HEADER, "|---" + AXIS_RULE]
    for rank in RANKS:
        match = lambda row, rank=rank: cohort_label(row.get("rank")) == rank
        lines.append(
            f"| {rank} | {_axes(counted, match)} |"
        )
    lines += ["", "### ナラティブ整合別 20日リターン(仮説: 衝突時は劣化?)", "| ナラティブ " + AXIS_HEADER, "|---" + AXIS_RULE]
    for narrative in NARRATIVES:
        match = lambda row, narrative=narrative: cohort_label(row.get("narrative")) == narrative
        lines.append(f"| {narrative} | {_axes(counted, match)} |")
    lines += ["", "### 判断別 リターン(仮説: 見送りは防御か機会損失か)", "| 判断 " + AXIS_HEADER, "|---" + AXIS_RULE]
    for judge in JUDGES:
        match = lambda row, judge=judge: cohort_label(row.get("judge")) == judge
        lines.append(
            f"| {judge} | {_axes(counted, match)} |"
        )
    lines += ["", "### 初動分類別 リターン(仮説: 初動ギャップは持続するか)", "",
              "この群は**ギャップで分けている**ので、前日終値起点で見ると分類に使った",
              "当のギャップを測り直すことになり、必ず「GUは強い」と出る。",
              "",
              "| 初動 " + AXIS_HEADER, "|---" + AXIS_RULE]
    for value in ("GU", "フラット", "GD"):
        match = lambda row, value=value: cohort_label(row.get("shodo")) == value
        lines.append(
            f"| {value} | {_axes(counted, match)} |"
        )
    lines += ["", "### 反応分類別 リターン(仮説: 初日の値動きパターンに持続性はあるか)", "",
              "この分類は初日の引けで確定する。約定起点はその後に存在する価格なので、",
              "分類と結果が1本も重ならない。翌日終値起点だと、分類を決めるその値段で",
              "約定する前提になっていた。",
              "",
              "| 分類 " + AXIS_HEADER, "|---" + AXIS_RULE]
    for value in ("GU継続", "GU失速", "GD反発", "GD継続"):
        match = lambda row, value=value: cohort_label(row.get("reaction")) == value
        lines.append(
            f"| {value} | {_axes(counted, match)} |"
        )
    lines += ["", "### AIサプライズ評価 × 実際の市場反応(自己較正)", "",
              "元はギャップで較正していたが、ギャップは寄り付きで起きるのでどちら向きにも",
              "取引できず、しかもサプライズ評価自体が大引け後に付く。",
              "",
              "| サプライズ " + AXIS_HEADER, "|---" + AXIS_RULE]
    for value in SURPRISES:
        match = lambda row, value=value: cohort_label(row.get("surprise")) == value
        lines.append(
            f"| {value} | {_axes(counted, match)} |"
        )
    # A section titled 集計 three lines under a sentence promising the reserved
    # rows enter no aggregate. Empty today because no result column is filled,
    # and the dashboard directly asks the reader to fill it.
    done = [row for row in counted if (row.get("result") or "").strip()]
    if done:
        counts = {}
        for row in done:
            counts[row["result"].strip()] = counts.get(row["result"].strip(), 0) + 1
        lines += ["", "### 手動レビュー結果の集計", "| result | 件数 |", "|---|---|"]
        for key in sorted(counts):
            lines.append(f"| {key} | {counts[key]} |")
    lines += ["", "---", "本資料は観察と仮説検証の記録であり、特定銘柄の売買を推奨するものではありません。"]
    return "\n".join(lines) + "\n"


def render_weekly(rows, as_of: date):
    """Only lists records; it computes no statistic, so it needs no split."""
    since = as_of - timedelta(days=7)
    week = [row for row in rows if str(since) <= row.get("date", "") <= str(as_of)]
    lines = [f"# AI決算研究ログ 週次検証 {as_of}", "", "決算発表に対する株価反応を記録・検証する個人研究ログ。売買推奨ではなく観察と仮説検証の記録です。", "", f"## 今週の記録({len(week)}件)", ""]
    if week:
        lines += ["| コード | 銘柄 | ランク | 判断 | ナラ | ギャップ | 翌日 | 分類 |", "|---|---|---|---|---|---|---|---|"]
        for row in week:
            lines.append(f"| {row['code']} | {row['name']} | {row.get('rank','')} | {row.get('judge','')} | {row.get('narrative','')} | {pctf(row.get('gap'))} | {pctf(row.get('ret_d1'))} | {row.get('reaction','') or '記録中'} |")
        lines.append("")
        for row in week:
            lines += [f"### {row['name']}({row['code']})", f"- 見立て: {row.get('memo','')}", f"- 撤回条件: {row.get('exit_condition','')}", f"- 反応: ギャップ{pctf(row.get('gap'))} 翌日{pctf(row.get('ret_d1'))}", ""]
    else:
        lines += ["今週の新規記録はありません。", ""]
    observed = [row for row in rows if str(as_of - timedelta(days=35)) <= row.get("date", "") < str(since) and row.get("ret_d5") not in (None, "")]
    if observed:
        # It lists rows on both sides of the reserve cutoff under a heading
        # that says the answers are in. No statistic is computed here, and none
        # of these rows has been through the correction — the reader forming a
        # hypothesis in the section directly below is looking at the reserved
        # period, which is the one thing the reserve exists to prevent.
        lines += [
            f"## 経過観測 — 先週以前の記録の答え合わせ({len(observed)}件)",
            "",
            "この節は一覧であって検証ではない。留保期間のレコードも含み、"
            "どの数字も多重比較補正を通っていない。",
            "",
            "| 発表日 | 銘柄 | 判断(当時) | ギャップ | 翌日 | 5日 | 20日 |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in sorted(observed, key=lambda item: item.get("date", "")):
            lines.append(f"| {row.get('date','')} | {row['name']}({row['code']}) | {row.get('judge','')} | {pctf(row.get('gap'))} | {pctf(row.get('ret_d1'))} | {pctf(row.get('ret_d5'))} | {pctf(row.get('ret_d20')) if row.get('ret_d20') not in (None,'') else '記録中'} |")
        lines.append("")
    lines += ["## 今週の気づき・仮説", "", "(投稿前にここを手書き。例: 衝突判定の銘柄は翌日リターンが弱い傾向。件数が増えたら検証)", "", "---", "本記事は特定銘柄の売買を推奨するものではありません。投資判断はご自身の責任で行ってください。"]
    return "\n".join(lines) + "\n"


def render_note(rows, as_of: date, *, aggregation=None):
    # Split here rather than trusting the caller. The parameter version was
    # fail-open: forgetting it silently put the reserved third back into every
    # published figure and printed a sentence saying no reserve existed.
    split = split_by_date(rows)
    counted = split.exploration
    since = as_of - timedelta(days=7)
    week = sorted((row for row in rows if str(since) <= row.get("date", "") <= str(as_of)), key=lambda item: (item.get("rank", "z"), item.get("date", "")))
    insights = []
    for narrative in NARRATIVES:
        # Every figure the note carries is measured from the price an order
        # fills at. The note is the block a reader is told to copy, so an
        # anchor corrected in the dashboard and not here is a corrected report
        # publishing the uncorrected number.
        figures = _anchored(
            counted, lambda row, narrative=narrative: cohort_label(row.get("narrative")) == narrative,
            EXIT_EVENT_D20,
        )
        if figures != "-":
            insights.append(f"ナラティブ「{narrative}」の約定から20日 勝率/中央値/平均: {figures}")
    for reaction in ("GD反発", "GD継続", "GU継続", "GU失速"):
        # Split on the first day's own move, which is settled at that day's
        # close — strictly before the price this return starts from.
        figures = _anchored(
            counted, lambda row, reaction=reaction: cohort_label(row.get("reaction")) == reaction, EXIT_EVENT_D5
        )
        if figures != "-":
            insights.append(f"初日「{reaction}」の約定からの5日 勝率/中央値/平均: {figures}")
    lines = [f"# AI決算研究ログ 週次検証 {as_of}(note投稿用ドラフト)", "", "―― 使い方 ――  下の「今週の気づき」に一筆だけ書き、`本文ここから`以降をnoteにコピペして公開してください。", "", "## 今週の気づき(←ここだけ手書き。これがこの記事の主役)", "", "（例: 衝突判定の銘柄は翌日リターンが弱い傾向が続いている。件数が増えたら本検証する。）", "", "──────────  本文ここから  ──────────", "", "決算発表に対する株価反応を記録・検証している個人研究ログです。特定銘柄の売買を推奨するものではなく、観察と仮説検証の記録です。", "", f"## 今週記録した銘柄({len(week)}件)", ""]
    if week:
        for row in week:
            lines += [f"▼ {row['name']}({row['code']})　ランク{row.get('rank','-')} / 判断:{row.get('judge','-')} / ナラティブ:{row.get('narrative','-')}", f"　見立て: {row.get('memo','') or '—'}", f"　初動: ギャップ{pctf(row.get('gap'))} → 翌日{pctf(row.get('ret_d1'))}（{row.get('reaction','') or '記録中'}）", f"　撤回条件(記録時): {row.get('exit_condition','') or '—'}", ""]
    else:
        lines += ["今週の新規記録はありませんでした。", ""]
    if insights:
        lines += [
            "## 今週時点の検証メモ(自動集計)",
            "",
            # Inside the block this file tells the reader to copy and publish.
            # The dashboard said what the correction left and the note did not,
            # so the figures below travelled without it.
            findings_line(aggregation if aggregation is not None else build_aggregation(rows, [], "")),
            "",
            statistics_scope(split),
            "",
        ] + [f"・{item}" for item in insights] + [""]
    lines += ["──────────  本文ここまで  ──────────", "", "免責: 本記事は特定銘柄の売買を推奨するものではありません。投資判断はご自身の責任で行ってください。"]
    return "\n".join(lines) + "\n"


def _source_output(source_repo: Path, source_commit: str, path: str):
    output_commit = git_text(source_repo, "log", "-1", "--format=%H", source_commit, "--", path).strip()
    output_bytes = git_bytes(source_repo, output_commit, path)
    _, rows = parse_csv_bytes(git_bytes(source_repo, output_commit, "data/records.csv"))
    return output_commit, output_bytes, rows


def build_reports(source_repo: Path, source_commit: str, final_rows, context_views, as_of: date):
    source_files = {}
    parity = {}
    dashboard_commit, old_dashboard, dashboard_rows = _source_output(source_repo, source_commit, "dashboard.md")
    match = re.search(r"最終更新: ([0-9-]+ [0-9:]+)", old_dashboard.decode("utf-8"))
    if not match:
        raise ValueError("legacy dashboard timestamp is missing")
    # Parity is a statement about the retired system, so it is checked with the
    # renderer frozen at that system's shape. Reading it with the current one
    # would report a difference in ERS as a loss in the migration, and would
    # make every future improvement to the reports look like data corruption.
    rendered_old_dashboard = render_dashboard_as_retired(dashboard_rows, match.group(1)).encode("utf-8")
    source_files["source/dashboard.md"] = old_dashboard
    parity["dashboard"] = {"source_commit": dashboard_commit, "byte_equal": rendered_old_dashboard == old_dashboard, "source_sha256": sha256_bytes(old_dashboard), "rendered_sha256": sha256_bytes(rendered_old_dashboard)}
    for path, renderer, label in (
        ("weekly_report.md", render_weekly_as_retired, "weekly_report"),
        ("note_draft.md", render_note_as_retired, "note_draft"),
    ):
        output_commit, old_output, output_rows = _source_output(source_repo, source_commit, path)
        match = re.search(r"週次検証 ([0-9]{4}-[0-9]{2}-[0-9]{2})", old_output.decode("utf-8"))
        if not match:
            raise ValueError(f"legacy {label} as-of date is missing")
        rendered = renderer(output_rows, date.fromisoformat(match.group(1))).encode("utf-8")
        source_files[f"source/{path}"] = old_output
        parity[label] = {"source_commit": output_commit, "byte_equal": rendered == old_output, "source_sha256": sha256_bytes(old_output), "rendered_sha256": sha256_bytes(rendered)}
    if not all(item["byte_equal"] for item in parity.values()):
        raise ValueError("legacy publishing parity failed")
    reports = render_reports(final_rows, context_views, source_commit, as_of)
    reports["publishing_parity.json"] = json.dumps({
        "schema_version": "legacy_publishing_parity_v1", "source_commit": source_commit,
        "record_count": len(final_rows),
        "tso_context_link_count": sum(view["join_status"] == "ok" for view in context_views),
        "outputs": parity,
    }, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    return source_files, reports, parity


def render_reports(final_rows, context_views, source_commit: str, as_of: date):
    """The published reports, from the record alone.

    Split out of `build_reports` because that call also proves the retired
    system's own renderer still reproduces its own output byte for byte, and
    that proof needs the retired repository at a pinned commit. Two machines
    have it; CI does not. So the reports the reader actually reads could not be
    checked anywhere — they sat committed, generated once, with nothing
    noticing when the code that makes them changed underneath.

    Everything here comes from files this repository carries and hashes.
    """
    coverage = sum(view["join_status"] == "ok" for view in context_views)
    provenance = f"dataset_origin: earnings-research-os / record_mode: legacy_observational / source_commit: {source_commit} / TSO context: {coverage}/{len(context_views)}"
    aggregation = build_aggregation(final_rows, context_views, source_commit)
    context = aggregation["market_context"]
    def _score(name):
        value = context.get(name)
        return "-" if value is None else f"{value:.2f}"

    context_line = (
        f"TSO point-in-time context: {context['linked_count']}/{aggregation['record_count']}件(探索対象) / "
        f"平均risk-on {_score('mean_risk_on_score')} / 平均risk-off {_score('mean_risk_off_score')}"
    )
    # Each renderer splits the record for itself, with no reserve argument, so
    # the aggregation and the published tables cannot end up on different
    # populations by one call site being changed and not the other. The scope
    # sentence is written beside the figures it qualifies; injected here it
    # landed above the line the note tells the reader to copy from, so the
    # published article carried the numbers and left their scope behind.
    dashboard = render_dashboard(final_rows, f"{as_of} 00:00", aggregation=aggregation)
    dashboard = dashboard.replace("\n\n", f"\n\n{provenance}\n\n{context_line}\n\n", 1)
    weekly = render_weekly(final_rows, as_of).replace("\n\n", f"\n\n{provenance}\n\n", 1)
    note = render_note(final_rows, as_of, aggregation=aggregation).replace(
        "\n\n", f"\n\n{provenance}\n\n", 1
    )
    return {
        "dashboard.md": dashboard.encode("utf-8"),
        "weekly_report.md": weekly.encode("utf-8"),
        "note_draft.md": note.encode("utf-8"),
        "aggregation_summary.json": json.dumps(
            aggregation, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8") + b"\n",
    }


def write_reports(output_dir: Path, reports: dict[str, bytes]):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in reports.items():
        path = output_dir / name
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(content)
        temp.replace(path)


# Fetched separately from the frozen migration, because the retired system never
# recorded it. Kept beside the repository root rather than inside the migration
# tree: that tree is reproduced byte for byte from the retired repository and a
# file it never held does not belong in it.
ENTRY_PRICES = Path("data/market_prices/legacy_event_sessions.jsonl")
ENTRY_MANIFEST = Path("data/market_prices/manifest.json")


def with_entry_prices(rows, path: Path, manifest_path: Path):
    """Give each record the price its order would have filled at.

    Refuses rather than degrades. Without this file every entry-anchored return
    is None, which reads in the published tables as "not enough records" — the
    same words a genuinely small cohort gets. A missing fetch would look like a
    finding about the data.

    The fetch is checked against the record before it is used: it re-derives the
    five prices the record already holds, and a disagreement means it read a
    different series and its entry price cannot be trusted either.
    """
    fetched = read_entry_prices(path)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest["sha256"] != entry_digest(path):
        raise ValueError("fetched prices do not match the digest recorded for them")
    problems = disagreements(fetched, rows, accepted(manifest_path))
    if problems:
        raise ValueError(
            "fetched prices disagree with the record in %d places: %s"
            % (len(problems), "; ".join(problems[:3]))
        )
    return attach_entry_prices(rows, by_event(fetched))


def reporting_date(rows) -> date:
    """The as-of the reports carry: the last day the record covers.

    One derivation, called by both paths that produce reports. They used to
    disagree — the migration took an as-of from its caller while the rebuild
    derived this one — so a report freshly made by the documented command
    failed the verification of the same reports on the next line, and rebuilding
    it silently moved the weekly window.
    """
    dates = sorted(row["date"] for row in rows if row.get("date"))
    if not dates:
        raise ValueError("frozen legacy record carries no usable dates")
    return date.fromisoformat(dates[-1])


def rebuild_reports(input_root: Path, entry_prices: Path = ENTRY_PRICES,
                    entry_manifest: Path = ENTRY_MANIFEST):
    """The published reports, rebuilt from what this repository already carries.

    No retired repository, no TSO checkout, nothing outside these files. That
    is the point: the reports a reader actually opens were generated once, by
    hand, on a machine that had those checkouts — so when the statistics under
    them changed, nothing said the committed files no longer matched the code.
    They sat for weeks describing a pipeline that had been replaced.

    Every input is hash-checked against the migration manifest, so "rebuilt
    from the record" means the record and not whatever is on disk.
    """
    input_root = Path(input_root)
    manifest = json.loads((input_root / "migration_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("prospective_records_created") != 0 or manifest.get("formal_evidence_created") != 0:
        raise ValueError("frozen legacy migration boundary is invalid")
    if manifest.get("tso_writeback_performed") is not False:
        raise ValueError("frozen legacy migration must remain read-only to TSO")
    digests = manifest.get("output_sha256", {})
    for name in ("source/records.csv", "legacy_context_view.jsonl"):
        expected = digests.get(name)
        actual = sha256_bytes((input_root / name).read_bytes())
        if not expected or actual != expected:
            raise ValueError(f"frozen legacy input hash mismatch: {name}")
    _fields, rows = parse_csv_bytes((input_root / "source/records.csv").read_bytes())
    rows = with_entry_prices(rows, entry_prices, entry_manifest)
    contexts = [
        json.loads(line)
        for line in (input_root / "legacy_context_view.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Derived, not passed in. An as-of supplied by the caller would put a
    # different date in the file every day it was rebuilt, and the check
    # against the committed copies would report a mismatch that means nothing.
    return render_reports(rows, contexts, manifest["frozen_source_commit"], reporting_date(rows))


def verify_reports(input_root: Path, output_dir: Path, entry_prices: Path = ENTRY_PRICES,
                   entry_manifest: Path = ENTRY_MANIFEST):
    """Refuse committed reports that the current code would not produce."""
    expected = rebuild_reports(input_root, entry_prices, entry_manifest)
    output_dir = Path(output_dir)
    for name, content in expected.items():
        path = output_dir / name
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError(f"published report is not what the current code produces: {name}")
    return {"status": "verified", "report_count": len(expected)}
