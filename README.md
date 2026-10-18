# サプリメント図鑑 SNS自動投稿

Threads・Instagram へ 1日2回、自動で投稿する仕組みです（GitHub Actions・無料）。
X は x.com の予約投稿機能に、週1回まとめて予約します。

- 投稿ルールの正：`../投稿方針.md`
- 投稿案の正：`../sns投稿管理.xlsx`（このフォルダの `data/posts.json` は書き出したコピー）
- Python：`C:\Users\sorat\anaconda3\python.exe`（`python` コマンドは使えない）
- **ID・パスワード・トークンはチャットに書かない。** GitHub の Secrets にユーザー自身が入力する

---

## しくみ

```
sns投稿管理.xlsx ──(export_posts.py)──▶ data/posts.json ＋ images/*.jpg
                                    └─(make_schedule.py)──▶ data/schedule.csv（いつ・どの投稿）
GitHub Actions（朝7:17・夜21:17）──(scripts/post.py)──▶ Threads・Instagram に投稿 ─▶ data/log.csv に記録
GitHub Actions（毎週水曜3:00）──(scripts/refresh_tokens.py)──▶ トークンを延長して Secrets を上書き
data/log.csv ＋ data/x_log.csv ──(sync_log_to_xlsx.py)──▶ 管理表の「最終投稿日」「投稿回数」
schedule.csv ──(x_week.py)──▶ X予約一覧（14本）→ 確認 → x.com で予約 → x_log.csv
```

| ファイル | 役割 |
|---|---|
| `tools/export_posts.py` | 管理表 → `data/posts.json`。画像を JPEG（長辺1440px）に変換。文字数・PR表記も点検 |
| `tools/make_schedule.py` | 投稿の順番（`data/schedule.csv`）を作る |
| `tools/x_week.py` | X の1週間分の予約一覧を作る／予約済みを記録する |
| `tools/sync_log_to_xlsx.py` | 投稿記録を管理表に反映する |
| `scripts/post.py` | （GitHub で動く）その枠の投稿を Threads・Instagram に出す |
| `scripts/refresh_tokens.py` | （GitHub で動く）トークンの延長 |
| `.github/workflows/` | 自動実行の時刻などの設定 |

### 投稿の順番のルール（make_schedule.py）

- 1日2本（朝・夜）。最初の5本はサイト紹介 A-001〜A-005（A-001 は各SNSで手動で固定表示にする）
- 投稿の型（パターン）ごとに全期間へ均等に散らす → PR（⑨）は全体の約12%、月ごとでも2割以内
- 同じテーマは続けない／同じページは8日以上あける／同じページは 共感→影響→習慣→成分→公的データ→商品 の順を優先
- 1日のうち1本は Instagram 本文のある投稿にする（Instagram は毎日1本前後）
- 季節もの：C-012（冬の体調管理）は12〜2月、pollen（花粉）は2〜3月の中で散らす
- Instagram は Instagram 本文がある投稿だけ。PR投稿には Instagram 本文がないので、Instagram には出ない

---

## はじめの準備（1回だけ）

### ユーザーがやること
1. X・Instagram・Threads のアカウントを作る（Instagram はプロアカウント〈クリエイター〉に切り替え。Threads は Instagram から作る）。アイコンは `../images/sns_icon_futaba.webp`
2. GitHub のアカウントを作る
3. GitHub に **公開（Public）** リポジトリ（名前の案：`supplement-atlas-sns`）を作る
   - Instagram は画像を「誰でも開けるURL」で渡す必要があるため公開にする。入るのは投稿文・画像・予定表・投稿記録だけで、鍵は入らない
4. Meta の開発者アプリを作り、Threads と Instagram のトークンを発行する（Claude が画面を見ながら案内）
   - Threads：ユースケース「Threads API にアクセス」、権限 `threads_basic` `threads_content_publish`
   - Instagram：ユースケース「Instagram のメッセージとコンテンツを管理」→「Instagram ログインによる API 設定」でトークンを生成。権限 `instagram_business_basic` `instagram_business_content_publish`
   - アプリは「開発モード」のままで自分のアカウントには投稿できる（審査は不要）
