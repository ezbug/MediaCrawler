from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import LeadEvidence


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _link(label: object, url: object) -> str:
    label = _cell(label)
    url = _cell(url)
    return f"[{label}]({url})" if url else label


def render_verified_leads(run_id: str, leads: Iterable[LeadEvidence]) -> str:
    rows = list(leads)
    lines = [
        f"# POLYV 可核验需求候选：{run_id}",
        "",
        f"共 {len(rows)} 条。仅包含评分达标、企业场景及项目/选型/价格/交付证据成立、并在 Ego Lite 中重新定位成功的记录；同一用户或同一企业只保留一条。",
        "",
        "| 平台 | 来源 | 内容标题 | 内容URL | 评论定位URL | 定位方式 | 评论ID | 父评论ID | 用户 | 用户主页 | 完整原话 | 发布时间 | 企业场景 | 需求证据 | 评分 | 身份置信度 | Ego验证状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for lead in rows:
        locator_url = lead.comment_url or (lead.url if lead.source_type in {"post", "answer", "content"} else "")
        evidence = "; ".join(lead.evidence_sentences or lead.reasons)
        verified = lead.locator_verified_at or "已验证"
        lines.append(
            f"| {_cell(lead.platform)} | {_cell(lead.source_type)} | {_cell(lead.content_title)} | "
            f"{_link(lead.url, lead.url)} | {_link(locator_url, locator_url)} | {_cell(lead.locator_method)} | "
            f"{_cell(lead.native_comment_id or lead.comment_id)} | {_cell(lead.parent_comment_id)} | {_cell(lead.user)} | "
            f"{_link(lead.profile_url, lead.profile_url)} | {_cell(lead.quote)} | {_cell(lead.locator_verified_at or '未知')} | "
            f"{_cell(lead.event_type or lead.category)} | {_cell(evidence)} | {lead.score} | {_cell(lead.identity_confidence)} | {_cell(verified)} |"
        )
    if not rows:
        lines.extend(["", "当前批次没有满足全部交付条件的记录。"])
    return "\n".join(lines) + "\n"


def write_verified_lead_artifacts(
    data_root: Path,
    run_id: str,
    leads: Iterable[LeadEvidence],
    locator_checks: Iterable[dict],
    url_checks: dict[str, dict] | None = None,
) -> dict[str, Path]:
    reports_root = data_root / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    selected = list(leads)
    markdown_path = reports_root / f"{run_id}-verified-leads.md"
    jsonl_path = reports_root / f"{run_id}-verified-leads.jsonl"
    locator_path = reports_root / f"{run_id}-locator-checks.json"
    write_report(markdown_path, render_verified_leads(run_id, selected))
    jsonl_path.write_text(
        "".join(json.dumps(lead.to_dict(), ensure_ascii=False) + "\n" for lead in selected),
        encoding="utf-8",
    )
    locator_path.write_text(
        json.dumps(
            {"run_id": run_id, "checks": list(locator_checks), "url_checks": url_checks or {}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"markdown": markdown_path, "jsonl": jsonl_path, "locators": locator_path}


def render_report(
    run_id: str,
    leads: Iterable[LeadEvidence],
    top_contents: Iterable[LeadEvidence],
    platform_status: dict,
    failures: dict[str, str],
    funnel_stats: dict | None = None,
    url_checks: dict[str, dict] | None = None,
) -> str:
    leads = sorted(leads, key=lambda item: (-item.score, item.platform, item.content_id))
    top_contents = list(top_contents)
    lines = [
        f"# POLYV 需求雷达日报：{run_id}",
        "",
        "## 运行状态",
        "",
        "| 平台 | 状态 | 内容数 | 评论数 | 内容/分钟 | 评论/分钟 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for platform, status in platform_status.items():
        lines.append(
            f"| {_cell(platform)} | {_cell(status.get('status'))} | "
            f"{status.get('contents', 0)} | {status.get('comments', 0)} | "
            f"{status.get('contents_per_minute', 0):.2f} | {status.get('comments_per_minute', 0):.2f} |"
        )
    for platform, reason in failures.items():
        lines.append(f"- {_cell(platform)}：{_cell(reason)}")

    if url_checks is not None:
        lines.extend(
            [
                "",
                "## 报告链接验证",
                "",
                "校验只判断公开网页是否可访问；需要登录、被限流或被平台拦截的链接单独标记，不当作已验证成功。",
                "",
                "| 链接 | 结果 | HTTP | 最终地址 | 说明 | 校验时间 |",
                "| --- | --- | ---: | --- | --- | --- |",
            ]
        )
        status_names = {
            "ok": "可访问",
            "not_found": "404/410",
            "blocked": "需登录/被拦截",
            "timeout": "超时",
            "invalid": "无效链接",
            "error": "网络错误",
            "failed": "失败",
        }
        for url, result in url_checks.items():
            lines.append(
                f"| [{_cell(url)}]({_cell(url)}) | {status_names.get(result.get('status'), result.get('status', '未知'))} | "
                f"{result.get('http_status', 0)} | {_cell(result.get('final_url', ''))} | "
                f"{_cell(result.get('reason', ''))} | {_cell(result.get('checked_at', ''))} |"
            )

    if funnel_stats:
        lines.extend(
            [
                "",
                "## 线索漏斗",
                "",
                "| 阶段 | 数量 |",
                "| --- | ---: |",
                f"| 初筛内容 | {funnel_stats.get('contents', 0)} |",
                f"| 初筛评论 | {funnel_stats.get('comments', 0)} |",
                f"| 原始内容 | {funnel_stats.get('raw_contents', 0)} |",
                f"| 原始评论 | {funnel_stats.get('raw_comments', 0)} |",
                f"| 规则候选 | {funnel_stats.get('prefilter', 0)} |",
                f"| 已调查主页 | {funnel_stats.get('profiles', 0)} |",
                f"| 公开来源 | {funnel_stats.get('external_evidence', 0)} |",
                f"| 模型通过 | {funnel_stats.get('model_passed', funnel_stats.get('high_value', 0))} |",
                f"| 证据不足 | {funnel_stats.get('evidence_insufficient', funnel_stats.get('review', 0))} |",
                f"| Ego Lite 定位通过 | {funnel_stats.get('locator_verified', 0)} |",
                f"| 可核验需求候选 | {funnel_stats.get('deliverable', 0)} |",
                f"| 人工确认高价值 | {funnel_stats.get('manual_confirmed', 0)} |",
            ]
        )
        query_stats = funnel_stats.get("query_stats", [])
        if query_stats:
            lines.extend(
                [
                    "",
                    "### 查询命中统计",
                    "",
                    "| 查询 | 内容 | 评论 | 候选 | 候选率 |",
                    "| --- | ---: | ---: | ---: | ---: |",
                ]
            )
            for item in query_stats:
                lines.append(
                    f"| {_cell(item['keyword'])} | {item['contents']} | {item['comments']} | {item['leads']} | {item.get('candidate_rate', 0):.2%} |"
                )

    threshold = int(funnel_stats.get("threshold", 4)) if funnel_stats else 4
    high_value = [
        lead
        for lead in leads
        if lead.score >= threshold
        and lead.stage == "model_reviewed"
        and lead.decision == "high_value"
    ]
    review_candidates = [
        lead
        for lead in leads
        if lead.stage == "model_fallback"
        or lead.decision == "review"
    ]
    demand_candidates = [
        lead
        for lead in leads
        if lead.score >= threshold and lead.decision != "reject"
    ]
    model_passed = [lead for lead in leads if lead.stage == "model_reviewed" and lead.decision == "high_value"]
    manual_confirmed = [lead for lead in leads if lead.decision == "manual_confirmed"]
    rejected_leads = [lead for lead in leads if lead.stage == "model_rejected" or lead.decision == "reject"]

    from .locator import select_deliverable_leads

    deliverable = select_deliverable_leads(leads, 20, threshold)
    lines.extend(
        [
            "",
            "## 可核验需求候选（最多20条）",
            "",
            "该列表只包含评分、企业场景、项目/选型/价格/交付证据和 Ego Lite 页面定位均通过的记录；评论没有平台直链时，评论定位URL为内容页，需结合作者与完整原话定位。",
            "",
            "| 平台 | 来源 | 内容标题 | 内容URL | 评论定位URL | 定位方式 | 评论ID | 父评论ID | 用户 | 用户主页 | 完整原话 | 企业场景 | 需求证据 | 评分 | 身份 | Ego验证 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for lead in deliverable:
        locator_url = lead.comment_url or (lead.url if lead.source_type in {"post", "answer", "content"} else "")
        evidence = "; ".join(lead.evidence_sentences or lead.reasons)
        lines.append(
            f"| {_cell(lead.platform)} | {_cell(lead.source_type)} | {_cell(lead.content_title)} | "
            f"{_link(lead.url, lead.url)} | {_link(locator_url, locator_url)} | {_cell(lead.locator_method)} | "
            f"{_cell(lead.native_comment_id or lead.comment_id)} | {_cell(lead.parent_comment_id)} | {_cell(lead.user)} | "
            f"{_link(lead.profile_url, lead.profile_url)} | {_cell(lead.quote)} | {_cell(lead.event_type or lead.category)} | "
            f"{_cell(evidence)} | {lead.score} | {_cell(lead.identity_confidence)} | {_cell(lead.locator_verified_at or '已验证')} |"
        )
    if not deliverable:
        lines.append("| - | - | 当前没有满足全部核验条件的记录 | - | - | - | - | - | - | - | - | - | - | - | - | - |")

    def append_lead_table(title: str, rows: list[LeadEvidence]) -> None:
        lines.extend(
            [
                "",
                title,
                "",
                "| 平台 | 用户 | 主页 | 业务事件 | 原话 | 需求类型 | POLYV方向 | 意向 | 身份 | 原文 | 证据 |",
                "| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |",
            ]
        )
        for lead in rows[:20]:
            evidence = "; ".join(lead.reasons + lead.evidence_urls)
            lines.append(
                f"| {_cell(lead.platform)} | {_cell(lead.user)} | "
                f"[主页]({_cell(lead.profile_url)}) | {_cell(lead.event_type)} | {_cell(lead.quote)} | "
                f"{_cell(lead.category)} | {_cell(lead.solution)} | {lead.score} | "
                f"{_cell(lead.identity_confidence)} | [原文]({_cell(lead.url)}) | {_cell(evidence)} |"
            )

    append_lead_table(f"## 需求候选（评分 ≥{threshold}，不等同于高价值）", demand_candidates)
    append_lead_table(f"## 高价值潜客 TOP20（评分 ≥{threshold}）", high_value)
    lines.extend(["", "> 上表只展示模型判定为高价值的记录；人工确认结果单独列出，不由模型自动写入。"])
    append_lead_table("## 模型通过（待人工确认）", model_passed)
    append_lead_table("## 人工确认高价值", manual_confirmed)
    append_lead_table(f"## 待复核候选（低于 {threshold} 分或模型要求复核）", review_candidates)

    lines.extend(
        [
            "",
            "## 已过滤记录与原因",
            "",
            "| 平台 | 用户 | 原话 | 模型分数 | 过滤原因 | 原文 |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for lead in rejected_leads[:50]:
        reason = lead.rejection_reason or "; ".join(lead.reasons) or "模型判定不满足高价值条件"
        lines.append(
            f"| {_cell(lead.platform)} | {_cell(lead.user)} | {_cell(lead.quote)} | {lead.score} | "
            f"{_cell(reason)} | [原文]({_cell(lead.url)}) |"
        )

    lines.extend(["", "## 🎯 高价值转化闭环实施方案（公域回复 + 视频选题 + 私信 + 资料包）", ""])
    from .conversion_engine import build_conversion_pack

    for index, lead in enumerate(top_contents[:10], start=1):
        pack = build_conversion_pack(lead)
        lines.extend(
            [
                f"### {index}. [{_cell(lead.platform).upper()}] {_cell(lead.content_title or lead.category)} (意向分: {lead.score})",
                f"- **目标链接**：[{_cell(lead.url)}]({_cell(lead.url)})",
                f"- **目标用户/原话**：@{_cell(lead.user)}：\"{_cell(lead.quote)}\"",
                f"- **匹配需求/方向**：{_cell(lead.category)} → {_cell(lead.solution)}",
                "",
                f"#### 1️⃣ 优先公域高价值回复（避坑建议，不硬推）：",
                f"> {pack.reply_text}",
                "",
                f"#### 2️⃣ 承接短视频选题与黄金 3 秒 Hook（主页信任飞轮）：",
                f"- **短视频选题**：**《{pack.video_topic}》**",
                f"- **黄金 3 秒 Hook**：\"{pack.video_hook}\"",
                "",
                f"#### 3️⃣ 私信沟通开场白（诊断式切入，非群发）：",
                f"> {pack.dm_opener}",
                "",
                f"#### 4️⃣ 推荐落地转化资料包：",
                f"- **对标案例**：{pack.recommended_materials['case']}",
                f"- **方案模板**：{pack.recommended_materials['template']}",
                f"- **演示体验**：{pack.recommended_materials['demo']}",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
