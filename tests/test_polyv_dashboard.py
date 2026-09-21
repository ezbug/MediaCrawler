from __future__ import annotations

import json
from pathlib import Path

from local_tools.polyv_radar.dashboard import clean_dashboard_leads, load_dry_run_queue
from local_tools.polyv_radar.models import LeadEvidence


def _lead(**updates) -> LeadEvidence:
    lead = LeadEvidence(
        platform="zhihu",
        content_id="answer-1",
        comment_id="",
        url="https://www.zhihu.com/question/1/answer/2",
        user="aidou",
        quote="公司年会要搞线上直播，有好的直播平台推荐吗？",
        category="企业直播",
        solution="企业直播方向",
        score=5,
        company="高新科技",
        profile_url="https://www.zhihu.com/people/aidou",
        author_id="aidou-id",
        identity_confidence="high",
        dimensions={"business_scene": 2, "platform_intent": 2, "identity": 1},
        stage="model_reviewed",
        decision="high_value",
        intent_class="buyer_request",
        locator_status="verified",
    )
    for key, value in updates.items():
        setattr(lead, key, value)
    return lead


def test_dashboard_cleaning_keeps_verified_buyer_and_audits_noise() -> None:
    kept, filtered = clean_dashboard_leads(
        [_lead(), _lead(content_id="answer-2", user="平台服务商", company="", profile_bio="直播平台解决方案", locator_status="verified")]
    )
    assert [lead.content_id for lead in kept] == ["answer-1"]
    assert filtered[0]["reason"]


def test_dashboard_cleaning_does_not_treat_raw_score_as_verified() -> None:
    kept, filtered = clean_dashboard_leads([_lead(locator_status="pending")])
    assert kept == []
    assert "定位" in filtered[0]["reason"]


def test_dashboard_reads_file_queue_and_matches_dry_run_result(tmp_path: Path) -> None:
    dispatch = tmp_path / "dispatch"
    dispatch.mkdir()
    queue = {
        "platform": "zhihu",
        "url": "https://www.zhihu.com/question/1/answer/2",
        "author": "aidou",
        "text": "测试草稿",
        "content_id": "answer-1",
        "comment_id": "",
        "quote": "公司年会要搞线上直播，有好的直播平台推荐吗？",
    }
    (dispatch / "run-1-model.jsonl").write_text(json.dumps(queue, ensure_ascii=False) + "\n", encoding="utf-8")
    result = {**queue, "status": "dry_run", "structured_result": {"draft_verified": True}, "screenshot": "/tmp/preview.png"}
    (dispatch / "dispatch-1.jsonl").write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = load_dry_run_queue(tmp_path, "run-1")
    assert len(rows) == 1
    assert rows[0]["source"] == "dispatch_file"
    assert rows[0]["dry_run_status"] == "dry_run"
    assert rows[0]["submitted"] is False


def test_dashboard_reads_verified_send_from_structured_dispatch_result(tmp_path: Path) -> None:
    dispatch = tmp_path / "dispatch"
    dispatch.mkdir()
    queue = {
        "platform": "zhihu",
        "url": "https://www.zhihu.com/question/1/answer/2",
        "author": "aidou",
        "text": "测试回复",
        "content_id": "answer-1",
        "comment_id": "",
        "quote": "公司年会要搞线上直播，有好的直播平台推荐吗？",
    }
    (dispatch / "run-1-model.jsonl").write_text(json.dumps(queue, ensure_ascii=False) + "\n", encoding="utf-8")
    result = {
        **queue,
        "status": "submitted_verified",
        "structured_result": {"submitted": True, "verified": True, "target_matched": True},
    }
    (dispatch / "dispatch-1.jsonl").write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = load_dry_run_queue(tmp_path, "run-1")
    assert rows[0]["dry_run_status"] == "submitted_verified"
    assert rows[0]["submitted"] is True
    assert rows[0]["verified"] is True
    assert rows[0]["lead_status"] == "submitted_verified"
