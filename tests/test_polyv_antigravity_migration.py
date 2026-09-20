from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_tools.polyv_radar.antigravity_import import import_antigravity
from local_tools.polyv_radar.approval import approve_lead
from local_tools.polyv_radar.models import LeadEvidence
from local_tools.polyv_radar.status import transition
from local_tools.polyv_radar.storage import RadarStore
from local_tools.polyv_radar.config import RadarConfig


def test_import_maps_legacy_status_and_excludes_env(tmp_path: Path) -> None:
    source = tmp_path / "antigravity"
    source.mkdir()
    (source / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")
    (source / "leads_master_data.json").write_text(
        json.dumps([
            {
                "id": "LEAD-001",
                "platform": "抖音",
                "user_name": "用户甲",
                "pub_date": "2026-09-14",
                "url": "https://www.douyin.com/video/123",
                "original_inquiry": "我们公司下个月需要平台",
                "scenario": "企业培训",
                "stealth_hook_reply": "问题—机制—建议",
                "status": "pushed",
            },
            {
                "id": "LEAD-002",
                "platform": "B站",
                "user_name": "用户乙",
                "url": "https://www.bilibili.com/video/BV1test",
                "original_inquiry": "普通教程",
                "scenario": "技术学习",
                "status": "invalidated",
            },
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    result = import_antigravity(source, tmp_path / "data", "session-1")
    assert result["rows"] == 2
    assert result["submitted_verified"] == 0
    assert not (tmp_path / "data" / "legacy" / "antigravity-session-1" / ".env").exists()
    store = RadarStore(tmp_path / "data" / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads("legacy-antigravity-session-1")
    assert {lead.stage for lead in leads} == {"legacy_unverified", "legacy_rejected"}
    assert store.count("outreach_attempts") == 0
    assert len(store.load_status_events("legacy-antigravity-session-1")) == 2
    store.close()

    second = import_antigravity(source, tmp_path / "data", "session-1")
    assert second["rows"] == 2
    store = RadarStore(tmp_path / "data" / "radar.sqlite3")
    store.initialize()
    assert store.count("leads") == 2
    assert store.count_status_events("legacy-antigravity-session-1", distinct=True) == 2
    assert store.count_status_events("legacy-antigravity-session-1", distinct=False) == 2
    store.close()


def test_approval_requires_locator_and_url_and_creates_queue(tmp_path: Path) -> None:
    config = RadarConfig(data_root=tmp_path / "data", platforms=["dy"], keywords={})
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    lead = LeadEvidence(
        platform="dy", content_id="v1", comment_id="c1", url="https://www.douyin.com/video/1",
        user="用户甲", quote="公司正在找平台报价", category="企业直播", solution="企业直播",
        score=6, dimensions={"business_scene": 2, "project_timing": 2, "platform_intent": 2},
        stage="model_reviewed", decision="high_value", locator_status="verified",
    )
    store.save_leads("run-1", [lead])
    store.close()
    result = approve_lead(config, "run-1", "c1", url_checker=lambda _: {"status": "ok", "http_status": 200})
    assert result["status"] == "approved"
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    queued = store.load_outreach_queue("run-1")
    assert len(queued) == 1
    assert queued[0]["lead_status"] == "approved"
    assert store.load_leads("run-1")[0].decision == "manual_confirmed"
    store.close()


def test_legacy_lead_cannot_skip_reverification(tmp_path: Path) -> None:
    config = RadarConfig(data_root=tmp_path / "data", platforms=["dy"], keywords={})
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    store.save_leads("run-1", [LeadEvidence(
        platform="dy", content_id="v1", comment_id="legacy:LEAD-1", url="https://www.douyin.com/video/1",
        user="用户甲", quote="需求", category="企业直播", solution="企业直播", score=4,
        stage="legacy_unverified", decision="legacy_unverified", locator_status="verified",
    )])
    store.close()
    with pytest.raises(ValueError, match="历史未验证"):
        approve_lead(config, "run-1", "LEAD-1", url_checker=lambda _: {"status": "ok"})


def test_approval_can_use_ego_url_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = RadarConfig(data_root=tmp_path / "data", platforms=["zhihu"], keywords={})
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    lead = LeadEvidence(
        platform="zhihu", content_id="article-1", comment_id="", url="https://zhuanlan.zhihu.com/p/1",
        comment_url="https://zhuanlan.zhihu.com/p/1", user="起风了", quote="我们公司需要企业培训平台",
        category="企业培训", solution="企业培训", score=7,
        content_title="企业培训需求",
        dimensions={"business_scene": 2, "project_timing": 2, "platform_intent": 2},
        stage="model_reviewed", decision="high_value", locator_status="verified",
    )
    store.save_leads("run-ego", [lead])
    store.close()

    calls = []

    def fake_ego_check(urls, repo_root, work_dir, taskspace=None, **_):
        calls.append((urls, repo_root, work_dir, taskspace))
        return ({lead.url: {"url": lead.url, "status": "ok", "http_status": 403, "reason": "Ego Lite页面可访问"}}, "")

    monkeypatch.setattr("local_tools.polyv_radar.approval.validate_urls_with_ego", fake_ego_check)
    result = approve_lead(config, "run-ego", "article-1", repo_root=tmp_path, taskspace=8)

    assert result["status"] == "approved"
    assert calls and calls[0][3] == 8


def test_status_machine_rejects_skipping_approval() -> None:
    assert transition("model_reviewed", "approved").new == "approved"
    with pytest.raises(ValueError):
        transition("discovered", "submitted_verified")
