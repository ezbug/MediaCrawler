from pathlib import Path

from local_tools.polyv_radar.html_dashboard import _dispatch_status, _status, render_html_dashboard


def test_html_dashboard_renders_current_manual_candidates_and_locator_status(tmp_path: Path) -> None:
    review = tmp_path / "review"
    review.mkdir()
    (review / "run-1-manual-candidates.jsonl").write_text(
        '{"candidate_id":"manual-1","platform":"xhs","user":"用户","author_id":"a1",'
        '"published_at":"2026-09-21","freshness":"current","triage_label":"keep_current",'
        '"quote":"公司需要培训平台","source_role":"unknown","rule_score":4,'
        '"candidate_kind":"manual_review","reply_draft":"草稿文本",'
        '"content_url":"https://example.com/content","comment_url":"https://example.com/comment"}\n',
        encoding="utf-8",
    )
    (review / "run-1-manual-locator.jsonl").write_text(
        '{"candidate_id":"manual-1","status":"verified","locator_method":"native_id",'
        '"locator_url":"https://example.com/comment#1","reason":"唯一命中",'
        '"dry_run_status":"dry_run","target_matched":true,"draft_verified":true}\n',
        encoding="utf-8",
    )
    rendered = render_html_dashboard(tmp_path, "run-1")
    assert "POLYV 需求候选 HTML 大板" in rendered
    assert "定位通过" in rendered
    assert "公司需要培训平台" in rendered
    assert "Ego Lite 已定位" in rendered
    assert "Dry-Run通过" in rendered
    assert "草稿文本" in rendered


def test_html_dashboard_prefers_specific_failure_code_over_generic_status() -> None:
    row = {
        "dispatch_status": "target_not_found",
        "failure_code": "target_url_normalization",
    }

    assert _status(row) == ("blocked", "目标地址规范化失败")
    assert _dispatch_status(row) == ("blocked", "目标地址规范化失败")
