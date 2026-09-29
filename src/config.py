"""config.yaml の読み込みと APIキー（環境変数）の取得。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULTS = {
    "region": "JP",
    "language": "ja",
    "keywords": [],
    "search": {"days_back": 7, "max_results": 25},
    "trending": {"max_results": 50},
    "thresholds": {
        "outlier_ratio": 3.0,
        "outlier_min_views": 10000,
        "shorts_max_seconds": 180,
    },
    "report": {"top_n": 10, "use_ai_summary": True},
    "ai": {"model": "claude-sonnet-5-5"},
    "storage": {"db_path": "data/trends.db", "keep_days": 90, "reports_dir": "reports"},
}


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, user_cfg)
    cfg["keywords"] = [str(k).strip() for k in cfg.get("keywords") or [] if str(k).strip()]
    cfg["search"]["max_results"] = max(1, min(int(cfg["search"]["max_results"]), 50))
    cfg["trending"]["max_results"] = max(1, min(int(cfg["trending"]["max_results"]), 200))
    return cfg


@dataclass
class ApiKeys:
    youtube: str | None
    anthropic: str | None


def load_api_keys() -> ApiKeys:
    """APIキーはコードに書かず、環境変数（GitHub Secrets）から読む。"""
    return ApiKeys(
        youtube=os.environ.get("YOUTUBE_API_KEY") or None,
        anthropic=os.environ.get("ANTHROPIC_API_KEY") or None,
    )
