# 日次の本文確保（launchd）

TDnet は決算短信の本文を**約31日で落とす**。取りに行かなければ、毎日そのぶんが
永久に失われる。254件の台帳では、気づいた時点で **132件が既に消えていた**。

GitHub Actions では動かせない。コーパスは `~/.ers-corpus/` にあり、GitHub の
サーバーからは書けないためである。だから Mac 上の launchd で回す。

## 置き場

| | |
| --- | --- |
| 専用clone | `~/.ers-corpus/repo` |
| wrapper | `~/.ers-corpus/capture.sh` |
| plist | `~/Library/LaunchAgents/com.ers.capture-disclosures.plist` |
| コーパス | `~/.ers-corpus/documents/` |
| ログ | `~/.ers-corpus/capture.log` |

**専用の clone を使う。** 日常作業のローカル clone は別セッションの未コミット
変更が常駐しがちで、無人のジョブがそこで `git pull` すると衝突する。

## 入れる

```sh
git clone https://github.com/Tadaim2tk/earnings-research-system.git ~/.ers-corpus/repo
cp tools/launchd/capture.sh ~/.ers-corpus/capture.sh
chmod +x ~/.ers-corpus/capture.sh
cp tools/launchd/com.ers.capture-disclosures.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ers.capture-disclosures.plist
```

## 止める

```sh
launchctl bootout gui/$(id -u)/com.ers.capture-disclosures
```

## 確かめる

```sh
launchctl print gui/$(id -u)/com.ers.capture-disclosures | grep -E "state|runs ="
tail -20 ~/.ers-corpus/capture.log
```

**`runs = 0` のままなら一度も動いていない。** 登録できていることと動いていること
は別で、workflow が success でも観測していない場合があるのと同じ形である
（ERS-ADR-0025 以降くり返し踏んでいる）。

## 挙動

- 毎日 22:00。開示は15時台以降に集中するので、その日のぶんが揃ってから走る
- **3日ぶん遡る。** 週末と、一度の失敗を吸収するため
- Mac が寝ていた日は、次に起きたときに launchd が追いつかせる
- 取り残しか失敗があれば **0 以外で終える**。緑は「全部取れた」以外を意味しない
