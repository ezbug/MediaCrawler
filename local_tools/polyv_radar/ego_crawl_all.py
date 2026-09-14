#!/usr/bin/env python3
"""Unified orchestrator for ego lite crawling across 4 platforms and generating conversion reports."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from local_tools.polyv_radar.config import load_config
from local_tools.polyv_radar.runner import analyze_store, ingest_existing_run, report_store

PLATFORM_SCRIPTS = {
    "dy": "ego_dy_crawler.mjs",
    "xhs": "ego_xhs_crawler.mjs",
    "bili": "ego_bili_crawler.mjs",
    "zhihu": "ego_zhihu_crawler.mjs",
}


def run_ego_crawlers(run_id: str, platforms: list[str], repo_root: Path, data_root: Path) -> dict[str, bool]:
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
        print(f"\n==========================================")
        print(f"[+] Launching ego lite crawler for {plat.upper()}...")
        print(f"==========================================")

        cmd = ["ego-browser", "nodejs"]
        inline_script = f"""
const mod = await import('{script_path.as_posix()}');
const fn = Object.values(mod).find(v => typeof v === 'function');
if (fn) {{
  await fn('{run_id}');
}} else {{
  console.error("No export function found in {script_name}");
}}
"""
        try:
            res = subprocess.run(
                cmd,
                input=inline_script,
                text=True,
                capture_output=True,
                check=False,
                timeout=300
            )
            print(res.stdout)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
            results[plat] = (res.returncode == 0)
        except subprocess.TimeoutExpired:
            print(f"[-] {plat.upper()} crawler timed out after 300s", file=sys.stderr)
            results[plat] = False
        except Exception as e:
            print(f"[-] {plat.upper()} failed: {e}", file=sys.stderr)
            results[plat] = False

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified ego lite radar orchestrator")
    parser.add_argument("--config", default="local_tools/polyv_radar/polyv_radar_config.json")
    parser.add_argument("--platforms", nargs="+", default=["dy", "xhs", "bili", "zhihu"], choices=["dy", "xhs", "bili", "zhihu"])
    parser.add_argument("--run-id", default=None, help="Use existing run_id instead of crawling")
    parser.add_argument("--skip-crawl", action="store_true", help="Skip crawling and only run ingest/analyze/report")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    config_path = (repo_root / args.config) if not Path(args.config).is_absolute() else Path(args.config)
    config = load_config(config_path)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if not args.skip_crawl:
        print(f"[*] Starting 4-platform ego lite crawl. Run ID: {run_id}")
        crawl_results = run_ego_crawlers(run_id, args.platforms, repo_root, config.data_root)
        print(f"[*] Crawl results: {json.dumps(crawl_results, ensure_ascii=False)}")

    print(f"\n[*] Ingesting crawled data into SQLite store ({config.data_root / 'radar.sqlite3'})...")
    ingest_res = ingest_existing_run(config, run_id)
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
