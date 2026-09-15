from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import RadarConfig
from .runner import CollectionResult, collect, safe_name
from .storage import RadarStore


DEFAULT_KEYWORDS = {
    "dy": ["公司年会直播 平台报价", "员工线上培训 平台推荐", "医学学术会议 直播平台"],
    "xhs": ["企业年会直播 策划 平台", "员工培训平台 选型 报价", "课程版权保护 防录屏 解决方案"],
}


def _benchmark_config(config: RadarConfig, platform: str, keywords: list[str]) -> RadarConfig:
    return RadarConfig(
        **{
            **config.__dict__,
            "platforms": [platform],
            "keywords": {f"benchmark-{index}": keyword for index, keyword in enumerate(keywords, start=1)},
            "platform_keywords": {},
            "max_contents": 10,
            "max_comments": 20,
        }
    )


def _run_summary(result: CollectionResult) -> dict:
    store = RadarStore(result.store_path)
    store.initialize()
    run_row = store.connection.execute(
        "SELECT started_at, finished_at FROM runs WHERE run_id = ?", (result.run_id,)
    ).fetchone()
    contents = len(store.iter_contents(result.run_id))
    comments = len(store.iter_comments(result.run_id))
    tasks = store.load_crawl_tasks(result.run_id)
    store.close()
    duration = 0.0
    if run_row:
        try:
            duration = max(
                0.0,
                (datetime.fromisoformat(run_row["finished_at"]) - datetime.fromisoformat(run_row["started_at"])).total_seconds(),
            )
        except ValueError:
            duration = 0.0
    return {
        "run_id": result.run_id,
        "duration_seconds": duration,
        "contents": contents,
        "comments": comments,
        "failures": result.failures,
        "tasks": tasks,
    }


def _acceptance(ego: dict, native: dict) -> dict:
    def coverage(name: str) -> float:
        baseline = ego.get(name, 0)
        return native.get(name, 0) / baseline if baseline else 1.0

    return {
        "duration_le_60_percent": bool(ego["duration_seconds"] <= 0 or native["duration_seconds"] <= ego["duration_seconds"] * 0.6),
        "content_coverage_ge_80_percent": coverage("contents") >= 0.8,
        "comment_coverage_ge_80_percent": coverage("comments") >= 0.8,
        "no_new_auth_error": not any("登录" in str(value) or "auth" in str(value).lower() for value in native.get("failures", {}).values()),
    }


def run_benchmark(
    config: RadarConfig,
    repo_root: Path,
    platform: str,
    keywords: list[str] | None = None,
    runner: Callable | None = None,
) -> dict:
    selected = keywords or DEFAULT_KEYWORDS.get(platform, ["企业直播平台推荐"])
    bench_config = _benchmark_config(config, platform, selected)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ego_result = collect(bench_config, repo_root, collector="ego", run_id=f"benchmark-{stamp}-{safe_name(platform)}-ego")
    native_result = collect(bench_config, repo_root, runner=runner or __import__("subprocess").run, collector="native", run_id=f"benchmark-{stamp}-{safe_name(platform)}-native")
    ego = _run_summary(ego_result)
    native = _run_summary(native_result)
    acceptance = _acceptance(ego, native)
    output_dir = config.data_root / "reports" / "benchmarks"
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"{stamp}-{safe_name(platform)}"
    payload = {
        "platform": platform,
        "keywords": selected,
        "limits": {"max_contents": 10, "max_comments": 20},
        "ego": ego,
        "native": native,
        "acceptance": acceptance,
        "accepted": all(acceptance.values()),
    }
    (base.with_suffix(".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 采集后端 A/B 基准：{platform} {stamp}",
        "",
        f"查询：{', '.join(selected)}",
        "",
        "| 后端 | 耗时（秒） | 内容 | 评论 | 失败数 |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| Ego | {ego['duration_seconds']:.2f} | {ego['contents']} | {ego['comments']} | {len(ego['failures'])} |",
        f"| Native | {native['duration_seconds']:.2f} | {native['contents']} | {native['comments']} | {len(native['failures'])} |",
        "",
        f"验收结论：{'通过' if payload['accepted'] else '未通过'}",
        "",
        "| 条件 | 结果 |",
        "| --- | --- |",
    ]
    for name, passed in acceptance.items():
        lines.append(f"| {name} | {'通过' if passed else '未通过'} |")
    (base.with_suffix(".md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"platform": platform, "json_path": str(base.with_suffix(".json")), "markdown_path": str(base.with_suffix(".md")), "accepted": payload["accepted"]}
