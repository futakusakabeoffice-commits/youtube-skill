"""指標の計算（再生/登録者比、勢い、エンゲージメント率、動画タイプ、タイトルの特徴）。"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

import isodate

# タイトルの単語抽出：漢字・カタカナの連続、英単語。ひらがな（助詞など）は拾わない
WORD_RE = re.compile(r"[一-龥々〆]{2,}|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9+#]+")
STOPWORDS = {
    "shorts", "short", "official", "video", "music", "the", "and", "for", "with", "you",
    "feat", "ft", "mv", "ver", "vs", "part", "live", "full",
}
QUESTION_WORDS = ("なぜ", "どうして", "何故", "どうやって", "本当", "なに", "何が", "どっち", "どれ")


def parse_duration(iso: str | None) -> int:
    """ISO 8601 の長さ（例: PT1H2M3S）を秒に変換。ライブ配信中などで取れない場合は0。"""
    if not iso:
        return 0
    try:
        return int(isodate.parse_duration(iso).total_seconds())
    except (isodate.ISO8601Error, ValueError, TypeError):
        return 0


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def title_features(title: str) -> dict:
    t = unicodedata.normalize("NFKC", title)
    return {
        "title_len": len(t),
        "has_number": bool(re.search(r"\d", t)),
        "has_brackets": "【" in t and "】" in t,
        "is_question": "?" in t or t.rstrip("!！。 ").endswith("か") or any(w in t for w in QUESTION_WORDS),
    }


def title_words(title: str) -> list[str]:
    t = unicodedata.normalize("NFKC", title)
    return [w for w in WORD_RE.findall(t) if w.lower() not in STOPWORDS]


def build_records(
    items: dict[str, dict],
    subscribers: dict[str, int | None],
    categories: dict[str, str],
    sources: dict[str, set[str]],
    shorts_max_seconds: int = 180,
    now: datetime | None = None,
) -> list[dict]:
    """APIの生データを、レポート・保存用の1動画1レコードにまとめる。"""
    now = now or datetime.now(timezone.utc)
    records = []
    for vid, item in items.items():
        snip = item.get("snippet", {})
        stats = item.get("statistics", {})
        views = int(stats.get("viewCount", 0))
        likes = int(stats["likeCount"]) if "likeCount" in stats else None
        comments = int(stats["commentCount"]) if "commentCount" in stats else None
        duration = parse_duration(item.get("contentDetails", {}).get("duration"))
        published = parse_datetime(snip["publishedAt"])
        hours = max((now - published).total_seconds() / 3600, 1.0)  # 公開直後の過大評価を防ぐため最低1時間
        subs = subscribers.get(snip.get("channelId"))

        rec = {
            "video_id": vid,
            "title": snip.get("title", ""),
            "channel_id": snip.get("channelId", ""),
            "channel_title": snip.get("channelTitle", ""),
            "published_at": published,
            "duration_sec": duration,
            # APIにショート判定はないため長さで推定（0秒=ライブ等は長尺扱い）
            "video_type": "ショート" if 0 < duration <= shorts_max_seconds else "長尺",
            "category_id": snip.get("categoryId", ""),
            "category_name": categories.get(snip.get("categoryId", ""), snip.get("categoryId", "不明")),
            "tags": snip.get("tags", []),
            "views": views,
            "likes": likes,
            "comments": comments,
            "subscribers": subs,
            # 登録者数が非公開・0のチャンネルは比率計算から除外
            "ratio": views / subs if subs else None,
            "hours_since": hours,
            "views_per_hour": views / hours,
            "engagement": ((likes or 0) + (comments or 0)) / views if views else None,
            "sources": sorted(sources.get(vid, set())),
            "views_diff": None,
            "prev_date": None,
        }
        rec.update(title_features(rec["title"]))
        records.append(rec)
    return records


def trending_stats(records: list[dict]) -> dict:
    if not records:
        return {}
    n = len(records)
    shorts = sum(1 for r in records if r["video_type"] == "ショート")
    durations = [r["duration_sec"] for r in records if r["duration_sec"] > 0]
    return {
        "count": n,
        "shorts_pct": shorts / n * 100,
        "long_pct": (n - shorts) / n * 100,
        "top_categories": Counter(r["category_name"] for r in records).most_common(3),
        "avg_duration_sec": sum(durations) / len(durations) if durations else 0,
        "avg_engagement_pct": _avg([r["engagement"] for r in records]) * 100,
    }


def title_stats(records: list[dict], top_words: int = 10) -> dict:
    if not records:
        return {}
    n = len(records)
    counter: Counter[str] = Counter()
    display: dict[str, str] = {}  # 英単語は大文字小文字を区別せず数え、最初に出た表記で表示
    for r in records:
        words = title_words(r["title"])
        for w in words:
            display.setdefault(w.lower(), w)
        counter.update({w.lower() for w in words})  # 1タイトル内の重複は1回と数える
    return {
        "count": n,
        "avg_len": sum(r["title_len"] for r in records) / n,
        "number_pct": sum(r["has_number"] for r in records) / n * 100,
        "brackets_pct": sum(r["has_brackets"] for r in records) / n * 100,
        "question_pct": sum(r["is_question"] for r in records) / n * 100,
        "top_words": [(display[w], c) for w, c in counter.most_common(top_words)],
    }


def _avg(values: list[float | None]) -> float:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0
