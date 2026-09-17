from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from local_tools.polyv_radar.config import RadarConfig, load_config
from local_tools.polyv_radar.runner import build_crawl_command, collect
from local_tools.polyv_radar.storage import RadarStore
from local_tools.polyv_radar.adapters import normalize_comment, normalize_content
from local_tools.polyv_radar.scoring import score_purchase_evidence
from local_tools.polyv_radar.benchmark import _acceptance
from local_tools.polyv_radar.url_validation import validate_url, validate_urls_with_ego


def test_native_command_batches_keywords_without_changing_limits() -> None:
    command = build_crawl_command(
        "/workspace/MediaCrawler",
        "dy",
        "公司年会直播,员工线上培训,医学学术会议",
        "/tmp/raw",
        10,
        20,
    )

    assert command[command.index("--keywords") + 1] == "公司年会直播,员工线上培训,医学学术会议"
    assert command[command.index("--crawler_max_notes_count") + 1] == "10"
    assert command[command.index("--max_comments_count_singlenotes") + 1] == "20"


def test_collect_rejects_non_ego_browser_backends(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_runner(command, **kwargs):
        calls.append(command)
        output_dir = Path(command[command.index("--save_data_path") + 1])
        jsonl_dir = output_dir / "dy" / "jsonl"
        jsonl_dir.mkdir(parents=True)
        contents = [
            {"aweme_id": "dy-1", "desc": "公司年会直播", "source_keyword": "公司年会直播"},
            {"aweme_id": "dy-2", "desc": "员工线上培训", "source_keyword": "员工线上培训"},
        ]
        comments = [
            {"comment_id": "c-1", "aweme_id": "dy-1", "content": "公司需要平台", "source_keyword": "公司年会直播"},
            {"comment_id": "c-2", "aweme_id": "dy-2", "content": "求平台推荐", "source_keyword": "员工线上培训"},
        ]
        (jsonl_dir / "search_contents.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in contents) + "\n", encoding="utf-8")
        (jsonl_dir / "search_comments.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in comments) + "\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(ValueError, match="Ego Lite"):
        collect(
        RadarConfig(
            data_root=tmp_path / "radar-data",
            platforms=["dy"],
            keywords={
                "年会": "公司年会直播",
                "培训": "员工线上培训",
                "医学": "医学学术会议",
            },
            collector_backend="native",
            max_contents=10,
            max_comments=20,
        ),
        tmp_path,
            runner=fake_runner,
            collector="native",
            run_id="run-native",
        )

    assert calls == []


def test_config_rejects_non_ego_platform_collectors(tmp_path: Path) -> None:
    config_path = tmp_path / "radar.toml"
    config_path.write_text(
        """[run]
collector_backend = "ego"
platform_workers = 2
platform_collectors = { dy = "hybrid" }
platforms = ["dy"]

[keywords]
"企业直播" = "企业直播平台"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Ego Lite"):
        load_config(config_path)


def test_crawl_task_migration_is_additive(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    store.save_crawl_task({"run_id": "run-1", "platform": "dy", "keyword": "测试", "backend": "native"})
    assert store.count("crawl_tasks") == 1
    assert store.load_crawl_tasks("run-1")[0]["keyword"] == "测试"
    store.close()


def test_comment_purchase_signal_remains_recent_for_90_days() -> None:
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    content = normalize_content(
        "dy",
        {"aweme_id": "dy-1", "desc": "公司年会直播平台", "create_time": now.isoformat()},
        "公司年会直播",
    )
    comment = normalize_comment(
        "dy",
        {
            "comment_id": "c-1",
            "aweme_id": "dy-1",
            "content": "我们公司正在筹备年会直播，求平台报价",
            "create_time": (now - timedelta(days=60)).isoformat(),
        },
    )

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment, now=now, recent_days=90)
    assert result.dimensions["project_timing"] == 2


def test_comment_older_than_configured_recent_window_loses_project_bonus() -> None:
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    content = normalize_content(
        "dy",
        {"aweme_id": "dy-1", "desc": "公司年会直播平台", "create_time": now.isoformat()},
        "公司年会直播",
    )
    comment = normalize_comment(
        "dy",
        {
            "comment_id": "c-1",
            "aweme_id": "dy-1",
            "content": "我们公司正在筹备年会直播，求平台报价",
            "create_time": (now - timedelta(days=91)).isoformat(),
        },
    )

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment, now=now, recent_days=90)
    assert result.dimensions["project_timing"] == 1


def test_partner_event_is_classified_as_a_business_event() -> None:
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    content = normalize_content(
        "dy",
        {"aweme_id": "dy-partner", "desc": "合作伙伴大会筹备", "create_time": now.isoformat()},
        "合作伙伴大会",
    )
    comment = normalize_comment(
        "dy",
        {
            "comment_id": "partner-comment",
            "aweme_id": "dy-partner",
            "content": "我们公司下个月要办合作伙伴大会，正在找技术服务商报价。",
            "create_time": (now - timedelta(days=2)).isoformat(),
        },
    )

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment, now=now, recent_days=90)

    assert result.event_type == "合作伙伴大会"
    assert result.score >= 6


def test_benchmark_acceptance_requires_speed_coverage_and_auth_health() -> None:
    ego = {"duration_seconds": 100, "contents": 10, "comments": 20, "failures": {}}
    native = {"duration_seconds": 50, "contents": 8, "comments": 16, "failures": {}}

    result = _acceptance(ego, native)

    assert all(result.values())
    assert _acceptance(ego, {**native, "duration_seconds": 61})["duration_le_60_percent"] is False
    assert _acceptance(ego, {**native, "failures": {"dy:q": "需要登录"}})["no_new_auth_error"] is False


def test_url_validation_rejects_non_http_and_local_targets() -> None:
    assert validate_url("file:///tmp/report.md")["status"] == "invalid"
    assert validate_url("http://127.0.0.1:8080/")["status"] == "invalid"


def test_url_validation_uses_ego_lite_runner_and_persists_browser_results(tmp_path: Path) -> None:
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        output_path = tmp_path / "url-check-output.json"
        output_path.write_text(
            json.dumps({"results": [{"url": "https://example.com/item", "status": "ok", "http_status": 200, "final_url": "https://example.com/item", "reason": "页面可访问"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    checks, log = validate_urls_with_ego(
        ["https://example.com/item"],
        tmp_path,
        tmp_path,
        runner=fake_runner,
    )

    assert not log
    assert calls[0][0] == ["ego-browser", "nodejs"]
    assert checks["https://example.com/item"]["status"] == "ok"
