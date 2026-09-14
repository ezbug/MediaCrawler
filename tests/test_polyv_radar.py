from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from local_tools.polyv_radar.adapters import normalize_comment, normalize_content
from local_tools.polyv_radar.cli import apply_collect_overrides
from local_tools.polyv_radar.config import RadarConfig
from local_tools.polyv_radar.models import LeadEvidence
from local_tools.polyv_radar.report import render_report
from local_tools.polyv_radar.runner import analyze_records, build_crawl_command, ingest_existing_run
from local_tools.polyv_radar.scoring import score_text
from local_tools.polyv_radar.storage import RadarStore


def test_normalizes_supported_platform_content() -> None:
    samples = {
        "dy": {
            "aweme_id": "dy-1",
            "desc": "企业培训直播方案",
            "nickname": "培***者",
            "creator_hash": "dy-hash",
            "create_time": 1788000000,
            "liked_count": "1200",
            "comment_count": "12",
            "share_count": "8",
            "aweme_url": "https://www.douyin.com/video/dy-1",
        },
        "xhs": {
            "note_id": "xhs-1",
            "title": "员工培训平台怎么选",
            "desc": "正在找企业培训平台",
            "nickname": "小***书",
            "creator_hash": "xhs-hash",
            "time": 1788000000,
            "liked_count": 300,
            "comment_count": 5,
            "note_url": "https://www.xiaohongshu.com/explore/xhs-1",
        },
        "bili": {
            "video_id": "bili-1",
            "title": "直播 SDK 集成经验",
            "desc": "WebRTC 接入",
            "nickname": "UP***主",
            "creator_hash": "bili-hash",
            "create_time": 1788000000,
            "video_play_count": "9000",
            "video_comment": "20",
            "video_url": "https://www.bilibili.com/video/avbili-1",
        },
        "zhihu": {
            "content_id": "zh-1",
            "title": "海外直播需要什么方案",
            "content_text": "多语言直播和全球分发",
            "user_nickname": "知***户",
            "creator_hash": "zh-hash",
            "created_time": 1788000000,
            "voteup_count": 88,
            "comment_count": 9,
            "content_url": "https://www.zhihu.com/question/zh-1",
        },
    }

    for platform, raw in samples.items():
        item = normalize_content(platform, raw, "测试关键词")
        assert item is not None
        assert item.platform == platform
        assert item.content_id
        assert item.url.startswith("http")
        assert item.source_keywords == ["测试关键词"]


def test_normalizes_nested_comment_and_preserves_parent() -> None:
    item = normalize_comment(
        "dy",
        {
            "comment_id": "comment-2",
            "aweme_id": "dy-1",
            "content": "我们公司也在找直播平台",
            "nickname": "评***者",
            "creator_hash": "comment-hash",
            "like_count": 7,
            "parent_comment_id": "comment-1",
            "create_time": 1788000000,
        },
    )

    assert item is not None
    assert item.content_id == "dy-1"
    assert item.parent_comment_id == "comment-1"
    assert item.text == "我们公司也在找直播平台"


def test_scores_recent_enterprise_need_and_exposes_evidence() -> None:
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    result = score_text(
        "我们公司最近正在做万人培训直播，老板让我找平台，多少钱？",
        published_at=now - timedelta(days=3),
        now=now,
        category_hint="企业培训",
    )

    assert result.score >= 8
    assert result.category == "企业培训"
    assert "明确企业需求" in result.reasons
    assert "近期项目" in result.reasons
    assert "询问方案/价格" in result.reasons
    assert result.evidence_sentences


def test_advertising_is_penalized_and_score_is_clamped() -> None:
    result = score_text(
        "我们提供直播SDK源码和代理招商，加微信咨询。",
        published_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )

    assert result.score <= 3
    assert "广告或同行推广" in result.reasons


def test_generic_price_discussion_is_not_a_lead_without_business_context() -> None:
    result = score_text("这个价格太贵了，我还是等等。", published_at=None)

    assert result.score == 2
    assert "透露公司/职位" not in result.reasons


