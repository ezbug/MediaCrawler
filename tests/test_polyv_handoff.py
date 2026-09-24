from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from local_tools.polyv_radar.handoff import export_handoff
from local_tools.polyv_radar.cli import build_parser


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data_root = tmp_path / "data"
    dispatch = data_root / "dispatch"
    queue_path = dispatch / "20260923-leads100-strict.jsonl"
    result_path = dispatch / "dispatch-20260923-leads100-strict-live.jsonl"
    screenshot = data_root / "reports" / "reply_preview_test.png"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"preview-image")
    queued = {
        "platform": "xhs",
        "url": "https://www.xiaohongshu.com/explore/note-1?xsec_token=ephemeral#comment-c-1",
        "author": "Example User",
        "text": "回复草稿",
        "content_id": "note-1",
        "comment_id": "c-1",
        "quote": "我们公司下个月找培训平台",
        "content_url": "https://www.xiaohongshu.com/explore/note-1?xsec_token=ephemeral",
        "comment_url": "https://www.xiaohongshu.com/explore/note-1#comment-c-1",
        "source_type": "comment",
        "locator_status": "verified",
    }
    _jsonl(queue_path, [queued])
    _jsonl(result_path, [{
        **queued,
        "status": "submitted_verified",
        "submitted": True,
        "verified": True,
        "timestamp": "2026-09-23T00:00:00Z",
        "screenshot": str(screenshot),
    }])
    _jsonl(data_root / "reply_history.jsonl", [{
        "platform": "xhs",
        "target_url": queued["url"],
        "target_author": queued["author"],
        "reply_text": queued["text"],
        "mode": "submit",
        "submitted": True,
        "verified": True,
        "timestamp": "2026-09-23T00:00:00Z",
        "screenshot": str(screenshot),
    }])
    locators = data_root / "locators"
    locators.mkdir()
    (locators / "20260923-leads100-output.json").write_text(json.dumps({"results": [{
        "candidate_id": "candidate-1",
        "platform": "xhs",
        "content_id": "note-1",
        "comment_id": "c-1",
        "user": "Example User",
        "author_id": "author-1",
        "quote": queued["quote"],
        "content_url": queued["content_url"],
        "comment_url": queued["comment_url"],
        "source_type": "comment",
        "status": "verified",
        "verified_at": "2026-09-22T00:00:00Z",
    }]}), encoding="utf-8")
    (locators / "20260923-leads100-input.json").write_text(json.dumps({"candidates": [{
        "candidate_id": "candidate-1",
        "platform": "xhs",
        "content_id": "note-1",
        "comment_id": "c-1",
        "user": "Example User",
        "author_id": "author-1",
        "quote": queued["quote"],
        "source_type": "comment",
    }]}), encoding="utf-8")
    review_path = data_root / "review" / "polyv-100-quality-review.jsonl"
    _jsonl(review_path, [{
        "platform": "xhs",
        "content_id": "note-1",
        "comment_id": "c-1",
        "author": "Example User",
        "quote": queued["quote"],
        "quality_status": "not_established",
        "quality_reason": "缺少可核验的数字化交付需求证据。",
        "reviewed_by": "Codex local evidence audit",
    }])
    return data_root, queue_path, result_path, review_path


def test_export_cross_checks_send_history_and_separates_preview_evidence(tmp_path: Path) -> None:
    data_root, queue_path, result_path, review_path = _fixture(tmp_path)

    result = export_handoff(
        data_root,
        campaign="polyv-100",
        repo_root=tmp_path,
        revision="f" * 40,
        queue_path=queue_path,
        results_path=result_path,
        quality_review_path=review_path,
    )

    ledger = [json.loads(line) for line in Path(result["ledger_path"]).read_text().splitlines()]
    assert result["counts"]["dispatch_verified"] == 1
    assert result["counts"]["runtime_verified"] == 1
    assert result["counts"]["qualified"] == 0
    send = ledger[0]["dispatch"][0]
    assert send["status"] == "submitted_verified"
    assert send["reply_history_match"] is True
    assert send["screenshot"]["visual_evidence_state"] == "draft_preview_only"
    assert send["screenshot"]["post_send_screenshot"] is False
    assert ledger[0]["quality"]["status"] == "not_established"
    assert "xsec_token" not in ledger[0]["content_url"]


def test_export_is_content_addressed_and_never_rewrites_existing_snapshot(tmp_path: Path) -> None:
    data_root, queue_path, result_path, review_path = _fixture(tmp_path)
    kwargs = dict(
        data_root=data_root,
        campaign="polyv-100",
        repo_root=tmp_path,
        revision="a" * 40,
        queue_path=queue_path,
        results_path=result_path,
        quality_review_path=review_path,
    )

    first = export_handoff(**kwargs)
    manifest_path = Path(first["manifest_path"])
    ledger_path = Path(first["ledger_path"])
    history_path = data_root / "reply_history.jsonl"
    history_before = history_path.read_bytes()
    before = (manifest_path.read_bytes(), ledger_path.read_bytes())
    second = export_handoff(**kwargs)

    assert second["snapshot_id"] == first["snapshot_id"]
    assert (manifest_path.read_bytes(), ledger_path.read_bytes()) == before
    assert history_path.read_bytes() == history_before
    manifest = json.loads(manifest_path.read_text())
    assert manifest["git_revision"] == "a" * 40
    assert manifest["ledger_sha256"] == hashlib.sha256(ledger_path.read_bytes()).hexdigest()


