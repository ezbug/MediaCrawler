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
    filter_previously_queued,
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


def test_cross_batch_successful_dry_run_is_deduplicated(tmp_path: Path) -> None:
    item = DispatchItem("zhihu", "https://www.zhihu.com/question/1/answer/2", "用户", "回复内容")
    dispatch_dir = tmp_path / "dispatch"
    write_dispatch_queue(dispatch_dir / "old-run-model.jsonl", [item])
    (dispatch_dir / "dispatch-old-dry-run.jsonl").write_text(
        json.dumps({**item.to_dict(), "status": "dry_run", "mode": "dry_run", "draft_verified": True}) + "\n",
        encoding="utf-8",
    )

    kept, skipped = filter_previously_queued([item], tmp_path)

    assert kept == []
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "already_queued_or_successfully_attempted"


def test_failed_result_remains_retryable(tmp_path: Path) -> None:
    item = DispatchItem("zhihu", "https://www.zhihu.com/question/1/answer/2", "用户", "回复内容")
    dispatch_dir = tmp_path / "dispatch"
    write_dispatch_queue(dispatch_dir / "old-run-model.jsonl", [item])
    (dispatch_dir / "dispatch-old-failed.jsonl").write_text(
        json.dumps({**item.to_dict(), "status": "target_not_found", "mode": "dry_run", "target_matched": False}) + "\n",
        encoding="utf-8",
    )

    kept, skipped = filter_previously_queued([item], tmp_path)

    assert kept == [item]
    assert skipped == []


def test_live_reply_history_suppresses_duplicate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from local_tools.polyv_radar import dispatch as dispatch_module

    history = tmp_path / "reply_history.jsonl"
    item = DispatchItem("dy", "https://www.douyin.com/video/1", "用户", "回复内容")
    history.write_text(
        json.dumps({
            "platform": item.platform,
            "target_url": item.url,
            "target_author": item.author,
            "reply_text": item.text,
            "submitted": True,
            "mode": "submit",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dispatch_module, "REPLY_HISTORY_PATH", history)

    kept, skipped = filter_previously_queued([item], tmp_path)

    assert kept == []
    assert len(skipped) == 1
