from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import CommentRecord, ContentRecord, LeadEvidence


CATEGORY_TERMS = {
    "企业培训": ("员工培训", "经销商培训", "线上培训", "企业大学", "培训直播", "课程培训"),
    "企业直播": ("发布会直播", "万人直播", "直播卡顿", "直播平台", "线上活动", "活动直播"),
    "视频安全": ("课程盗录", "防下载", "防录屏", "视频泄露", "视频安全"),
    "AI视频": ("PPT转视频", "数字人培训", "AI课程", "批量做视频", "AI视频"),
    "技术集成": ("直播SDK", "APP接直播", "自建直播", "WebRTC", "直播API", "SDK"),
    "出海": ("海外直播", "全球发布会", "多语言直播", "全球直播", "海外分发"),
}

SOLUTIONS = {
    "企业培训": "企业培训直播与点播方向",
    "企业直播": "企业活动直播与互动直播方向",
    "视频安全": "视频点播与内容安全方向",
    "AI视频": "AI课程与数字化视频生产方向",
    "技术集成": "直播 SDK、API 与 WebRTC 集成方向",
    "出海": "全球直播、多语言与海外分发方向",
    "未分类": "直播与视频平台能力方向",
}

EXPLICIT_NEED = ("我们公司", "我司", "公司需要", "企业需要", "正在找", "需要一个", "需要做", "想找", "老板让我")
PROJECT_TERMS = ("项目", "上线", "准备", "正在做", "筹备", "落地", "启动", "实施", "老板让我")
INQUIRY_TERMS = ("多少钱", "价格", "费用", "方案", "平台推荐", "推荐一下", "能不能支持", "怎么选", "有没有")
ROLE_TERMS = ("公司", "企业", "老板", "负责人", "经理", "HR", "人事", "运营", "技术", "老师", "培训")
AD_TERMS = ("我们提供", "加微信", "私信", "招商", "代理", "源码", "代运营", "同行", "厂家", "欢迎咨询")


@dataclass
class ScoreResult:
    score: int
    category: str
    reasons: list[str] = field(default_factory=list)
    evidence_sentences: list[str] = field(default_factory=list)


def classify_category(text: str, category_hint: str | None = None) -> str:
    if category_hint in CATEGORY_TERMS:
        return category_hint
    for category, terms in CATEGORY_TERMS.items():
        if any(term.lower() in text.lower() for term in terms):
            return category
    return "未分类"


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?\n]+", text) if part.strip()]


def _evidence(text: str, terms: tuple[str, ...]) -> list[str]:
    sentences = _sentences(text)
    matches = [sentence for sentence in sentences if any(term.lower() in sentence.lower() for term in terms)]
    return matches[:3] or sentences[:1]


def score_text(
    text: str,
    published_at: datetime | None,
    now: datetime | None = None,
    category_hint: str | None = None,
    recent_days: int = 30,
) -> ScoreResult:
    text = text.strip()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if published_at and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    score = 0
    reasons: list[str] = []
    evidence: list[str] = []
    category = classify_category(text, category_hint)

    if any(term.lower() in text.lower() for term in EXPLICIT_NEED):
        score += 3
        reasons.append("明确企业需求")
        evidence.extend(_evidence(text, EXPLICIT_NEED))

    is_recent = published_at is not None and now - timedelta(days=recent_days) <= published_at <= now
    if is_recent and any(term.lower() in text.lower() for term in PROJECT_TERMS):
        score += 3
        reasons.append("近期项目")
        evidence.extend(_evidence(text, PROJECT_TERMS))

    if any(term.lower() in text.lower() for term in INQUIRY_TERMS):
        score += 2
        reasons.append("询问方案/价格")
        evidence.extend(_evidence(text, INQUIRY_TERMS))

    if any(term.lower() in text.lower() for term in ROLE_TERMS):
        score += 2
        reasons.append("透露公司/职位")
        evidence.extend(_evidence(text, ROLE_TERMS))

    if any(term.lower() in text.lower() for term in AD_TERMS):
        score -= 5
        reasons.append("广告或同行推广")
        evidence.extend(_evidence(text, AD_TERMS))

    unique_evidence = list(dict.fromkeys(evidence))
    return ScoreResult(max(0, min(10, score)), category, reasons, unique_evidence)


def score_lead(
    content: ContentRecord,
    comment: CommentRecord | None,
    now: datetime | None = None,
    category_hint: str | None = None,
) -> LeadEvidence:
    quote = comment.text if comment else content.text
    context = f"{content.title}\n{content.text}".strip()
    signal_text = quote.strip()
    inferred_category = category_hint or classify_category(context)
    result = score_text(signal_text, comment.published_at if comment else content.published_at, now, inferred_category)
    return LeadEvidence(
        platform=content.platform,
        content_id=content.content_id,
        comment_id=comment.comment_id if comment else "",
        url=content.url,
        user=comment.author if comment else content.author,
        quote=quote,
        category=result.category,
        solution=SOLUTIONS.get(result.category, SOLUTIONS["未分类"]),
        score=result.score,
        reasons=result.reasons,
        evidence_sentences=result.evidence_sentences,
        outreach="公开答疑，并明确说明POLYV身份",
        content_title=content.title,
    )
