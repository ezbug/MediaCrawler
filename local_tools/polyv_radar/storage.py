from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import CommentRecord, ContentRecord, LeadEvidence


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


class RadarStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS contents (
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                author_hash TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                likes INTEGER NOT NULL DEFAULT 0,
                comments_count INTEGER NOT NULL DEFAULT 0,
                shares INTEGER NOT NULL DEFAULT 0,
                plays INTEGER NOT NULL DEFAULT 0,
                source_keywords TEXT NOT NULL DEFAULT '[]',
                content_type TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (platform, content_id)
            );
            CREATE TABLE IF NOT EXISTS comments (
                platform TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                content_id TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                author_hash TEXT NOT NULL DEFAULT '',
                parent_comment_id TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                likes INTEGER NOT NULL DEFAULT 0,
                source_keyword TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (platform, comment_id)
            );
            CREATE TABLE IF NOT EXISTS run_contents (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                PRIMARY KEY (run_id, platform, content_id)
            );
            CREATE TABLE IF NOT EXISTS run_comments (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                PRIMARY KEY (run_id, platform, comment_id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                platform_status TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS leads (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                comment_id TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                PRIMARY KEY (run_id, platform, content_id, comment_id)
            );
            """
        )
        self.connection.commit()

    def upsert_content(self, item: ContentRecord, run_id: str | None = None) -> bool:
        now = datetime.now().astimezone().isoformat()
        existing = self.connection.execute(
            "SELECT source_keywords FROM contents WHERE platform = ? AND content_id = ?",
            (item.platform, item.content_id),
        ).fetchone()
        keywords = set(item.source_keywords)
        if existing:
            keywords.update(json.loads(existing["source_keywords"] or "[]"))
        values = (
            item.platform,
            item.content_id,
            item.title,
            item.text,
            item.url,
            item.author,
            item.author_hash,
            _iso(item.published_at),
            item.likes,
            item.comments_count,
            item.shares,
            item.plays,
            json.dumps(sorted(keywords), ensure_ascii=False),
            item.content_type,
        )
        if existing:
            self.connection.execute(
                """UPDATE contents SET title=?, text=?, url=?, author=?, author_hash=?, published_at=?,
                   likes=?, comments_count=?, shares=?, plays=?, source_keywords=?, content_type=?, last_seen_at=?
                   WHERE platform=? AND content_id=?""",
                (*values[2:], now, values[0], values[1]),
            )
            self.connection.commit()
            inserted = False
        else:
            self.connection.execute(
                """INSERT INTO contents
                   (platform, content_id, title, text, url, author, author_hash, published_at, likes,
                    comments_count, shares, plays, source_keywords, content_type, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, now, now),
            )
            inserted = True
        if run_id:
            self.connection.execute(
                """INSERT OR IGNORE INTO run_contents(run_id, platform, content_id)
                   VALUES (?, ?, ?)""",
                (run_id, item.platform, item.content_id),
            )
        self.connection.commit()
        return inserted

    def upsert_comment(self, item: CommentRecord, run_id: str | None = None) -> bool:
        now = datetime.now().astimezone().isoformat()
        existing = self.connection.execute(
            "SELECT 1 FROM comments WHERE platform = ? AND comment_id = ?",
            (item.platform, item.comment_id),
        ).fetchone()
        values = (
            item.platform,
            item.comment_id,
            item.content_id,
            item.text,
            item.author,
            item.author_hash,
            item.parent_comment_id,
            _iso(item.published_at),
            item.likes,
            item.source_keyword,
        )
        if existing:
            self.connection.execute(
                """UPDATE comments SET content_id=?, text=?, author=?, author_hash=?, parent_comment_id=?,
                   published_at=?, likes=?, source_keyword=?, last_seen_at=?
                   WHERE platform=? AND comment_id=?""",
                (*values[2:], now, values[0], values[1]),
            )
            self.connection.commit()
            inserted = False
        else:
            self.connection.execute(
                """INSERT INTO comments
                   (platform, comment_id, content_id, text, author, author_hash, parent_comment_id,
                    published_at, likes, source_keyword, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, now, now),
            )
            inserted = True
        if run_id:
            self.connection.execute(
                """INSERT OR IGNORE INTO run_comments(run_id, platform, comment_id)
                   VALUES (?, ?, ?)""",
                (run_id, item.platform, item.comment_id),
            )
        self.connection.commit()
        return inserted

    def clear_run_links(self, run_id: str) -> None:
        self.connection.execute("DELETE FROM run_contents WHERE run_id = ?", (run_id,))
        self.connection.execute("DELETE FROM run_comments WHERE run_id = ?", (run_id,))
        self.connection.commit()

    def save_run(self, run_id: str, status: str, platform_status: dict, started_at: str, finished_at: str) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO runs(run_id, started_at, finished_at, status, platform_status)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, started_at, finished_at, status, json.dumps(platform_status, ensure_ascii=False)),
        )
        self.connection.commit()

    def save_leads(self, run_id: str, leads: Iterable[LeadEvidence]) -> None:
        self.connection.execute("DELETE FROM leads WHERE run_id = ?", (run_id,))
        for lead in leads:
            self.connection.execute(
                "INSERT OR REPLACE INTO leads(run_id, platform, content_id, comment_id, payload) VALUES (?, ?, ?, ?, ?)",
                (run_id, lead.platform, lead.content_id, lead.comment_id, json.dumps(lead.to_dict(), ensure_ascii=False)),
            )
        self.connection.commit()

    def iter_contents(self, run_id: str | None = None) -> list[ContentRecord]:
        if run_id:
            rows = self.connection.execute(
                """SELECT c.* FROM contents c
                   JOIN run_contents rc ON rc.platform = c.platform AND rc.content_id = c.content_id
                   WHERE rc.run_id = ? ORDER BY c.first_seen_at""",
                (run_id,),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM contents ORDER BY first_seen_at").fetchall()
        return [
            ContentRecord(
                platform=row["platform"],
                content_id=row["content_id"],
                title=row["title"],
                text=row["text"],
                url=row["url"],
                author=row["author"],
                author_hash=row["author_hash"],
                published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
                likes=row["likes"],
                comments_count=row["comments_count"],
                shares=row["shares"],
                plays=row["plays"],
                source_keywords=json.loads(row["source_keywords"]),
                content_type=row["content_type"],
            )
            for row in rows
        ]

    def iter_comments(self, run_id: str | None = None) -> list[CommentRecord]:
        if run_id:
            rows = self.connection.execute(
                """SELECT c.* FROM comments c
                   JOIN run_comments rc ON rc.platform = c.platform AND rc.comment_id = c.comment_id
                   WHERE rc.run_id = ? ORDER BY c.first_seen_at""",
                (run_id,),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM comments ORDER BY first_seen_at").fetchall()
        return [
            CommentRecord(
                platform=row["platform"],
                comment_id=row["comment_id"],
                content_id=row["content_id"],
                text=row["text"],
                author=row["author"],
                author_hash=row["author_hash"],
                parent_comment_id=row["parent_comment_id"],
                published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
                likes=row["likes"],
                source_keyword=row["source_keyword"],
            )
            for row in rows
        ]

    def load_leads(self, run_id: str) -> list[LeadEvidence]:
        rows = self.connection.execute("SELECT payload FROM leads WHERE run_id = ?", (run_id,)).fetchall()
        return [LeadEvidence(**json.loads(row["payload"])) for row in rows]

    def count(self, table: str) -> int:
        if table not in {"contents", "comments", "leads", "runs"}:
            raise ValueError(f"Unsupported table: {table}")
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def close(self) -> None:
        self.connection.close()