5. GitHub の個人用トークン（Fine-grained。対象はこのリポジトリだけ、権限は **Secrets: Read and write**）を作る。トークン自動更新が Secrets を書き換えるのに使う
6. リポジトリの Settings → Secrets and variables → Actions に入力：

| Secrets の名前 | 中身 |
|---|---|
| `THREADS_ACCESS_TOKEN` | Threads の長期トークン |
| `IG_ACCESS_TOKEN` | Instagram の長期トークン |
| `SECRETS_PAT` | 5. の GitHub 個人用トークン |
| `THREADS_USER_ID` / `IG_USER_ID` | （入れなくてよい。自動で調べる） |

鍵が入っていない SNS は自動で飛ばすので、Threads だけ先に始めることもできます。

### Claude がやること
1. 開始日を決めて順番を作り直す：`tools\make_schedule.py --start <開始日>`
2. このフォルダを GitHub のリポジトリに送る（`git remote add origin …` → `git push`）
3. Actions の画面で「SNS自動投稿」を **check（鍵の確認）** で手動実行して、つながっているアカウント名と画像URLを確認。次に **お試し（dry_run）** で本文を確認
4. 1本目を手動実行（dry_run を外す）→ 各SNSで表示を確認 → A-001 を固定表示に（ユーザー）

---

## ふだんの運用

### 毎日（自動）
- 朝7:17・夜21:17ごろ（GitHub の混雑で数十分遅れることがある）に Threads・Instagram へ投稿
- 失敗すると GitHub から登録メールに通知が届く。Actions の画面でログを見られる

### 週1回（Claude と一緒に）
1. `git pull`（GitHub の最新の投稿記録を取ってくる）
2. `tools\sync_log_to_xlsx.py` で管理表に反映（**Excel は閉じておく**）
3. `tools\x_week.py --from <来週の月曜など>` で X の予約一覧（`../X予約/X予約_日付.html`）を作り、ユーザーに見せて OK をもらう
4. x.com（ログイン済みのブラウザ）で14本を予約。**画像は付けない**（URLのカード画像で見せる）
5. `tools\x_week.py --from <同じ日付> --mark-done` で記録 → `git add -A`・`git commit`・`git push`

### 管理表を直したとき・投稿案を増やしたとき
1. `tools\export_posts.py`（posts.json と画像を更新。注意が出たら管理表を直す）
2. 必要なら `tools\make_schedule.py --start <まだ投稿していない日>` で順番を作り直す
   - **注意**：作り直すと、その日以降の予定がすべて入れ替わる。X の予約済み分とずれないよう、開始日は X の予約が終わっている週の翌日にする
3. `git add -A`・`git commit`・`git push`

### 2巡目
`tools\make_schedule.py --start <2巡目の開始日> --round 2`（サイト紹介も混ぜて並べ直す）

### 一時停止・設定の変更（GitHub の Settings → Secrets and variables → Actions → Variables）
| Variables の名前 | 値 | 効果 |
|---|---|---|
| `AUTOPOST_PAUSED` | `1` | 自動投稿を止める（消すと再開） |
| `IG_STORY` | `1` | Instagram のストーリーズにも同じ画像を出す（リンクスタンプは API では付けられない） |

投稿時刻を変えるときは `.github/workflows/post.yml` の `cron`（**日本時間−9時間**で書く）を直す。

---

## 注意
- トークンは60日で切れる。毎週水曜に自動延長しているので、普段は何もしなくてよい。延長に失敗したら GitHub からメールが届くので、Claude と一緒にトークンを発行し直す
- GitHub の個人用トークン（SECRETS_PAT・名前 sns-autopost-secrets）の有効期限は **2027年10月18日**。期限の前に GitHub からメールが来るので、同じ権限（このリポジトリだけ・Secrets 読み書き）で作り直して Secrets を上書きする
- 投稿は API 経由なので、Instagram の位置情報・音楽・リンクスタンプなどは付けられない
- 作成：2026年10月18日
