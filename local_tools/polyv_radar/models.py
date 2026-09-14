from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ContentRecord:
    platform: str
    content_id: str
    title: str = ""
    text: str = ""
    url: str = ""
    author: str = ""
    author_hash: str = ""
    published_at: datetime | None = None
    likes: int = 0
    comments_count: int = 0
    shares: int = 0
    plays: int = 0
    source_keywords: list[str] = field(default_factory=list)
    content_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat() if self.published_at else None
        return data


@dataclass
class CommentRecord:
    platform: str
    comment_id: str
    content_id: str
    text: str = ""
    author: str = ""
    author_hash: str = ""
    parent_comment_id: str = ""
    published_at: datetime | None = None
    likes: int = 0
    source_keyword: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat() if self.published_at else None
        return data


@dataclass
class LeadEvidence:
    platform: str
    content_id: str
    comment_id: str
    url: str
    user: str
    quote: str
    category: str
    solution: str
    score: int
    reasons: list[str] = field(default_factory=list)
    evidence_sentences: list[str] = field(default_factory=list)
    outreach: str = ""
    content_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
