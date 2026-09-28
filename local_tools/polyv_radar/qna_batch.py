from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import RadarConfig
from .manual_candidates import build_manual_candidates
from .scoring import classify_account_role, classify_category, classify_event, classify_publisher_role, freshness_bucket
from .storage import RadarStore
from .target_urls import normalize_comment_url


BUSINESS_TERMS = (
    "培训", "员工", "经销商", "企业大学", "大会", "年会", "发布会", "学术会议",
    "医学", "招商", "订货", "峰会", "巡展", "课程", "防盗", "盗录", "录屏",
    "视频平台", "直播平台", "线上活动", "活动直播", "企业直播", "研讨会", "会议",
    "培训平台", "课程安全", "版权",
)
BUYER_TERMS = (
    "我们公司", "我司", "老板让我", "公司需要", "正在找", "求推荐", "求方案", "报价",
    "预算", "采购", "选型", "平台推荐", "供应商", "多少钱", "下个月", "本月", "近期",
    "准备", "筹备", "正在做", "需求", "怎么选", "哪家", "能不能支持", "私有化", "防录屏",
    "费用", "价格", "人数", "部署", "交付", "联系客服", "材料自己导入",
)
DIRECT_NEED_TERMS = (
    "我们公司", "我司", "公司需要", "企业需要", "正在找", "求推荐", "求方案", "报价",
    "预算", "采购", "选型", "多少钱", "下个月", "本月", "近期", "筹备", "正在做",
    "有需求", "需求", "怎么选", "哪家", "能不能支持", "私有化", "防录屏", "费用", "价格",
    "公司年会", "我们就是公司", "不对外", "公司培训",
    "人数", "部署", "交付", "联系客服", "材料自己导入",
)
STRONG_REQUEST_TERMS = (
    "我们公司", "我司", "公司需要", "企业需要", "正在找", "求推荐", "求方案", "报价", "预算",
    "采购", "选型", "多少钱", "怎么选", "哪家", "平台", "系统", "私有化", "防录屏", "费用",
    "价格", "公司年会", "我们就是公司", "不对外", "有需求", "材料自己导入",
)
PRODUCT_CONTEXT_TERMS = (
    "平台", "系统", "直播", "线上", "视频", "课程", "录屏", "盗版", "防盗", "防录",
    "部署", "接口", "上传", "观看", "人数", "方案", "报价", "费用", "预算", "交付",
    "活动", "大会", "年会", "发布会", "内容安全", "版权保护",
)
NON_PRODUCT_TOPIC_TERMS = (
    "招聘", "找工作", "offer", "工资", "薪资", "hc", "求职", "书籍", "电脑", "网工",
    "客户经理", "产品行销", "试用期", "女生", "灯具采购", "模板", "风筝", "歌曲",
)
HARD_NOISE = (
    "路由器", "交换机", "wifi", "webRTC", "ndi", "rtsp", "srt", "obs", "编程", "源码",
    "招聘", "兼职", "骗局", "求模板", "求模版", "求教程", "安装教程", "求案例", "我第一",
    "我第二", "我第三", "学习了", "好浮夸", "怎么弄，", "怎么弄?", "作者", "官方号",
    "欢迎咨询", "可以的 老师", "啥都没有用", "预算直接报多两个0", "好浮夸",
)
PROVIDER_TERMS = (
    "我们提供", "欢迎咨询", "助力企业", "解决方案", "官方号", "服务商", "供应商", "平台方",
    "报价表", "工具测评", "功能清单", "咨询师", "会展公司", "直播团队", "根据需求定制",
)
CONTENT_GUIDE_TERMS = (
    "攻略", "指南", "避坑", "排名", "top10", "十大", "五大", "测评", "深度解析",
    "方案合集", "成功案例", "功能清单", "清单", "一篇文章", "选型指南", "必备", "实测", "保姆级",
)
CONTENT_PROVIDER_TERMS = (
    "云直播", "直播服务", "直播团队", "影像", "企业培训系统", "培训平台", "企学宝",
    "小鹅通", "轻速云", "映目", "欢拓", "诺云", "飞训", "职星", "知博云", "保利威",
)
CONTENT_PROVIDER_ACCOUNT_TERMS = (
    "直播", "培训", "系统", "视觉", "策划", "会务", "影视", "传媒", "课程", "加密",
    "saas", "学院", "教育", "老师", "教培", "团建", "产品经理", "影像",
)
CONTENT_NON_PRODUCT_TERMS = (
    "投票", "选票", "聊天室", "看病", "中医", "摄影摄像", "外模", "走秀", "tvc", "歌曲",
)
ACCOUNT_PROVIDER_HINTS = (
    "策划", "工具", "测评", "加密", "卖课", "知识通", "演出", "会务", "传媒", "直播团队",
)
TECHNICAL_ONLY_TERMS = (
    "docker", "路由器", "端口", "数据库", "排错", "上传视频", "代码", "接口没走", "外网使用",
)


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _has(text: str, terms: Iterable[str]) -> bool:
    lowered = _norm(text)
    return any(_norm(term) in lowered for term in terms)


