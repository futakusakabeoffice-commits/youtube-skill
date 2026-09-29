# YouTube トレンド自動分析システム 仕様書

毎朝、YouTubeで「今伸びている動画」を自動で収集・分析し、日次レポート（Markdown）を出力するシステムの設計書です。
このファイルを Claude Code などのAIコーディングツールに渡せば、そのまま実装を依頼できる形で書いています。

---

## 1. 目的

- 日本のYouTubeで今どんな動画が再生されているかを毎日把握する
- 自分が狙うジャンルで「登録者数のわりに再生数が多い動画（企画の力で伸びた動画）」を見つける
- 伸びている動画の共通点（タイトル・長さ・テーマ）から、次に作る動画の企画案を得る

---

## 2. 全体構成

```
[毎朝7:00 自動実行（GitHub Actions）]
        ↓
[Pythonスクリプト]
        ↓
[YouTube Data API v3 でデータ取得]
  ├─ 日本の急上昇動画
  └─ 指定キーワードの直近7日間の人気動画
        ↓
[指標を計算]（再生/登録者比、1時間あたり再生数 など）
        ↓
[SQLiteに履歴を保存]（前日比を出すため）
        ↓
[（任意）Claude APIで傾向を要約・企画案を生成]
        ↓
[reports/YYYY-MM-DD.md を出力] → リポジトリにコミット
```

---

## 3. 事前準備

1. Googleアカウントで Google Cloud Console にログインし、新しいプロジェクトを作成する
2. 「YouTube Data API v3」を有効化する
3. 「認証情報」から APIキー を発行する
4. GitHubで非公開リポジトリを作成する
5. リポジトリの Settings → Secrets に以下を登録する
   - `YOUTUBE_API_KEY`（必須）
   - `ANTHROPIC_API_KEY`（AI要約を使う場合のみ）

※ APIキーはコードに直接書かず、必ずSecrets（環境変数）で管理すること。

---

## 4. 設定ファイル（config.yaml）

分析したいジャンルに合わせて、ここだけ書き換えれば使えるようにする。

```yaml
region: JP
language: ja

# 自分が狙うジャンルのキーワード（1つにつき検索1回）
keywords:
  - "副業 始め方"
  - "節約 術"
  - "AI 使い方"

search:
  days_back: 7          # 直近何日に公開された動画を対象にするか
  max_results: 25       # キーワードごとの取得件数（最大50）

trending:
  max_results: 50       # 急上昇動画の取得件数

thresholds:
  outlier_ratio: 3.0    # 再生数 ÷ 登録者数 がこれ以上なら「企画で伸びた動画」
  shorts_max_seconds: 180  # これ以下の長さをショートとみなす

report:
  top_n: 10             # レポートに載せる上位件数
  use_ai_summary: true  # Claude APIで要約するか
```

---

## 5. データ収集の仕様

| 手順 | APIメソッド | 主なパラメータ | 取得する情報 |
|---|---|---|---|
| ① 急上昇 | `videos.list` | `chart=mostPopular`, `regionCode=JP` | 日本の急上昇動画 |
| ② キーワード検索 | `search.list` | `q=キーワード`, `type=video`, `order=viewCount`, `publishedAfter=7日前`, `regionCode=JP`, `relevanceLanguage=ja` | 動画IDの一覧 |
| ③ 動画の詳細 | `videos.list` | `part=snippet,statistics,contentDetails` | タイトル、公開日時、再生数、高評価数、コメント数、長さ、タグ |
| ④ チャンネル情報 | `channels.list` | `part=statistics` | 登録者数 |

- ③④はIDを最大50件ずつまとめて取得し、API消費を抑える
- 登録者数が非公開のチャンネルは比率計算から除外する

---

## 6. 計算する指標

| 指標 | 計算式 | 意味 |
|---|---|---|
| 再生/登録者比 | 再生数 ÷ 登録者数 | 3倍以上なら「チャンネルの力ではなく企画で伸びた」可能性が高い |
| 勢い（1時間あたり再生数） | 再生数 ÷ 公開からの経過時間 | 今まさに伸びている動画を見つける |
| エンゲージメント率 | （高評価数 + コメント数）÷ 再生数 | 視聴者の反応の強さ |
| 動画タイプ | 長さ ≦ 180秒 → ショート、それ以外 → 長尺 | APIにショート判定がないため長さで推定 |
| 前日比 | 今日の再生数 − 昨日の再生数 | 履歴DBに同じ動画があれば計算 |
| タイトルの特徴 | 文字数、数字の有無、【】の有無、疑問形か | 伸びるタイトルの傾向をつかむ |

---

## 7. データ保存（SQLite: data/trends.db）

```
videos
  video_id (PK), title, channel_id, channel_title,
  published_at, duration_sec, video_type, category_id, tags

snapshots
  video_id, collected_date, views, likes, comments,
  subscribers, source（trending / keyword名）
  PRIMARY KEY (video_id, collected_date)
```

- 毎日 snapshots に1行ずつ追加し、前日比や伸び方の推移を出せるようにする
- 90日より古いsnapshotsは削除して容量を抑える

