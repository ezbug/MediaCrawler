from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import LeadEvidence


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def render_report(
    run_id: str,
    leads: Iterable[LeadEvidence],
    top_contents: Iterable[LeadEvidence],
    platform_status: dict,
    failures: dict[str, str],
    funnel_stats: dict | None = None,
) -> str:
    leads = sorted(leads, key=lambda item: (-item.score, item.platform, item.content_id))
    top_contents = list(top_contents)
    lines = [f"# POLYV 需求雷达日报：{run_id}", "", "## 运行状态", "", "| 平台 | 状态 | 内容数 | 评论数 |", "| --- | --- | ---: | ---: |"]
    for platform, status in platform_status.items():
        lines.append(
            f"| {_cell(platform)} | {_cell(status.get('status'))} | "
            f"{status.get('contents', 0)} | {status.get('comments', 0)} |"
        )
    for platform, reason in failures.items():
        lines.append(f"- {_cell(platform)}：{_cell(reason)}")

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
                f"| 规则候选 | {funnel_stats.get('prefilter', 0)} |",
                f"| 已调查主页 | {funnel_stats.get('profiles', 0)} |",
                f"| 公开来源 | {funnel_stats.get('external_evidence', 0)} |",
                f"| 模型高价值 | {funnel_stats.get('high_value', 0)} |",
                f"| 待人工复核 | {funnel_stats.get('review', 0)} |",
            ]
        )
        query_stats = funnel_stats.get("query_stats", [])
        if query_stats:
            lines.extend(
                [
                    "",
                    "### 查询命中统计",
                    "",
                    "| 查询 | 内容 | 评论 | 候选 |",
                    "| --- | ---: | ---: | ---: |",
                ]
            )
            for item in query_stats:
                lines.append(
                    f"| {_cell(item['keyword'])} | {item['contents']} | {item['comments']} | {item['leads']} |"
                )

    high_value = [lead for lead in leads if lead.score >= 6 and lead.stage != "model_rejected" and lead.stage != "model_fallback"]
    review_candidates = [lead for lead in leads if 4 <= lead.score < 6 or lead.stage == "model_fallback"]

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

    append_lead_table("## 高价值潜客 TOP20（评分 ≥6）", high_value)
    append_lead_table("## 待复核候选（评分 4～5）", review_candidates)

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