def _identity(row: dict) -> str:
    return _norm(row.get("author_id") or row.get("user") or "")


def _is_noise(row: dict) -> bool:
    quote = str(row.get("quote") or "")
    title = str(row.get("content_title") or "")
    combined = f"{quote}\n{title}"
    # These are prior POLYV copy or self-authored account traces, not new leads.
    if "polyv" in _norm(quote) or "具体能力、交付方式" in quote:
        return True
    account_role, _ = classify_account_role(str(row.get("user") or ""))
    if account_role == "likely_provider":
        return True
    user_key = _norm(row.get("user") or "")
    if any(_norm(term) in user_key for term in ACCOUNT_PROVIDER_HINTS):
        return True
    if _has(quote, ("预算直接报多两个0", "好浮夸")):
        return True
    if _has(quote, HARD_NOISE) and not _has(quote, DIRECT_NEED_TERMS):
        return True
    # Provider content remains a useful container only when this user's own
    # words contain a separate need, cost, timing, or delivery question.
    if row.get("source_role") == "likely_provider" and not _has(quote, DIRECT_NEED_TERMS):
        return True
    if _has(quote, ("工具测评", "工具报价表", "功能清单", "根据需求定制", "全案供应商")) and not _has(quote, DIRECT_NEED_TERMS):
        return True
    if _has(quote, PROVIDER_TERMS) and not _has(quote, DIRECT_NEED_TERMS):
        return True
    if row.get("freshness") == "current" and not _has(quote, DIRECT_NEED_TERMS):
        return True
    if row.get("source_type") in {"comment", "reply"} and row.get("freshness") == "historical" and not _has(quote, DIRECT_NEED_TERMS):
        return True
    if row.get("source_type") in {"comment", "reply"} and not _has(quote, STRONG_REQUEST_TERMS):
        return True
    if _has(quote, TECHNICAL_ONLY_TERMS) and not _has(quote, STRONG_REQUEST_TERMS):
        return True
    if _has(quote, NON_PRODUCT_TOPIC_TERMS) and not _has(quote, PRODUCT_CONTEXT_TERMS):
        return True
    if not _has(quote, PRODUCT_CONTEXT_TERMS):
        return True
    return not _has(combined, BUSINESS_TERMS)


def _rank(row: dict) -> tuple:
    quote = str(row.get("quote") or "")
    return (
        0 if row.get("freshness") == "current" else 1,
        0 if row.get("triage_label") == "keep_current" else 1 if row.get("triage_label") == "keep_reactivation" else 2,
        0 if _has(quote, BUYER_TERMS) else 1,
        -int(row.get("rule_score") or 0),
        -int(row.get("priority") or 0),
        str(row.get("platform") or ""),
    )


