from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .dispatch import DispatchItem, dispatch_queue
from .hunt import run_hunt
from .locator import locate_store
from .pipeline import enrich_store, prefilter_store, review_store
from .runner import analyze_store, collect, ingest_existing_run, report_store
from .storage import RadarStore


def _preflight() -> dict:
    try:
        result = subprocess.run(
            ["/Users/sexpistole111/.local/bin/jev-ego-preflight"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"JEV/Ego Lite预检失败: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "JEV/Ego Lite预检失败").strip())
    return {"status": "ready", "output": (result.stdout or "").strip()[-1000:]}


def _approved_items(store: RadarStore, run_id: str) -> tuple[list[dict], list[DispatchItem]]:
    rows = store.load_outreach_queue(run_id, statuses=("approved", "queued"))
    items = [
        DispatchItem(
            platform=str(row["platform"]),
            url=str(row["target_url"]),
            author=str(row["target_author"]),
            text=str(row["draft_text"]),
            content_id=str(row["content_id"]),
            comment_id=str(row["comment_id"]),
        )
        for row in rows
        if row.get("target_url") and row.get("target_author") and row.get("draft_text")
    ]
    return rows, items


def run_daily(
    config,
    repo_root: Path,
    taskspace: int,
    submit_approved: bool = False,
    run_id: str | None = None,
    skip_crawl: bool = False,
    codex: str = "codex",
    max_candidates: int = 50,
) -> dict:
    if not isinstance(taskspace, int) or taskspace <= 0:
        raise ValueError("daily 必须显式提供用户已登录的 Ego Lite TaskSpace")
    preflight = _preflight()
    current_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stages: dict[str, object] = {"preflight": preflight}
    if skip_crawl:
        stages["ingest"] = ingest_existing_run(config, current_run_id).platform_status
    else:
        stages["collect"] = collect(config, repo_root, collector="ego", run_id=current_run_id, taskspace=taskspace).platform_status
    stages["analyze"] = {"count": len(analyze_store(config, current_run_id))}
    stages["prefilter"] = {"count": len(prefilter_store(config, current_run_id, max_candidates))}
    stages["enrich"] = enrich_store(config, repo_root, current_run_id, taskspace=taskspace)
    stages["review"] = review_store(config, current_run_id, codex=codex)
    stages["locate"] = locate_store(config, repo_root, current_run_id, max_candidates=max_candidates, taskspace=taskspace)
    report_path = report_store(config, current_run_id, "daily", taskspace=taskspace)

    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    queue_rows, items = _approved_items(store, current_run_id)
    dispatch_results: list[dict] = []
    if submit_approved and items:
        dispatch_results = dispatch_queue(items, taskspace=taskspace, submit=True, max_sends=5, cooldown_seconds=30)
        for row, result in zip(queue_rows, dispatch_results):
            status = str(result.get("lead_status", result.get("status", "failed")))
            if status == "submitted_verified":
                store.update_outreach_queue_status(int(row["queue_id"]), "submitted_verified")
            elif status in {"submitted_unverified", "post_not_found", "click_failed", "input_failed", "blocked"}:
                store.update_outreach_queue_status(int(row["queue_id"]), status)
            store.save_outreach_attempt({
                "queue_id": int(row["queue_id"]),
                "run_id": current_run_id,
                "platform": row["platform"],
                "mode": "submit",
                "status": status,
                "structured_result": result.get("structured_result", {}),
                "screenshot_path": result.get("screenshot", ""),
                "error": result.get("message", ""),
            })
    store.close()
    stages["dispatch"] = {
        "mode": "submit" if submit_approved else "not_submitted",
        "approved_queue": len(queue_rows),
        "attempted": len(dispatch_results),
        "verified": sum(item.get("lead_status", item.get("status")) == "submitted_verified" for item in dispatch_results),
    }
    return {
        "run_id": current_run_id,
        "report_path": str(report_path),
        "stages": stages,
        "dispatch_results": dispatch_results,
    }
