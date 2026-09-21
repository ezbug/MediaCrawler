from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from .models import CommentRecord, ContentRecord
from .scoring import (
    MANUAL_REVIEW_SIGNAL_TERMS,
    NEGATIVE_TERMS,
    TECHNICAL_INTEREST_TERMS,
    POLYV_MANUAL_CONTEXT_TERMS,
    classify_account_role,
    classify_category,
    classify_event,
    classify_intent,
    classify_publisher_role,
    freshness_bucket,
    score_purchase_evidence,
)


def _key(value: object) -> str:
    return "".join(str(value or "").casefold().split())


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _source_date(content: ContentRecord, comment: CommentRecord | None) -> datetime | None:
    return (comment.published_at if comment and comment.published_at else None) or content.published_at


def _has_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(str(term).casefold() in lowered for term in terms)


def _looks_like_technical_interest(text: str) -> bool:
    lowered = text.casefold()
    return _has_any(text, TECHNICAL_INTEREST_TERMS) and not _has_any(
        text, ("公司", "企业", "机构", "项目", "采购", "预算", "报价", "供应商", "平台", "方案")
    )


def _candidate_action(freshness: str, source_role: str, small_need: bool, historical_event: bool) -> str:
    if freshness == "historical":
        return "历史复活：先确认现在是否仍有需求，再说明POLYV可以结合场景提供定制方案，邀请私信沟通。"
    if source_role == "likely_provider":
        return "条件复核：先确认帖子是否为友商/服务商宣传；只有评论用户存在独立需求时才继续。"
    if small_need:
        return "小需求复核：确认是否仍有持续培训、长期平台或权限管理需求。"
    if historical_event:
        return "历史事件复核：确认活动是否还有后续线上化、回放或内容管理需求。"
    return "进入人工复核：补充主页、公开身份和需求定位证据。"


def _reactivation_draft(quote: str, category: str) -> str:
    clean = re.sub(r"\s+", " ", quote).strip()[:80]
    return (
        f"之前看到你提到“{clean}”，想确认一下现在这方面还有需求吗？"
        f"如果还在推进，POLYV也可以结合{category}的具体场景帮你定制方案。"
        "方便的话可以私信我，我先按你的实际情况帮你梳理。"
    )


def _triage_candidate(
    quote: str,
    freshness: str,
    intent_class: str,
    small_need: bool,
    historical_event: bool,
) -> tuple[str, str]:
    """Suggest a human triage label without changing formal lead status."""
    direct_terms = (
        "我们公司", "我司", "老板让我", "公司需要", "正在找", "求推荐", "求方案",
        "报价", "预算", "采购", "供应商", "服务商", "平台推荐", "选型",
    )
    useful_experience_terms = (
        "用户体验", "售后服务", "性价比", "长久持续", "长期使用", "已经选好", "还没选",
        "制造业", "大客户", "线下培训", "公开课", "一年", "万", "天课", "培训",
    )
    if freshness == "current":
        if intent_class == "buyer_request" or _has_any(quote, direct_terms):
            return "keep_current", "当前原话含有明确需求、预算、平台或选型信号"
        if small_need:
            return "conditional", "业务主题相关，但明确透露需求规模较小"
        if _has_any(quote, useful_experience_terms):
            return "keep_current", "当前原话包含平台体验、长期使用或已选型信号"
        return "drop_low_signal", "当前主题相关，但原话缺少可行动需求"
    if freshness == "historical":
        if _has_any(quote, direct_terms) or _has_any(quote, useful_experience_terms):
            return "keep_reactivation", "历史原话仍包含公司、培训规模、费用或业务场景，可先确认是否还有需求"
        if historical_event:
            return "conditional", "历史主题相关，但原话更像旁观或泛评价"
        return "drop_low_signal", "历史原话没有足够的业务行动信号"
    return "conditional", "时间或证据需要人工确认"