def _content_candidate(content, config: RadarConfig, run_id: str) -> dict | None:
    title = str(content.title or "").strip()
    text = str(content.text or title).strip()
    combined = f"{title}\n{text}"
    author = str(content.author or "").strip()
    author_key = _norm(author)
    if not title or not content.url or not author_key:
        return None
    if any(_norm(term) in author_key for term in (*CONTENT_PROVIDER_TERMS, *CONTENT_PROVIDER_ACCOUNT_TERMS)):
        return None
    publisher_role, _ = classify_publisher_role(content)
    if publisher_role == "likely_provider":
        return None
    if _has(combined, CONTENT_NON_PRODUCT_TERMS):
        return None
    guide_exception = _has(combined, ("公司要", "公司需要", "正在找", "求推荐", "多少钱", "报价", "预算", "我们公司", "领导要求")) or bool(re.search(r"\d+\s*人", combined))
    if _has(combined, CONTENT_GUIDE_TERMS) and not guide_exception:
        return None
    if not _has(combined, BUSINESS_TERMS) or not _has(combined, DIRECT_NEED_TERMS):
        return None
    has_question_signal = any(token in combined for token in ("？", "?", "求推荐", "有没有", "哪家", "怎么选", "多少钱", "报价"))
    has_ownership_signal = _has(combined, ("我们公司", "我司", "公司需要", "公司要", "企业需要", "领导要求", "下个月", "全国渠道"))
    if not (has_question_signal or has_ownership_signal):
        return None
    if author_key in {"知乎答主", "知乎用户", "b站创作者", "抖音创作者", "小红书用户"}:
        return None
    published = content.published_at
    freshness = freshness_bucket(published, datetime.now(timezone.utc), config.recent_days, config.max_lead_age_days)
    if freshness == "stale":
        return None
    source_type = "answer" if "/answer/" in content.url else "post"
    row = {
        "candidate_id": f"qna-content-{content.platform}-{content.content_id}",
        "platform": content.platform,
        "source_type": source_type,
        "content_id": content.content_id,
        "content_title": title,
        "content_url": content.url,
        "comment_url": content.url,
        "comment_id": "",
        "native_comment_id": "",
        "parent_comment_id": "",
        "user": author,
        "author_id": content.author_id or author,
        "profile_url": content.author_url or content.creator_url,
        "quote": text,
        "published_at": content.published_at.isoformat() if content.published_at else "",
        "freshness": freshness,
        "candidate_kind": "content_request",
        "category": classify_category(combined),
        "event_type": classify_event(combined),
        "intent_class": "buyer_request",
        "intent_reason": "帖子或回答本体包含业务场景与平台/价格/选型问题",
        "source_role": publisher_role,
        "source_role_reason": "内容作者角色已做规则初筛，仍需主页核验",
        "comment_role": "unknown",
        "comment_role_reason": "内容型候选，无评论作者角色",
        "small_need": False,
        "historical_event": freshness == "historical",
        "rule_score": 4,
        "rule_dimensions": {},
        "evidence": [text],
        "recommended_action": "先核验作者身份和原文，再决定公开回复或历史复活",
        "reply_draft": "",
        "triage_label": "keep_reactivation" if freshness == "historical" else "keep_current",
        "triage_reason": "内容本体存在明确业务场景和选型/价格问题",
        "priority": 90 if freshness == "current" else 60,
        "origin_run_id": run_id,
        "qna_status": "pending_locator",
    }
    row["reply_text"] = _draft(row)
    return row


