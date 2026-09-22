from __future__ import annotations

from pathlib import Path

from local_tools.polyv_radar.daily import _approved_items
from local_tools.polyv_radar.models import LeadEvidence
from local_tools.polyv_radar.storage import RadarStore


def test_daily_rebuilds_comment_target_from_lead_content_url(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    store.save_leads("run-1", [LeadEvidence(
        platform="xhs", content_id="note-1", comment_id="comment-1",
        url="https://www.xiaohongshu.com/explore/note-1",
        comment_url="https://www.xiaohongshu.com/user/profile/user-1",
        user="用户甲", quote="公司正在找平台报价", category="企业培训", solution="企业培训",
        score=6, stage="approved", decision="manual_confirmed", locator_status="verified",
    )])
    store.queue_outreach({
        "run_id": "run-1", "platform": "xhs", "content_id": "note-1", "comment_id": "comment-1",
        "lead_status": "approved", "target_url": "https://www.xiaohongshu.com/user/profile/user-1",
        "target_author": "用户甲", "draft_text": "测试回复",
    })

    rows, items = _approved_items(store, "run-1")

    assert len(rows) == 1
    assert items[0].url == "https://www.xiaohongshu.com/explore/note-1"
    assert items[0].content_url == "https://www.xiaohongshu.com/explore/note-1"
    assert items[0].source_type == "comment"
    store.close()
