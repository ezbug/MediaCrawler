from __future__ import annotations

import sqlite3
from pathlib import Path

from local_tools.polyv_radar.adapters import normalize_comment
from local_tools.polyv_radar.locator import locate_comment, locator_url
from local_tools.polyv_radar.models import CommentRecord
from local_tools.polyv_radar.storage import RadarStore


def test_comment_normalization_preserves_native_locator_fields() -> None:
    comment = normalize_comment(
        "bili",
        {
            "comment_id": "internal-1",
            "native_comment_id": "rpid-1",
            "native_parent_id": "rpid-root",
            "comment_url": "https://www.bilibili.com/video/BV1abc/#replyrpid-1",
            "source_type": "reply",
            "content_id": "BV1abc",
            "text": "公司正在筹备发布会直播，求平台报价",
            "author": "测试用户",
            "published_at_raw": "2天前",
        },
    )

    assert comment is not None
    assert comment.native_comment_id == "rpid-1"
    assert comment.native_parent_id == "rpid-root"
    assert comment.comment_url.endswith("#replyrpid-1")
    assert comment.source_type == "reply"
    assert comment.published_at is None
    assert comment.published_at_raw == "2天前"


def test_locator_requires_one_author_and_quote_match() -> None:
    comments = [
        {"author": "甲", "text": "我们公司正在做线上培训"},
        {"author": "乙", "text": "我们公司正在做线上培训"},
    ]

    result = locate_comment(comments, author="乙", quote="我们公司正在做线上培训")

    assert result.status == "verified"
    assert result.index == 1
    assert result.method == "author_quote"


def test_locator_marks_duplicate_matches_ambiguous() -> None:
    comments = [
        {"author": "甲", "text": "求平台报价"},
        {"author": "甲", "text": "求平台报价"},
    ]

    result = locate_comment(comments, author="甲", quote="求平台报价")

    assert result.status == "ambiguous"


def test_locator_url_only_claims_direct_url_for_verified_native_link() -> None:
    direct = locator_url(
        "bili",
        "https://www.bilibili.com/video/BV1abc/",
        native_comment_id="rpid-1",
        comment_url="https://www.bilibili.com/video/BV1abc/#replyrpid-1",
        verified=True,
    )
    fallback = locator_url(
        "dy",
        "https://www.douyin.com/video/123",
        native_comment_id="",
        comment_url="",
        verified=False,
    )

    assert direct.url.endswith("#replyrpid-1")
    assert direct.method == "direct_url"
    assert fallback.url == "https://www.douyin.com/video/123"
    assert fallback.method == "author_quote"


def test_old_comments_table_gets_locator_columns_without_data_loss(tmp_path: Path) -> None:
    path = tmp_path / "radar.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE comments (
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
        )"""
    )
    connection.execute(
        "INSERT INTO comments(platform, comment_id, content_id, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
        ("dy", "legacy-1", "video-1", "now", "now"),
    )
    connection.commit()
    connection.close()

    store = RadarStore(path)
    store.initialize()
    columns = {row[1] for row in store.connection.execute("PRAGMA table_info(comments)")}
    assert {"native_comment_id", "native_parent_id", "comment_url", "source_type", "published_at_raw"} <= columns
    assert store.count("comments") == 1
    assert store.count("comment_locators") == 0
    store.close()


def test_comment_record_defaults_to_comment_source() -> None:
    comment = CommentRecord(platform="dy", comment_id="c", content_id="v")

    assert comment.source_type == "comment"


def test_store_persists_batch_locator_result(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    store.save_comment_locator(
        {
            "run_id": "run-1",
            "platform": "dy",
            "content_id": "video-1",
            "comment_id": "comment-1",
            "source_type": "comment",
            "content_url": "https://www.douyin.com/video/video-1",
            "comment_url": "https://www.douyin.com/video/video-1",
            "locator_method": "author_quote",
            "status": "verified",
            "matched_author": "甲",
            "matched_quote": "求平台报价",
        }
    )

    rows = store.load_comment_locators("run-1")

    assert rows[0]["status"] == "verified"
    assert rows[0]["locator_method"] == "author_quote"
    store.close()
