"""Independent SQLite storage for ZigoAI discovery data.

The POLYV store deliberately remains a separate schema and file.  This store
only persists ZigoAI raw observations, screening decisions and verification
evidence; it has no dispatch or outreach tables.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _fallback_id(row: dict, prefix: str) -> str:
    payload = "|".join(str(row.get(key, "")) for key in ("platform", "content_id", "author_id", "author", "text", "source_keyword"))
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


class ZigoStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def initialize(self) -> None:
        self.connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS zigo_runs (
                run_id TEXT PRIMARY KEY,
                product_domain TEXT NOT NULL CHECK(product_domain IN ('sales_agent', 'geo')),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'ingested',
                platform_status TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS zigo_contents (
                product_domain TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                author_id TEXT NOT NULL DEFAULT '',
                author_url TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'post',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (product_domain, platform, content_id)
            );
            CREATE TABLE IF NOT EXISTS zigo_content_sources (
                product_domain TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                source_keyword TEXT NOT NULL,
                PRIMARY KEY (product_domain, platform, content_id, source_keyword)
            );
            CREATE TABLE IF NOT EXISTS zigo_comments (
                product_domain TEXT NOT NULL,
                platform TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                content_id TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                author_id TEXT NOT NULL DEFAULT '',
                author_url TEXT NOT NULL DEFAULT '',
                parent_comment_id TEXT NOT NULL DEFAULT '',
                native_comment_id TEXT NOT NULL DEFAULT '',
                native_parent_id TEXT NOT NULL DEFAULT '',
                comment_url TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'comment',
                published_at TEXT NOT NULL DEFAULT '',
                published_at_raw TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (product_domain, platform, comment_id)
            );
            CREATE TABLE IF NOT EXISTS zigo_run_contents (
                run_id TEXT NOT NULL,
                product_domain TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                PRIMARY KEY (run_id, product_domain, platform, content_id)
            );
            CREATE TABLE IF NOT EXISTS zigo_run_comments (
                run_id TEXT NOT NULL,
                product_domain TEXT NOT NULL,
                platform TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                PRIMARY KEY (run_id, product_domain, platform, comment_id)
            );
            CREATE TABLE IF NOT EXISTS zigo_candidates (
                run_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                product_domain TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT '',
                content_id TEXT NOT NULL DEFAULT '',
                comment_id TEXT NOT NULL DEFAULT '',
                decision TEXT NOT NULL DEFAULT '',
                rule_score INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                PRIMARY KEY (run_id, candidate_id)
            );
            CREATE TABLE IF NOT EXISTS zigo_checks (
                run_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                PRIMARY KEY (run_id, candidate_id)
            );
            CREATE TABLE IF NOT EXISTS zigo_keyword_sources (
                version TEXT NOT NULL,
                product_domain TEXT NOT NULL,
                keyword TEXT NOT NULL,
                category TEXT NOT NULL,
                derivation TEXT NOT NULL,
                source_id TEXT NOT NULL DEFAULT '',
                source_pages TEXT NOT NULL DEFAULT '[]',
                source_sha256 TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (version, product_domain, keyword, category)
            );
            CREATE TABLE IF NOT EXISTS zigo_events (
                event_key TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS zigo_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def _upsert_run(self, run_id: str, product_domain: str, now: str) -> None:
        self.connection.execute(
            """INSERT INTO zigo_runs(run_id, product_domain, started_at, finished_at, status)
               VALUES(?, ?, ?, ?, 'ingested')
               ON CONFLICT(run_id) DO UPDATE SET finished_at=excluded.finished_at""",
            (run_id, product_domain, now, now),
        )

    def ingest_run(
        self,
        run_id: str,
        product_domain: str,
        records: Iterable[dict],
        screened: Iterable[dict],
        checks: Iterable[dict] | None = None,
        keyword_sources: Iterable[dict] | None = None,
    ) -> dict:
        if product_domain not in {"sales_agent", "geo"}:
            raise ValueError(f"unsupported ZigoAI product domain: {product_domain}")
        self.initialize()
        now = _now()
        inserted_contents = inserted_comments = 0
        self._upsert_run(run_id, product_domain, now)
        for row in records:
            source_type = str(row.get("source_type") or "post")
            platform = str(row.get("platform") or "")
            content_id = str(row.get("content_id") or _fallback_id(row, "content"))
            source_keyword = str(row.get("source_keyword") or "")
            if source_type in {"comment", "reply"}:
                comment_id = str(row.get("comment_id") or row.get("native_comment_id") or _fallback_id(row, "comment"))
                existing = self.connection.execute(
                    "SELECT 1 FROM zigo_comments WHERE product_domain=? AND platform=? AND comment_id=?",
                    (product_domain, platform, comment_id),
                ).fetchone()
                self.connection.execute(
                    """INSERT INTO zigo_comments(
                        product_domain, platform, comment_id, content_id, text, author, author_id,
                        author_url, parent_comment_id, native_comment_id, native_parent_id, comment_url,
                        source_type, published_at, published_at_raw, first_seen_at, last_seen_at, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_domain, platform, comment_id) DO UPDATE SET
                        text=excluded.text, author=excluded.author, author_id=excluded.author_id,
                        author_url=excluded.author_url, last_seen_at=excluded.last_seen_at,
                        payload=excluded.payload""",
                    (product_domain, platform, comment_id, content_id, str(row.get("text") or row.get("quote") or ""),
                     str(row.get("author") or ""), str(row.get("author_id") or ""), str(row.get("author_url") or ""),
                     str(row.get("parent_comment_id") or ""), str(row.get("native_comment_id") or ""),
                     str(row.get("native_parent_id") or ""), str(row.get("comment_url") or ""), source_type,
                     str(row.get("published_at") or ""), str(row.get("published_at_raw") or ""), now, now, _json(row)),
                )
                inserted_comments += int(existing is None)
                self.connection.execute(
                    "INSERT OR IGNORE INTO zigo_run_comments(run_id, product_domain, platform, comment_id) VALUES(?, ?, ?, ?)",
                    (run_id, product_domain, platform, comment_id),
                )
            else:
                existing = self.connection.execute(
                    "SELECT 1 FROM zigo_contents WHERE product_domain=? AND platform=? AND content_id=?",
                    (product_domain, platform, content_id),
                ).fetchone()
                self.connection.execute(
                    """INSERT INTO zigo_contents(
                        product_domain, platform, content_id, title, text, url, author, author_id,
                        author_url, published_at, source_type, first_seen_at, last_seen_at, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_domain, platform, content_id) DO UPDATE SET
                        title=excluded.title, text=excluded.text, url=excluded.url,
                        author=excluded.author, author_id=excluded.author_id,
                        author_url=excluded.author_url, last_seen_at=excluded.last_seen_at,
                        payload=excluded.payload""",
                    (product_domain, platform, content_id, str(row.get("title") or row.get("content_title") or ""),
                     str(row.get("text") or ""), str(row.get("url") or ""), str(row.get("author") or ""),
                     str(row.get("author_id") or ""), str(row.get("author_url") or ""),
                     str(row.get("published_at") or ""), source_type, now, now, _json(row)),
                )
                inserted_contents += int(existing is None)
                self.connection.execute(
                    "INSERT OR IGNORE INTO zigo_run_contents(run_id, product_domain, platform, content_id) VALUES(?, ?, ?, ?)",
                    (run_id, product_domain, platform, content_id),
                )
                if source_keyword:
                    self.connection.execute(
                        "INSERT OR IGNORE INTO zigo_content_sources(product_domain, platform, content_id, source_keyword) VALUES(?, ?, ?, ?)",
                        (product_domain, platform, content_id, source_keyword),
                    )

        for row in screened:
            candidate_id = str(row.get("candidate_id") or _fallback_id(row, "candidate"))
            self.connection.execute(
                """INSERT INTO zigo_candidates(run_id, candidate_id, product_domain, platform, content_id,
                   comment_id, decision, rule_score, payload) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, candidate_id) DO UPDATE SET decision=excluded.decision,
                   rule_score=excluded.rule_score, payload=excluded.payload""",
                (run_id, candidate_id, product_domain, str(row.get("platform") or ""), str(row.get("content_id") or ""),
                 str(row.get("comment_id") or ""), str(row.get("decision") or ""), int(row.get("rule_score") or 0), _json(row)),
            )
        for row in checks or []:
            candidate_id = str(row.get("candidate_id") or "")
            if not candidate_id:
                continue
            self.connection.execute(
                """INSERT INTO zigo_checks(run_id, candidate_id, status, payload) VALUES(?, ?, ?, ?)
                   ON CONFLICT(run_id, candidate_id) DO UPDATE SET status=excluded.status, payload=excluded.payload""",
                (run_id, candidate_id, str(row.get("status") or ""), _json(row)),
            )
        for row in keyword_sources or []:
            self.connection.execute(
                """INSERT OR REPLACE INTO zigo_keyword_sources(
                   version, product_domain, keyword, category, derivation, source_id, source_pages, source_sha256)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(row.get("version") or ""), str(row.get("product_domain") or product_domain),
                 str(row.get("keyword") or ""), str(row.get("category") or ""), str(row.get("derivation") or ""),
                 str(row.get("source_id") or ""), _json(row.get("source_pages") or []), str(row.get("source_sha256") or "")),
            )
        event_key = f"{run_id}:ingest:{product_domain}"
        event = self.connection.execute(
            "INSERT OR IGNORE INTO zigo_events(event_key, run_id, event_type, created_at, payload) VALUES(?, ?, ?, ?, ?)",
            (event_key, run_id, "run_ingested", now, _json({"product_domain": product_domain})),
        )
        changed = event.rowcount > 0
        if changed:
            current = self.connection.execute("SELECT value FROM zigo_meta WHERE key='revision'").fetchone()
            revision = int(current[0]) + 1 if current else 1
            self.connection.execute("INSERT OR REPLACE INTO zigo_meta(key, value) VALUES('revision', ?)", (str(revision),))
        self.connection.commit()
        return {"run_id": run_id, "product_domain": product_domain, "inserted_contents": inserted_contents,
                "inserted_comments": inserted_comments, "changed": changed}

    def save_keyword_sources(self, rows: Iterable[dict]) -> int:
        self.initialize()
        saved = 0
        for row in rows:
            self.connection.execute(
                """INSERT OR REPLACE INTO zigo_keyword_sources(
                   version, product_domain, keyword, category, derivation, source_id, source_pages, source_sha256)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(row.get("version") or ""), str(row.get("product_domain") or ""),
                 str(row.get("keyword") or ""), str(row.get("category") or ""), str(row.get("derivation") or ""),
                 str(row.get("source_id") or ""), _json(row.get("source_pages") or []), str(row.get("source_sha256") or "")),
            )
            saved += 1
        self.connection.commit()
        return saved

    def summary(self, product_domain: str | None = None) -> dict:
        self.initialize()
        direct_clause = " WHERE product_domain = ?" if product_domain else ""
        direct_params = (product_domain,) if product_domain else ()
        run_clause = " AND r.product_domain = ?" if product_domain else ""
        run_params = (product_domain,) if product_domain else ()
        def direct_count(table: str) -> int:
            return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}{direct_clause}", direct_params).fetchone()[0])
        def linked_count(table: str, column: str) -> int:
            return int(self.connection.execute(
                f"SELECT COUNT(DISTINCT rc.product_domain || '|' || rc.platform || '|' || rc.{column}) FROM {table} rc JOIN zigo_runs r ON r.run_id=rc.run_id WHERE 1=1{run_clause}",
                run_params,
            ).fetchone()[0])
        return {
            "runs": direct_count("zigo_runs"),
            "contents": linked_count("zigo_run_contents", "content_id"),
            "comments": linked_count("zigo_run_comments", "comment_id"),
            "candidates": int(self.connection.execute(
                "SELECT COUNT(*) FROM zigo_candidates WHERE decision != 'excluded'"
                + (" AND product_domain=?" if product_domain else ""), direct_params,
            ).fetchone()[0]),
            "verified": int(self.connection.execute(
                "SELECT COUNT(*) FROM zigo_candidates WHERE decision='evidence_verified_candidate'"
                + (" AND product_domain=?" if product_domain else ""), direct_params,
            ).fetchone()[0]),
            "revision": int(self.connection.execute("SELECT value FROM zigo_meta WHERE key='revision'").fetchone()[0]) if self.connection.execute("SELECT 1 FROM zigo_meta WHERE key='revision'").fetchone() else 0,
        }

    def list_runs(self, product_domain: str | None = None) -> list[dict]:
        query = "SELECT run_id, product_domain, started_at, finished_at, status FROM zigo_runs"
        params: list[str] = []
        if product_domain:
            query += " WHERE product_domain=?"
            params.append(product_domain)
        rows = self.connection.execute(query + " ORDER BY started_at DESC", params).fetchall()
        return [dict(row) for row in rows]

    def list_candidates(self, run_id: str | None = None, product_domain: str | None = None, limit: int = 100, include_excluded: bool = False) -> list[dict]:
        query = "SELECT * FROM zigo_candidates WHERE 1=1"
        params: list[object] = []
        if run_id:
            query += " AND run_id=?"
            params.append(run_id)
        if product_domain:
            query += " AND product_domain=?"
            params.append(product_domain)
        if not include_excluded:
            query += " AND decision != 'excluded'"
        query += " ORDER BY rule_score DESC, candidate_id LIMIT ?"
        params.append(max(1, min(limit, 500)))
        return [dict(row) for row in self.connection.execute(query, params).fetchall()]

    def revision(self) -> int:
        row = self.connection.execute("SELECT value FROM zigo_meta WHERE key='revision'").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self.connection.close()
