"""Reproduce the retired system's three published files byte for byte.

The migration's claim is that nothing was lost: given the retired repository's
own rows, this code reproduces the exact bytes it published, and any difference
is a difference in the data rather than in the reading of it. That claim only
holds against a renderer frozen at the shape the retired system used.

So these are copies, deliberately, of the renderers as they stood before ERS
began changing what a report says. They are not maintained. Improvements to
what ERS publishes belong in ``publishing``; a change here breaks a statement
about the past, which is why the parity test reads the retired repository's own
committed output rather than anything this file produces.
"""

from datetime import date, timedelta

from .importer import JUDGES, NARRATIVES, RANKS, SURPRISES


def pctf(value):
    if value in (None, ""):
        return "-"
    return f"{float(value) * 100:+.1f}%"


def _avg(rows, predicate, key="ret_d20"):
    values = [float(row[key]) for row in rows if row.get(key) not in (None, "") and predicate(row)]
    return f"{sum(values) / len(values) * 100:+.1f}% (n={len(values)})" if values else "-"


def render_dashboard_as_retired(rows, updated_at: str):
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
    lines += ["", "## 仮説検証", "", "### ランク別 平均リターン(仮説: AI事前評価に予測力はあるか)",
              "| ランク | 翌日 | 5日 | 20日 |", "|---|---|---|---|"]
    for rank in RANKS:
        lines.append(f"| {rank} | {_avg(rows, lambda row, rank=rank: row.get('rank') == rank, 'ret_d1')} | {_avg(rows, lambda row, rank=rank: row.get('rank') == rank, 'ret_d5')} | {_avg(rows, lambda row, rank=rank: row.get('rank') == rank)} |")
    lines += ["", "### ナラティブ整合別 平均20日リターン(仮説: 衝突時は劣化?)", "| ナラティブ | 平均 |", "|---|---|"]
    for narrative in NARRATIVES:
        lines.append(f"| {narrative} | {_avg(rows, lambda row, narrative=narrative: row.get('narrative') == narrative)} |")
    lines += ["", "### 判断別 平均20日リターン(仮説: 見送りは防御か機会損失か)", "| 判断 | 平均 |", "|---|---|"]
    for judge in JUDGES:
        lines.append(f"| {judge} | {_avg(rows, lambda row, judge=judge: row.get('judge') == judge)} |")
    lines += ["", "### 初動分類別 平均リターン(仮説: 初動ギャップは持続するか)", "| 初動 | 翌日 | 5日 | 20日 |", "|---|---|---|---|"]
    for value in ("GU", "フラット", "GD"):
        lines.append(f"| {value} | {_avg(rows, lambda row, value=value: row.get('shodo') == value, 'ret_d1')} | {_avg(rows, lambda row, value=value: row.get('shodo') == value, 'ret_d5')} | {_avg(rows, lambda row, value=value: row.get('shodo') == value)} |")
    lines += ["", "### 反応分類別 平均リターン(仮説: 初日の値動きパターンに持続性はあるか)", "| 分類 | 5日 | 20日 |", "|---|---|---|"]
    for value in ("GU継続", "GU失速", "GD反発", "GD継続"):
        lines.append(f"| {value} | {_avg(rows, lambda row, value=value: row.get('reaction') == value, 'ret_d5')} | {_avg(rows, lambda row, value=value: row.get('reaction') == value)} |")
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


def render_weekly_as_retired(rows, as_of: date):
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


def render_note_as_retired(rows, as_of: date):
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
