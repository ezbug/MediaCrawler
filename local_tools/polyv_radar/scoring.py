from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import CommentRecord, ContentRecord, LeadEvidence


EVENT_TYPES = {
    "公司年会": ("公司年会", "年会直播", "年会活动"),
    "经销商大会": ("经销商大会", "渠道大会", "经销商培训", "全国经销商", "渠道培训"),
    "合作伙伴大会": ("合作伙伴大会", "伙伴大会", "合作大会"),
    "员工培训": ("员工培训", "企业培训", "企业内训", "企业大学", "线上培训"),
    "新品发布会": ("新品发布会", "产品发布会", "新品发布", "发布会直播"),
    "客户答谢会": ("客户答谢会", "客户大会", "客户活动"),
    "行业峰会": ("行业峰会", "行业论坛", "高峰论坛", "行业大会"),
    "职业教育活动": ("职业教育", "职业院校", "校际活动", "公开课"),
    "线上招商": ("线上招商", "招商会", "招商直播", "招商活动"),
    "订货会": ("订货会", "渠道订货", "经销商订货"),
    "巡展路演": ("区域巡展", "全国路演", "品牌路演", "巡展活动"),
    "医学会议": ("医学会议", "学术会议", "医学培训", "医生培训"),
    "金融投教": ("金融投教", "投教直播", "证券培训", "投资者教育"),
    "版权保护": ("课程版权", "课程防盗录", "课程防盗版", "视频防外传", "防录屏"),
    "海外发布会": ("海外发布会", "海外直播", "全球发布会", "多语言直播"),
}

PURCHASE_SCENE_TERMS = (
    "公司", "企业", "机构", "经销商", "员工", "客户", "门店", "渠道", "大会", "发布会", "培训",
    "会议", "课程", "投教", "年会", "招商", "企业大学", "Webinar", "研讨会",
)
PROJECT_TIMING_TERMS = (
    "下个月", "本月", "近期", "最近", "正在", "准备", "筹备", "项目", "上线", "落地", "启动", "实施",
    "大会", "发布会", "年会", "培训",
)
PLATFORM_INTENT_TERMS = (
    "求推荐", "推荐", "平台", "供应商", "服务商", "选型", "采购", "预算", "报价", "多少钱", "费用",
    "方案", "用什么", "有没有", "哪家", "怎么选",
)
DELIVERY_INQUIRY_TERMS = (
    "部署", "私有化", "接口", "SDK", "API", "接入", "并发", "交付", "实施周期", "周期", "能不能支持", "支持多少人", "支持并发",
    "多少钱", "报价", "费用",
)


