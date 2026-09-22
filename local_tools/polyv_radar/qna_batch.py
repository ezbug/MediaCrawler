from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from .config import RadarConfig
from .manual_candidates import build_manual_candidates
from .storage import RadarStore


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
    "人数", "部署", "交付", "联系客服", "材料自己导入",
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
