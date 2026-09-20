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
                native_comment_id TEXT NOT NULL DEFAULT '',
                native_parent_id TEXT NOT NULL DEFAULT '',
                comment_url TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'comment',
                published_at_raw TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS crawl_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                keyword TEXT NOT NULL DEFAULT '',
                backend TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                duration_seconds REAL NOT NULL DEFAULT 0,
                raw_contents INTEGER NOT NULL DEFAULT 0,
                raw_comments INTEGER NOT NULL DEFAULT 0,
                dedup_contents INTEGER NOT NULL DEFAULT 0,
                dedup_comments INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                fallback_backend TEXT NOT NULL DEFAULT '',
                fallback_reason TEXT NOT NULL DEFAULT ''
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
            CREATE TABLE IF NOT EXISTS comment_locators (
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                comment_id TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'comment',
                content_url TEXT NOT NULL DEFAULT '',
                comment_url TEXT NOT NULL DEFAULT '',
                locator_method TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                native_comment_id TEXT NOT NULL DEFAULT '',
                native_parent_id TEXT NOT NULL DEFAULT '',
                matched_author TEXT NOT NULL DEFAULT '',
                matched_quote TEXT NOT NULL DEFAULT '',
                final_url TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                screenshot_path TEXT NOT NULL DEFAULT '',
                verified_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (run_id, platform, content_id, comment_id)
            );
            CREATE TABLE IF NOT EXISTS legacy_imports (
                import_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'started',
                imported_at TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS lead_status_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                comment_id TEXT NOT NULL DEFAULT '',
                from_status TEXT NOT NULL DEFAULT '',
                to_status TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'system',
                reason TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                event_key TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outreach_queue (
                queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                comment_id TEXT NOT NULL DEFAULT '',
                lead_status TEXT NOT NULL DEFAULT 'approved',
                target_url TEXT NOT NULL DEFAULT '',
                target_author TEXT NOT NULL DEFAULT '',
                draft_text TEXT NOT NULL DEFAULT '',
                locator_status TEXT NOT NULL DEFAULT '',
                url_status TEXT NOT NULL DEFAULT '',
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, platform, content_id, comment_id)
            );
            CREATE TABLE IF NOT EXISTS outreach_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'dry_run',
                status TEXT NOT NULL,
                structured_result TEXT NOT NULL DEFAULT '{}',
                screenshot_path TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                attempted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interaction_events (
                interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT '',
                quote TEXT NOT NULL DEFAULT '',
                observed_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'observed',
                metadata TEXT NOT NULL DEFAULT '{}'
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
                "native_comment_id": "TEXT NOT NULL DEFAULT ''",
                "native_parent_id": "TEXT NOT NULL DEFAULT ''",
                "comment_url": "TEXT NOT NULL DEFAULT ''",
                "source_type": "TEXT NOT NULL DEFAULT 'comment'",
                "published_at_raw": "TEXT NOT NULL DEFAULT ''",
            },
            "lead_status_events": {
                "event_key": "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in migrations.items():
            present = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in present:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        self._backfill_status_event_keys()

    def _backfill_status_event_keys(self) -> None:
        rows = self.connection.execute(
            "SELECT event_id, run_id, platform, content_id, comment_id, to_status, metadata FROM lead_status_events WHERE event_key = ''"
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            legacy_id = str(metadata.get("legacy_id", ""))
            event_key = self._status_event_key(
                row["run_id"], row["platform"], row["content_id"], row["comment_id"], row["to_status"], legacy_id
            )
            self.connection.execute(
                "UPDATE lead_status_events SET event_key = ? WHERE event_id = ?",
                (event_key, row["event_id"]),
            )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_lead_status_events_event_key ON lead_status_events(event_key)"
        )

    @staticmethod
    def _status_event_key(
        run_id: str,
        platform: str,
        content_id: str,
        comment_id: str,
        to_status: str,
        legacy_id: str = "",
    ) -> str:
        return "|".join(str(value or "") for value in (run_id, platform, content_id, comment_id, to_status, legacy_id))

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
            item.native_comment_id,
            item.native_parent_id,
            item.comment_url,
            item.source_type,
            item.published_at_raw,
        )
        if existing:
            self.connection.execute(
                """UPDATE comments SET content_id=?, text=?, author=?, author_hash=?, parent_comment_id=?,
                   author_id=?, author_url=?, published_at=?, likes=?, source_keyword=?, native_comment_id=?,
                   native_parent_id=?, comment_url=?, source_type=?, published_at_raw=?, last_seen_at=?
                   WHERE platform=? AND comment_id=?""",
                (
                    values[2], values[3], values[4], values[5], values[8],
                    values[6], values[7], values[9], values[10], values[11], values[12], values[13],
                    values[14], values[15], values[16], now,
                    values[0], values[1],
                ),
            )
            self.connection.commit()
            inserted = False
        else:
            self.connection.execute(
                """INSERT INTO comments
                   (platform, comment_id, content_id, text, author, author_hash, author_id, author_url,
                    parent_comment_id, published_at, likes, source_keyword, native_comment_id,
                    native_parent_id, comment_url, source_type, published_at_raw, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

    def save_crawl_task(self, task: dict) -> None:
        self.connection.execute(
            """INSERT INTO crawl_tasks
               (run_id, platform, keyword, backend, started_at, finished_at, duration_seconds,
                raw_contents, raw_comments, dedup_contents, dedup_comments, status, error,
                fallback_backend, fallback_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.get("run_id", ""), task.get("platform", ""), task.get("keyword", ""),
                task.get("backend", ""), task.get("started_at", ""), task.get("finished_at", ""),
                float(task.get("duration_seconds", 0) or 0), int(task.get("raw_contents", 0) or 0),
                int(task.get("raw_comments", 0) or 0), int(task.get("dedup_contents", 0) or 0),
                int(task.get("dedup_comments", 0) or 0), task.get("status", ""), task.get("error", ""),
                task.get("fallback_backend", ""), task.get("fallback_reason", ""),
            ),
        )
        self.connection.commit()

    def load_crawl_tasks(self, run_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM crawl_tasks WHERE run_id = ? ORDER BY task_id", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def save_comment_locator(self, locator: dict) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO comment_locators
               (run_id, platform, content_id, comment_id, source_type, content_url, comment_url,
                locator_method, status, native_comment_id, native_parent_id, matched_author,
                matched_quote, final_url, reason, screenshot_path, verified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                locator.get("run_id", ""), locator.get("platform", ""), locator.get("content_id", ""),
                locator.get("comment_id", ""), locator.get("source_type", "comment"),
                locator.get("content_url", ""), locator.get("comment_url", ""),
                locator.get("locator_method", ""), locator.get("status", "pending"),
                locator.get("native_comment_id", ""), locator.get("native_parent_id", ""),
                locator.get("matched_author", ""), locator.get("matched_quote", ""),
                locator.get("final_url", ""), locator.get("reason", ""),
                locator.get("screenshot_path", ""), locator.get("verified_at", ""),
            ),
        )
        self.connection.commit()

    def load_comment_locators(self, run_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM comment_locators WHERE run_id = ? ORDER BY platform, content_id, comment_id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def clear_comment_locators(self, run_id: str) -> None:
        self.connection.execute("DELETE FROM comment_locators WHERE run_id = ?", (run_id,))
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
                native_comment_id=row["native_comment_id"],
                native_parent_id=row["native_parent_id"],
                comment_url=row["comment_url"],
                source_type=row["source_type"] or "comment",
                published_at_raw=row["published_at_raw"],
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

    def save_legacy_import(self, payload: dict) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO legacy_imports
               (import_id, session_id, source_path, destination_path, manifest_path,
                row_count, status, imported_at, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.get("import_id", ""), payload.get("session_id", ""),
                payload.get("source_path", ""), payload.get("destination_path", ""),
                payload.get("manifest_path", ""), int(payload.get("row_count", 0) or 0),
                payload.get("status", "started"), payload.get("imported_at", ""), payload.get("error", ""),
            ),
        )
        self.connection.commit()

    def add_status_event(
        self,
        run_id: str,
        platform: str,
        content_id: str,
        comment_id: str,
        to_status: str,
        from_status: str = "",
        actor: str = "system",
        reason: str = "",
        metadata: dict | None = None,
    ) -> None:
        metadata = metadata or {}
        event_key = self._status_event_key(
            run_id, platform, content_id, comment_id, to_status, str(metadata.get("legacy_id", ""))
        )
        existing = self.connection.execute(
            "SELECT 1 FROM lead_status_events WHERE event_key = ? LIMIT 1",
            (event_key,),
        ).fetchone()
        if existing:
            return
        self.connection.execute(
            """INSERT INTO lead_status_events
               (run_id, platform, content_id, comment_id, from_status, to_status,
                actor, reason, metadata, event_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, platform, content_id, comment_id, from_status, to_status,
                actor, reason, json.dumps(metadata, ensure_ascii=False), event_key,
                datetime.now().astimezone().isoformat(),
            ),
        )
        self.connection.commit()

    def load_status_events(self, run_id: str, platform: str = "", content_id: str = "") -> list[dict]:
        query = "SELECT * FROM lead_status_events WHERE run_id = ?"
        params: list[str] = [run_id]
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if content_id:
            query += " AND content_id = ?"
            params.append(content_id)
        query += " ORDER BY event_id"
        return [dict(row) for row in self.connection.execute(query, params).fetchall()]

    def count_status_events(self, run_id: str, distinct: bool = True) -> int:
        if distinct:
            query = """SELECT COUNT(DISTINCT CASE WHEN event_key != '' THEN event_key ELSE CAST(event_id AS TEXT) END)
                       FROM lead_status_events WHERE run_id = ?"""
        else:
            query = "SELECT COUNT(*) FROM lead_status_events WHERE run_id = ?"
        return int(self.connection.execute(query, (run_id,)).fetchone()[0])

    def queue_outreach(self, payload: dict) -> int:
        now = datetime.now().astimezone().isoformat()
        self.connection.execute(
            """INSERT INTO outreach_queue
               (run_id, platform, content_id, comment_id, lead_status, target_url,
                target_author, draft_text, locator_status, url_status, approved_by,
                approved_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, platform, content_id, comment_id) DO UPDATE SET
                lead_status=excluded.lead_status, target_url=excluded.target_url,
                target_author=excluded.target_author, draft_text=excluded.draft_text,
                locator_status=excluded.locator_status, url_status=excluded.url_status,
                approved_by=excluded.approved_by, approved_at=excluded.approved_at,
                updated_at=excluded.updated_at""",
            (
                payload.get("run_id", ""), payload.get("platform", ""), payload.get("content_id", ""),
                payload.get("comment_id", ""), payload.get("lead_status", "approved"),
                payload.get("target_url", ""), payload.get("target_author", ""), payload.get("draft_text", ""),
                payload.get("locator_status", ""), payload.get("url_status", ""),
                payload.get("approved_by", ""), payload.get("approved_at", ""),
                payload.get("created_at", now), payload.get("updated_at", now),
            ),
        )
        row = self.connection.execute(
            """SELECT queue_id FROM outreach_queue
               WHERE run_id = ? AND platform = ? AND content_id = ? AND comment_id = ?""",
            (payload.get("run_id", ""), payload.get("platform", ""), payload.get("content_id", ""), payload.get("comment_id", "")),
        ).fetchone()
        self.connection.commit()
        return int(row[0])

    def load_outreach_queue(self, run_id: str = "", statuses: Iterable[str] = ()) -> list[dict]:
        query = "SELECT * FROM outreach_queue WHERE 1=1"
        params: list[str] = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        status_values = [str(item) for item in statuses if str(item)]
        if status_values:
            placeholders = ",".join("?" for _ in status_values)
            query += f" AND lead_status IN ({placeholders})"
            params.extend(status_values)
        query += " ORDER BY queue_id"
        return [dict(row) for row in self.connection.execute(query, params).fetchall()]

    def update_outreach_queue_status(self, queue_id: int, status: str) -> None:
        self.connection.execute(
            "UPDATE outreach_queue SET lead_status = ?, updated_at = ? WHERE queue_id = ?",
            (status, datetime.now().astimezone().isoformat(), int(queue_id)),
        )
        self.connection.commit()

    def save_outreach_attempt(self, payload: dict) -> int:
        self.connection.execute(
            """INSERT INTO outreach_attempts
               (queue_id, run_id, platform, mode, status, structured_result,
                screenshot_path, error, attempted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(payload.get("queue_id", 0) or 0), payload.get("run_id", ""), payload.get("platform", ""),
                payload.get("mode", "dry_run"), payload.get("status", "failed"),
                json.dumps(payload.get("structured_result", {}), ensure_ascii=False),
                payload.get("screenshot_path", ""), payload.get("error", ""),
                payload.get("attempted_at", datetime.now().astimezone().isoformat()),
            ),
        )
        attempt_id = int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        self.connection.commit()
        return attempt_id

    def count_verified_attempts_today(self, day: str) -> int:
        return int(self.connection.execute(
            "SELECT COUNT(*) FROM outreach_attempts WHERE status = 'submitted_verified' AND attempted_at LIKE ?",
            (f"{day}%",),
        ).fetchone()[0])

    def save_interaction_event(self, payload: dict) -> int:
        self.connection.execute(
            """INSERT INTO interaction_events
               (run_id, platform, source_url, author, event_type, quote, observed_at, status, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.get("run_id", ""), payload.get("platform", ""), payload.get("source_url", ""),
                payload.get("author", ""), payload.get("event_type", ""), payload.get("quote", ""),
                payload.get("observed_at", datetime.now().astimezone().isoformat()), payload.get("status", "observed"),
                json.dumps(payload.get("metadata", {}), ensure_ascii=False),
            ),
        )
        interaction_id = int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        self.connection.commit()
        return interaction_id

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
        if table not in {"contents", "comments", "leads", "runs", "crawl_tasks", "profiles", "profile_posts", "external_evidence", "lead_assessments", "comment_locators", "legacy_imports", "lead_status_events", "outreach_queue", "outreach_attempts", "interaction_events"}:
            raise ValueError(f"Unsupported table: {table}")
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def close(self) -> None:
        self.connection.close()
