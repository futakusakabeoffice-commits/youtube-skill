"""SQLite への履歴保存、前日比の計算、古いデータの削除。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id      TEXT PRIMARY KEY,
    title         TEXT,
    channel_id    TEXT,
    channel_title TEXT,
    published_at  TEXT,
    duration_sec  INTEGER,
    video_type    TEXT,
    category_id   TEXT,
    tags          TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    video_id       TEXT,
    collected_date TEXT,
    views          INTEGER,
    likes          INTEGER,
    comments       INTEGER,
    subscribers    INTEGER,
    source         TEXT,
    PRIMARY KEY (video_id, collected_date)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(collected_date);
"""


class Storage:
    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def attach_previous(self, records: list[dict], today: date) -> None:
        """各動画の直近の過去スナップショットと比べて、再生数の増加分（前日比）を記録に付ける。"""
        ids = [r["video_id"] for r in records]
        prev: dict[str, tuple[str, int]] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            marks = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"""
                SELECT s.video_id, s.collected_date, s.views FROM snapshots s
                JOIN (SELECT video_id, MAX(collected_date) AS d FROM snapshots
                      WHERE collected_date < ? AND video_id IN ({marks}) GROUP BY video_id) m
                  ON s.video_id = m.video_id AND s.collected_date = m.d
                """,
                [today.isoformat(), *chunk],
            ).fetchall()
            prev.update({vid: (d, views) for vid, d, views in rows})
        for r in records:
            if r["video_id"] in prev:
                d, views = prev[r["video_id"]]
                r["prev_date"] = d
                r["views_diff"] = r["views"] - views

    def save(self, records: list[dict], today: date) -> None:
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                  title=excluded.title, channel_title=excluded.channel_title,
                  duration_sec=excluded.duration_sec, video_type=excluded.video_type,
                  category_id=excluded.category_id, tags=excluded.tags
                """,
                [
                    (
                        r["video_id"], r["title"], r["channel_id"], r["channel_title"],
                        r["published_at"].isoformat(), r["duration_sec"], r["video_type"],
                        r["category_id"], json.dumps(r["tags"], ensure_ascii=False),
                    )
                    for r in records
                ],
            )
            # 同じ日に再実行した場合は上書き
            self.conn.executemany(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        r["video_id"], today.isoformat(), r["views"], r["likes"], r["comments"],
                        r["subscribers"], ",".join(r["sources"]),
                    )
                    for r in records
                ],
            )

    def prune(self, today: date, keep_days: int = 90) -> int:
        cutoff = (today - timedelta(days=keep_days)).isoformat()
        with self.conn:
            deleted = self.conn.execute(
                "DELETE FROM snapshots WHERE collected_date < ?", (cutoff,)
            ).rowcount
            self.conn.execute(
                "DELETE FROM videos WHERE video_id NOT IN (SELECT DISTINCT video_id FROM snapshots)"
            )
        return deleted
