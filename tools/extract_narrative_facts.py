"""確保した短信から事実を抜く。固定した測定器で。

定義は `earnings_research.narrative` にあり、ここはモデルを回すだけ。分けてある
のは、定義をテストするのにモデルを動かしたくないからで、混ぜるとテストのたびに
8Bを読み込むか、読み込まないために定義を検査しないかのどちらかになる。

モデルは別のvenvに入っている（conda base は Python 3.8 で MLX が動かない）。

    ~/.venvs/ers-llm/bin/python tools/extract_narrative_facts.py

**版ごとに別のディレクトリへ書く。** 版が変わったときに同じ場所へ上書きすると、
前の測定とその `extracted_at` が消える。版を変えて取り直すことは想定された運用
なので、消す方に倒さない。

**固定した revision と runtime が実際に一致するかを検査する。** 宣言だけ置いて
実行時に確かめないと、別の重みで測ったものが同じ版を名乗って記録に入る。

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


def runtime_mismatch():
    """固定した runtime と実際の版の食い違い。

    生成側が変われば同じ重みでも出力が変わりうる。宣言だけ置いて確かめないと、
    別の runtime で測ったものが同じ版を名乗って記録に入る。
    """
    from importlib.metadata import PackageNotFoundError, version
    out = []
    for package, pinned in sorted(I.RUNTIME.items()):
        try:
            found = version(package)
        except PackageNotFoundError:
            out.append("%s 無し（固定は %s）" % (package, pinned))
            continue
        if found != pinned:
            out.append("%s %s（固定は %s）" % (package, found, pinned))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", default=str(DOCUMENTS))
    ap.add_argument("--facts", default=str(FACTS))
    ap.add_argument("--limit", type=int, default=0, help="0 なら全部")
    args = ap.parse_args()

    documents = sorted(Path(args.documents).glob("*.json"))
    # 版ごとに分ける。前の測定を消さない。
    out = Path(args.facts) / I.INSTRUMENT_VERSION
    out.mkdir(parents=True, exist_ok=True)
    print("測定器 %s / 文書 %d件" % (I.INSTRUMENT_VERSION, len(documents)), flush=True)

    mismatched = runtime_mismatch()
    if mismatched:
        print("固定した runtime と違う: %s" % ", ".join(mismatched), file=sys.stderr)
        print("この版を名乗って測ってはいけない。", file=sys.stderr)
        return 2

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    # 重みを commit で固定する。リポジトリ名だけでは中身が変わりうる。
    model, tokeniser = load(I.MODEL, revision=I.MODEL_REVISION)
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
                # 生の出力を残す。理由だけだと「読めなかった」が行き止まりに
                # なり、上限が妥当なのかモデルが暴走したのかを後から判断できない。
                record["raw_output"] = output[:2000]
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
