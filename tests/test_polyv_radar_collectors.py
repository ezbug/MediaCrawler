from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from local_tools.polyv_radar.config import RadarConfig, load_config
from local_tools.polyv_radar.runner import build_crawl_command, collect
from local_tools.polyv_radar.storage import RadarStore


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


def test_native_collection_starts_once_and_keeps_source_keywords(tmp_path: Path) -> None:
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

    result = collect(
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

    assert len(calls) == 1
    assert calls[0][calls[0].index("--keywords") + 1] == "公司年会直播,员工线上培训,医学学术会议"
    assert result.platform_status["dy"]["contents"] == 2
    assert result.platform_status["dy"]["comments"] == 2

    store = RadarStore(result.store_path)
    store.initialize()
    assert {tuple(item.source_keywords) for item in store.iter_contents("run-native")} == {
        ("公司年会直播",),
        ("员工线上培训",),
    }
    assert {item.source_keyword for item in store.iter_comments("run-native")} == {"公司年会直播", "员工线上培训"}
    tasks = store.load_crawl_tasks("run-native")
    assert len(tasks) == 3
    assert {item["backend"] for item in tasks} == {"native"}
    assert all(item["duration_seconds"] >= 0 for item in tasks)
    store.close()


def test_config_supports_global_and_platform_collector_precedence(tmp_path: Path) -> None:
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

    config = load_config(config_path)

    assert config.get_collector_for_platform("dy") == "hybrid"
    assert config.get_collector_for_platform("xhs") == "ego"
    assert config.platform_workers == 2


def test_crawl_task_migration_is_additive(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    store.save_crawl_task({"run_id": "run-1", "platform": "dy", "keyword": "测试", "backend": "native"})
    assert store.count("crawl_tasks") == 1
    assert store.load_crawl_tasks("run-1")[0]["keyword"] == "测试"
    store.close()
