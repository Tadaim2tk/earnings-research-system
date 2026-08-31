#!/bin/zsh
# 決算短信の本文を、TDnetから消える前に確保する。launchd から毎日呼ばれる。
#
# TDnet は文書を約31日で落とす。取りに行かなければ、毎日そのぶんが永久に失われる。
# 保存するのは抽出テキストと sha256 まで。PDF本体は残さない。
#
# 止めるには:
#   launchctl bootout gui/$(id -u)/com.ers.capture-disclosures
set -u
# 既定は実運用の置き場。差し替えられるのは、終了コードの伝わり方を実際に走らせて
# 確かめるためで、そこが黙って壊れると launchd は失敗を成功として記録する。
REPO=${ERS_REPO:-/Users/maruyamayuuki/.ers-corpus/repo}
LOG=${ERS_LOG:-/Users/maruyamayuuki/.ers-corpus/capture.log}
PY=${ERS_PYTHON:-/Users/maruyamayuuki/opt/anaconda3/bin/python}
CAPTURE=${ERS_CAPTURE:-$REPO/tools/capture_disclosures.py}

# ログが太りすぎたら頭を落とす。無人で回るので、放っておくと際限なく伸びる。
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
  tail -c 500000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z')"
  cd "$REPO" || { echo "clone が無い: $REPO"; exit 1; }
  # 更新に失敗しても走らせる。取り逃しのほうが取り返しがつかない。
  git pull -q 2>&1 || echo "  (git pull 失敗。手元の版で続行)"
  echo "  repo $(git rev-parse --short HEAD)"
  PYTHONPATH="$REPO/src" "$PY" "$CAPTURE" --days 3
  # `status` は zsh の読み取り専用変数（`$?` の別名）なので使えない。代入は
  # 黙って失敗し、直したつもりで直っていない状態になる。
  captured=$?
  echo "  exit=$captured"
} >> "$LOG" 2>&1

# **中括弧の終了コードは最後のコマンド（echo）のものになる。** そのままだと、
# 取り残しや失敗があっても launchd は成功として記録し、31日で消える開示が
# 取られないまま誰にも見えない。取得側の状態をそのまま返す。
exit ${captured:-1}
