"""発表時刻を、開示の索引から読む。

`EventTiming` は「いつ発表されたか」を要求するが、旧OSの254件はイベント日しか
持っていない。時刻が無いと `pre_open` / `intraday` / `post_close` が決まらず、
どのセッションで約定できたかも決まらない。想定で埋めれば、その想定が結論になる。

索引は `webapi.yanoshin.jp` の TDnet 一覧を使う。このリポジトリが既に
`ICECO_TDNET_INDEX` として本番で叩いている先で、`robots.txt` の
`User-Agent: *` は `Allow:/`（制限は Googlebot のみ）、`llms.txt` が日付レンジ
検索まで含めて公開されている。2026-08-29 実測。

**選別を厳密にする理由。** 決算日には同じ会社から複数の開示が出る。実測した例:

    12:00  第２四半期（中間期）決算短信〔日本基準〕
    12:00  第２四半期 決算説明資料
    13:00  決算説明動画と書き起こし公開のお知らせ

「決算」で拾うと13:00の動画告知を掴む。実際の短信は12:00 ——昼休み中で、後場では
ない。1時間の差ではなくセッションの差になる。だから短信だけを取り、複数あるとき
は選ばずに `ambiguous` を返す。

**本文は持ち帰らない。** 必要なのは時刻であって開示の中身ではない。タイトルは
選別のためだけに使い、記録に残すのは時刻・URL・取得時刻・content_sha256 に留める。
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

JST = timezone(timedelta(hours=9))

SOURCE = "tdnet_index_json"
BASE = "https://webapi.yanoshin.jp/webapi/tdnet/list"

# 短信そのものだけ。説明資料・説明会・動画・Q&A はどれも「決算」を含むが、
# 発表そのものではない。
TANSHIN = "決算短信"
# 訂正は原本ではない。時刻は原本のものを使うので、別に数えて選ばない。
CORRECTION = "訂正"

# 選別の結果。無いことを黙って落とさず、なぜ無いかを言う。
SELECTIONS = ("matched", "ambiguous", "correction_only", "no_tanshin", "no_disclosure",
              "unresolved_code", "invalid_timestamp")

# 索引は TDnet の表示名で、市場の接頭辞（グロース `Ｇ－`、REIT `Ｒ－`）や
# `ＨＤ` の略記が付く。台帳側は正式名に近い。落としてから比べる。
# `normalise` が NFKC を通した**後**に当てるので、ここは半角で書く。
# 全角のまま書いた版は `Ｇ－` が既に `G-` になっていて一度も当たらなかった。
MARKET_PREFIX = re.compile(r"^[GRSNP]-")
HOLDINGS = re.compile(r"(ホールディングス|HD|グループ)$")

# 台帳のコードは4桁のことも、末尾0を付けた5桁のこともある。それ以外の形は
# ティッカーではない——`80310_dup` は重複行の目印で、4文字で切ると本物の
# 8031 の開示に一致してしまう。切る前に形を見る。
CODE = re.compile(r"^(?:[0-9]{4}|[0-9]{3}[A-Z])$")
CODE5 = re.compile(r"^(?:[0-9]{4}|[0-9]{3}[A-Z])0$")


def normalise(title: str) -> str:
    """全角空白と空白を落として比較する。

    実データのタイトルは「2026年10月期　第２四半期（中間期）決算短信」のように
    全角空白を含む。区切りの入り方は会社ごとに違い、そこで一致を落とすと
    「短信が無い」という誤った不在が生まれる。
    """
    return "".join(unicodedata.normalize("NFKC", title or "").split())


def is_tanshin(title: str) -> bool:
    return TANSHIN in normalise(title)


def is_correction(title: str) -> bool:
    return CORRECTION in normalise(title)


def items_from(payload) -> List[dict]:
    """`json` は `{"Tdnet": {...}}` で包み、`json2` は包まない。

    どちらで取っても同じ形で返す。取得側の書式の違いを選別へ持ち込まない。
    """
    if isinstance(payload, list):
        rows = payload
    else:
        rows = payload.get("items") or []
    return [row.get("Tdnet", row) if isinstance(row, dict) else row for row in rows]


def short_code(code: str) -> Optional[str]:
    """4桁の証券コードにする。ティッカーでない文字列は `None` を返す。

    以前は無条件に4文字で切っていた。台帳には `80310_dup`（重複行の目印、
    会社名は `—`）が入っており、切ると `8031` になって**三井物産の実際の開示に
    一致し、同じ時刻と同じハッシュを与えていた**。台帳が確かめていない身元を、
    切り詰めが勝手に主張していたことになる。

    受け付けるのは4桁（`7698` / `130A`）と、末尾0を付けた5桁（`76980`）だけ。
    """
    text = (code or "").strip()
    if CODE.match(text):
        return text
    if CODE5.match(text):
        return text[:4]
    return None


def company_key(name: Optional[str]) -> str:
    """比較用に名前を削る。市場の接頭辞と持株会社の語尾を落とす。"""
    text = normalise(name or "")
    text = MARKET_PREFIX.sub("", text)
    text = HOLDINGS.sub("", text)
    return text.replace("株式会社", "").replace("・", "")


def same_company(ledger_name: Optional[str], index_name: Optional[str]) -> Optional[bool]:
    """会社名が同じものを指しているか。判断できなければ `None`。

    **これは門ではなく観測である。** 索引の表示名は `ＫＴＫ`（台帳は
    `ケイティケイ`）、`日フイルコン`（同 `日本フイルコン`）のように略され、
    一致を要求すると本物を大量に落とす。実測で254件中73件が落ちた。
    身元の門はコードの形（`short_code`）が担い、名前は記録に残して
    後から見えるようにする——ゲートは保守的に、検知は敏感に。
    """
    a, b = company_key(ledger_name), company_key(index_name)
    if not a or not b or a in ("—", "-", "…"):
        return None
    return a in b or b in a


def announced_at(item: dict) -> Optional[datetime]:
    stamp = (item.get("pubdate") or "").strip()
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
    except ValueError:
        return None


@dataclass(frozen=True)
class Selection:
    """どの開示を発表とみなしたか、そしてみなせなかったのはなぜか。"""

    status: str
    announced_at: Optional[datetime] = None
    document_url: Optional[str] = None
    content_sha256: Optional[str] = None
    candidates: int = 0
    corrections: int = 0
    # 名前が一致したか。`None` は照合できなかったことを表す。判定には使わない。
    name_agrees: Optional[bool] = None

    def __post_init__(self):
        if self.status not in SELECTIONS:
            raise ValueError("%s is not one of %s" % (self.status, ", ".join(SELECTIONS)))
        if self.status == "matched" and self.announced_at is None:
            raise ValueError("a match has to say when")
        if self.status != "matched" and self.announced_at is not None:
            raise ValueError("only a match carries an instant")


def digest(item: dict) -> str:
    """索引が返した行そのものの指紋。

    本文は残さないので、後から「同じものを見たか」を確かめる手掛かりがこれになる。
    """
    return hashlib.sha256(
        json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def select(items: Sequence[dict], code: str, event_date: str,
           expect_name: Optional[str] = None) -> Selection:
    """その会社・その日の開示から、決算短信を1件選ぶ。

    複数あれば選ばない。どちらが発表かを推測すると、その推測が時刻になる。

    `expect_name` を渡すと会社名も照合する。コード1列で身元を決めると、
    台帳の重複マーカーが実在企業の開示を拾う。
    """
    want = short_code(code)
    if want is None:
        return Selection("unresolved_code")
    same_day = [
        i for i in items
        if short_code(i.get("company_code", "")) == want
        and (i.get("pubdate") or "")[:10] == event_date
    ]
    if not same_day:
        return Selection("no_disclosure")

    tanshin = [i for i in same_day if is_tanshin(i.get("title", ""))]
    corrections = [i for i in tanshin if is_correction(i.get("title", ""))]
    originals = [i for i in tanshin if not is_correction(i.get("title", ""))]

    if not tanshin:
        return Selection("no_tanshin", candidates=len(same_day))
    if not originals:
        return Selection("correction_only", candidates=len(same_day),
                         corrections=len(corrections))
    if len(originals) > 1:
        return Selection("ambiguous", candidates=len(originals),
                         corrections=len(corrections))

    only = originals[0]
    agrees = same_company(expect_name, only.get("company_name")) if expect_name else None
    when = announced_at(only)
    if when is None:
        # 短信は在ったが時刻が読めない。`no_tanshin` にすると、観測したことの
        # 反対を記録し、提供側の書式崩れを正当な不在として隠すことになる。
        return Selection("invalid_timestamp", candidates=len(same_day), name_agrees=agrees)
    return Selection(
        "matched",
        announced_at=when,
        document_url=only.get("document_url") or None,
        content_sha256=digest(only),
        candidates=1,
        corrections=len(corrections),
        name_agrees=agrees,
    )


def date_url(day: str, limit: int = 1000) -> str:
    """1日分の索引。`day` は `YYYY-MM-DD`。"""
    return "%s/%s.json2?limit=%d" % (BASE, day.replace("-", ""), limit)


def truncated(items: Sequence[dict], limit: int) -> bool:
    """索引が上限に張り付いたか。

    実測: 2026-08-07 を `limit=1000` で取ると 1000件ちょうど返り、実際には
    1627件あった。足りない分に含まれていた2社は `no_disclosure` として
    記録され、**開示が無かったことにされた**。上限は不在と見分けがつかないので、
    張り付きは取得側で潰すしかない。
    """
    return len(items) >= limit