def test_sqlite_upsert_deduplicates_content_and_comments(tmp_path) -> None:
    content = normalize_content(
        "dy",
        {
            "aweme_id": "dy-1",
            "desc": "员工培训",
            "aweme_url": "https://www.douyin.com/video/dy-1",
        },
        "员工培训",
    )
    comment = normalize_comment(
        "dy",
        {
            "comment_id": "comment-1",
            "aweme_id": "dy-1",
            "content": "公司需要培训直播",
        },
    )
    assert content is not None
    assert comment is not None

    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    assert store.upsert_content(content) is True
    content.source_keywords.append("发布会直播")
    assert store.upsert_content(content) is False
    assert store.upsert_comment(comment) is True
    assert store.upsert_comment(comment) is False

    row = store.connection.execute(
        "SELECT source_keywords FROM contents WHERE platform = 'dy' AND content_id = 'dy-1'"
    ).fetchone()
    assert row is not None
    assert "发布会直播" in row[0]
    assert store.count("contents") == 1
    assert store.count("comments") == 1
    store.close()


def test_report_contains_top_lead_and_failure_status() -> None:
    lead = LeadEvidence(
        platform="dy",
        content_id="dy-1",
        comment_id="comment-1",
        url="https://www.douyin.com/video/dy-1",
        user="评***者",
        quote="我们公司需要一个培训直播平台，多少钱？",
        category="企业培训",
        solution="企业培训直播与点播方向",
        score=8,
        reasons=["明确企业需求", "询问方案/价格"],
        evidence_sentences=["我们公司需要一个培训直播平台，多少钱？"],
        outreach="公开答疑并说明POLYV身份",
    )
    report = render_report(
        run_id="20260914-1",
        leads=[lead],
        top_contents=[lead],
        platform_status={"dy": {"status": "success", "contents": 1, "comments": 1}},
        failures={"xhs": "等待登录"},
    )

    assert "高价值潜客 TOP20（评分 ≥6）" in report
    assert "企业培训" in report
    assert "POLYV" in report
    assert "等待登录" in report


def test_build_crawl_command_keeps_first_run_limits() -> None:
    command = build_crawl_command(
        repo_root="/workspace/MediaCrawler",
        platform="dy",
        keyword="员工培训",
        output_dir="/workspace/raw/run/dy/employee",
        max_contents=10,
        max_comments=20,
    )

    assert command[:4] == ["uv", "run", "main.py", "--platform"]
    assert "dy" in command
    assert "员工培训" in command
    assert "--crawler_max_notes_count" in command
    assert command[command.index("--crawler_max_notes_count") + 1] == "10"
    assert command[command.index("--max_comments_count_singlenotes") + 1] == "20"
    assert command[command.index("--get_sub_comment") + 1] == "true"
    assert command[command.index("--save_data_option") + 1] == "jsonl"


def test_analyze_records_creates_reviewable_lead() -> None:
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    content = normalize_content(
        "dy",
        {
            "aweme_id": "dy-1",
            "desc": "企业培训直播经验",
            "aweme_url": "https://www.douyin.com/video/dy-1",
            "create_time": 1788000000,
        },
        "员工培训",
    )
    comment = normalize_comment(
        "dy",
        {
            "comment_id": "comment-1",
            "aweme_id": "dy-1",
            "content": "我们公司最近需要培训直播平台，多少钱？",
            "nickname": "评***者",
            "create_time": 1788000000,
        },
    )
    assert content is not None
    assert comment is not None

    leads = analyze_records([content], [comment], now=now)

    assert len(leads) == 1
    assert leads[0].comment_id == "comment-1"
    assert leads[0].score >= 6
    assert leads[0].category == "企业培训"


