from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import CommentRecord, ContentRecord, LeadEvidence


CATEGORY_TERMS = {
    "企业直播": ("企业直播", "发布会直播", "万人直播", "直播卡顿", "直播平台推荐", "线上活动直播", "活动直播", "直播选型"),
    "私域直播": ("私域直播", "微信直播", "企微直播", "公众号直播", "私域搭建", "私域运营直播", "私域裂变"),
    "视频点播": ("视频点播", "点播系统", "企业点播", "点播平台", "点播播放器", "视频托管", "私有化点播"),
    "企业培训": ("企业培训", "企业内训", "员工培训", "经销商培训", "线上培训", "企业大学", "培训平台", "微课培训", "培训直播", "课程培训"),
    "视频安全": ("课程盗录", "防下载", "防录屏", "视频泄露", "视频安全", "动态水印", "加密播放器"),
    "AI视频": ("PPT转视频", "数字人培训", "AI微课", "批量做视频", "AI视频制作"),
    "技术集成": ("直播SDK", "点播SDK", "APP接直播", "自建直播", "WebRTC", "直播API", "SDK选型"),
    "出海": ("海外直播", "全球发布会", "多语言直播", "全球直播", "海外分发"),
}

SOLUTIONS = {
    "企业直播": "企业活动直播与互动直播方向",
    "私域直播": "私域流量直播运营与微信生态转化方向",
    "视频点播": "企业私有化点播、视频托管与音视频处理方向",
    "企业培训": "企业培训直播与数字化内训点播方向",
    "视频安全": "视频点播与内容安全加密防盗录方向",
    "AI视频": "AI课程与数字化微课生产方向",
    "技术集成": "直播与点播 SDK、API 与 WebRTC 集成方向",
    "出海": "全球直播、多语言与海外分发方向",
    "未分类": "直播与视频平台能力方向",
}

EXPLICIT_NEED = ("我们公司", "我司", "公司需要", "企业需要", "正在找", "需要一个", "需要做", "想找", "老板让我", "求推荐", "哪家平台", "用什么系统", "怎么选平台")
PROJECT_TERMS = ("项目", "上线", "准备", "正在做", "筹备", "落地", "启动", "实施", "采购", "老板让我")
INQUIRY_TERMS = ("多少钱", "价格", "费用", "方案", "平台推荐", "推荐一下", "能不能支持", "怎么选", "有没有做过", "好用吗", "怎么收费", "试用")
ROLE_TERMS = ("公司", "企业", "老板", "负责人", "总监", "经理", "HR", "人事", "运营", "技术", "采购", "IT")
AD_TERMS = ("我们提供", "加微信", "私信我", "招商", "代理", "源码", "代运营", "同行", "厂家", "欢迎咨询", "出各种", "诚信接单")

# Hard negative terms to filter out non-B2B discussions (medical, gaming, casual chat)
NEGATIVE_TERMS = (
    "用药", "不良反应", "消化不良", "吃了", "药丸", "药店", "医院", "处方", "挂号",
    "王者荣耀", "kpl", "折叠屏", "手机", "测评", "数码", "打游戏", "动漫", "游戏",
    "离职", "辞职", "工资只有", "打工人", "破防", "领导恶心", "摆烂", "躺平"
)


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
    if category_hint:
        return category_hint
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

    if any(term.lower() in text.lower() for term in NEGATIVE_TERMS):
        score -= 8
        reasons.append("非B端业务场景/消费数码/医疗讨论")
        evidence.extend(_evidence(text, NEGATIVE_TERMS))

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
