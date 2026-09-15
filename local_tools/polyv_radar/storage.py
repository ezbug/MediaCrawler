from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import (
    CommentRecord,
    ContentRecord,
    ExternalEvidence,
    LeadAssessment,
    LeadEvidence,
    ProfilePost,
    ProfileSnapshot,
)


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
                author_id TEXT NOT NULL DEFAULT '',
                author_url TEXT NOT NULL DEFAULT '',
                creator_url TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                likes INTEGER NOT NULL DEFAULT 0,
                comments_count INTEGER NOT NULL DEFAULT 0,
                shares INTEGER NOT NULL DEFAULT 0,
                plays INTEGER NOT NULL DEFAULT 0,
                source_keywords TEXT NOT NULL DEFAULT '[]',
                content_type TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
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
                author_id TEXT NOT NULL DEFAULT '',
                author_url TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS run_content_sources (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                source_keyword TEXT NOT NULL,
                PRIMARY KEY (run_id, platform, content_id, source_keyword)
            );
            CREATE TABLE IF NOT EXISTS run_comments (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                PRIMARY KEY (run_id, platform, comment_id)
            );
            CREATE TABLE IF NOT EXISTS run_comment_sources (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                source_keyword TEXT NOT NULL,
                PRIMARY KEY (run_id, platform, comment_id, source_keyword)
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
            CREATE TABLE IF NOT EXISTS profiles (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                author_id TEXT NOT NULL,
                author_url TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                bio TEXT NOT NULL DEFAULT '',
                verified INTEGER NOT NULL DEFAULT 0,
                company TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                identity_confidence TEXT NOT NULL DEFAULT 'low',
                source_urls TEXT NOT NULL DEFAULT '[]',
                captured_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (run_id, platform, author_id)
            );
            CREATE TABLE IF NOT EXISTS profile_posts (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                author_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (run_id, platform, author_id, post_id)
            );
            CREATE TABLE IF NOT EXISTS external_evidence (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                author_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                snippet TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                match_confidence TEXT NOT NULL DEFAULT 'low',
                PRIMARY KEY (run_id, platform, author_id, source_url)
            );
            CREATE TABLE IF NOT EXISTS lead_assessments (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                comment_id TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                PRIMARY KEY (run_id, platform, content_id, comment_id)
            );
            """
        )
        self._migrate_legacy_columns()
        self.connection.commit()

    def _migrate_legacy_columns(self) -> None:
        migrations = {
            "contents": {
                "author_id": "TEXT NOT NULL DEFAULT ''",
                "author_url": "TEXT NOT NULL DEFAULT ''",
                "creator_url": "TEXT NOT NULL DEFAULT ''",
                "tags": "TEXT NOT NULL DEFAULT '[]'",
            },
            "comments": {
                "author_id": "TEXT NOT NULL DEFAULT ''",
                "author_url": "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in migrations.items():
            present = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in present:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

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
            item.author_id,
            item.author_url,
            item.creator_url,
            _iso(item.published_at),
            item.likes,
            item.comments_count,
            item.shares,
            item.plays,
            json.dumps(sorted(keywords), ensure_ascii=False),
            item.content_type,
            json.dumps(item.tags, ensure_ascii=False),
        )
        if existing:
            self.connection.execute(
                """UPDATE contents SET title=?, text=?, url=?, author=?, author_hash=?, author_id=?, author_url=?,
                   creator_url=?, published_at=?, likes=?, comments_count=?, shares=?, plays=?, source_keywords=?,
                   content_type=?, tags=?, last_seen_at=?
                   WHERE platform=? AND content_id=?""",
                (*values[2:], now, values[0], values[1]),
            )
            self.connection.commit()
            inserted = False
        else:
            self.connection.execute(
                """INSERT INTO contents
                   (platform, content_id, title, text, url, author, author_hash, author_id, author_url,
                    creator_url, published_at, likes, comments_count, shares, plays, source_keywords,
                    content_type, tags, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, now, now),
            )
            inserted = True
        if run_id:
            self.connection.execute(
                """INSERT OR IGNORE INTO run_contents(run_id, platform, content_id)
                   VALUES (?, ?, ?)""",
                (run_id, item.platform, item.content_id),
            )
            for keyword in item.source_keywords:
                self.connection.execute(
                    """INSERT OR IGNORE INTO run_content_sources
                       (run_id, platform, content_id, source_keyword)
                       VALUES (?, ?, ?, ?)""",
                    (run_id, item.platform, item.content_id, keyword),
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
            item.author_id,
            item.author_url,
            item.parent_comment_id,
            _iso(item.published_at),
            item.likes,
            item.source_keyword,
        )
        if existing:
            self.connection.execute(
                """UPDATE comments SET content_id=?, text=?, author=?, author_hash=?, parent_comment_id=?,
                   author_id=?, author_url=?, published_at=?, likes=?, source_keyword=?, last_seen_at=?
                   WHERE platform=? AND comment_id=?""",
                (
                    values[2], values[3], values[4], values[5], values[8],
                    values[6], values[7], values[9], values[10], values[11], now,
                    values[0], values[1],
                ),
            )
            self.connection.commit()
            inserted = False
        else:
            self.connection.execute(
                """INSERT INTO comments
                   (platform, comment_id, content_id, text, author, author_hash, author_id, author_url,
                    parent_comment_id, published_at, likes, source_keyword, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, now, now),
            )
            inserted = True
        if run_id:
            self.connection.execute(
                """INSERT OR IGNORE INTO run_comments(run_id, platform, comment_id)
                   VALUES (?, ?, ?)""",
                (run_id, item.platform, item.comment_id),
            )
            if item.source_keyword:
                self.connection.execute(
                    """INSERT OR IGNORE INTO run_comment_sources
                       (run_id, platform, comment_id, source_keyword)
                       VALUES (?, ?, ?, ?)""",
                    (run_id, item.platform, item.comment_id, item.source_keyword),
                )
        self.connection.commit()
        return inserted

    def clear_run_links(self, run_id: str) -> None:
        self.connection.execute("DELETE FROM run_contents WHERE run_id = ?", (run_id,))
        self.connection.execute("DELETE FROM run_content_sources WHERE run_id = ?", (run_id,))
        self.connection.execute("DELETE FROM run_comments WHERE run_id = ?", (run_id,))
        self.connection.execute("DELETE FROM run_comment_sources WHERE run_id = ?", (run_id,))
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
        result = []
        for row in rows:
            source_rows = self.connection.execute(
                """SELECT source_keyword FROM run_content_sources
                   WHERE run_id = ? AND platform = ? AND content_id = ?
                   ORDER BY source_keyword""",
                (run_id, row["platform"], row["content_id"]),
            ).fetchall() if run_id else []
            source_keywords = [item["source_keyword"] for item in source_rows] or json.loads(row["source_keywords"])
            result.append(ContentRecord(
                platform=row["platform"],
                content_id=row["content_id"],
                title=row["title"],
                text=row["text"],
                url=row["url"],
                author=row["author"],
                author_hash=row["author_hash"],
                author_id=row["author_id"],
                author_url=row["author_url"],
                creator_url=row["creator_url"],
                published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
                likes=row["likes"],
                comments_count=row["comments_count"],
                shares=row["shares"],
                plays=row["plays"],
                source_keywords=source_keywords,
                content_type=row["content_type"],
                tags=json.loads(row["tags"] or "[]"),
            )
            )
        return result

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
        result = []
        for row in rows:
            source_rows = self.connection.execute(
                """SELECT source_keyword FROM run_comment_sources
                   WHERE run_id = ? AND platform = ? AND comment_id = ?
                   ORDER BY source_keyword""",
                (run_id, row["platform"], row["comment_id"]),
            ).fetchall() if run_id else []
            source_keyword = source_rows[0]["source_keyword"] if source_rows else row["source_keyword"]
            result.append(CommentRecord(
                platform=row["platform"],
                comment_id=row["comment_id"],
                content_id=row["content_id"],
                text=row["text"],
                author=row["author"],
                author_hash=row["author_hash"],
                author_id=row["author_id"],
                author_url=row["author_url"],
                parent_comment_id=row["parent_comment_id"],
                published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
                likes=row["likes"],
                source_keyword=source_keyword,
            )
            )
        return result

    def load_leads(self, run_id: str) -> list[LeadEvidence]:
        rows = self.connection.execute("SELECT payload FROM leads WHERE run_id = ?", (run_id,)).fetchall()
        return [LeadEvidence(**json.loads(row["payload"])) for row in rows]

    def upsert_profile(self, profile: ProfileSnapshot) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO profiles
               (run_id, platform, author_id, author_url, display_name, bio, verified, company, role,
                identity_confidence, source_urls, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile.run_id, profile.platform, profile.author_id, profile.author_url, profile.display_name,
                profile.bio, int(profile.verified), profile.company, profile.role,
                profile.identity_confidence, json.dumps(profile.source_urls, ensure_ascii=False), profile.captured_at,
            ),
        )
        self.connection.commit()

    def clear_enrichment(self, run_id: str) -> None:
        """Clear only derived profile evidence for one run before re-enrichment."""
        for table in ("external_evidence", "profile_posts", "profiles"):
            self.connection.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
        self.connection.commit()

    def upsert_profile_post(self, post: ProfilePost) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO profile_posts
               (run_id, platform, author_id, post_id, url, title, text, published_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (post.run_id, post.platform, post.author_id, post.post_id, post.url, post.title, post.text, post.published_at),
        )
        self.connection.commit()

    def upsert_external_evidence(self, evidence: ExternalEvidence) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO external_evidence
               (run_id, platform, author_id, source_url, source_type, title, snippet, published_at, match_confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evidence.run_id, evidence.platform, evidence.author_id, evidence.source_url, evidence.source_type,
                evidence.title, evidence.snippet, evidence.published_at, evidence.match_confidence,
            ),
        )
        self.connection.commit()

    def update_profile_identity(
        self,
        run_id: str,
        platform: str,
        author_id: str,
        identity_confidence: str,
        source_urls: Iterable[str],
    ) -> None:
        self.connection.execute(
            """UPDATE profiles SET identity_confidence = ?, source_urls = ?
               WHERE run_id = ? AND platform = ? AND author_id = ?""",
            (
                identity_confidence,
                json.dumps(sorted({str(url) for url in source_urls if str(url)}), ensure_ascii=False),
                run_id,
                platform,
                author_id,
            ),
        )
        self.connection.commit()

    def save_assessments(self, assessments: Iterable[LeadAssessment]) -> None:
        for assessment in assessments:
            self.connection.execute(
                """INSERT OR REPLACE INTO lead_assessments
                   (run_id, platform, content_id, comment_id, payload) VALUES (?, ?, ?, ?, ?)""",
                (
                    assessment.run_id, assessment.platform, assessment.content_id, assessment.comment_id,
                    json.dumps(assessment.__dict__, ensure_ascii=False),
                ),
            )
        self.connection.commit()

    def load_profiles(self, run_id: str) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM profiles WHERE run_id = ?", (run_id,)).fetchall()
        return [dict(row) | {"source_urls": json.loads(row["source_urls"] or "[]")} for row in rows]

    def load_external_evidence(self, run_id: str) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM external_evidence WHERE run_id = ?", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def load_profile_posts(self, run_id: str) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM profile_posts WHERE run_id = ?", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def count(self, table: str) -> int:
        if table not in {"contents", "comments", "leads", "runs", "profiles", "profile_posts", "external_evidence", "lead_assessments"}:
            raise ValueError(f"Unsupported table: {table}")
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def close(self) -> None:
        self.connection.close()