def test_collect_continues_after_platform_failure(tmp_path: Path) -> None:
    def fake_runner(command, **kwargs):
        platform = command[command.index("--platform") + 1]
        output_dir = Path(command[command.index("--save_data_path") + 1])
        if platform == "xhs":
            return SimpleNamespace(returncode=1, stdout="", stderr="需要登录")
        jsonl_dir = output_dir / "dy" / "jsonl"
        jsonl_dir.mkdir(parents=True)
        (jsonl_dir / "search_contents.jsonl").write_text(
            '{"aweme_id":"dy-1","desc":"员工培训","aweme_url":"https://www.douyin.com/video/dy-1"}\n',
            encoding="utf-8",
        )
        (jsonl_dir / "search_comments.jsonl").write_text(
            '{"comment_id":"c-1","aweme_id":"dy-1","content":"公司需要培训直播平台"}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    from local_tools.polyv_radar.runner import collect

    result = collect(
        RadarConfig(
            data_root=tmp_path / "radar-data",
            platforms=["dy", "xhs"],
            keywords={"企业培训": "员工培训"},
        ),
        tmp_path,
        runner=fake_runner,
    )

    assert result.platform_status["dy"]["contents"] == 1
    assert result.platform_status["dy"]["comments"] == 1
    assert result.platform_status["xhs"]["status"] == "partial"
    assert result.failures["xhs:员工培训"] == "需要登录"


def test_ingest_recovers_partial_run(tmp_path: Path) -> None:
    raw_dir = tmp_path / "radar-data" / "raw" / "run-1" / "dy" / "员工培训" / "dy" / "jsonl"
    raw_dir.mkdir(parents=True)
    (raw_dir / "search_contents.jsonl").write_text(
        '{"aweme_id":"dy-1","desc":"员工培训","aweme_url":"https://www.douyin.com/video/dy-1"}\n',
        encoding="utf-8",
    )
    result = ingest_existing_run(
        RadarConfig(
            data_root=tmp_path / "radar-data",
            platforms=["dy"],
            keywords={"企业培训": "员工培训"},
        ),
        "run-1",
    )
    assert result.platform_status["dy"]["contents"] == 1
    assert result.platform_status["dy"]["status"] == "success"


def test_collect_keeps_jsonl_when_task_times_out(tmp_path: Path) -> None:
    def fake_runner(command, **kwargs):
        assert kwargs["timeout"] == 7
        output_dir = Path(command[command.index("--save_data_path") + 1])
        jsonl_dir = output_dir / "douyin" / "jsonl"
        jsonl_dir.mkdir(parents=True)
        (jsonl_dir / "search_contents.jsonl").write_text(
            '{"aweme_id":"dy-timeout","desc":"员工培训","aweme_url":"https://www.douyin.com/video/dy-timeout"}\n',
            encoding="utf-8",
        )
        raise subprocess.TimeoutExpired(
            command,
            7,
            output="部分输出".encode(),
            stderr="等待超时".encode(),
        )

    from local_tools.polyv_radar.runner import collect

    result = collect(
        RadarConfig(
            data_root=tmp_path / "radar-data",
            platforms=["dy"],
            keywords={"企业培训": "员工培训"},
            task_timeout_seconds=7,
        ),
        tmp_path,
        runner=fake_runner,
    )

    assert result.platform_status["dy"]["contents"] == 1
    assert "任务超时" in result.failures["dy:员工培训"]


def test_collect_overrides_limit_a_run_to_selected_keyword_and_platform() -> None:
    config = RadarConfig(
        data_root=Path("/tmp/radar-data"),
        platforms=["dy", "xhs"],
        keywords={"企业培训": "员工培训", "企业直播": "发布会直播"},
    )
    args = SimpleNamespace(
        platform=["dy"],
        keyword=["员工培训"],
        max_contents=5,
        max_comments=10,
        task_timeout_seconds=60,
    )

    limited = apply_collect_overrides(config, args)

    assert limited.platforms == ["dy"]
    assert limited.keywords == {"企业培训": "员工培训"}
    assert limited.max_contents == 5
    assert limited.max_comments == 10
    assert limited.task_timeout_seconds == 60


def test_ingest_applies_content_and_per_content_comment_limits(tmp_path: Path) -> None:
    output_dir = tmp_path / "raw"
    jsonl_dir = output_dir / "douyin" / "jsonl"
    jsonl_dir.mkdir(parents=True)
    (jsonl_dir / "search_contents.jsonl").write_text(
        "\n".join(
            f'{{"aweme_id":"dy-{index}","desc":"员工培训","aweme_url":"https://www.douyin.com/video/dy-{index}"}}'
            for index in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    (jsonl_dir / "search_comments.jsonl").write_text(
        "\n".join(
            f'{{"comment_id":"c-{index}","aweme_id":"dy-0","content":"评论 {index}"}}'
            for index in range(4)
        )
        + "\n",
        encoding="utf-8",
    )

    from local_tools.polyv_radar.runner import _ingest_output

    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    contents, comments = _ingest_output(output_dir, "dy", "员工培训", store, 2, 2)

    assert contents == 2
    assert comments == 2
    store.close()