---

## 8. 日次レポートの出力形式（reports/YYYY-MM-DD.md）

```markdown
# YouTubeトレンド日次レポート（2026-10-01）

## 今日のサマリー
（AI要約：今日目立った傾向を3〜5行で）

## 企画で伸びた動画 TOP10（再生/登録者比）
| # | タイトル | チャンネル | 登録者 | 再生数 | 比率 | 長さ | タイプ |

## 今まさに伸びている動画 TOP10（1時間あたり再生数）
| # | タイトル | 公開から | 再生数 | 勢い | タイプ |

## キーワード別の上位動画
### 副業 始め方
| # | タイトル | 再生数 | 比率 | 長さ |

## 急上昇の傾向
- ショート / 長尺の割合
- 多かったカテゴリ TOP3
- 平均の動画の長さ

## タイトルの傾向
- 平均文字数、数字入りタイトルの割合、よく使われている単語 TOP10

## 企画アイデア（AI生成）
1. ...
2. ...
3. ...
```

---

## 9. AI要約（任意）

`use_ai_summary: true` のとき、集計結果（上位動画のタイトル・長さ・比率など）をJSONにまとめて Claude API に渡し、以下を生成させる。

- 今日の傾向のサマリー（3〜5行）
- 伸びている動画に共通する特徴（タイトル・長さ・テーマ）
- 設定したキーワードのジャンルで作れる企画案を3つ

プロンプト例：

```
あなたはYouTubeの企画アナリストです。
以下は日本のYouTubeで今日伸びている動画のデータです。
1. 目立った傾向を3〜5行で要約してください
2. 伸びている動画の共通点を、タイトル・長さ・テーマの観点で挙げてください
3. 「{keywords}」のジャンルで、個人が作れる企画案を3つ提案してください
データにない推測は「推測」と明記してください。

{data_json}
```

- 使用モデル：`claude-sonnet-5-5`
- APIエラー時はAI部分をスキップし、数値レポートだけ出力する

---

## 10. 自動実行（GitHub Actions）

`.github/workflows/daily.yml`

```yaml
name: Daily YouTube Trend Report

on:
  schedule:
    - cron: "0 22 * * *"   # UTC 22:00 = 日本時間 毎朝7:00
  workflow_dispatch:        # 手動実行ボタン

permissions:
  contents: write

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - name: Commit report
        run: |
          git config user.name "trend-bot"
          git config user.email "bot@example.com"
          git add reports/ data/
          git commit -m "report: $(date +%F)" || echo "no changes"
          git push
```

---

## 11. APIの使用量（クォータ）の目安

YouTube Data API は1日あたりの使用上限（初期値は1万ユニット程度）がある。

| 処理 | 消費の目安 | 回数 | 合計 |
|---|---|---|---|
| 急上昇（videos.list） | 1 | 1回 | 1 |
| キーワード検索（search.list） | 100 | キーワード数 | 例：3個で300 |
| 動画詳細（videos.list） | 1 | 50件ごとに1回 | 数ユニット |
| チャンネル情報（channels.list） | 1 | 50件ごとに1回 | 数ユニット |

→ キーワード10個程度までなら上限に余裕がある。検索（search.list）が最も重いので、キーワードを増やすときは注意。

---

## 12. フォルダ構成

```
youtube-trend-analyzer/
├── main.py              # 全体の実行
├── config.yaml          # 設定
├── requirements.txt     # google-api-python-client, pyyaml, anthropic, isodate
├── src/
│   ├── collector.py     # API取得
│   ├── metrics.py       # 指標計算
│   ├── storage.py       # SQLite保存
│   ├── summarizer.py    # Claude API要約
│   └── report.py        # Markdown出力
├── data/trends.db
├── reports/
└── .github/workflows/daily.yml
```

---

## 13. 実装タスク一覧（AIに依頼する順番）

1. config.yaml の読み込みと、APIキーを環境変数から読む処理
2. collector.py：急上昇・キーワード検索・動画詳細・チャンネル情報の取得（50件ずつまとめて取得）
3. metrics.py：6章の指標を計算（ISO 8601の動画の長さを秒に変換）
4. storage.py：SQLiteへの保存、前日比の計算、90日より古いデータの削除
5. report.py：8章の形式でMarkdownを出力
6. summarizer.py：Claude APIでの要約（失敗時はスキップ）
7. GitHub Actions の設定と、手動実行での動作確認
8. エラー処理：API上限到達・通信エラー時もログを残して処理を止めない

---

## 14. 注意点

- YouTubeの登録者数はAPIでも丸められた値（上位3桁）で返るため、比率はあくまで目安
- ショート判定は長さによる推定で、正確ではない
- 急上昇チャートは音楽・大手チャンネルが多いため、個人向けの参考にはキーワード検索の結果を重視する
- 取得したデータは自分の分析用にとどめ、YouTube API の利用規約に従うこと
- 1週間ほど動かしたら、キーワードやしきい値（outlier_ratio など）を見直す
