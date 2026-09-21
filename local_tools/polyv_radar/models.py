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
    author_id: str = ""
    author_url: str = ""
    creator_url: str = ""
    published_at: datetime | None = None
    likes: int = 0
    comments_count: int = 0
    shares: int = 0
    plays: int = 0
    source_keywords: list[str] = field(default_factory=list)
    content_type: str = ""
    tags: list[str] = field(default_factory=list)

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
    author_id: str = ""
    author_url: str = ""
    parent_comment_id: str = ""
    published_at: datetime | None = None
    likes: int = 0
    source_keyword: str = ""
    native_comment_id: str = ""
    native_parent_id: str = ""
    comment_url: str = ""
    source_type: str = "comment"
    published_at_raw: str = ""

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
    event_type: str = ""
    company: str = ""
    role: str = ""
    profile_bio: str = ""
    profile_url: str = ""
    author_url: str = ""
    identity_confidence: str = "low"
    dimensions: dict[str, int] = field(default_factory=dict)
    evidence_urls: list[str] = field(default_factory=list)
    stage: str = "legacy"
    decision: str = ""
    rejection_reason: str = ""
    intent_class: str = "unknown"
    intent_reason: str = ""
    author_id: str = ""
    source_type: str = "comment"
    comment_url: str = ""
    parent_comment_id: str = ""
    locator_status: str = "pending"
    locator_method: str = ""
    locator_verified_at: str = ""
    locator_reason: str = ""
    native_comment_id: str = ""
    published_at: str = ""
    freshness: str = "unknown"
    source_role: str = "unknown"
    candidate_kind: str = "current_demand"
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProfileSnapshot:
    run_id: str
    platform: str
    author_id: str
    author_url: str = ""
    display_name: str = ""
    bio: str = ""
    verified: bool = False
    company: str = ""
    role: str = ""
    identity_confidence: str = "low"
    source_urls: list[str] = field(default_factory=list)
    captured_at: str = ""


@dataclass
class ProfilePost:
    run_id: str
    platform: str
    author_id: str
    post_id: str
    url: str = ""
    title: str = ""
    text: str = ""
    published_at: str = ""


@dataclass
class ExternalEvidence:
    run_id: str
    platform: str
    author_id: str
    source_url: str
    source_type: str = ""
    title: str = ""
    snippet: str = ""
    published_at: str = ""
    match_confidence: str = "low"


@dataclass
class LeadAssessment:
    run_id: str
    platform: str
    content_id: str
    comment_id: str = ""
    score: int = 0
    dimensions: dict[str, int] = field(default_factory=dict)
    event_type: str = ""
    identity_confidence: str = "low"
    evidence: list[dict[str, str]] = field(default_factory=list)
    decision: str = "reject"
    reason: str = ""
    model_status: str = "rule"
    evidence_hash: str = ""
    reviewer_version: str = ""
    reviewer_attempts: int = 0
    review_latency_seconds: float = 0.0
