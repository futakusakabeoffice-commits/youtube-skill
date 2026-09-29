# YouTube トレンド自動分析

毎朝7:00（日本時間）に YouTube の「今伸びている動画」を自動で集めて分析し、
`reports/YYYY-MM-DD.md` に日次レポートを出力します。設計書は [docs/spec.md](docs/spec.md)。

## レポートでわかること

- **企画で伸びた動画**：再生数 ÷ 登録者数 が大きい動画（チャンネルの力ではなく企画の力で伸びた可能性が高い）
- **今まさに伸びている動画**：1時間あたりの再生数
- **前日から再生数が伸びた動画**：2日目以降、履歴DBとの比較で表示
- **キーワード別の上位動画**：`config.yaml` で指定したジャンルの直近7日間の人気動画
- **急上昇の傾向**：ショート/長尺の割合、多いカテゴリ、平均の長さ
- **タイトルの傾向**：平均文字数、数字・【】・疑問形の割合、よく使われる単語
- **AI要約・企画アイデア**（任意）：Claude API で傾向の要約と企画案3つを生成

## セットアップ

### 1. YouTube APIキーを取得する

1. [Google Cloud Console](https://console.cloud.google.com/) で新しいプロジェクトを作成
2. 「APIとサービス」→「ライブラリ」で **YouTube Data API v3** を有効化
3. 「認証情報」→「認証情報を作成」→ **APIキー** を発行

### 2. （任意）Anthropic APIキーを取得する

AI要約を使う場合のみ。[Claude Console](https://platform.claude.com/) で APIキーを発行します。
未設定の場合は AI 部分だけ自動でスキップされ、数値レポートは出力されます。

### 3. GitHub に登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録します。

| 名前 | 内容 |
|---|---|
| `YOUTUBE_API_KEY` | 手順1のキー（必須） |
| `ANTHROPIC_API_KEY` | 手順2のキー（任意） |

※ APIキーはコードやファイルに直接書かないでください。

### 4. 動作確認

**Actions** タブ →「Daily YouTube Trend Report」→ **Run workflow** で手動実行できます。
成功すると `reports/` にその日のレポートがコミットされます。以降は毎朝7:00に自動実行されます。

## 自分のジャンルに合わせる

`config.yaml` の `keywords` を、自分が狙うジャンルのキーワードに書き換えてください。

```yaml
keywords:
  - "副業 始め方"
  - "節約 術"
  - "AI 使い方"
```

| 設定 | 意味 |
|---|---|
| `search.days_back` | 直近何日に公開された動画を対象にするか |
| `thresholds.outlier_ratio` | 再生/登録者比がこれ以上なら「企画で伸びた動画」 |
| `thresholds.outlier_min_views` | 登録者が極端に少ないチャンネルのノイズを除く最低再生数 |
| `thresholds.shorts_max_seconds` | これ以下の長さをショートとみなす |
| `report.top_n` | レポートに載せる上位件数 |
| `report.use_ai_summary` | AI要約を使うか |

1週間ほど動かしたら、キーワードやしきい値を見直すのがおすすめです。

### APIの使用量について

YouTube Data API は1日1万ユニットが上限です。キーワード検索が1回100ユニットと重く、
それ以外は数ユニットなので、**キーワードは10個程度まで**なら余裕があります。
上限に達した場合もその時点までのデータでレポートを作り、レポート冒頭に注意を表示します。

## ローカルで実行する

```bash
pip install -r requirements.txt
export YOUTUBE_API_KEY=...
export ANTHROPIC_API_KEY=...   # 任意
python main.py
```

テスト（APIキー不要）：

```bash
pip install pytest
python -m pytest
```

## 構成

```
main.py              # 全体の実行（取得 → 指標計算 → 保存 → AI要約 → レポート）
config.yaml          # 設定
src/config.py        # 設定とAPIキーの読み込み
src/collector.py     # YouTube API からの取得（50件ずつまとめて取得、上限・通信エラー時も止まらない）
src/metrics.py       # 指標計算
src/storage.py       # SQLite（data/trends.db）への履歴保存・前日比・90日より古いデータの削除
src/summarizer.py    # Claude API による要約と企画案
src/report.py        # Markdown レポート出力
.github/workflows/daily.yml  # 毎朝7:00の自動実行
```

## 注意点

- 登録者数は API でも丸められた値（上位3桁）なので、比率はあくまで目安です
- ショート判定は長さによる推定で、正確ではありません
- 急上昇は音楽・大手チャンネルが多いため、個人向けの参考にはキーワード検索の結果を重視してください
- 取得したデータは自分の分析用にとどめ、YouTube API の利用規約に従ってください
