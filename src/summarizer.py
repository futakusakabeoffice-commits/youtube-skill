"""Claude API による傾向の要約と企画案の生成。

失敗しても例外は外に出さず None を返し、数値レポートだけが出力されるようにする。
"""

from __future__ import annotations

import json
import logging

import anthropic

log = logging.getLogger(__name__)

PROMPT = """あなたはYouTubeの企画アナリストです。
以下は日本のYouTubeで今日伸びている動画のデータです。
1. 目立った傾向を3〜5行で要約してください
2. 伸びている動画の共通点を、タイトル・長さ・テーマの観点で挙げてください
3. 「{keywords}」のジャンルで、個人が作れる企画案を3つ提案してください
データにない推測は「推測」と明記してください。

<data>
{data_json}
</data>"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "今日の傾向のサマリー（3〜5行）"},
        "common_features": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "length": {"type": "string"},
                "theme": {"type": "string"},
            },
            "required": ["title", "length", "theme"],
            "additionalProperties": False,
        },
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "動画タイトル案"},
                    "concept": {"type": "string", "description": "企画の中身と、伸びると考える根拠"},
                    "format": {"type": "string", "description": "ショート / 長尺 と想定の長さ"},
                },
                "required": ["title", "concept", "format"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "common_features", "ideas"],
    "additionalProperties": False,
}


def _video_brief(r: dict) -> dict:
    return {
        "title": r["title"],
        "channel": r["channel_title"],
        "subscribers": r["subscribers"],
        "views": r["views"],
        "views_per_subscriber": round(r["ratio"], 2) if r["ratio"] is not None else None,
        "views_per_hour": round(r["views_per_hour"]),
        "duration_sec": r["duration_sec"],
        "type": r["video_type"],
        "category": r["category_name"],
        "hours_since_published": round(r["hours_since"]),
    }


def build_payload(analysis: dict, keywords: list[str]) -> dict:
    return {
        "target_keywords": keywords,
        "outliers_by_views_per_subscriber": [_video_brief(r) for r in analysis["outliers"]],
        "fastest_growing_by_views_per_hour": [_video_brief(r) for r in analysis["velocity"]],
        "keyword_top_videos": {
            kw: [_video_brief(r) for r in recs[:5]] for kw, recs in analysis["by_keyword"].items()
        },
        "trending_stats": analysis["trending_stats"],
        "title_stats": analysis["title_stats"],
    }


def summarize(analysis: dict, keywords: list[str], api_key: str, model: str) -> dict | None:
    payload = build_payload(analysis, keywords)
    prompt = PROMPT.format(
        keywords="」「".join(keywords) or "指定なし",
        data_json=json.dumps(payload, ensure_ascii=False, indent=1, default=str),
    )
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            # 安全分類器による辞退時は、推奨モデルでサーバー側が自動再実行する
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        log.error("AI要約をスキップ: ANTHROPIC_API_KEY が無効です")
        return None
    except anthropic.RateLimitError:
        log.error("AI要約をスキップ: レート制限に達しました")
        return None
    except anthropic.APIStatusError as e:
        log.error("AI要約をスキップ: APIエラー HTTP %s %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError as e:
        log.error("AI要約をスキップ: 通信エラー %s", e)
        return None

    if response.stop_reason == "refusal":
        log.error("AI要約をスキップ: モデルが応答を辞退しました")
        return None
    if response.stop_reason == "max_tokens":
        log.error("AI要約をスキップ: 出力が上限で途切れました")
        return None

    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.error("AI要約をスキップ: 応答をJSONとして読めませんでした")
        return None