def _fallback_comment_candidate(content, comment, config: RadarConfig, run_id: str) -> dict | None:
    quote = str(comment.text or "").strip()
    if not quote or not _has(quote, STRONG_REQUEST_TERMS):
        return None
    combined = f"{content.title}\n{content.text}\n{quote}"
    if not _has(combined, BUSINESS_TERMS):
        return None
    published = comment.published_at or content.published_at
    freshness = freshness_bucket(published, datetime.now(timezone.utc), config.recent_days, config.max_lead_age_days)
    if freshness == "stale":
        return None
    row = {
        "candidate_id": f"qna-comment-{content.platform}-{content.content_id}-{comment.comment_id}",
        "platform": content.platform,
        "source_type": comment.source_type or "comment",
        "content_id": content.content_id,
        "content_title": content.title,
        "content_url": content.url,
        "comment_url": normalize_comment_url(
            comment.comment_url,
            content.url,
            comment.source_type or "comment",
        ),
        "comment_id": comment.comment_id,
        "native_comment_id": comment.native_comment_id,
        "parent_comment_id": comment.parent_comment_id or comment.native_parent_id,
        "user": comment.author,
        "author_id": comment.author_id or comment.author,
        "profile_url": comment.author_url or content.author_url or content.creator_url,
        "quote": quote,
        "published_at": comment.published_at.isoformat() if comment.published_at else (content.published_at.isoformat() if content.published_at else comment.published_at_raw),
        "freshness": freshness,
        "candidate_kind": "historical_reactivation" if freshness == "historical" else "manual_review",
        "category": classify_category(combined),
        "event_type": classify_event(combined),
        "intent_class": "buyer_request",
        "intent_reason": "评论原话包含第一人称、项目、价格或选型信号",
        "source_role": classify_publisher_role(content)[0],
        "source_role_reason": "评论来自业务场景内容，发布者角色与评论用户分开判断",
        "comment_role": "unknown",
        "comment_role_reason": "需要主页二跳确认",
        "small_need": False,
        "historical_event": freshness == "historical",
        "rule_score": 4,
        "rule_dimensions": {},
        "evidence": [quote],
        "recommended_action": "先核验作者和原话定位，再决定公开回复",
        "reply_draft": "",
        "triage_label": "keep_reactivation" if freshness == "historical" else "keep_current",
        "triage_reason": "评论原话含有可行动的业务或采购信号",
        "priority": 80 if freshness == "current" else 50,
        "origin_run_id": run_id,
        "qna_status": "pending_locator",
    }
    if _is_noise(row):
        return None
    row["reply_text"] = _draft(row)
    return row


def _draft(row: dict) -> str:
    quote = re.sub(r"\s+", " ", str(row.get("quote") or "")).strip().strip("。")[:90]
    category = str(row.get("category") or "企业培训/活动内容")
    if row.get("freshness") == "historical":
        return (
            f"之前看到你提到“{quote}”，想确认一下现在这方面还有需求吗？"
            f"如果还在推进，POLYV可以结合{category}的实际场景帮你梳理方案；"
            "方便的话可以私信沟通。"
        )
    if row.get("triage_label") == "conditional":
        return (
            f"看到你提到“{quote}”。这类{category}通常要先看参与人数、内容形式和后续管理方式；"
            "如果需求还在推进，POLYV可以按实际场景帮你做方案梳理。"
        )
    return (
        f"看到你提到“{quote}”。这类{category}可以先把参与规模、观看对象、内容形态和交付方式列清，"
        "再比较平台方案；POLYV可以结合具体场景帮你梳理，方便的话可以私信沟通。"
    )


