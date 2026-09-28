from __future__ import annotations

from urllib.parse import urlparse


COMMENT_SOURCE_TYPES = {"comment", "reply"}
CONTENT_SOURCE_TYPES = {"content", "post", "answer"}


def normalize_comment_url(comment_url: str, content_url: str, source_type: str) -> str:
    """Return a locator URL that can load the target content page."""
    comment = str(comment_url or "").strip()
    content = str(content_url or "").strip()
    source = str(source_type or "comment").strip().lower()
    if source in CONTENT_SOURCE_TYPES:
        return comment or content
    if not comment:
        return content
    path = urlparse(comment).path.lower()
    if "/user/profile/" in path or path.endswith("/profile"):
        return content
    return comment


def dispatch_target_url(content_url: str, comment_url: str, source_type: str) -> str:
    """Return the page URL that the browser should open."""
    content = str(content_url or "").strip()
    comment = normalize_comment_url(comment_url, content, source_type)
    source = str(source_type or "comment").strip().lower()
    if source in COMMENT_SOURCE_TYPES:
        return content or comment
    return comment or content

