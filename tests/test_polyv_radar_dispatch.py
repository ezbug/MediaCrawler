from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from local_tools.polyv_radar.dispatch import (
    DispatchItem,
    build_dispatch_command,
    build_dispatch_queue,
    dispatch_queue,
    load_dispatch_queue,
    write_dispatch_queue,
)
from local_tools.polyv_radar.models import LeadEvidence


def _lead(**updates) -> LeadEvidence:
    lead = LeadEvidence(
        platform="dy", content_id="video-1", comment_id="comment-1",
        url="https://www.douyin.com/video/1", user="目标用户", quote="我们公司正在找培训平台",
        category="企业培训", solution="企业培训", score=8,
        stage="model_reviewed", decision="high_value", locator_status="verified",
        source_type="comment",
        dimensions={
            "business_scene": 2,
            "project_timing": 2,
            "platform_intent": 2,
            "delivery_inquiry": 1,
        },
    )
    for key, value in updates.items():
        setattr(lead, key, value)
    return lead


def test_build_dispatch_queue_selects_verified_reviewed_leads_only() -> None:
    manual = _lead(decision="manual_confirmed")
    model = _lead(content_id="video-2", comment_id="comment-2")
    skipped = _lead(content_id="video-3", locator_status="pending")

    assert len(build_dispatch_queue([manual, model, skipped], "manual")) == 1
    assert len(build_dispatch_queue([manual, model, skipped], "model")) == 1


def test_model_dispatch_rejects_generic_author_editorial_content() -> None:
    blocked = _lead(
        platform="zhihu",
        content_id="article-1",
        comment_id="",
        user="知乎答主",
        quote="中小企业培训数字化选型，别再交智商税了",
        content_title="中小企业培训数字化选型，别再交智商税了",
        source_type="post",
        dimensions={"business_scene": 2, "project_timing": 2, "platform_intent": 2, "identity": 1},
    )

    assert build_dispatch_queue([blocked], "model") == []


def test_dispatch_queue_uses_ego_wrapper_and_explicit_submit() -> None:
    item = DispatchItem("dy", "https://www.douyin.com/video/1", "目标用户", "测试回复")
    command = build_dispatch_command(item, taskspace=12, submit=True)
    assert command[0].endswith("polyv-lead-auto-reply/scripts/auto_reply")
    assert "--taskspace" in command and "12" in command and "--submit" in command

    calls: list[list[str]] = []
    results = dispatch_queue(
        [item], taskspace=12, submit=True, cooldown_seconds=0,
        runner=lambda command, **_: calls.append(command) or subprocess.CompletedProcess(command, 0, "done", ""),
    )
    assert calls == [command]
    assert results[0]["status"] == "submitted_unverified"


def test_dispatch_queue_preserves_target_quote_for_zhihu_matching() -> None:
    item = DispatchItem(
        "zhihu",
        "https://zhuanlan.zhihu.com/p/1",
        "起风了",
        "测试回复",
        quote="中小企业培训数字化选型",
    )
    command = build_dispatch_command(item, taskspace=8, submit=True)

    assert "--quote" in command
    assert "中小企业培训数字化选型" in command


def test_dispatch_queue_file_requires_target_author(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    path.write_text(json.dumps({"platform": "dy", "url": "https://example.test", "text": "回复"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="author"):
        load_dispatch_queue(path)

    valid = tmp_path / "valid.jsonl"
    write_dispatch_queue(valid, [DispatchItem("dy", "https://example.test", "用户", "回复")])
    assert load_dispatch_queue(valid)[0].author == "用户"


def test_dispatch_exit_zero_without_structured_success_is_unverified() -> None:
    item = DispatchItem("dy", "https://www.douyin.com/video/unverified", "目标用户", "回复内容")
    results = dispatch_queue(
        [item], taskspace=12, submit=True, cooldown_seconds=0,
        runner=lambda command, **_: subprocess.CompletedProcess(command, 0, "done", ""),
    )
    assert results[0]["status"] == "submitted_unverified"
    assert results[0]["lead_status"] == "submitted_unverified"


def test_dispatch_enforces_global_five_item_limit() -> None:
    items = [DispatchItem("dy", f"https://www.douyin.com/video/{index}", f"用户{index}", "回复") for index in range(6)]
    calls: list[list[str]] = []
    results = dispatch_queue(
        items, taskspace=12, submit=False, max_sends=5,
        runner=lambda command, **_: calls.append(command) or subprocess.CompletedProcess(command, 0, "ok", ""),
    )
    assert len(calls) == 5
    assert len(results) == 5
