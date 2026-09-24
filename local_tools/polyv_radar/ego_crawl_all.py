#!/usr/bin/env python3
"""Unified orchestrator for ego lite crawling across 4 platforms and generating conversion reports."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from local_tools.polyv_radar.config import load_config
from local_tools.polyv_radar.runner import analyze_store, ingest_existing_run, report_store
from local_tools.polyv_radar.workflow import save_workflow_candidate, save_workflow_run

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


def build_ego_batch_launcher(
    script_path: Path,
    keywords: list[str],
    max_contents: int,
    max_comments: int,
    out_dir: Path,
    taskspace: int,
    snapshot_dir: Path,
    result_path: Path | None = None,
) -> str:
    script_path = script_path.expanduser().resolve()
    batch_script = script_path.parent / "ego_platform_batch.mjs"
    return "\n".join(
        [
            f"process.env.POLYV_TASKSPACE_ID = {json.dumps(str(taskspace), ensure_ascii=False)};",
            f"process.env.POLYV_BATCH_SCRIPT = {json.dumps(script_path.as_posix(), ensure_ascii=False)};",
            f"process.env.POLYV_BATCH_KEYWORDS = {json.dumps(json.dumps(keywords, ensure_ascii=False), ensure_ascii=False)};",
            f"process.env.POLYV_BATCH_OUTPUT_DIR = {json.dumps(out_dir.as_posix(), ensure_ascii=False)};",
            f"process.env.POLYV_BATCH_SNAPSHOT_DIR = {json.dumps(snapshot_dir.as_posix(), ensure_ascii=False)};",
            f"process.env.POLYV_BATCH_RESULT_PATH = {json.dumps(result_path.as_posix() if result_path else '', ensure_ascii=False)};",
            f"process.env.POLYV_BATCH_MAX_CONTENTS = {json.dumps(str(max_contents), ensure_ascii=False)};",
            f"process.env.POLYV_BATCH_MAX_COMMENTS = {json.dumps(str(max_comments), ensure_ascii=False)};",
            f"await import({json.dumps(batch_script.as_uri(), ensure_ascii=False)} + '?batch=' + Date.now());",
            "",
        ]
    )


def run_ego_crawlers(run_id: str, platforms: list[str], config, repo_root: Path, data_root: Path, taskspace: int) -> dict[str, bool]:
    if not isinstance(taskspace, int) or taskspace <= 0:
        raise ValueError("必须显式提供用户已登录的 Ego Lite TaskSpace；不创建或接管新会话")
    results = {}
    workflow_started = datetime.now(timezone.utc)
    workflow_platforms: list[dict] = []
    tools_dir = repo_root / "local_tools" / "polyv_radar"
    raw_dir = data_root / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir = data_root / "workflow-runs" / run_id
    snapshot_root = workflow_dir / "snapshots"

    for plat in platforms:
        script_name = PLATFORM_SCRIPTS.get(plat)
        if not script_name:
            print(f"[-] Unknown platform: {plat}")
            results[plat] = False
            continue

        script_path = tools_dir / script_name
        plat_keywords = list(config.get_keywords_for_platform(plat).values())
        out_dir = raw_dir / plat
        snapshot_dir = snapshot_root / plat
        result_path = workflow_dir / f"{plat}-batch.json"
        out_dir.mkdir(parents=True, exist_ok=True)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc)
        runner_script = build_ego_batch_launcher(
            script_path, plat_keywords, config.max_contents, config.max_comments, out_dir, taskspace, snapshot_dir, result_path
        )
        print(f"\n==========================================")
        print(f"[+] Launching one Ego Lite batch: {plat.upper()} | {len(plat_keywords)} 个关键词")
        print(f"==========================================")
        plat_success = True
        stdout = ""
        stderr = ""
        error = ""
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
            stdout = res.stdout or ""
            stderr = res.stderr or ""
            print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)
            if res.returncode != 0:
                plat_success = False
                error = (stderr or stdout or f"退出码 {res.returncode}").strip()[-500:]
        except subprocess.TimeoutExpired as exc:
            plat_success = False
            error = f"任务超过 {config.task_timeout_seconds} 秒，已保留已落盘数据"
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "")
            print(f"[-] {plat.upper()} batch timed out", file=sys.stderr)
        except Exception as exc:
            plat_success = False
            error = str(exc)[-500:]
            print(f"[-] {plat.upper()} failed: {exc}", file=sys.stderr)
        finished_at = datetime.now(timezone.utc)
        batch_payload = {}
        if result_path.is_file():
            try:
                parsed = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    batch_payload = parsed
            except (OSError, json.JSONDecodeError):
                batch_payload = {}
        results[plat] = plat_success
        workflow_platforms.append(
            {
                "platform": plat,
                "backend": "ego",
                "keywords": plat_keywords,
                "taskspace": taskspace,
                "page": "p1",
                "output_dir": str(out_dir),
                "snapshot_dir": str(snapshot_dir),
                "batch_result_path": str(result_path),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_seconds": max(0.0, (finished_at - started_at).total_seconds()),
                "status": "success" if plat_success else "partial",
                "error": error,
                "stdout_tail": stdout[-2000:],
                "stderr_tail": stderr[-2000:],
                "tasks": batch_payload.get("tasks", []),
            }
        )
    workflow_payload = {
        "workflow_name": "polyv-leads",
        "workflow_version": "1",
        "run_id": run_id,
        "mode": "ego_snapshot_batch",
        "taskspace": taskspace,
        "page": "p1",
        "started_at": workflow_started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "platforms": workflow_platforms,
        "results": results,
    }
    save_workflow_run(data_root, run_id, workflow_payload)
    save_workflow_candidate(data_root, run_id, workflow_platforms)
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
    report_path = report_store(config, run_id, taskspace=args.taskspace)
    print(f"\n==================================================")
    print(f"[✓] SUCCESS! Report generated at:\n{report_path}")
    print(f"==================================================")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
