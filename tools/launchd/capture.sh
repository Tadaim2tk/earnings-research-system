#!/bin/zsh
# 決算短信の本文を、TDnetから消える前に確保する。launchd から毎日呼ばれる。
#
# TDnet は文書を約31日で落とす。取りに行かなければ、毎日そのぶんが永久に失われる。
# 保存するのは抽出テキストと sha256 まで。PDF本体は残さない。
#
# 止めるには:
#   launchctl bootout gui/$(id -u)/com.ers.capture-disclosures
set -u
REPO=/Users/maruyamayuuki/.ers-corpus/repo
LOG=/Users/maruyamayuuki/.ers-corpus/capture.log
PY=/Users/maruyamayuuki/opt/anaconda3/bin/python

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
  PYTHONPATH="$REPO/src" "$PY" "$REPO/tools/capture_disclosures.py" --days 3
  echo "  exit=$?"
} >> "$LOG" 2>&1