def collect_qna_pool(
    config: RadarConfig,
    *,
    target: int = 50,
    pool_size: int = 80,
    run_ids: Iterable[str] | None = None,
) -> list[dict]:
    """Build a cross-run, user-deduped Q&A pool without browser access."""
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    try:
        if run_ids is None:
            rows = store.connection.execute(
                "SELECT run_id FROM runs WHERE run_id NOT LIKE 'legacy-%' ORDER BY started_at DESC"
            ).fetchall()
            selected_runs = [str(row[0]) for row in rows]
        else:
            selected_runs = [str(run_id) for run_id in run_ids]
        candidates: dict[tuple[str, str], dict] = {}
        for run_id in selected_runs:
            for content in store.iter_contents(run_id):
                content_row = _content_candidate(content, config, run_id)
                if content_row is None:
                    continue
                key = (str(content_row.get("platform") or ""), _identity(content_row))
                previous = candidates.get(key)
                if previous is None or _rank(content_row) < _rank(previous):
                    candidates[key] = content_row
            rows = build_manual_candidates(
                store.iter_contents(run_id),
                store.iter_comments(run_id),
                max_candidates=1000,
                recent_days=config.recent_days,
                max_age_days=config.max_lead_age_days,
                excluded_author_names=config.excluded_author_names,
                negative_terms=config.taxonomy_negative_terms,
            )
            for row in rows:
                if row.get("triage_label") == "drop_low_signal" or _is_noise(row):
                    continue
                identity = _identity(row)
                if not identity:
                    continue
                key = (str(row.get("platform") or ""), identity)
                row = {
                    **row,
                    "origin_run_id": run_id,
                    "qna_status": "pending_locator",
                    "reply_text": _draft(row),
                }
                previous = candidates.get(key)
                if previous is None or _rank(row) < _rank(previous):
                    candidates[key] = row
            content_by_key = {(item.platform, item.content_id): item for item in store.iter_contents(run_id)}
            for comment in store.iter_comments(run_id):
                content = content_by_key.get((comment.platform, comment.content_id))
                if content is None:
                    continue
                fallback = _fallback_comment_candidate(content, comment, config, run_id)
                if fallback is None:
                    continue
                key = (str(fallback.get("platform") or ""), _identity(fallback))
                previous = candidates.get(key)
                if previous is None or _rank(fallback) < _rank(previous):
                    candidates[key] = fallback
        ordered = sorted(candidates.values(), key=_rank)
        for index, row in enumerate(ordered[:pool_size], 1):
            row["candidate_id"] = f"qna-{index:03d}-{row['platform']}-{row['content_id']}-{row['comment_id']}"
        return ordered[:pool_size]
    finally:
        store.close()


def write_qna_pool(data_root: Path, run_id: str, rows: Iterable[dict]) -> dict[str, Path]:
    rows = list(rows)
    review_root = Path(data_root) / "review"
    report_root = Path(data_root) / "reports"
    review_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    json_path = review_root / f"{run_id}-manual-candidates.jsonl"
    md_path = report_root / f"{run_id}-qna-pool.md"
    json_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    counts = Counter(str(row.get("platform") or "") for row in rows)
    lines = [
        f"# POLYV Q&A 发送候选池：{run_id}",
        "",
        "本表是跨历史批次、按平台用户去重后的候选池。定位和Dry-Run通过前不代表已发送。历史记录使用复活式问法；所有真实回复仍需在发送前完成最终确认。",
        "",
        f"候选池：{len(rows)} 条；平台分布：" + ", ".join(f"{key} {value}" for key, value in sorted(counts.items())),
        "",
        "| # | 平台 | 用户 | 时间层 | 分类 | 原话 | 来源批次 | 回复草稿 | 内容URL |",
        "| ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(rows, 1):
        def cell(value):
            return str(value or "").replace("|", "\\|").replace("\n", " ").strip()
        url = cell(row.get("content_url"))
        lines.append(
            f"| {index} | {cell(row.get('platform'))} | {cell(row.get('user'))} | {cell(row.get('freshness'))} | "
            f"{cell(row.get('triage_label'))} | {cell(row.get('quote'))} | {cell(row.get('origin_run_id'))} | "
            f"{cell(row.get('reply_text'))} | [{url}]({url}) |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def build_locator_rows(rows: Iterable[dict]) -> list[dict]:
    result = []
    for row in rows:
        result.append(
            {
                **row,
                "run_id": row.get("origin_run_id", ""),
                "content_url": row.get("content_url", ""),
                "reply_text": row.get("reply_text", ""),
            }
        )
    return result


def write_locator_queue(data_root: Path, run_id: str, rows: Iterable[dict]) -> Path:
    path = Path(data_root) / "locators" / f"{run_id}-input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidates": list(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
