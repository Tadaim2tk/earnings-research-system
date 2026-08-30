"""属性で切る。**条件を書いたら、それが何件を落としたかも返す。**

「金曜の決算だけ」「引け後に出たものだけ」を組み合わせて確かめるための道具。

**落ちた件数を必ず返す。** 条件を重ねると母集団が変わるが、変わったことに気づか
ないまま数字を比べると、公開したダッシュボードでやった誤りをまた繰り返す——
行ごとに母集団が違うのに「全245件」と書いた件である。
"""

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


def get(row: Mapping[str, Any], path: str, default=None):
    """`"disclosure.session_class"` のような道で値を取る。"""
    cursor: Any = row
    for step in path.split("."):
        if not isinstance(cursor, Mapping) or step not in cursor:
            return default
        cursor = cursor[step]
    return cursor


def where(rows: Sequence[Mapping[str, Any]], **conditions) -> Tuple[List[dict], Dict[str, int]]:
    """条件で絞り、**条件ごとに何件落としたか**を一緒に返す。

    条件は `disclosure__session_class="post_close"` のように書く。値に集合や
    リストを渡すと「そのいずれか」になる。呼べるものを渡すとそのまま述語になる。
    """
    kept = list(rows)
    dropped: Dict[str, int] = {}
    for key, want in conditions.items():
        path = key.replace("__", ".")
        before = len(kept)
        if callable(want):
            kept = [r for r in kept if want(get(r, path))]
        elif isinstance(want, (set, frozenset, list, tuple)):
            kept = [r for r in kept if get(r, path) in want]
        else:
            kept = [r for r in kept if get(r, path) == want]
        dropped[key] = before - len(kept)
    return kept, dropped


def group(rows: Sequence[Mapping[str, Any]], path: str) -> Dict[Any, List[dict]]:
    """ある属性で束ねる。値が無い行は `None` の束に入る——捨てない。"""
    out: Dict[Any, List[dict]] = {}
    for row in rows:
        out.setdefault(get(row, path), []).append(row)
    return out


def returns_of(rows: Sequence[Mapping[str, Any]], held: int) -> Tuple[List[float], List[str]]:
    """保有本数を指定して、リターンと銘柄コードを揃えて取り出す。

    **揃えて返すのは、統計にかけるとき銘柄をクラスタとして渡すため。** 別々に
    取ると順序がずれる。
    """
    values, codes = [], []
    for row in rows:
        value = get(row, "price.returns.held_%d" % held)
        code = get(row, "identity.ticker")
        if value is not None and code:
            values.append(value)
            codes.append(code)
    return values, codes
