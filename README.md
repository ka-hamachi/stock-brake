# 日本株 高値更新 Slack 通知

GitHub Actions で kabutan.jp を 5 分ごとに監視し、年初来高値・52週高値を更新した銘柄を Slack に通知します。PC がシャットダウンしていても常時動作します。

## 通知内容

| 種類 | 説明 |
|------|------|
| 年初来高値更新 | 当年1月1日以降の最高値を更新した銘柄 |
| 52週高値更新 | 過去52週間の最高値を更新した銘柄 |

> 上場来高値（IPO以来の最高値）は kabutan.jp では公開されていないため、代替として52週高値を使用しています。

## セットアップ手順

### 1. GitHub リポジトリを作成して Push

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
git push -u origin main
```

### 2. Slack Webhook URL をシークレットに登録

GitHubリポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を追加:

| Name | Value |
|------|-------|
| `SLACK_WEBHOOK_URL` | `https://hooks.slack.com/services/...` |

### 3. GitHub Actions を有効化

リポジトリの **Actions タブ** を開き、「I understand my workflows, go ahead and enable them」をクリック。

### 4. 動作確認（手動実行）

Actions タブ → 「日本株 高値更新モニター」→ 「Run workflow」で即時実行して Slack に通知が届くか確認。

## 動作仕様

- **実行間隔**: 5分ごと（東証取引時間 JST 09:00-11:30, 12:30-15:30、月〜金）
- **状態管理**: `data/state.json` に当日通知済み銘柄を記録（日付が変わると自動リセット）
- **重複通知防止**: 同じ銘柄は1日1回のみ通知

## ファイル構成

```
.
├── .github/workflows/monitor.yml  # GitHub Actions スケジュール定義
├── data/state.json                # 通知済み銘柄の状態ファイル（自動更新）
├── monitor.py                     # メインスクリプト
├── requirements.txt               # Python 依存パッケージ
└── README.md
```
