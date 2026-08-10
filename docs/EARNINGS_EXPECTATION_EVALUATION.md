# Earnings Expectation Evaluation

## 目的

発表前に固定した予想と仮説を、決算資料から得た構造化実績へ接続し、次を一度に記録する。

1. 実績が事前予想を上回ったか、範囲内か、下回ったか
2. 会社予想が上方修正、据え置き、下方修正のどれか
3. 累計実績が通期会社予想のどこまで進んだか
4. 事前仮説を支持、混在、棄却、未判定のどれとして扱うか
5. 株価反応を混ぜない決算そのものの評価

出力の機械契約は [`earnings_evaluation.schema.json`](../schemas/analysis/earnings_evaluation.schema.json) とする。

## 入力

- validatorを通過した`pre_earnings_baseline`のlocked row
- 同じeventに属する発表前の`hypothesis_log`
- `earnings_event`と`company_master`
- `earnings_document_analysis_v1`の解析結果
- baselineの金額単位を円へ換算する倍率
- eventから確認したticker

baseline CSVの金額は現行運用に合わせて既定で百万円とし、CLIの倍率`1000000`を結果にも記録する。1株利益は円であるため金額倍率を適用しない。

## 比較規則

### 市場予想と実績

現行baselineには市場予想の対象期間列がないため、同じeventの`quarter`から対象期間を導出する。`Q1`は第1四半期累計、`Q2`は半期累計、`Q3`は9か月累計、`Q4/FY`は通期として扱う。導出期間と資料解析結果の期間が一致するときだけ比較し、四半期累計実績を通期予想へ直接比較しない。

差率はERS計算値として次の式と出典fieldを保存する。

```text
(actual - expected) / abs(expected) * 100
```

既定の許容幅は1%である。期待値が0の場合は差率を作らず、割合による方向判定を行わない。

### 会社予想

発表前baselineに保存された通期会社予想と、今回資料に記載された通期会社予想を比較する。実績値と会社予想を同じ値として上書きしない。

### 進捗率

累計実績を通期会社予想で割った値は参考値として保存する。季節性を考慮しないため、進捗率だけで上振れ・下振れを断定しない。

### 仮説

baseline lock以前に作られ、発表時点で`active`または`pending`だった発表前仮説だけを対象にする。会社資料の定性記述に対象語と方向が明確に対応する場合だけ支持または棄却を判定する。一意に対応しない場合は`pending`とし、文章の雰囲気から結果を作らない。元の仮説行は変更しない。

## 出力境界

結果には資料URL、ページ、発表前baseline field、ERS計算式、制約事項を残す。株価、リターン、売買判断は含めない。

```text
事前baseline + 発表前hypothesis + 決算資料解析
                       ↓
             earnings_evaluation_v1
                       ↓
              株価反応追跡（次工程）
```

## 実行

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli evaluate-earnings \
  --baseline data/samples/pre_earnings_baseline_sample.csv \
  --baseline-id BASE-HOKUTO-001 \
  --hypotheses data/samples/hypothesis_log_sample.csv \
  --events data/samples/earnings_event_sample.csv \
  --companies data/samples/company_master_sample.csv \
  --analysis /path/to/earnings_document_analysis.json \
  --evaluated-at 2027-05-10T16:00:00+09:00 \
  --output /path/to/earnings_evaluation.json
```

eventの会社ID、会社masterのticker、資料解析結果のticker、発表日を照合し、別企業・別eventの解析結果を誤接続しない。

## アイスコhistorical proofの扱い

`EDA-7698-20250212.json`は9か月累計実績であり、repositoryには当該historical eventのlocked baselineが存在しない。したがって、実在しない事前予想や仮説を作って評価結果を恒久保存しない。通期会社予想への進捗は資料解析内の参考値として扱える。

第1号prospective eventでは、発表前にlocked baselineが作成された後、この処理を資料解析の次工程として使用する。
