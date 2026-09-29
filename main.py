"""YouTubeトレンド日次分析：取得 → 指標計算 → 保存 → (AI要約) → レポート出力。"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from src.config import load_api_keys, load_config
from src.metrics import build_records, title_stats, trending_stats
from src.report import render, write_report
from src.storage import Storage

JST = timezone(timedelta(hours=9))
log = logging.getLogger("trend")


def collect(collector, cfg: dict) -> tuple[dict[str, dict], dict[str, set[str]], dict[str, list[str]]]:
    """急上昇とキーワード検索の結果を集め、動画詳細を50件ずつまとめて取得する。"""
    items: dict[str, dict] = {}
    sources: dict[str, set[str]] = {}
    keyword_ids: dict[str, list[str]] = {}

    for item in collector.fetch_trending(cfg["trending"]["max_results"]):
        items[item["id"]] = item
        sources.setdefault(item["id"], set()).add("trending")

    for kw in cfg["keywords"]:
        ids = collector.search_keyword(kw, cfg["search"]["days_back"], cfg["search"]["max_results"])
        keyword_ids[kw] = ids
        for vid in ids:
            sources.setdefault(vid, set()).add(kw)

    missing = [vid for ids in keyword_ids.values() for vid in ids if vid not in items]
    items.update(collector.fetch_videos(missing))
    return items, sources, keyword_ids


def analyze(records: list[dict], keyword_ids: dict[str, list[str]], cfg: dict) -> dict:
    top_n = cfg["report"]["top_n"]
    th = cfg["thresholds"]
    by_id = {r["video_id"]: r for r in records}

    outliers = sorted(
        (
            r for r in records
            if r["ratio"] is not None
            and r["ratio"] >= th["outlier_ratio"]
            and r["views"] >= th["outlier_min_views"]
        ),
        key=lambda r: r["ratio"],
        reverse=True,
    )[:top_n]
    velocity = sorted(records, key=lambda r: r["views_per_hour"], reverse=True)[:top_n]
    growth = sorted(
        (r for r in records if r["views_diff"] and r["views_diff"] > 0),
        key=lambda r: r["views_diff"],
        reverse=True,
    )[:top_n]
    by_keyword = {
        kw: sorted((by_id[v] for v in ids if v in by_id), key=lambda r: r["views"], reverse=True)
        for kw, ids in keyword_ids.items()
    }
    trending = [r for r in records if "trending" in r["sources"]]
    return {
        "outliers": outliers,
        "velocity": velocity,
        "growth": growth,
        "by_keyword": by_keyword,
        "trending_stats": trending_stats(trending),
        "title_stats": title_stats(records),
    }


def run(cfg: dict, collector, today: date, anthropic_key: str | None, summarize_fn=None) -> int:
    items, sources, keyword_ids = collect(collector, cfg)
    if not items:
        log.error("動画データを1件も取得できませんでした。APIキーやクォータを確認してください")
        for msg in collector.errors:
            log.error("  %s", msg)
        return 1

    channel_ids = [it["snippet"]["channelId"] for it in items.values()]
    subscribers = collector.fetch_subscribers(channel_ids)
    categories = collector.fetch_categories()
    records = build_records(
        items, subscribers, categories, sources, cfg["thresholds"]["shorts_max_seconds"]
    )
    log.info("分析対象: %d本", len(records))

    storage = Storage(cfg["storage"]["db_path"])
    try:
        storage.attach_previous(records, today)
        storage.save(records, today)
        deleted = storage.prune(today, cfg["storage"]["keep_days"])
        if deleted:
            log.info("古いスナップショットを%d件削除しました", deleted)
    finally:
        storage.close()

    analysis = analyze(records, keyword_ids, cfg)

    ai = None
    if cfg["report"]["use_ai_summary"]:
        if not anthropic_key:
            log.warning("ANTHROPIC_API_KEY が未設定のため AI要約をスキップします")
        else:
            if summarize_fn is None:
                from src.summarizer import summarize as summarize_fn
            ai = summarize_fn(analysis, cfg["keywords"], anthropic_key, cfg["ai"]["model"])

    content = render(today, analysis, ai, cfg, collector.errors)
    path = write_report(content, cfg["storage"]["reports_dir"], today)
    log.info("レポートを出力しました: %s", path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="YouTubeトレンド日次レポートを作成します")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    keys = load_api_keys()
    if not keys.youtube:
        log.error("環境変数 YOUTUBE_API_KEY が設定されていません")
        return 1

    from src.collector import YouTubeCollector

    collector = YouTubeCollector(keys.youtube, cfg["region"], cfg["language"])
    today = datetime.now(JST).date()
    return run(cfg, collector, today, keys.anthropic)


if __name__ == "__main__":
    sys.exit(main())
