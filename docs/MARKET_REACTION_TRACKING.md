# Market Reaction Tracking

## 目的

決算評価が完成したeventについて、次の価格点を一つの追跡結果へまとめる。

1. 決算発表前のregular-session終値
2. 発表直後の価格
3. 翌営業日終値
4. 5営業日後終値

株価取得元への接続は行わない。許可された取得元から必要項目だけを整理したJSONを入力とし、raw CSV、画面、HTMLは保存しない。

入力と出力の機械契約は次を正本とする。

- [`market_reaction_observations.schema.json`](../schemas/analysis/market_reaction_observations.schema.json)
- [`market_reaction_tracking.schema.json`](../schemas/analysis/market_reaction_tracking.schema.json)

## 事前条件

- `earnings_evaluation_v1`が`evaluated`である
- event statusのcurrent chainに`occurred`があり、実発表時刻が確定している
- event、company master、決算評価、価格観測のevent ID、企業名、tickerが一致する
- 価格はunadjustedの実取引価格である
- source確認時刻、記録者、source identifierを持つ
- sourceのterms判定根拠と、価格を選んだ事前ruleを持つ
- raw price dataをrepositoryへ保存しない

予定時刻だけのevent、別企業、調整済み価格、quoteのみの値は比較へ使用しない。

## 価格点

### 発表前終値

`pre_event_close`は、発表より前に終了した最後のregular sessionの公式終値とする。

- `before_open`と`intraday`: 原則として前営業日終値
- `after_close`: 原則として発表当日の取引終了時終値

すべての長期returnはこの価格を共通基準とする。

### 発表直後

発表sessionに応じて次を使う。

| session | 発表直後価格 |
| --- | --- |
| `before_open` | 発表当日の公式始値 |
| `intraday` | 発表後に終了した最初の完全な分足終値、事前定義VWAP、または監査可能なmanual trade price |
| `after_close` | 次regular sessionの公式始値 |

場中決算では、前営業日終値とは別に、発表時刻より厳密に前に終了した最後の完全な分足終値を`pre_announcement_reference`として要求する。発表直後の純粋なevent-window returnはこの値を基準にする。

VWAPを使う場合は、開始・終了時刻とsessionを`vwap_window`へ事前記録する。window不明のVWAPは受理しない。

### 翌営業日と5営業日後

calendar dayを足し算しない。入力には、確認済みの取引calendarから発表日後の5sessionを昇順で記録する。

- 先頭sessionの公式終値を`next_business_day_close`
- 5番目sessionの公式終値を`fifth_business_day_close`

祝日や臨時休場を週末判定だけで補完しない。

## 計算

各milestoneの発表前終値比:

```text
(milestone_price / pre_event_close - 1) * 100
```

場中を含む発表直後のevent-window return:

```text
(immediate_price / event_window_reference - 1) * 100
```

計算値には`ers_calculated`と式を付ける。方向判定の許容幅は±0.5%とし、その範囲は`muted`とする。

## 途中状態

5営業日後まで待つ間も、確認済み価格を失わない。

- 未到達価格は`pending`
- 既存milestoneは`observed`
- 全価格と場中用referenceが揃うと`complete`

途中で別の値へ上書きせず、新しい観測bundleから新しい追跡snapshotを生成する。

## Corporate action

価格窓内のsplit等が`present`または`unknown`なら、価格自体は保持するがreturnを計算しない。確認後に`none_detected`となったbundleだけを通常比較へ進める。raw event reactionへadjusted priceを混ぜない。

## 反応経路

- `extended`: 初期反応と5営業日後が同方向で、値幅が拡大
- `sustained`: 同方向を維持しているが、値幅は拡大していない
- `reversed`: 初期反応と5営業日後が逆方向
- `muted`: 各時点が許容幅内
- `mixed`: 上記に当てはまらない
- `pending`: 必要時点待ち
- `not_comparable`: corporate action等が未解決

反応経路は市場の観測結果であり、売買判断ではない。

## 実行

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 -m earnings_research.cli track-market-reaction \
  --observations /path/to/market_reaction_observations.json \
  --evaluation /path/to/earnings_evaluation.json \
  --events data/earnings_event.csv \
  --event-status-history data/event_status_history.csv \
  --companies data/company_master.csv \
  --output /path/to/market_reaction_tracking.json
```

## 完成境界

この能力は価格観測の検証、return計算、途中追跡、反応経路の記録までを担当する。価格provider採用、API接続、売買判断、backtest、TSO連携は含めない。