def build_manual_candidates(
    contents: Iterable[ContentRecord],
    comments: Iterable[CommentRecord],
    *,
    max_candidates: int = 50,
    now: datetime | None = None,
    recent_days: int = 90,
    max_age_days: int = 730,
    excluded_author_names: Iterable[str] = (),
    negative_terms: Iterable[str] = (),
) -> list[dict]:
    """Keep useful-but-not-yet-qualified clues for human labeling.

    This queue deliberately sits below the formal score gate. It is a labeled
    review pool, not a dispatch queue and not a high-value lead list.
    """
    now = now or datetime.now(timezone.utc)
    content_by_key = {(item.platform, item.content_id): item for item in contents}
    comments_by_content: dict[tuple[str, str], list[CommentRecord]] = defaultdict(list)
    for comment in comments:
        comments_by_content[(comment.platform, comment.content_id)].append(comment)
    excluded = tuple(str(item).casefold() for item in excluded_author_names if item)
    configured_negative = tuple(str(item) for item in negative_terms if item)
    candidates: dict[tuple[str, str, str], dict] = {}

    for key, content in content_by_key.items():
        publisher_role, publisher_reason = classify_publisher_role(content)
        for comment in comments_by_content.get(key, []):
            author = comment.author or ""
            if any(token in author.casefold() for token in excluded):
                continue
            comment_role, comment_role_reason = classify_account_role(author)
            if comment_role == "likely_provider":
                continue
            quote = (comment.text or "").strip()
            combined = f"{content.title}\n{content.text}\n{quote}".strip()
            if not quote or _has_any(combined, (*NEGATIVE_TERMS, *configured_negative)):
                continue
            if _looks_like_technical_interest(quote):
                continue
            intent_class, intent_reason = classify_intent(content, comment)
            published_at = _source_date(content, comment)
            freshness = freshness_bucket(published_at, now, recent_days, max_age_days)
            if freshness == "stale":
                continue
            event_type = classify_event(f"{content.title}\n{content.text}")
            category = classify_category(f"{content.title}\n{content.text}")
            has_business_context = event_type != "未分类" or _has_any(combined, POLYV_MANUAL_CONTEXT_TERMS)
            has_manual_signal = _has_any(quote, MANUAL_REVIEW_SIGNAL_TERMS)
            small_need = _has_any(quote, ("只有新员工", "用一下", "临时", "线下培训偏多", "需求小", "公开课"))
            historical_event = freshness == "historical" and has_business_context and _has_any(
                combined, ("公司", "企业", "我们", "培训", "大会", "会议", "课程", "发布会")
            )
            direct_need = intent_class == "buyer_request" or _has_any(
                quote, ("我们公司", "我司", "老板让我", "公司需要", "正在找", "求推荐", "求方案", "报价", "预算", "采购")
            )
            provider_container = publisher_role == "likely_provider" or intent_class in {"provider_content", "guide_content"}
            if not has_business_context:
                continue
            if not (direct_need or has_manual_signal or historical_event):
                continue
            if provider_container and not (direct_need or has_manual_signal or small_need):
                continue
            kind = "historical_reactivation" if freshness == "historical" else (
                "conditional_provider_context" if provider_container else ("small_need" if small_need else "manual_review")
            )
            triage_label, triage_reason = _triage_candidate(
                quote,
                freshness,
                intent_class,
                small_need,
                historical_event,
            )
            priority = 0
            priority += 40 if freshness == "current" else 20 if freshness == "historical" else 10
            priority += 25 if direct_need else 0
            priority += 15 if provider_container else 0
            priority += 10 if historical_event else 0
            priority += 5 if small_need else 0
            score = score_purchase_evidence(
                content,
                comment,
                now=now,
                recent_days=recent_days,
                negative_terms=negative_terms,
            )
            identity = comment.author_id or comment.author_url or comment.author
            dedupe_key = (content.platform, _key(identity), _key(quote))
            candidates[dedupe_key] = {
                "candidate_id": f"manual-{content.platform}-{content.content_id}-{comment.comment_id}",
                "platform": content.platform,
                "source_type": comment.source_type or "comment",
                "content_id": content.content_id,
                "content_title": content.title,
                "content_url": content.url,
                "comment_url": comment.comment_url or content.url,
                "comment_id": comment.comment_id,
                "native_comment_id": comment.native_comment_id,
                "parent_comment_id": comment.parent_comment_id,
                "native_parent_id": comment.native_parent_id,
                "user": comment.author,
                "author_id": comment.author_id,
                "profile_url": comment.author_url or content.creator_url or content.author_url,
                "quote": quote,
                "published_at": _iso(published_at) or comment.published_at_raw,
                "freshness": freshness,
                "candidate_kind": kind,
                "category": category,
                "event_type": event_type,
                "intent_class": intent_class,
                "intent_reason": intent_reason,
                "source_role": publisher_role,
                "source_role_reason": publisher_reason,
                "comment_role": comment_role,
                "comment_role_reason": comment_role_reason,
                "small_need": small_need,
                "historical_event": historical_event,
                "rule_score": score.score,
                "rule_dimensions": score.dimensions,
                "evidence": score.evidence_sentences or [quote],
                "recommended_action": _candidate_action(freshness, publisher_role, small_need, historical_event),
                "reply_draft": _reactivation_draft(quote, category) if freshness == "historical" else "",
                "triage_label": triage_label,
                "triage_reason": triage_reason,
                "priority": priority,
            }

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-int(item["priority"]), -int(item["rule_score"]), item["platform"], item["candidate_id"]),
    )
    return ordered[:max_candidates]


def write_manual_candidate_artifacts(data_root, run_id: str, candidates: Iterable[dict]) -> dict:
    from pathlib import Path
    import json

    rows = list(candidates)
    review_root = Path(data_root) / "review"
    report_root = Path(data_root) / "reports"
    review_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    json_path = review_root / f"{run_id}-manual-candidates.jsonl"
    md_path = report_root / f"{run_id}-manual-candidates.md"
    json_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    lines = [
        f"# 人工待选线索：{run_id}",
        "",
        "这些记录低于正式候选门槛或需要人工判断来源角色，只用于学习和复核，不进入自动发送队列。",
        "",
        "| ID | 平台 | 建议分类 | 类型 | 时间层 | 来源角色 | 用户 | 原话 | 评分 | 建议动作 | 内容URL | 评论定位URL |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        def cell(value):
            return str(value or "").replace("|", "\\|").replace("\n", " ").strip()
        lines.append(
            f"| {cell(row['candidate_id'])} | {cell(row['platform'])} | {cell(row.get('triage_label'))} | {cell(row['candidate_kind'])} | "
            f"{cell(row['freshness'])} | {cell(row['source_role'])} | {cell(row['user'])} | {cell(row['quote'])} | "
            f"{row['rule_score']} | {cell(row['recommended_action'])} | [{cell(row['content_url'])}]({cell(row['content_url'])}) | "
            f"[{cell(row['comment_url'])}]({cell(row['comment_url'])}) |"
        )
    if not rows:
        lines.append("| - | - | - | - | - | 当前没有符合人工待选规则的记录 | - | - | - | - | - |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
