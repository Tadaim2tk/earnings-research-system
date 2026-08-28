"""Deterministic legacy dashboard, weekly report, and note-draft rendering."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from earnings_research.statistics.cohort import summarise

from .aggregation import build_aggregation
from .importer import JUDGES, NARRATIVES, RANKS, SURPRISES, git_bytes, git_text, parse_csv_bytes, sha256_bytes


def pctf(value):
    if value in (None, ""):
        return "-"
    return f"{float(value) * 100:+.1f}%"


def _avg(rows, predicate, key="ret_d20"):
    """Win rate, median and mean, because the mean alone hides its own shape.

    One name limit-up for three days and a group that all drifted up give the
    same average. The win rate and the middle separate them, and a cohort too
    small to say anything prints its size instead of a number.
    """
    values = sorted(
        float(row[key]) for row in rows if row.get(key) not in (None, "") and predicate(row)
    )
    if not values:
        return "-"
    summary = summarise(values)
    if not summary.reportable:
        return f"n={summary.n}(少)"
    return (
        f"{summary.win_rate * 100:.0f}% / {summary.median * 100:+.1f}% / "
        f"{summary.mean * 100:+.1f}% (n={summary.n})"
    )


def _anchored(rows, predicate, entry, exit_):
    """The same figures measured between two prices actually available."""
    values = []
    for row in rows:
        if not predicate(row):
            continue
        try:
            start, end = float(row[entry]), float(row[exit_])
        except (TypeError, ValueError, KeyError):
            continue
        if start:
            values.append((end - start) / start)
    return _avg([{"v": value} for value in values], lambda _row: True, "v")


def render_dashboard(rows, updated_at: str):
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
              "各セルは **勝率 / 中央値 / 平均 (n)**。平均だけでは、1銘柄の大幅高が群を",
              "持ち上げている場合と、群全体が揃って動いた場合を区別できない。",
              "", "### ランク別 リターン(仮説: AI事前評価に予測力はあるか)",
              "| ランク | 翌日 | 5日 | 20日 |", "|---|---|---|---|"]
    for rank in RANKS:
        lines.append(f"| {rank} | {_avg(rows, lambda row, rank=rank: row.get('rank') == rank, 'ret_d1')} | {_avg(rows, lambda row, rank=rank: row.get('rank') == rank, 'ret_d5')} | {_avg(rows, lambda row, rank=rank: row.get('rank') == rank)} |")
    lines += ["", "### ナラティブ整合別 20日リターン(仮説: 衝突時は劣化?)", "| ナラティブ | 勝率/中央値/平均 |", "|---|---|"]
    for narrative in NARRATIVES:
        lines.append(f"| {narrative} | {_avg(rows, lambda row, narrative=narrative: row.get('narrative') == narrative)} |")
    lines += ["", "### 判断別 20日リターン(仮説: 見送りは防御か機会損失か)", "| 判断 | 勝率/中央値/平均 |", "|---|---|"]
    for judge in JUDGES:
        lines.append(f"| {judge} | {_avg(rows, lambda row, judge=judge: row.get('judge') == judge)} |")
    lines += ["", "### 初動分類別 リターン(仮説: 初動ギャップは持続するか)", "",
              "これらの群は**ギャップで分けている**ので、前日終値起点のリターンで見ると",
              "分類に使った当のギャップを測り直すことになり、必ず「GUは強い」と出る。",
              "約定できる最初の価格は寄り付きなので、**寄り付き起点**で並べる。",
              "",
              "| 初動 | 寄り付き→翌日終値 | 寄り付き→5日 | 寄り付き→20日 |", "|---|---|---|---|"]
    for value in ("GU", "フラット", "GD"):
        match = lambda row, value=value: row.get("shodo") == value
        lines.append(
            f"| {value} | {_anchored(rows, match, 'next_open', 'next_close')} | "
            f"{_anchored(rows, match, 'next_open', 'd5_close')} | "
            f"{_anchored(rows, match, 'next_open', 'd20_close')} |"
        )
    lines += ["", "### 反応分類別 リターン(仮説: 初日の値動きパターンに持続性はあるか)", "",
              "この群は初日の値動きでも分けているので、寄り付き起点にも定義の半分が入る。",
              "戻しを見てから入るなら起点は翌日終値になる。",
              "",
              "| 分類 | 翌日終値→5日 | 翌日終値→20日 |", "|---|---|---|"]
    for value in ("GU継続", "GU失速", "GD反発", "GD継続"):
        match = lambda row, value=value: row.get("reaction") == value
        lines.append(
            f"| {value} | {_anchored(rows, match, 'next_close', 'd5_close')} | "
            f"{_anchored(rows, match, 'next_close', 'd20_close')} |"
        )
    lines += ["", "### AIサプライズ評価 × 実際の市場反応(自己較正)", "| サプライズ | 平均ギャップ | 平均翌日 |", "|---|---|---|"]
    for value in SURPRISES:
        lines.append(f"| {value} | {_avg(rows, lambda row, value=value: str(row.get('surprise', '')).strip() == value, 'gap')} | {_avg(rows, lambda row, value=value: str(row.get('surprise', '')).strip() == value, 'ret_d1')} |")
    done = [row for row in rows if (row.get("result") or "").strip()]
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
        lines += [f"## 経過観測 — 先週以前の記録の答え合わせ({len(observed)}件)", "", "| 発表日 | 銘柄 | 判断(当時) | ギャップ | 翌日 | 5日 | 20日 |", "|---|---|---|---|---|---|---|"]
        for row in sorted(observed, key=lambda item: item.get("date", "")):
            lines.append(f"| {row.get('date','')} | {row['name']}({row['code']}) | {row.get('judge','')} | {pctf(row.get('gap'))} | {pctf(row.get('ret_d1'))} | {pctf(row.get('ret_d5'))} | {pctf(row.get('ret_d20')) if row.get('ret_d20') not in (None,'') else '記録中'} |")
        lines.append("")
    lines += ["## 今週の気づき・仮説", "", "(投稿前にここを手書き。例: 衝突判定の銘柄は翌日リターンが弱い傾向。件数が増えたら検証)", "", "---", "本記事は特定銘柄の売買を推奨するものではありません。投資判断はご自身の責任で行ってください。"]
    return "\n".join(lines) + "\n"


def render_note(rows, as_of: date):
    since = as_of - timedelta(days=7)
    week = sorted((row for row in rows if str(since) <= row.get("date", "") <= str(as_of)), key=lambda item: (item.get("rank", "z"), item.get("date", "")))
    insights = []
    for narrative in NARRATIVES:
        values = [float(row["ret_d1"]) for row in rows if row.get("ret_d1") not in (None, "") and row.get("narrative") == narrative]
        if len(values) >= 3:
            insights.append(f"ナラティブ「{narrative}」の平均翌日リターン: {sum(values)/len(values)*100:+.1f}%(n={len(values)})")
    for reaction in ("GD反発", "GD継続", "GU継続", "GU失速"):
        values = [float(row["ret_d5"]) for row in rows if row.get("ret_d5") not in (None, "") and row.get("reaction") == reaction]
        if len(values) >= 3:
            insights.append(f"初日「{reaction}」のその後5日リターン: {sum(values)/len(values)*100:+.1f}%(n={len(values)})")
    lines = [f"# AI決算研究ログ 週次検証 {as_of}(note投稿用ドラフト)", "", "―― 使い方 ――  下の「今週の気づき」に一筆だけ書き、`本文ここから`以降をnoteにコピペして公開してください。", "", "## 今週の気づき(←ここだけ手書き。これがこの記事の主役)", "", "（例: 衝突判定の銘柄は翌日リターンが弱い傾向が続いている。件数が増えたら本検証する。）", "", "──────────  本文ここから  ──────────", "", "決算発表に対する株価反応を記録・検証している個人研究ログです。特定銘柄の売買を推奨するものではなく、観察と仮説検証の記録です。", "", f"## 今週記録した銘柄({len(week)}件)", ""]
    if week:
        for row in week:
            lines += [f"▼ {row['name']}({row['code']})　ランク{row.get('rank','-')} / 判断:{row.get('judge','-')} / ナラティブ:{row.get('narrative','-')}", f"　見立て: {row.get('memo','') or '—'}", f"　初動: ギャップ{pctf(row.get('gap'))} → 翌日{pctf(row.get('ret_d1'))}（{row.get('reaction','') or '記録中'}）", f"　撤回条件(記録時): {row.get('exit_condition','') or '—'}", ""]
    else:
        lines += ["今週の新規記録はありませんでした。", ""]
    if insights:
        lines += ["## 今週時点の検証メモ(自動集計)", ""] + [f"・{item}" for item in insights] + [""]
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
    rendered_old_dashboard = render_dashboard(dashboard_rows, match.group(1)).encode("utf-8")
    source_files["source/dashboard.md"] = old_dashboard
    parity["dashboard"] = {"source_commit": dashboard_commit, "byte_equal": rendered_old_dashboard == old_dashboard, "source_sha256": sha256_bytes(old_dashboard), "rendered_sha256": sha256_bytes(rendered_old_dashboard)}
    for path, renderer, label in (("weekly_report.md", render_weekly, "weekly_report"), ("note_draft.md", render_note, "note_draft")):
        output_commit, old_output, output_rows = _source_output(source_repo, source_commit, path)
        match = re.search(r"週次検証 ([0-9]{4}-[0-9]{2}-[0-9]{2})", old_output.decode("utf-8"))
        if not match:
            raise ValueError(f"legacy {label} as-of date is missing")
        rendered = renderer(output_rows, date.fromisoformat(match.group(1))).encode("utf-8")
        source_files[f"source/{path}"] = old_output
        parity[label] = {"source_commit": output_commit, "byte_equal": rendered == old_output, "source_sha256": sha256_bytes(old_output), "rendered_sha256": sha256_bytes(rendered)}
    if not all(item["byte_equal"] for item in parity.values()):
        raise ValueError("legacy publishing parity failed")
    coverage = sum(view["join_status"] == "ok" for view in context_views)
    provenance = f"dataset_origin: earnings-research-os / record_mode: legacy_observational / source_commit: {source_commit} / TSO context: {coverage}/{len(context_views)}"
    aggregation = build_aggregation(final_rows, context_views, source_commit)
    context = aggregation["market_context"]
    def _score(name):
        value = context.get(name)
        return "-" if value is None else f"{value:.2f}"

    context_line = (
        f"TSO point-in-time context: {context['linked_count']}/{len(final_rows)}件 / "
        f"平均risk-on {_score('mean_risk_on_score')} / 平均risk-off {_score('mean_risk_off_score')}"
    )
    dashboard = render_dashboard(final_rows, f"{as_of} 00:00")
    dashboard = dashboard.replace("\n\n", f"\n\n{provenance}\n\n{context_line}\n\n", 1)
    weekly = render_weekly(final_rows, as_of).replace("\n\n", f"\n\n{provenance}\n\n", 1)
    note = render_note(final_rows, as_of).replace("\n\n", f"\n\n{provenance}\n\n", 1)
    reports = {
        "dashboard.md": dashboard.encode("utf-8"),
        "weekly_report.md": weekly.encode("utf-8"),
        "note_draft.md": note.encode("utf-8"),
        "publishing_parity.json": json.dumps({
            "schema_version": "legacy_publishing_parity_v1", "source_commit": source_commit,
            "record_count": len(final_rows), "tso_context_link_count": coverage,
            "outputs": parity,
        }, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "aggregation_summary.json": json.dumps(
            aggregation, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8") + b"\n",
    }
    return source_files, reports, parity


def write_reports(output_dir: Path, reports: dict[str, bytes]):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in reports.items():
        path = output_dir / name
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(content)
        temp.replace(path)
