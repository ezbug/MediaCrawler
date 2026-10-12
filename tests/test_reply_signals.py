import json
from pathlib import Path

from local_tools.polyv_radar.cumulative_dashboard import render_from_sources
from local_tools.polyv_radar.reply_signals import append_reply_signal, load_reply_signals, merge_reply_signals


def test_reply_signals_are_append_only_and_deduplicated(tmp_path: Path) -> None:
    first = append_reply_signal(
        tmp_path,
        {
            "platform": "dy",
            "target_url": "https://www.douyin.com/video/1",
            "target_author": "用户",
            "quote": "第一次回复",
            "wave": 1,
        },
    )
    second = append_reply_signal(
        tmp_path,
        {
            "platform": "dy",
            "target_url": "https://www.douyin.com/video/1",
            "target_author": "用户",
            "quote": "第一次回复",
            "wave": 1,
        },
    )
    assert first["written"] is True
    assert second["written"] is False
    rows = load_reply_signals(tmp_path)
    assert len(rows) == 1
    assert rows[0]["observed_at"]


def test_second_wave_signal_marks_dashboard_row(tmp_path: Path) -> None:
    append_reply_signal(
        tmp_path,
        {
            "platform": "dy",
            "target_url": "https://www.douyin.com/video/1",
            "target_author": "用户",
            "quote": "第二次回复",
            "wave": 2,
        },
    )
    rows = merge_reply_signals(
        [
            {
                "platform": "dy",
                "target_url": "https://www.douyin.com/video/1",
                "target_author": "用户",
            }
        ],
        tmp_path,
    )
    assert rows[0]["second_wave_reply"] is True
    assert rows[0]["reply_wave"] == 2
    assert rows[0]["reply_signal"] == "second_wave_reply"


def test_dashboard_shows_second_wave_signal(tmp_path: Path) -> None:
    ledger = tmp_path / "reply_history.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "platform": "dy",
                "target_url": "https://www.douyin.com/video/1",
                "target_author": "用户",
                "target_quote": "需要推荐",
                "reply_text": "先看流程",
                "mode": "live",
                "clicked": True,
                "submitted": True,
                "timestamp": "2026-10-12T08:00:00Z",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    append_reply_signal(
        tmp_path,
        {
            "platform": "dy",
            "target_url": "https://www.douyin.com/video/1",
            "target_author": "用户",
            "quote": "第二次回复",
            "wave": 2,
        },
    )
    html, view = render_from_sources(ledger, tmp_path)
    assert "二次回复待设计" in html
    assert view.target_count == 1
