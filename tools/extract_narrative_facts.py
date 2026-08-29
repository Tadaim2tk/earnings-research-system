"""確保した短信から事実を抜く。固定した測定器で。

定義は `earnings_research.narrative` にあり、ここはモデルを回すだけ。分けてある
のは、定義をテストするのにモデルを動かしたくないからで、混ぜるとテストのたびに
8Bを読み込むか、読み込まないために定義を検査しないかのどちらかになる。

モデルは別のvenvに入っている（conda base は Python 3.8 で MLX が動かない）。

    ~/.venvs/ers-llm/bin/python tools/extract_narrative_facts.py

**版が変われば取り直す。** 出力に `instrument_version` を書き、一致するものだけ
飛ばす。プロンプトや温度を変えたのに古い採点が残っていると、標本の途中で意味が
変わる——それを避けるために版を digest にしてある。

**評価はしない。** ここは Extracted Facts で、点にするのは Evaluation Policy の
仕事である。
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_research.narrative import instrument as I  # noqa: E402
from earnings_research.narrative.section import narrative_section  # noqa: E402

DOCUMENTS = Path.home() / ".ers-corpus/documents"
FACTS = Path.home() / ".ers-corpus/facts"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", default=str(DOCUMENTS))
    ap.add_argument("--facts", default=str(FACTS))
    ap.add_argument("--limit", type=int, default=0, help="0 なら全部")
    args = ap.parse_args()

    documents = sorted(Path(args.documents).glob("*.json"))
    out = Path(args.facts)
    out.mkdir(parents=True, exist_ok=True)
    print("測定器 %s / 文書 %d件" % (I.INSTRUMENT_VERSION, len(documents)), flush=True)

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    model, tokeniser = load(I.MODEL)
    sampler = make_sampler(temp=I.TEMPERATURE)

    done = skipped = no_section = unreadable = 0
    started = time.time()
    for n, path in enumerate(documents, 1):
        if args.limit and done >= args.limit:
            break
        target = out / path.name
        if target.exists():
            try:
                if json.loads(target.read_text(encoding="utf-8")).get(
                        "instrument_version") == I.INSTRUMENT_VERSION:
                    skipped += 1
                    continue
            except ValueError:
                pass                       # 壊れていれば取り直す

        document = json.loads(path.read_text(encoding="utf-8"))
        section = narrative_section(document.get("text", ""))
        record = {
            "ticker": document.get("ticker"),
            "event_date": document.get("event_date"),
            "announced_at": document.get("announced_at"),
            "text_sha256": document.get("text_sha256"),
            "instrument_version": I.INSTRUMENT_VERSION,
            "model": I.MODEL,
            "extracted_at": datetime.now().astimezone().isoformat(),
        }
        if section is None:
            record["status"] = "no_section"
            no_section += 1
        else:
            messages = [{"role": "user", "content": I.build_prompt(section)}]
            prompt = tokeniser.apply_chat_template(
                messages, add_generation_prompt=True,
                enable_thinking=I.ENABLE_THINKING, tokenize=False)
            output = generate(model, tokeniser, prompt=prompt,
                              max_tokens=I.MAX_TOKENS, sampler=sampler, verbose=False)
            facts, why = I.parse(output)
            record["section_chars"] = len(section)
            if facts is None:
                record["status"] = "unreadable"
                record["reason"] = why
                unreadable += 1
            else:
                record["status"] = "extracted"
                record["facts"] = facts
                done += 1
        tmp = target.with_suffix(".part")
        tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
        if n % 10 == 0:
            rate = (time.time() - started) / max(1, done + no_section + unreadable)
            print("  [%3d/%3d] 抽出%3d 節なし%3d 読めず%3d  %.1fs/件"
                  % (n, len(documents), done, no_section, unreadable, rate), flush=True)

    print("\n抽出 %d / 節なし %d / 読めず %d / 既存 %d"
          % (done, no_section, unreadable, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
