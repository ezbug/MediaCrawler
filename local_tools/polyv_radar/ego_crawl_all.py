#!/usr/bin/env python3
"""Unified orchestrator for ego lite crawling across 4 platforms and generating conversion reports."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from local_tools.polyv_radar.config import load_config
from local_tools.polyv_radar.runner import analyze_store, ingest_existing_run, report_store

PLATFORM_SCRIPTS = {
    "dy": "ego_dy_crawler.mjs",
    "xhs": "ego_xhs_crawler.mjs",
    "bili": "ego_bili_crawler.mjs",
    "zhihu": "ego_zhihu_crawler.mjs",
}


def build_ego_launcher(script_path: Path, keyword: str, max_contents: int, max_comments: int, out_dir: Path) -> str:
    return (
        f"process.argv = [\"node\", {json.dumps(script_path.as_posix(), ensure_ascii=False)}, {json.dumps(keyword, ensure_ascii=False)}, "
        f"{json.dumps(str(max_contents))}, {json.dumps(str(max_comments))}, {json.dumps(out_dir.as_posix(), ensure_ascii=False)}];\n"
        f"await import({json.dumps(script_path.as_posix(), ensure_ascii=False)});\n"
    )


def run_ego_crawlers(run_id: str, platforms: list[str], config, repo_root: Path, data_root: Path, taskspace: int) -> dict[str, bool]:
    if not isinstance(taskspace, int) or taskspace <= 0:
        raise ValueError("必须显式提供用户已登录的 Ego Lite TaskSpace；不创建或接管新会话")
    results = {}
    tools_dir = repo_root / "local_tools" / "polyv_radar"
    raw_dir = data_root / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    for plat in platforms:
        script_name = PLATFORM_SCRIPTS.get(plat)
        if not script_name:
            print(f"[-] Unknown platform: {plat}")
            results[plat] = False
            continue

        script_path = tools_dir / script_name
        plat_success = True

        plat_keywords = config.get_keywords_for_platform(plat)
        for category, keyword in plat_keywords.items():
            out_dir = raw_dir / plat / keyword
            out_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n==========================================")
            print(f"[+] Launching ego lite crawler: {plat.upper()} | 关键词: {keyword}")
            print(f"==========================================")

            runner_script = build_ego_launcher(script_path, keyword, config.max_contents, config.max_comments, out_dir)
            try:
                env = os.environ.copy()
                env["POLYV_TASKSPACE_ID"] = str(taskspace)
                res = subprocess.run(
                    ["ego-browser", "nodejs"],
                    input=runner_script,
                    text=True,
                    capture_output=True,
                    check=False,
                    env=env,
                    timeout=config.task_timeout_seconds,
                )
                print(res.stdout)
                if res.stderr:
                    print(res.stderr, file=sys.stderr)
                if res.returncode != 0:
                    plat_success = False
            except subprocess.TimeoutExpired:
                print(f"[-] {plat.upper()} crawler timed out on keyword {keyword}", file=sys.stderr)
                plat_success = False
            except Exception as e:
                print(f"[-] {plat.upper()} failed on keyword {keyword}: {e}", file=sys.stderr)
                plat_success = False

        results[plat] = plat_success
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified ego lite radar orchestrator")
    parser.add_argument("--config", default="local_tools/polyv_radar/polyv_radar_config.json")
    parser.add_argument("--platforms", nargs="+", default=["dy", "xhs", "bili", "zhihu"], choices=["dy", "xhs", "bili", "zhihu"])
    parser.add_argument("--run-id", default=None, help="Use existing run_id instead of crawling")
    parser.add_argument("--skip-crawl", action="store_true", help="Skip crawling and only run ingest/analyze/report")
    parser.add_argument("--max-contents", type=int, default=None)
    parser.add_argument("--max-comments", type=int, default=None)
    parser.add_argument("--taskspace", type=int, required=True, help="用户已登录的 Ego Lite TaskSpace")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    config_path = (repo_root / args.config) if not Path(args.config).is_absolute() else Path(args.config)
    config = load_config(config_path)
    overrides = {}
    if args.max_contents is not None:
        overrides["max_contents"] = args.max_contents
    if args.max_comments is not None:
        overrides["max_comments"] = args.max_comments
    if overrides:
        config = replace(config, **overrides)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    started_at = datetime.now(timezone.utc)
    if not args.skip_crawl:
        print(f"[*] Starting 4-platform ego lite crawl. Run ID: {run_id}")
        crawl_results = run_ego_crawlers(run_id, args.platforms, config, repo_root, config.data_root, args.taskspace)
        print(f"[*] Crawl results: {json.dumps(crawl_results, ensure_ascii=False)}")

    print(f"\n[*] Ingesting crawled data into SQLite store ({config.data_root / 'radar.sqlite3'})...")
    ingest_res = ingest_existing_run(
        config,
        run_id,
        started_at=started_at.isoformat() if not args.skip_crawl else None,
        finished_at=datetime.now(timezone.utc).isoformat() if not args.skip_crawl else None,
    )
    print(f"[+] Ingested run {ingest_res.run_id}. Failures: {ingest_res.failures}")

    print(f"\n[*] Analyzing leads and scoring...")
    leads = analyze_store(config, run_id)
    print(f"[+] Identified {len(leads)} high-intent leads.")

    print(f"\n[*] Generating 4-in-1 conversion report with public replies, video topics, DM openers & cases...")
    report_path = report_store(config, run_id)
    print(f"\n==================================================")
    print(f"[✓] SUCCESS! Report generated at:\n{report_path}")
    print(f"==================================================")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
