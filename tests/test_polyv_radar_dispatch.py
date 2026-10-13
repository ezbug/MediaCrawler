from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from local_tools.polyv_radar.dispatch import (
    DispatchItem,
    build_dispatch_command,
    build_dispatch_queue,
    classify_dispatch_failure,
    dispatch_key,
    dispatch_queue,
    filter_previously_queued,
    load_dispatch_queue,
    verified_submission,
    write_dispatch_queue,
)
from local_tools.polyv_radar.models import LeadEvidence
from local_tools.polyv_radar.target_urls import dispatch_target_url, normalize_comment_url


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


def test_failed_dry_run_preserves_runtime_failure_reason(monkeypatch):
    from local_tools.polyv_radar import dispatch
    item = DispatchItem(platform="bili", url="https://example.test/video", author="Provider", text="Draft")
    monkeypatch.setattr(dispatch, "_read_structured_result", lambda *args: {
        "draft_verified": False, "failure_code": "input_unavailable", "submitted": False,
    })
    result = dispatch_queue([item], taskspace=1, runner=lambda *args, **kwargs:
                            subprocess.CompletedProcess(args[0], 1, stdout="", stderr="no editor"))
    assert result[0]["failure_code"] == "input_unavailable"
    assert result[0]["status"] == "failed"
    assert result[0]["submitted"] is False


def test_build_dispatch_queue_selects_verified_reviewed_leads_only() -> None:
    manual = _lead(decision="manual_confirmed")
    model = _lead(content_id="video-2", comment_id="comment-2")
    skipped = _lead(content_id="video-3", locator_status="pending")

    assert len(build_dispatch_queue([manual, model, skipped], "manual")) == 1
    assert len(build_dispatch_queue([manual, model, skipped], "model")) == 1


def test_comment_dispatch_opens_content_url_and_normalizes_profile_locator() -> None:
    content = "https://www.xiaohongshu.com/explore/note-1"
    profile = "https://www.xiaohongshu.com/user/profile/user-1"
    assert normalize_comment_url(profile, content, "comment") == content
    assert dispatch_target_url(content, profile, "comment") == content
    assert dispatch_target_url(content, content, "post") == content


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
    item = DispatchItem("dy", "https://www.douyin.com/video/1", "目标用户", "测试回复", own_account="我方账号")
    command = build_dispatch_command(item, taskspace=12, submit=True)
    assert command[0].endswith("polyv-lead-auto-reply/scripts/auto_reply")
    assert "--taskspace" in command and "12" in command and "--submit" in command
    assert "--page" in command and "p1" in command

    p2_command = build_dispatch_command(item, taskspace=12, submit=True, page="p2")
    assert "--page" in p2_command and "p2" in p2_command

    calls: list[list[str]] = []
    results = dispatch_queue(
        [item], taskspace=12, submit=True, cooldown_seconds=0,
        runner=lambda command, **_: calls.append(command) or subprocess.CompletedProcess(command, 0, "done", ""),
    )
    assert calls == [command]
    assert results[0]["status"] == "submitted_unverified"


def test_dispatch_command_preserves_source_type() -> None:
    item = DispatchItem(
        "xhs",
        "https://www.xiaohongshu.com/explore/note-1",
        "作者",
        "回复",
        source_type="post",
    )
    command = build_dispatch_command(item, taskspace=12, submit=False)
    assert "--source-type" in command
    assert command[command.index("--source-type") + 1] == "post"


