"""定性情報から事実を抜く測定器の定義。

**なぜ固定するのか。** 前向きに評価を積むあいだ、モデルが更新されれば同じ文書に
違う値が出る。そうなると集めた標本は途中で意味が変わっており、十分な数が溜まる
前に統一性を失う。**重みが固定されたモデルなら、3年前の資料を今日測り直しても
同じ値が出る。** 測定器としての性質はここにしかなく、更新され続けるAPIには作れない。

固定するのは重みだけではない。**プロンプト・出力の形・温度・生成長・節の切り出し
規則**まで含めて1つの版とし、その digest を `INSTRUMENT_VERSION` とする。どれか
一つでも変えれば別の測定器であり、過去の採点と混ぜてはいけない。

**ここは評価ではない。** 4層設計（Evidence / Extracted Facts / Evaluation Policy /
Evaluation Output）の Extracted Facts にあたる。「スコア7点」を出させると、その点の
意味がモデルの中にしか無く後から検証できない。会社が何と書いたかを列挙させ、点に
するのは Evaluation Policy の仕事にする。
"""

import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

from earnings_research.narrative.section import (
    BODY_CHARS,
    SECTION_RULE_VERSION,
)

MODEL = "mlx-community/Qwen3-8B-4bit"
# **リポジトリ名は可変である。** 同じ名前が別の重みやトークナイザに解決されても
# 名前を hash する限り版は動かない——「重みが固定されているから再現できる」という
# この層の前提が、そこで崩れる。解決済みの commit を固定する。
MODEL_REVISION = "545dc4251c05440727734bcd94334791f6ab0192"
# 生成側が変われば同じ重みでも出力が変わりうる。チャットテンプレートの適用も
# トークナイザの版に依存する。版に含める。
RUNTIME = {
    "mlx-lm": "0.29.1",
    "mlx": "0.29.3",
    "transformers": "4.57.6",
    "tokenizers": "0.22.2",
}
TEMPERATURE = 0.0
MAX_TOKENS = 300
# 思考モードは既定で入り、生成長を全部そこに使って答えに到達しないことがある。
# 測定器としては切る。
ENABLE_THINKING = False

# **明確化のつもりの一文が測定を壊した。** 「無ければ空配列」を足した版
# （`5f986834218c05b5`）を同じ103件に当てたところ、追い風が0件の文書が 21/74 から
# **51/74** へ増え、平均件数が 1.85 → 1.41 へ落ちた。旧版で理由を挙げていた32件が
# 0件になり、逆は2件だけだった。方向の項目（`sales_direction` 100%、
# `profit_direction` 99%）は動かず、**理由の列挙だけが壊れた**。
# スキーマを丁寧に書いたつもりが、モデルを空の答えへ寄せていた。
# プロンプトを版に含めてある理由が、そのまま実演された形である。
PROMPT = """次は日本企業の決算短信の「経営成績に関する説明」です。書かれている
ことだけを抜き出してください。書かれていないことは推測せず "不明" とすること。

以下のJSONだけを出力（前置き・説明・コードフェンス不要）:
{"sales_direction":"増加|減少|横ばい|不明",
 "profit_direction":"増加|減少|横ばい|不明",
 "tailwinds":["会社が挙げた追い風を原文の語で、最大6件"],
 "headwinds":["会社が挙げた逆風を原文の語で、最大6件"],
 "one_off":"有|無|不明",
 "outlook_mention":"上方|下方|据置|言及なし"}"""

DIRECTIONS = ("増加", "減少", "横ばい", "不明")
PRESENCE = ("有", "無", "不明")
OUTLOOK = ("上方", "下方", "据置", "言及なし")
# **反復を潰すのは重複排除の仕事で、件数上限の仕事ではない。** 上限6で落ちた5件を
# 実際に見たところ、4件は 8〜10 個の別々の逆風（中東情勢／物価上昇／インフレ再燃…）
# を挙げた正当な列挙で、暴走していたのは1件だけだった——「黒字化」が3回繰り返され
# ていた。上限だけで両方を捌こうとすると、正当な列挙を捨てるか暴走を通すかになる。
# 重複を先に落とし、そのうえで緩めの上限を置く。
MAX_REASONS = 10

FIELDS: Dict[str, Tuple[str, ...]] = {
    "sales_direction": DIRECTIONS,
    "profit_direction": DIRECTIONS,
    "one_off": PRESENCE,
    "outlook_mention": OUTLOOK,
}
LISTS = ("tailwinds", "headwinds")

# モデルは前置きやコードフェンスを付けることがある。最初のJSONオブジェクトを拾う。
JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def instrument_version() -> str:
    """この測定器の版。どれか一つでも変われば別物になる。"""
    material = json.dumps({
        "model": MODEL,
        "model_revision": MODEL_REVISION,
        "runtime": RUNTIME,
        "prompt": PROMPT,
        "fields": {k: list(v) for k, v in sorted(FIELDS.items())},
        "lists": list(LISTS),
        "max_reasons": MAX_REASONS,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "enable_thinking": ENABLE_THINKING,
        "section_rule": SECTION_RULE_VERSION,
        "body_chars": BODY_CHARS,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


INSTRUMENT_VERSION = instrument_version()


def build_prompt(section: str) -> str:
    return PROMPT + "\n\n---\n" + section


def parse(output: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """モデルの出力を事実へ。読めなければ理由を返す。

    直さない。壊れた出力を埋めて通すと、埋めた値が観測として記録される。
    """
    match = JSON_RE.search(output or "")
    if match is None:
        return None, "JSONが見つからない"
    try:
        payload = json.loads(match.group(0))
    except ValueError as exc:
        return None, "JSONとして読めない: %s" % str(exc)[:60]
    if not isinstance(payload, dict):
        return None, "オブジェクトではない"

    facts: Dict[str, Any] = {}
    for name, allowed in sorted(FIELDS.items()):
        value = payload.get(name)
        if value not in allowed:
            return None, "%s が語彙の外: %r" % (name, value)
        facts[name] = value
    for name in LISTS:
        # 欠けた鍵を空配列に読み替えない。**答えなかったことと「無かった」ことは
        # 別である。** 既定値で埋めると、モデルが黙った場合が「理由を挙げな
        # かった」という観測として記録される。
        if name not in payload:
            return None, "%s が無い" % name
        value = payload[name]
        if not isinstance(value, list):
            return None, "%s が配列ではない" % name
        if any(not isinstance(v, str) for v in value):
            return None, "%s に文字列でない要素がある" % name
        seen, items = set(), []
        for raw in value:
            item = raw.strip()
            if item and item not in seen:
                seen.add(item)
                items.append(item)
        if len(items) > MAX_REASONS:
            return None, "%s が %d 件を超えている" % (name, MAX_REASONS)
        facts[name] = items
    return facts, None
