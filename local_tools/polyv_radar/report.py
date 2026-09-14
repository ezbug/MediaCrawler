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

    lines.extend(["", "## 高价值内容 TOP10", ""])
    for index, lead in enumerate(top_contents[:10], start=1):
        lines.extend(
            [
                f"### {index}. {_cell(lead.content_title or lead.category)}",
                f"- 平台：{_cell(lead.platform)}",
                f"- 原文：[打开]({_cell(lead.url)})",
                f"- 关键原话：{_cell(lead.quote)}",
                f"- 建议回复：这类场景可以从直播稳定性、内容安全和培训交付三个方面评估。我是POLYV相关方向的学习者，公开说明一下我们可提供对应的视频直播与点播能力，具体以官方方案为准。",
                "",
            ]
        )
    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