CATEGORY_TERMS = {
    "企业直播": ("企业直播", "发布会直播", "万人直播", "直播卡顿", "直播平台推荐", "线上活动直播", "活动直播", "直播选型", "发布会转线上", "大并发直播选型", "线上研讨会", "线上研讨会推荐", "线上研讨会方案", "Webinar", "低延迟互动直播", "线上峰会策划"),
    "私域直播": ("私域直播", "微信直播", "企微直播", "公众号直播", "私域搭建", "私域运营直播", "私域裂变", "私域直播引流", "私域直播SOP", "小程序公众号直播"),
    "视频点播": ("视频点播", "点播系统", "企业点播", "点播平台", "点播播放器", "视频托管", "私有化点播"),
    "企业培训": ("企业培训", "企业内训", "员工培训", "经销商培训", "线上培训", "企业大学", "培训平台", "微课培训", "培训直播", "课程培训", "员工培训痛点", "门店与经销商", "企业内训系统搭建", "企业培训体系", "客户培训数字化", "经销商线上培训", "内训平台选型", "经销商培训难题", "在线教育系统源码"),
    "视频安全": ("课程盗录", "防下载", "防录屏", "视频泄露", "视频安全", "动态水印", "加密播放器", "课程盗录痛点", "课程防录屏方案", "课程防盗版", "视频防盗外传"),
    "AI视频": ("PPT转视频", "数字人培训", "AI微课", "批量做视频", "AI视频制作"),
    "技术集成": ("直播SDK", "点播SDK", "APP接直播", "自建直播", "WebRTC", "直播API", "SDK选型", "小程序嵌入直播"),
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
AD_TERMS = ("我们提供", "加微信", "私信我", "招商加盟", "招商代理", "招代理", "代理加盟", "源码", "代运营", "同行", "厂家", "欢迎咨询", "出各种", "诚信接单")

# Hard negative terms to filter out non-B2B discussions (entertainment, gaming, personal streaming, medical, casual chat)
NEGATIVE_TERMS = (
    # User-specified negatives:
    "娱乐直播", "游戏直播", "主播", "明星直播", "直播切片", "无人直播", "带货教程", "个人开播", "公会", "打赏", "榜一大哥", "pk",
    # Casual/medical/gaming negatives:
    "用药", "不良反应", "消化不良", "吃了", "药丸", "药店", "处方", "挂号",
    "王者荣耀", "kpl", "折叠屏", "手机", "测评", "数码", "打游戏", "动漫", "游戏",
    "离职", "辞职", "工资只有", "打工人", "破防", "领导恶心", "摆烂", "躺平"
)


@dataclass
class ScoreResult:
    score: int
    category: str
    reasons: list[str] = field(default_factory=list)
    evidence_sentences: list[str] = field(default_factory=list)


@dataclass
class PurchaseEvidenceScore:
    score: int
    dimensions: dict[str, int]
    event_type: str
    evidence_sentences: list[str] = field(default_factory=list)
    rejected_reason: str = ""


def classify_event(text: str) -> str:
    lowered = (text or "").lower()
    for event_type, terms in EVENT_TYPES.items():
        if any(term.lower() in lowered for term in terms):
            return event_type
    return "未分类"


def _dimension_evidence(text: str, terms: tuple[str, ...]) -> list[str]:
    return _evidence(text, terms) if any(term.lower() in text.lower() for term in terms) else []


def score_purchase_evidence(
    content: ContentRecord,
    comment: CommentRecord | None,
    profile: dict | None = None,
    external_evidence: Iterable[dict] = (),
    now: datetime | None = None,
    recent_days: int = 90,
) -> PurchaseEvidenceScore:
    now = now or datetime.now(timezone.utc)
    quote = comment.text if comment else content.text
    content_context = f"{content.title}\n{content.text}".strip()
    signal_text = quote.strip() if comment else content_context
    context = f"{content_context}\n{signal_text}".strip()
    lowered = context.lower()
    content_lower = content_context.lower()
    signal_lower = signal_text.lower()
    profile = profile or {}
    evidence_urls = [str(item.get("source_url", "")) for item in external_evidence if item.get("source_url")]

    if any(term.lower() in lowered for term in (*AD_TERMS, *NEGATIVE_TERMS)):
        return PurchaseEvidenceScore(
            score=0,
            dimensions={key: 0 for key in ("business_scene", "project_timing", "platform_intent", "delivery_inquiry", "identity")},
            event_type=classify_event(content_context) or classify_event(signal_text),
            rejected_reason="广告、同行或非B端内容",
        )

    has_scene = any(term.lower() in content_lower or term.lower() in signal_lower for term in PURCHASE_SCENE_TERMS)
    event_type = classify_event(content_context)
    if event_type == "未分类":
        event_type = classify_event(signal_text)
    business_scene = 2 if has_scene and event_type != "未分类" else (1 if has_scene else 0)

    published_at = comment.published_at if comment else content.published_at
    recent = bool(published_at and now - timedelta(days=max(1, recent_days)) <= published_at <= now)
    buyer_context = signal_text if comment else content_context
    buyer_lower = buyer_context.lower()
    project_hit = any(term.lower() in buyer_lower for term in PROJECT_TIMING_TERMS)
    project_timing = 2 if project_hit and recent else (1 if project_hit else 0)

    platform_hits = _dimension_evidence(buyer_context, PLATFORM_INTENT_TERMS)
    platform_intent = 2 if any(term.lower() in buyer_lower for term in ("求推荐", "供应商", "服务商", "选型", "采购", "报价", "多少钱", "哪家")) else (1 if platform_hits else 0)

    delivery_hits = _dimension_evidence(buyer_context, DELIVERY_INQUIRY_TERMS)
    delivery_inquiry = 2 if any(term.lower() in buyer_lower for term in ("报价", "多少钱", "部署", "私有化", "接口", "SDK", "API", "交付", "实施周期")) else (1 if delivery_hits else 0)

    identity_confidence = str(profile.get("identity_confidence", "low"))
    identity = {"high": 2, "medium": 1}.get(identity_confidence, 0)

    dimensions = {
        "business_scene": business_scene,
        "project_timing": project_timing,
        "platform_intent": platform_intent,
        "delivery_inquiry": delivery_inquiry,
        "identity": identity,
    }
    score = min(10, sum(dimensions.values()))
    rejected_reason = ""
    if business_scene == 0:
        rejected_reason = "缺少明确企业业务场景"
    elif project_timing == 0 and platform_intent == 0:
        rejected_reason = "缺少近期项目或采购意图"
    if business_scene == 0 or event_type == "未分类":
        score = min(score, 4)
        if not rejected_reason:
            rejected_reason = "技术或泛讨论，不能证明业务采购需求"

    evidence = []
    evidence.extend(_dimension_evidence(content_context, PURCHASE_SCENE_TERMS))
    evidence.extend(_dimension_evidence(buyer_context, PROJECT_TIMING_TERMS))
    evidence.extend(platform_hits)
    evidence.extend(delivery_hits)
    evidence.extend(evidence_urls)
    return PurchaseEvidenceScore(
        score=score,
        dimensions=dimensions,
        event_type=event_type,
        evidence_sentences=list(dict.fromkeys(evidence))[:8],
        rejected_reason=rejected_reason,
    )


def classify_category(text: str, category_hint: str | None = None) -> str:
    if category_hint in CATEGORY_TERMS:
        return category_hint
    if category_hint:
        hint_text = category_hint.lower()
        for category, terms in CATEGORY_TERMS.items():
            if any(term.lower() in hint_text for term in terms):
                return category
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
    recent_days: int = 90,
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
    recent_days: int = 90,
) -> LeadEvidence:
    quote = comment.text if comment else content.text
    context = f"{content.title}\n{content.text}".strip()
    signal_text = quote.strip()
    inferred_category = classify_category(context, category_hint)
    result = score_text(signal_text, comment.published_at if comment else content.published_at, now, inferred_category, recent_days)
    category_terms = CATEGORY_TERMS.get(inferred_category, ())
    has_business_scene = any(term.lower() in context.lower() or term.lower() in signal_text.lower() for term in category_terms)
    has_intent = any(
        term.lower() in signal_text.lower()
        for term in (*EXPLICIT_NEED, *PROJECT_TERMS, *INQUIRY_TERMS)
    )
    if not has_business_scene or not has_intent:
        result = ScoreResult(
            score=0,
            category=result.category,
            reasons=["过滤：缺少明确的视频业务场景或采购/项目意图"],
            evidence_sentences=result.evidence_sentences,
        )
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