def test_missing_reply_history_does_not_count_reported_success_as_verified(tmp_path: Path) -> None:
    data_root, queue_path, result_path, review_path = _fixture(tmp_path)
    (data_root / "reply_history.jsonl").write_text("", encoding="utf-8")

    result = export_handoff(
        data_root,
        campaign="polyv-100",
        repo_root=tmp_path,
        revision="b" * 40,
        queue_path=queue_path,
        results_path=result_path,
        quality_review_path=review_path,
    )

    assert result["counts"]["dispatch_verified"] == 1
    assert result["counts"]["runtime_verified"] == 0
    ledger = [json.loads(line) for line in Path(result["ledger_path"]).read_text().splitlines()]
    assert ledger[0]["dispatch"][0]["status"] == "reported_verified_history_missing"


def test_same_display_name_without_stable_id_does_not_merge_leads(tmp_path: Path) -> None:
    data_root, queue_path, result_path, review_path = _fixture(tmp_path)
    candidates_path = data_root / "locators" / "20260923-leads100-output.json"
    payload = json.loads(candidates_path.read_text())
    second = dict(payload["results"][0], candidate_id="candidate-2", content_id="note-2", comment_id="c-2", author_id="")
    payload["results"].append(second)
    candidates_path.write_text(json.dumps(payload), encoding="utf-8")
    inputs_path = data_root / "locators" / "20260923-leads100-input.json"
    inputs = json.loads(inputs_path.read_text())
    inputs["candidates"].append(second)
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")

    result = export_handoff(
        data_root,
        campaign="polyv-100",
        repo_root=tmp_path,
        revision="c" * 40,
        queue_path=queue_path,
        results_path=result_path,
        quality_review_path=review_path,
    )

    assert result["counts"]["candidate_pool_records"] == 2
    assert result["counts"]["unique_author_ids"] == 1
    assert result["counts"]["remaining_gap_to_target"] is None
    ledger = [json.loads(line) for line in Path(result["ledger_path"]).read_text().splitlines()]
    assert len({row["record_key"] for row in ledger}) == 2


def test_explicit_queue_and_result_paths_must_match_campaign(tmp_path: Path) -> None:
    data_root, queue_path, result_path, _ = _fixture(tmp_path)
    wrong = data_root / "dispatch" / "another-campaign.jsonl"
    _jsonl(wrong, [])

    with pytest.raises(ValueError, match="campaign"):
        export_handoff(
            data_root,
            campaign="polyv-100",
            repo_root=tmp_path,
            revision="d" * 40,
            queue_path=wrong,
            results_path=result_path,
        )


def test_cli_exposes_handoff_export_with_campaign_and_optional_evidence_paths() -> None:
    args = build_parser().parse_args([
        "handoff-export",
        "--config", "local_tools/polyv_radar/pilot.toml",
        "--campaign", "polyv-100",
        "--queue", "queue.jsonl",
        "--results", "results.jsonl",
        "--quality-review", "quality.jsonl",
    ])

    assert args.command == "handoff-export"
    assert args.campaign == "polyv-100"
    assert args.quality_review == "quality.jsonl"


def test_dry_run_does_not_write_snapshot(tmp_path: Path) -> None:
    data_root, queue_path, result_path, review_path = _fixture(tmp_path)

    result = export_handoff(
        data_root,
        campaign="polyv-100",
        repo_root=tmp_path,
        revision="1" * 40,
        queue_path=queue_path,
        results_path=result_path,
        quality_review_path=review_path,
        write=False,
    )

    assert not Path(result["manifest_path"]).exists()
    assert not Path(result["ledger_path"]).exists()


def test_changed_source_creates_new_snapshot_and_preserves_previous_one(tmp_path: Path) -> None:
    data_root, queue_path, result_path, review_path = _fixture(tmp_path)
    kwargs = dict(
        data_root=data_root,
        campaign="polyv-100",
        repo_root=tmp_path,
        revision="e" * 40,
        queue_path=queue_path,
        results_path=result_path,
        quality_review_path=review_path,
    )
    first = export_handoff(**kwargs)
    old_manifest = Path(first["manifest_path"]).read_bytes()
    with queue_path.open("a", encoding="utf-8") as queue:
        queue.write("\n")
    second = export_handoff(**kwargs)

    assert second["snapshot_id"] != first["snapshot_id"]
    assert Path(first["manifest_path"]).read_bytes() == old_manifest
