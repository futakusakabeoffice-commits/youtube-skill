"""YouTube Data API v3 からのデータ取得。

API上限到達・通信エラーが起きてもログを残して None / 空を返し、処理全体は止めない。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

BATCH = 50  # videos.list / channels.list は1回で最大50件
VIDEO_PARTS = "snippet,statistics,contentDetails"
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


def _chunks(items: list, size: int = BATCH):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _error_reason(err: HttpError) -> str:
    try:
        payload = json.loads(err.content.decode("utf-8"))
        return payload["error"]["errors"][0].get("reason", "")
    except (ValueError, KeyError, IndexError, AttributeError):
        return ""


class YouTubeCollector:
    def __init__(self, api_key: str, region: str = "JP", language: str = "ja"):
        self.youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        self.region = region
        self.language = language
        self.quota_exceeded = False
        self.errors: list[str] = []

    def _execute(self, request, what: str):
        if self.quota_exceeded:
            return None
        try:
            # num_retries: 5xx や一時的なレート制限は自動で再試行
            return request.execute(num_retries=3)
        except HttpError as e:
            reason = _error_reason(e)
            if reason in QUOTA_REASONS:
                self.quota_exceeded = True
                msg = f"APIの1日の上限に達しました（{what} の時点）。以降の取得をスキップします"
            else:
                msg = f"{what} の取得に失敗しました: HTTP {e.resp.status} {reason}".rstrip()
            log.error(msg)
            self.errors.append(msg)
        except (OSError, TimeoutError) as e:
            msg = f"{what} の取得中に通信エラー: {e}"
            log.error(msg)
            self.errors.append(msg)
        return None

    # ① 急上昇
    def fetch_trending(self, max_results: int = 50) -> list[dict]:
        items: list[dict] = []
        page_token = None
        while len(items) < max_results:
            resp = self._execute(
                self.youtube.videos().list(
                    part=VIDEO_PARTS,
                    chart="mostPopular",
                    regionCode=self.region,
                    hl=self.language,
                    maxResults=min(BATCH, max_results - len(items)),
                    pageToken=page_token,
                ),
                "急上昇動画",
            )
            if not resp:
                break
            items.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        log.info("急上昇: %d件", len(items))
        return items

    # ② キーワード検索（100ユニット/回）
    def search_keyword(self, keyword: str, days_back: int = 7, max_results: int = 25) -> list[str]:
        published_after = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        resp = self._execute(
            self.youtube.search().list(
                part="id",
                q=keyword,
                type="video",
                order="viewCount",
                publishedAfter=published_after,
                regionCode=self.region,
                relevanceLanguage=self.language,
                maxResults=max_results,
            ),
            f"キーワード検索「{keyword}」",
        )
        if not resp:
            return []
        ids = [it["id"]["videoId"] for it in resp.get("items", []) if it.get("id", {}).get("videoId")]
        log.info("検索「%s」: %d件", keyword, len(ids))
        return ids

    # ③ 動画の詳細（50件ずつ）
    def fetch_videos(self, video_ids: list[str]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for chunk in _chunks(list(dict.fromkeys(video_ids))):
            resp = self._execute(
                self.youtube.videos().list(part=VIDEO_PARTS, id=",".join(chunk), hl=self.language),
                "動画の詳細",
            )
            for item in (resp or {}).get("items", []):
                result[item["id"]] = item
        return result

    # ④ チャンネル情報（50件ずつ）。登録者数非公開は None
    def fetch_subscribers(self, channel_ids: list[str]) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        for chunk in _chunks(list(dict.fromkeys(channel_ids))):
            resp = self._execute(
                self.youtube.channels().list(part="statistics", id=",".join(chunk)),
                "チャンネル情報",
            )
            for item in (resp or {}).get("items", []):
                stats = item.get("statistics", {})
                if stats.get("hiddenSubscriberCount") or "subscriberCount" not in stats:
                    result[item["id"]] = None
                else:
                    result[item["id"]] = int(stats["subscriberCount"])
        return result

    # カテゴリID → 名前（1ユニット）
    def fetch_categories(self) -> dict[str, str]:
        resp = self._execute(
            self.youtube.videoCategories().list(part="snippet", regionCode=self.region, hl=self.language),
            "カテゴリ一覧",
        )
        return {it["id"]: it["snippet"]["title"] for it in (resp or {}).get("items", [])}
