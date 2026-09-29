import json
from datetime import date, datetime, timedelta, timezone

import pytest

import main
from src.config import load_config
from src.metrics import parse_duration, title_features, title_words
from src.summarizer import build_payload


def make_item(vid, title, channel, views, duration, hours_ago, category="24"):
    published = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "id": vid,
        "snippet": {
            "title": title,
            "channelId": channel,
            "channelTitle": f"ch-{channel}",
            "publishedAt": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "categoryId": category,
            "tags": ["tag"],
        },
        "statistics": {"viewCount": str(views), "likeCount": str(views // 50), "commentCount": "10"},
        "contentDetails": {"duration": duration},
    }


class FakeCollector:
    def __init__(self, view_boost=0):
        b = view_boost
        self.trending = [
            make_item("t1", "【検証】AIで副業は稼げるのか？", "big", 2_000_000 + b, "PT12M3S", 20),
            make_item("t2", "新曲MV", "music", 5_000_000 + b, "PT3M30S", 48, category="10"),
            make_item("t3", "節約術 5選 #shorts", "small", 300_000 + b, "PT45S", 10),
        ]
        self.keyword = {
            "副業 始め方": ["k1", "t1"],
            "節約 術": ["k2"],
        }
        self.details = {
            "k1": make_item("k1", "副業の始め方 完全ガイド 2026", "tiny", 150_000 + b, "PT25M", 72),
            "k2": make_item("k2", "1ヶ月3万円節約した方法", "hidden", 80_000 + b, "PT8M", 30),
        }
        self.errors = []

    def fetch_trending(self, max_results):
        return self.trending

    def search_keyword(self, kw, days_back, max_results):
        return self.keyword.get(kw, [])

    def fetch_videos(self, ids):
        return {i: self.details[i] for i in ids if i in self.details}

    def fetch_subscribers(self, channel_ids):
        return {"big": 1_000_000, "music": 10_000_000, "small": 20_000, "tiny": 5_000, "hidden": None}

    def fetch_categories(self):
        return {"24": "エンターテイメント", "10": "音楽"}


@pytest.fixture
def cfg(tmp_path):
    c = load_config("config.yaml")
    c["keywords"] = ["副業 始め方", "節約 術"]
    c["storage"]["db_path"] = str(tmp_path / "trends.db")
    c["storage"]["reports_dir"] = str(tmp_path / "reports")
    return c


def test_helpers():
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("P0D") == 0
    assert parse_duration(None) == 0
    f = title_features("【検証】AIで副業は稼げるのか？ 3選")
    assert f["has_brackets"] and f["has_number"] and f["is_question"]
    assert "副業" in title_words("【検証】AIで副業は稼げる")
    assert "shorts" not in title_words("節約術 #shorts")


def test_run_writes_report_with_ai_and_growth(cfg, tmp_path):
    ai = {
        "summary": "ショートと検証系が強い。",
        "common_features": {"title": "数字入り", "length": "10分前後", "theme": "お金"},
        "ideas": [{"title": "案1", "concept": "説明", "format": "長尺 10分"}],
    }
    captured = {}

    def fake_summarize(analysis, keywords, key, model):
        captured["payload"] = build_payload(analysis, keywords)
        return ai

    day1, day2 = date(2026, 9, 28), date(2026, 9, 29)
    assert main.run(cfg, FakeCollector(), day1, "key", fake_summarize) == 0
    assert main.run(cfg, FakeCollector(view_boost=1000), day2, "key", fake_summarize) == 0

    json.dumps(captured["payload"], ensure_ascii=False)  # JSON化できること
    report = (tmp_path / "reports" / "2026-09-29.md").read_text(encoding="utf-8")
    assert "# YouTubeトレンド日次レポート（2026-09-29）" in report
    assert "ショートと検証系が強い。" in report
    # tiny: 150,000 / 5,000 = 30倍、small: 15倍。大手・非公開は除外
    outliers = report.split("## 企画で伸びた動画")[1].split("## 今まさに")[0]
    assert outliers.index("副業の始め方") < outliers.index("節約術 5選")
    assert "新曲MV" not in outliers and "1ヶ月3万円" not in outliers
    assert "## 前日から再生数が伸びた動画" in report and "+1,000" in report
    assert "### 副業 始め方" in report and "### 節約 術" in report
    assert "ショート / 長尺の割合：33% / 67%" in report
    assert "## 企画アイデア（AI生成）" in report


def test_run_without_ai_key(cfg, tmp_path):
    assert main.run(cfg, FakeCollector(), date(2026, 9, 29), None) == 0
    report = (tmp_path / "reports" / "2026-09-29.md").read_text(encoding="utf-8")
    assert "AI要約はオフ" in report
    assert "前日から" not in report


def test_run_with_no_data(cfg):
    c = FakeCollector()
    c.trending, c.keyword = [], {}
    c.errors.append("APIの1日の上限に達しました")
    assert main.run(cfg, c, date(2026, 9, 29), None) == 1
