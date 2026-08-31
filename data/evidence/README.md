# Immutable Evidence Capture

1日分の捕捉ごとにディレクトリを1つ作り、その中に:

```
population.json   母集団マニフェスト。一度だけ書く。上書き不可
bundles.jsonl     Evidence Bundle の追記専用台帳
```

**現在0件。** 取得元がまだ決まっていない。母集団（その日の決算発表企業一覧）も
Evidence（決算短信・適時開示の本文）も外部から取るものなので、`AGENTS.md` の
「Review source terms before adding external data collection」に従い、
**具体的な取得元を決めて利用条件を確認するまで取得しない**。

この能力が先にあるのは、取得が始まった日から失われるものを止めるためである。
過去254件の発表時刻は後から調査できるが、**今日開示された本文は明日には
差し替わっている**。

## この能力がしないこと

事実抽出も評価もランク付けもしない。Evidence があれば後から何度でもやり直せる
が、**Evidence は事実や評価から復元できない**。旧OSは1回のLLM呼び出しに母集団
選定・検索・事実抽出・評価・ランク化を全部入れ、判定だけを残した。だから
モデル更新・検索結果・選定基準・評価基準のどれが効いたのか分離できず、
新しいモデルに読み直させることもできない。

## 3つの系列を混ぜない

| 系列 | 位置づけ |
|---|---|
| Legacy 254件 | 旧AI判断の研究資料。Evidence は存在しない |
| Retrospective reconstructed | 過去資料を後から取得して再構成したもの。**当時モデルが見たものとは主張しない** |
| Prospective immutable | ここ。取得時点から保存する真正の系列。N=0 から始まる |

3番目だけが prospective validation に使える。1・2は historical replay と
候補モデルの理解に使う。
