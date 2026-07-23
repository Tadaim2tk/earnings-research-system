# 手入力パイロット実行ログ

## 実行状態

| pilot_case_id | company/event entered | pre-event source identified | baseline CSV | price reference | TSO snapshot | status |
| --- | --- | --- | --- | --- | --- | --- |
| `PILOT-01` | yes | yes | blocked | pending license review | not entered | reconstruction_ready |
| `PILOT-02` | yes | yes | blocked | pending license review | not entered | reconstruction_ready |
| `PILOT-03` | yes | yes | blocked | pending license review | not entered | reconstruction_ready |

`baseline CSV=blocked` はdata不足ではなく、historical reconstructionの真の `recorded_at` がannouncement後になるためである。validatorを通すための過去日時は作成しない。

## 入力結果

| metric | `PILOT-01` | `PILOT-02` | `PILOT-03` |
| --- | --- | --- | --- |
| baseline入力時間 | human未計測 | human未計測 | human未計測 |
| pre-event evidence | 1 official document | 1 official document | 1 official index/document |
| company guidance revenue | 1,190,000 million JPY | 47,000,000 million JPY | 98,000 million JPY |
| company guidance operating income | 280,000 million JPY | 4,700,000 million JPY | -980 million JPY |
| company guidance EPS | 231.91 JPY | 340.87 JPY | unknown |
| market consensus | unknown | unknown | unknown |
| score components | not assessed | not assessed | not assessed |
| TSO snapshot | unavailable/not required for reconstruction | unavailable/not required for reconstruction | unavailable/not required for reconstruction |
| raw reference price | pending | pending | pending |
| adjusted reference price | pending | pending | pending |
| adjustment factor | unknown | unknown | unknown |

agent-assisted調査時間はhuman hand-entry時間と同じ意味を持たないため、所要時間の合格基準には使用しない。将来eventのprospective pilotで人間が計測する。

## 毎回空欄になったfield

- `market_consensus_revenue`
- `market_consensus_operating_income`
- `market_consensus_eps`
- score component 18項目
- `pre_event_score`
- TSO snapshot fields
- raw/adjusted reference priceとadjustment factor

market consensusは利用可能なlicensed sourceが未選定である。score componentは正式な採点rubricがなく、neutral valueを推測入力しない。TSO snapshotはevent時点のsource rowを確認していないため作成しない。

## 重複作業

- company guidanceの主要数値をbaseline列とKPI expected rowへ重複入力する可能性がある。
- announcement datetimeを `earnings_event` とevidence metadataの双方へ記録する必要がある。
- raw/adjusted/factorは現行schemaでは `return_reference_price` と `evidence.notes` に分散する。

## schema判断へ持ち越す観測

1. historical reconstructionとprospective locked baselineを区別できない。
2. score未実施baselineを表現できず、全score componentがrequiredになっている。
3. market consensusがない場合でもbaseline自体は作れるが、scoreの意味が未定義である。
4. raw/adjusted/factorは専用列がないためevidenceへ分散する。
5. company guidanceとKPI expectedの重複入力ruleがない。

この時点ではschemaを変更しない。価格license確認とprospective pilotを終えた後、3件をまとめてreviewする。
