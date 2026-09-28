"""Acceptance tests for the Hermes takeover fixes.

Covers the two remaining required cases:

1. repeated worker results are idempotent (re-running the same batch is a no-op);
2. a clicked-but-unverified send suppresses a re-send (result unclear -> only
   re-check, never re-send).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_tools.polyv_radar import dispatch as dispatch_module
from local_tools.polyv_radar.dispatch import (
    DispatchItem,
    filter_previously_queued,
    write_dispatch_queue,
)


def _item(index: int = 1) -> DispatchItem:
    return DispatchItem(
        "zhihu",
        f"https://zhuanlan.zhihu.com/p/{index}",
        "企业HR",
        f"回复内容{index}",
        quote=f"公司需要培训平台，预算怎么算？{index}",
    )


def test_repeated_worker_results_are_idempotent(tmp_path: Path) -> None:
    """The same batch arriving twice must collapse, not duplicate."""
    items = [_item(1), _item(2)]

    # first worker run queues the batch
    dispatch_dir = tmp_path / "dispatch"
    write_dispatch_queue(dispatch_dir / "worker-batch-1.jsonl", items)

    # the identical batch arriving again changes nothing
    kept, skipped = filter_previously_queued(items, tmp_path)
    assert kept == []
    assert len(skipped) == 2
    assert all(row["reason"] == "already_queued_or_successfully_attempted" for row in skipped)

    # and running the filter a second time is still a no-op
    kept_again, skipped_again = filter_previously_queued(items, tmp_path)
    assert kept_again == []
    assert len(skipped_again) == 2


def test_new_targets_are_not_suppressed_by_idempotency(tmp_path: Path) -> None:
    dispatch_dir = tmp_path / "dispatch"
    write_dispatch_queue(dispatch_dir / "worker-batch-1.jsonl", [_item(1)])

    kept, skipped = filter_previously_queued([_item(2)], tmp_path)
    assert len(kept) == 1
    assert skipped == []


def test_clicked_but_unverified_send_suppresses_resend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Result unclear -> the target is NOT re-sent, only re-checked."""
    history = tmp_path / "reply_history.jsonl"
    item = _item(9)
    history.write_text(
        json.dumps({
            "timestamp": "2026-09-28T04:25:12.877Z",
            "platform": item.platform,
            "target_url": item.url,
            "target_author": item.author,
            "target_quote": item.quote,
            "reply_text": item.text,
            "mode": "live",
            "clicked": True,
            "submitted": True,      # submitted now mirrors `clicked`, not `verified`
            "verified": False,
            "status": "submitted_unverified",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dispatch_module, "REPLY_HISTORY_PATH", history)

    kept, skipped = filter_previously_queued([item], tmp_path)
    assert kept == []
    assert len(skipped) == 1


def test_rewording_does_not_reopen_a_closed_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A new draft for an already-touched target must still be suppressed."""
    history = tmp_path / "reply_history.jsonl"
    item = _item(4)
    history.write_text(
        json.dumps({
            "platform": item.platform,
            "target_url": item.url,
            "target_author": item.author,
            "target_quote": item.quote,
            "reply_text": "完全不同的第二版文案",
            "mode": "live",
            "clicked": True,
            "submitted": True,
            "verified": True,
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dispatch_module, "REPLY_HISTORY_PATH", history)

    kept, skipped = filter_previously_queued([item], tmp_path)
    assert kept == []
    assert len(skipped) == 1


def test_dry_run_history_does_not_close_a_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dry-run attempt must never block a real send later."""
    history = tmp_path / "reply_history.jsonl"
    item = _item(5)
    history.write_text(
        json.dumps({
            "platform": item.platform,
            "target_url": item.url,
            "target_author": item.author,
            "target_quote": item.quote,
            "reply_text": item.text,
            "mode": "dry_run",
            "clicked": False,
            "submitted": False,
            "verified": False,
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dispatch_module, "REPLY_HISTORY_PATH", history)

    kept, skipped = filter_previously_queued([item], tmp_path)
    assert len(kept) == 1
    assert skipped == []
