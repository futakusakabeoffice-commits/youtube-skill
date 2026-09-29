"""日次レポート（Markdown）の出力。"""

from __future__ import annotations

from datetime import date
from pathlib import Path


def fmt_num(n: float | int | None) -> str:
    """日本語の単位（万・億）で読みやすく表示する。"""
    if n is None:
        return "非公開"
    n = float(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1e8:
        return f"{sign}{n / 1e8:.1f}億"
    if n >= 1e4:
        return f"{sign}{n / 1e4:.1f}万"
    return f"{sign}{n:,.0f}"


def fmt_duration(sec: int) -> str:
    if sec <= 0:
        return "-"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_age(hours: float) -> str:
    if hours < 24:
        return f"{hours:.0f}時間"
    d, h = divmod(int(hours), 24)
    return f"{d}日{h}時間" if h else f"{d}日"


def _cell(text: str, limit: int = 60) -> str:
    text = text.replace("|", "｜").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _link(r: dict) -> str:
    return f"[{_cell(r['title'])}](https://www.youtube.com/watch?v={r['video_id']})"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["（該当する動画はありませんでした）", ""]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines + [""]


def render(
    today: date,
    analysis: dict,
    ai: dict | None,
    cfg: dict,
    warnings: list[str],
) -> str:
    th = cfg["thresholds"]
    out = [f"# YouTubeトレンド日次レポート（{today.isoformat()}）", ""]

    if warnings:
        out += ["> ⚠️ **注意**：一部のデータを取得できませんでした", ">"]
        out += [f"> - {w}" for w in warnings] + [""]

    out += ["## 今日のサマリー", ""]
    if ai:
        out += [ai["summary"].strip(), ""]
    else:
        out += ["（AI要約はオフ、または取得できませんでした）", ""]

    # 企画で伸びた動画
    out += [
        f"## 企画で伸びた動画 TOP{len(analysis['outliers']) or cfg['report']['top_n']}（再生/登録者比）",
        "",
        f"再生数 ÷ 登録者数 が {th['outlier_ratio']:g}倍以上、かつ {fmt_num(th['outlier_min_views'])}回以上再生された動画",
        "",
    ]
    out += _table(
        ["#", "タイトル", "チャンネル", "登録者", "再生数", "比率", "長さ", "タイプ"],
        [
            [
                str(i), _link(r), _cell(r["channel_title"], 20), fmt_num(r["subscribers"]),
                fmt_num(r["views"]), f"{r['ratio']:.1f}倍", fmt_duration(r["duration_sec"]), r["video_type"],
            ]
            for i, r in enumerate(analysis["outliers"], 1)
        ],
    )

    # 今まさに伸びている動画
    out += [f"## 今まさに伸びている動画 TOP{len(analysis['velocity'])}（1時間あたり再生数）", ""]
    out += _table(
        ["#", "タイトル", "公開から", "再生数", "勢い", "タイプ"],
        [
            [
                str(i), _link(r), fmt_age(r["hours_since"]), fmt_num(r["views"]),
                f"{fmt_num(r['views_per_hour'])}/時", r["video_type"],
            ]
            for i, r in enumerate(analysis["velocity"], 1)
        ],
    )

    # 前日比
    if analysis["growth"]:
        out += [f"## 前日から再生数が伸びた動画 TOP{len(analysis['growth'])}", ""]
        out += _table(
            ["#", "タイトル", "再生数", "前日比", "比較日", "タイプ"],
            [
                [
                    str(i), _link(r), fmt_num(r["views"]), "+" + fmt_num(r["views_diff"]),
                    r["prev_date"], r["video_type"],
                ]
                for i, r in enumerate(analysis["growth"], 1)
            ],
        )

    # キーワード別
    out += ["## キーワード別の上位動画", ""]
    if not analysis["by_keyword"]:
        out += ["（config.yaml にキーワードが設定されていません）", ""]
    for kw, recs in analysis["by_keyword"].items():
        out += [f"### {kw}", ""]
        out += _table(
            ["#", "タイトル", "再生数", "比率", "長さ", "エンゲージメント"],
            [
                [
                    str(i), _link(r), fmt_num(r["views"]),
                    f"{r['ratio']:.1f}倍" if r["ratio"] is not None else "-",
                    fmt_duration(r["duration_sec"]),
                    f"{r['engagement'] * 100:.1f}%" if r["engagement"] is not None else "-",
                ]
                for i, r in enumerate(recs[: cfg["report"]["top_n"]], 1)
            ],
        )

    # 急上昇の傾向
    ts = analysis["trending_stats"]
    out += ["## 急上昇の傾向", ""]
    if ts:
        cats = "、".join(f"{name}（{cnt}本）" for name, cnt in ts["top_categories"])
        out += [
            f"- 対象：急上昇 {ts['count']}本",
            f"- ショート / 長尺の割合：{ts['shorts_pct']:.0f}% / {ts['long_pct']:.0f}%",
            f"- 多かったカテゴリ TOP3：{cats}",
            f"- 平均の動画の長さ：{fmt_duration(round(ts['avg_duration_sec']))}",
            f"- 平均エンゲージメント率：{ts['avg_engagement_pct']:.2f}%",
            "",
        ]
    else:
        out += ["（急上昇データを取得できませんでした）", ""]

    # タイトルの傾向
    tt = analysis["title_stats"]
    out += ["## タイトルの傾向", ""]
    if tt:
        words = "、".join(f"{w}（{c}）" for w, c in tt["top_words"])
        out += [
            f"- 対象：取得した全動画 {tt['count']}本",
            f"- 平均文字数：{tt['avg_len']:.1f}文字",
            f"- 数字入りタイトルの割合：{tt['number_pct']:.0f}%",
            f"- 【】入りタイトルの割合：{tt['brackets_pct']:.0f}%",
            f"- 疑問形タイトルの割合：{tt['question_pct']:.0f}%",
            f"- よく使われている単語 TOP{len(tt['top_words'])}：{words}",
            "",
        ]

    if ai:
        cf = ai["common_features"]
        out += [
            "## 伸びている動画の共通点（AI分析）",
            "",
            f"- **タイトル**：{cf['title']}",
            f"- **長さ**：{cf['length']}",
            f"- **テーマ**：{cf['theme']}",
            "",
            "## 企画アイデア（AI生成）",
            "",
        ]
        for i, idea in enumerate(ai["ideas"], 1):
            out += [f"{i}. **{idea['title']}**（{idea['format']}）", f"   - {idea['concept']}"]
        out += [""]

    out += [
        "---",
        "※ 登録者数はAPIの丸め値のため比率は目安です。ショート判定は長さによる推定です。",
        "",
    ]
    return "\n".join(out)


def write_report(content: str, reports_dir: str | Path, today: date) -> Path:
    path = Path(reports_dir) / f"{today.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
