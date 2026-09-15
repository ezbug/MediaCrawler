from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit


def normalize_locator_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


@dataclass(frozen=True)
class LocatorResult:
    status: str
    index: int | None = None
    method: str = ""
    reason: str = ""


def locate_comment(
    comments: Iterable[dict],
    author: str,
    quote: str,
    native_comment_id: str = "",
    parent_comment_id: str = "",
) -> LocatorResult:
    rows = list(comments)
    expected_author = normalize_locator_text(author)
    expected_quote = normalize_locator_text(quote)
    matches: list[tuple[int, str]] = []
    for index, item in enumerate(rows):
        item_author = normalize_locator_text(item.get("author", ""))
        item_quote = normalize_locator_text(item.get("text", item.get("quote", "")))
        if native_comment_id and str(item.get("native_comment_id", "")) == native_comment_id:
            matches.append((index, "native_id"))
        elif item_author == expected_author and item_quote == expected_quote:
            matches.append((index, "author_quote"))

    if parent_comment_id:
        parent_matches = [
            item for item in matches
            if str(rows[item[0]].get("parent_comment_id", "")) == str(parent_comment_id)
            or str(rows[item[0]].get("native_parent_id", "")) == str(parent_comment_id)
        ]
        if parent_matches:
            matches = parent_matches
    if len(matches) == 1:
        index, method = matches[0]
        return LocatorResult("verified", index, method, "作者和原话唯一匹配")
    if len(matches) > 1:
        return LocatorResult("ambiguous", reason="作者和原话匹配多个评论")
    return LocatorResult("not_found", reason="页面中未找到对应作者和原话")


@dataclass(frozen=True)
class LocatorUrl:
    url: str
    method: str


def locator_url(
    platform: str,
    content_url: str,
    native_comment_id: str = "",
    comment_url: str = "",
    verified: bool = False,
) -> LocatorUrl:
    if verified and comment_url:
        return LocatorUrl(comment_url, "direct_url")
    if verified and platform == "bili" and native_comment_id:
        parts = urlsplit(content_url)
        return LocatorUrl(
            urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, f"reply{native_comment_id}")),
            "native_id",
        )
    return LocatorUrl(content_url, "author_quote")
