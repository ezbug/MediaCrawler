from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import CommentRecord, ContentRecord


PLATFORM_ALIASES = {"bilibili": "bili", "xiaohongshu": "xhs", "douyin": "dy"}


def _first(raw: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return default


def parse_count(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.endswith(("万", "w", "W")):
        multiplier = 10000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) or str(value).strip().isdigit():
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _platform_name(platform: str) -> str:
    return PLATFORM_ALIASES.get(platform.lower(), platform.lower())


def _content_id(platform: str, raw: dict[str, Any]) -> str:
    platform = _platform_name(platform)
    if platform == "dy":
        return str(_first(raw, "aweme_id", "video_id", "content_id"))
    if platform == "xhs":
        return str(_first(raw, "note_id", "content_id", "video_id"))
    if platform == "bili":
        return str(_first(raw, "video_id", "aid", "bvid", "content_id"))
    return str(_first(raw, "content_id", "question_id", "id"))


def normalize_content(platform: str, raw: dict[str, Any], source_keyword: str) -> ContentRecord | None:
    platform = _platform_name(platform)
    content_id = _content_id(platform, raw)
    if not content_id:
        return None

    title = str(_first(raw, "title", "desc", "content_text", default=""))
    text = str(_first(raw, "desc", "content_text", "content", "title", default=title))
    url = str(_first(raw, "aweme_url", "note_url", "video_url", "content_url", default=""))
    if not url:
        url = {
            "dy": f"https://www.douyin.com/video/{content_id}",
            "xhs": f"https://www.xiaohongshu.com/explore/{content_id}",
            "bili": f"https://www.bilibili.com/video/av{content_id}",
            "zhihu": f"https://www.zhihu.com/question/{content_id}",
        }.get(platform, "")

    return ContentRecord(
        platform=platform,
        content_id=content_id,
        title=title,
        text=text,
        url=url,
        author=str(_first(raw, "nickname", "user_nickname", "user_name", "author", default="")),
        author_hash=str(_first(raw, "creator_hash", "author_hash", default="")),
        published_at=parse_datetime(_first(raw, "create_time", "time", "pubdate", "created_time", default="")),
        likes=parse_count(_first(raw, "liked_count", "video_like", "voteup_count", "like_count")),
        comments_count=parse_count(_first(raw, "comment_count", "video_comment", "video_comment_count")),
        shares=parse_count(_first(raw, "share_count", "video_share_count")),
        plays=parse_count(_first(raw, "play_count", "video_play_count", "view_count")),
        source_keywords=[source_keyword] if source_keyword else [],
        content_type=str(_first(raw, "content_type", "video_type", "type", default="")),
    )


def normalize_comment(
    platform: str,
    raw: dict[str, Any],
    content_id: str | None = None,
    source_keyword: str = "",
) -> CommentRecord | None:
    platform = _platform_name(platform)
    comment_id = str(_first(raw, "comment_id", "cid", "rpid", "id"))
    content_id = str(content_id or _first(raw, "aweme_id", "note_id", "video_id", "content_id"))
    if not comment_id or not content_id:
        return None
    nested_content = raw.get("content")
    if isinstance(nested_content, dict):
        nested_content = nested_content.get("message", "")
    text = str(_first(raw, "text", "content", "comment_content", default=nested_content or ""))
    return CommentRecord(
        platform=platform,
        comment_id=comment_id,
        content_id=content_id,
        text=text,
        author=str(_first(raw, "nickname", "user_nickname", "user_name", "uname", "author", default="")),
        author_hash=str(_first(raw, "creator_hash", "author_hash", default="")),
        parent_comment_id=str(_first(raw, "parent_comment_id", "reply_id", "parent", default="")),
        published_at=parse_datetime(_first(raw, "create_time", "publish_time", "ctime", default="")),
        likes=parse_count(_first(raw, "like_count", "like", "digg_count")),
        source_keyword=source_keyword,
    )
