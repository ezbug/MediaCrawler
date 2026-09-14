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

    lines.extend(
        [
            "",
            "## 高价值候选 TOP20",
            "",
            "| 平台 | 用户 | 原话 | 需求类型 | POLYV方向 | 意向 | 原文 | 证据 |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for lead in leads[:20]:
        evidence = "; ".join(lead.reasons)
        lines.append(
            f"| {_cell(lead.platform)} | {_cell(lead.user)} | {_cell(lead.quote)} | "
            f"{_cell(lead.category)} | {_cell(lead.solution)} | {lead.score} | "
            f"[原文]({_cell(lead.url)}) | {_cell(evidence)} |"
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
