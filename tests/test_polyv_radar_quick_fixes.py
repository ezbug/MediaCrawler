from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from local_tools.polyv_radar.adapters import normalize_comment, normalize_content
from local_tools.polyv_radar.config import RadarConfig
from local_tools.polyv_radar.report import render_report
from local_tools.polyv_radar.runner import report_store
from local_tools.polyv_radar.runner import analyze_records, ingest_existing_run
from local_tools.polyv_radar.storage import RadarStore


def _content(platform: str, content_id: str, title: str, keyword: str):
    raw = {
        "title": title,
        "desc": title,
        "content_id": content_id,
        "url": "https://example.invalid/source/" + content_id,
        "create_time": 1788000000,
    }
    return normalize_content(platform, raw, keyword)


def test_bilibili_raw_url_is_normalized_to_a_valid_bv_url() -> None:
    item = normalize_content(
        "bili",
        {
            "bvid": "BV1fwRQB5ETc",
            "title": "直播 SDK 集成",
            "url": "https://www.bilibili.com/video/avBV1fwRQB5ETc",
        },
        "直播SDK",
    )

    assert item is not None
    assert item.url == "https://www.bilibili.com/video/BV1fwRQB5ETc/"


def test_store_can_scope_contents_and_comments_to_a_run(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    first = _content("dy", "video-1", "企业培训直播", "企业培训")
    second = _content("dy", "video-2", "企业培训直播", "企业培训")
    comment = normalize_comment(
        "dy",
        {"comment_id": "comment-1", "content_id": "video-1", "content": "公司需要培训直播"},
        source_keyword="企业培训",
    )
    assert first is not None and second is not None and comment is not None

    store.upsert_content(first, run_id="run-a")
    store.upsert_content(second, run_id="run-b")
    store.upsert_comment(comment, run_id="run-a")

    assert [item.content_id for item in store.iter_contents("run-a")] == ["video-1"]
    assert [item.comment_id for item in store.iter_comments("run-a")] == ["comment-1"]
    assert [item.content_id for item in store.iter_contents("run-b")] == ["video-2"]
    store.close()


def test_ingest_counts_comments_and_marks_complete_platform(tmp_path: Path) -> None:
    output_dir = tmp_path / "radar-data" / "raw" / "run-1" / "dy" / "企业培训" / "dy" / "jsonl"
    output_dir.mkdir(parents=True)
    (output_dir / "search_contents.jsonl").write_text(
        '{"aweme_id":"dy-1","desc":"企业培训直播","aweme_url":"https://www.douyin.com/video/dy-1"}\n',
        encoding="utf-8",
    )
    (output_dir / "search_comments.jsonl").write_text(
        '{"comment_id":"c-1","aweme_id":"dy-1","content":"公司需要培训直播平台"}\n',
        encoding="utf-8",
    )

    result = ingest_existing_run(
        RadarConfig(data_root=tmp_path / "radar-data", platforms=["dy"], keywords={"企业培训": "企业培训"}),
        "run-1",
    )

    assert result.platform_status["dy"] == {"status": "success", "contents": 1, "comments": 1, "tasks": 1}


def test_ingest_preserves_existing_run_timing(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar-data" / "radar.sqlite3")
    store.initialize()
    store.save_run(
        "run-1",
        "partial",
        {"dy": {"status": "partial", "contents": 0, "comments": 0, "tasks": 1}},
        "2026-09-15T01:00:00+00:00",
        "2026-09-15T01:02:00+00:00",
    )
    store.close()

    ingest_existing_run(
        RadarConfig(data_root=tmp_path / "radar-data", platforms=["dy"], keywords={"企业培训": "企业培训"}),
        "run-1",
    )

    store = RadarStore(tmp_path / "radar-data" / "radar.sqlite3")
    store.initialize()
    row = store.connection.execute(
        "SELECT started_at, finished_at FROM runs WHERE run_id = ?", ("run-1",)
    ).fetchone()
    assert row["started_at"] == "2026-09-15T01:00:00+00:00"
    assert row["finished_at"] == "2026-09-15T01:02:00+00:00"
    store.close()


def test_unrelated_comment_is_filtered_even_when_keyword_has_a_category_hint() -> None:
    content = _content("bili", "b-1", "AI编程课程实战", "企业培训")
    comment = normalize_comment(
        "bili",
        {"comment_id": "c-1", "content_id": "b-1", "nickname": "用户", "content": "老板让我上来说体面一点吗"},
        source_keyword="企业培训",
    )
    assert content is not None and comment is not None

    assert analyze_records(
        [content], [comment], now=datetime(2026, 9, 14, tzinfo=timezone.utc), category_by_keyword={"企业培训": "企业培训"}
    ) == []


def test_semantically_duplicate_comments_are_returned_once() -> None:
    content = _content("dy", "dy-1", "企业培训直播方案", "企业培训")
    first = normalize_comment(
        "dy",
        {"comment_id": "c-1", "content_id": "dy-1", "nickname": "用户", "content": "我们公司需要培训直播平台，多少钱？", "create_time": 1788000000},
        source_keyword="企业培训",
    )
    duplicate = normalize_comment(
        "dy",
        {"comment_id": "c-2", "content_id": "dy-1", "nickname": "用户", "content": "我们公司需要培训直播平台，多少钱？", "create_time": 1788000000},
        source_keyword="企业培训",
    )
    assert content is not None and first is not None and duplicate is not None

    leads = analyze_records(
        [content], [first, duplicate], now=datetime(2026, 9, 14, tzinfo=timezone.utc), category_by_keyword={"企业培训": "企业培训"}
    )

    assert len(leads) == 1


def test_report_separates_high_value_and_review_candidates() -> None:
    high = _lead(score=6)
    review = _lead(score=5)
    rejected = _lead(score=0)
    high.stage = "model_reviewed"
    high.decision = "high_value"
    review.stage = "model_reviewed"
    review.decision = "review"
    rejected.stage = "model_rejected"
    rejected.decision = "reject"
    rejected.rejection_reason = "无明确企业场景"
    report = render_report(
        "run-1",
        [high, review, rejected],
        [high],
        {"dy": {"status": "success", "contents": 1, "comments": 2}},
        {},
    )

    assert "高价值潜客 TOP20（评分 ≥4）" in report
    assert "待复核候选（低于 4 分或模型要求复核）" in report
    assert "已过滤记录与原因" in report
    assert "无明确企业场景" in report
    assert "dy-1" in report
    assert "| 5 |" in report


def test_report_store_can_write_a_suffix_without_replacing_default(tmp_path: Path) -> None:
    config = RadarConfig(data_root=tmp_path / "radar-data", platforms=["dy"], keywords={"企业培训": "企业培训"})
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    store.save_run("run-1", "success", {"dy": {"status": "success", "contents": 1, "comments": 0}}, "now", "now")
    store.close()

    default_path = report_store(config, "run-1")
    fixed_path = report_store(config, "run-1", "fixed")

    assert default_path.name == "run-1.md"
    assert fixed_path.name == "run-1-fixed.md"
    assert default_path.exists()
    assert fixed_path.exists()


def test_conversion_pack_marks_case_as_unverified_and_avoids_numeric_claims() -> None:
    from local_tools.polyv_radar.conversion_engine import build_conversion_pack

    pack = build_conversion_pack(_lead(score=6))

    assert pack.recommended_materials["case"].startswith("[待核实]")
    assert "%" not in pack.video_hook
    assert "90%" not in pack.video_topic


def _lead(score: int):
    from local_tools.polyv_radar.models import LeadEvidence

    return LeadEvidence(
        platform="dy",
        content_id="dy-1" if score == 6 else "dy-2",
        comment_id=f"comment-{score}",
        url="https://www.douyin.com/video/dy-1",
        user="用户",
        quote="我们公司需要培训直播平台，多少钱？",
        category="企业培训",
        solution="企业培训直播与数字化内训点播方向",
        score=score,
        reasons=["明确企业需求", "询问方案/价格"],
        evidence_sentences=["我们公司需要培训直播平台，多少钱？"],
        content_title="企业培训直播方案",
    )
