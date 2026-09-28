from local_tools.polyv_radar.qna_batch import _draft, _is_noise, build_locator_rows


def test_qna_batch_rejects_provider_and_generic_discussion() -> None:
    assert _is_noise({"quote": "预算直接报多两个0", "content_title": "企业线上年会直播"})
    assert _is_noise({"quote": "来了，直播技术全案供应商", "content_title": "年会直播供应商"})
    assert _is_noise({"quote": "这个老师怎么样？适合制造业不？", "content_title": "公司请老师来培训"})


def test_qna_batch_keeps_actionable_historical_request_and_uses_reactivation_copy() -> None:
    row = {
        "quote": "北京海淀60人报价",
        "content_title": "公司年会方案",
        "freshness": "historical",
        "category": "企业活动",
    }
    assert not _is_noise(row)
    draft = _draft(row)
    assert "现在这方面还有需求吗" in draft
    assert "POLYV" in draft


def test_locator_rows_keep_origin_and_reply_text() -> None:
    rows = build_locator_rows([
        {
            "origin_run_id": "run-1",
            "platform": "xhs",
            "content_url": "https://example.test/note",
            "user": "用户",
            "quote": "公司需要培训平台",
            "reply_text": "可以按场景梳理方案。",
        }
    ])
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["reply_text"] == "可以按场景梳理方案。"