def test_legacy_content_queue_without_source_type_infers_post_level(tmp_path: Path) -> None:
    path = tmp_path / "polyv-legacy-content-queue.jsonl"
    path.write_text(json.dumps({
        "platform": "xhs",
        "url": "https://www.xiaohongshu.com/explore/note-1",
        "author": "作者",
        "text": "回复",
        "quote": "活动报价",
        "comment_id": "",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    assert load_dispatch_queue(path)[0].source_type == "post"


def test_dispatch_failure_codes_separate_archive_and_evidence_errors() -> None:
    assert classify_dispatch_failure({}, "页面不见了") == "content_unavailable"
    assert classify_dispatch_failure({}, "Page.captureScreenshot timed out") == "screenshot_evidence_timeout"
    assert classify_dispatch_failure({}, "未找到小红书目标评论") == "target_not_found"


def test_dispatch_queue_preserves_target_quote_for_zhihu_matching() -> None:
    item = DispatchItem(
        "zhihu",
        "https://zhuanlan.zhihu.com/p/1",
        "起风了",
        "测试回复",
        quote="中小企业培训数字化选型",
        own_account="我方账号",
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
        [item], taskspace=12, submit=True, cooldown_seconds=0, own_account="我方账号",
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


def test_dispatch_identity_ignores_reply_wording_and_tracking_query() -> None:
    first = DispatchItem(
        "xhs",
        "https://www.xiaohongshu.com/explore/note-1?xsec_token=old&xsec_source=pc_feed",
        "作者",
        "第一版回复",
        content_id="note-1",
        comment_id="comment-1",
        author_id="user-1",
        quote="正在找企业培训平台",
    )
    second = DispatchItem(
        "xhs",
        "https://www.xiaohongshu.com/explore/note-1?xsec_token=new&xsec_source=pc_feed",
        "作者",
        "第二版回复",
        content_id="note-1",
        comment_id="comment-1",
        author_id="user-1",
        quote="正在找企业培训平台",
    )

    assert dispatch_key(first) == dispatch_key(second)


@pytest.mark.parametrize("account", ["", "Our account", "id:123"])
def test_own_account_round_trips_queue(tmp_path: Path, account: str) -> None:
    item = DispatchItem("xhs", "https://example.test/1", "Target", "Reply", own_account=account)
    path = tmp_path / "queue.jsonl"
    write_dispatch_queue(path, [item])
    assert load_dispatch_queue(path)[0].to_dict() == item.to_dict()
    command = build_dispatch_command(item, taskspace=1, submit=False)
    assert ("--own-account" in command) == bool(account)
    if account:
        assert command[command.index("--own-account") + 1] == account


def test_legacy_dry_run_without_account_remains_compatible(tmp_path: Path) -> None:
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps({"platform": "dy", "url": "https://example.test/1", "author": "Target", "text": "Reply"}) + "\n")
    items = load_dispatch_queue(path)
    assert items[0].own_account == ""
    results = dispatch_queue(items, taskspace=1, runner=lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", ""))
    assert results[0]["status"] == "dry_run"


@pytest.mark.parametrize("account", ["", "  "])
def test_submit_missing_account_fails_before_any_runner_or_runtime_check(monkeypatch: pytest.MonkeyPatch, account: str) -> None:
    from local_tools.polyv_radar import dispatch as module

    def unexpected(*args, **kwargs):
        pytest.fail("preflight must reject the batch before runner/runtime inspection")

    monkeypatch.setattr(module, "require_skill_runtime", unexpected)
    known = DispatchItem("dy", "https://example.test/1", "Target", "Reply", own_account="Our account")
    missing = DispatchItem("dy", "https://example.test/2", "Target", "Reply", own_account=account)
    with pytest.raises(ValueError, match="own_account"):
        build_dispatch_command(missing, taskspace=1, submit=True)
    with pytest.raises(ValueError, match="own_account"):
        dispatch_queue([known, missing], taskspace=1, submit=True, runner=unexpected)


def test_explicit_account_injection_fills_only_missing_item_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_tools.polyv_radar import dispatch as module

    monkeypatch.setattr(module, "_read_structured_result", lambda *_: None)
    items = [
        DispatchItem("dy", "https://example.test/1", "Target", "Reply"),
        DispatchItem("xhs", "https://example.test/2", "Target", "Reply", own_account="Item account"),
    ]
    calls = []
    results = dispatch_queue(
        items, taskspace=1, submit=True, own_account=" Explicit account ",
        runner=lambda cmd, **_: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    assert [cmd[cmd.index("--own-account") + 1] for cmd in calls] == ["Explicit account", "Item account"]
    assert [row["own_account"] for row in results] == ["Explicit account", "Item account"]
    assert items[0].own_account == ""


@pytest.mark.parametrize("field", ["posted_text", "own_account", "target_relation"])
@pytest.mark.parametrize("value", [None, False, "true", 1])
def test_verification_requires_positive_boolean_evidence(field: str, value: object) -> None:
    evidence = {"posted_text": True, "own_account": True, "target_relation": True}
    assert verified_submission({"submitted": True, "verified": True, "verification": evidence})
    evidence[field] = value
    assert not verified_submission({"submitted": True, "verified": True, "verification": evidence})


@pytest.mark.parametrize("evidence", [None, {}, [], "true"])
def test_legacy_verified_flag_alone_is_not_verified_submission(evidence: object) -> None:
    assert not verified_submission({"submitted": True, "verified": True, "verification": evidence})


@pytest.mark.parametrize("returncode", [0, 1])
@pytest.mark.parametrize("own_evidence", [None, False, True])
def test_runtime_result_ownership_controls_dispatch_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, returncode: int, own_evidence: bool | None) -> None:
    from local_tools.polyv_radar import dispatch as module

    history = tmp_path / "reply_history.jsonl"
    monkeypatch.setattr(module, "REPLY_HISTORY_PATH", history)
    item = DispatchItem("xhs", "https://example.test/1", "Target", "Reply", own_account="Our account")

    def runner(cmd, **kwargs):
        history.write_text(json.dumps({
            "platform": item.platform, "target_url": item.url,
            "target_author": item.author, "reply_text": item.text,
            "submitted": True, "verified": True, "status": "submitted_verified",
            "verification": {"posted_text": True, "own_account": own_evidence, "target_relation": True},
        }) + "\n")
        return subprocess.CompletedProcess(cmd, returncode, "", "")

    result = dispatch_queue([item], taskspace=1, submit=True, runner=runner)[0]
    assert result["verified"] is (own_evidence is True)
    assert result["status"] == ("submitted_verified" if own_evidence is True else "submitted_unverified")
    assert result["submitted"] is True
    assert result["structured_result"]["verified"] is True
