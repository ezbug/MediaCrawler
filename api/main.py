# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/main.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""
MediaCrawler WebUI API Server
Start command: uvicorn api.main:app --port 8080 --reload
Or: python -m api.main
"""
import asyncio
import os
import sys
import subprocess
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi import HTTPException

from .routers import crawler_router, data_router, websocket_router
from local_tools.polyv_radar.storage import RadarStore
from local_tools.polyv_radar.dashboard import (
    clean_dashboard_leads,
    filter_reason_counts,
    load_dry_run_queue,
    load_manual_candidates,
    merge_dashboard_queue,
)
from local_tools.polyv_radar.html_dashboard import latest_run_id, render_html_dashboard

# Project root directory (used for running subprocesses like uv run main.py)
PROJECT_ROOT = Path(__file__).parent.parent

app = FastAPI(
    title="MediaCrawler WebUI API",
    description="API for controlling MediaCrawler from WebUI",
    version="1.0.0"
)

# Get webui static files directory
WEBUI_DIR = os.path.join(os.path.dirname(__file__), "webui")

# CORS configuration - allow frontend dev server access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Backup port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(crawler_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(websocket_router, prefix="/api")


def _manual_artifact_counts(rows: list[dict]) -> tuple[int, int]:
    """Provide truthful candidate-backed counts for legacy/file-only batches."""
    content_keys = {
        (str(row.get("platform", "")), str(row.get("content_id", "")))
        for row in rows
        if row.get("platform") and row.get("content_id")
    }
    comment_count = sum(
        1 for row in rows
        if str(row.get("source_type", "comment")).casefold() in {"comment", "reply"}
        and row.get("comment_id")
    )
    return len(content_keys), comment_count


@app.get("/")
async def serve_frontend():
    """Return frontend page"""
    index_path = os.path.join(WEBUI_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "MediaCrawler WebUI API",
        "version": "1.0.0",
        "docs": "/docs",
        "note": "WebUI not found, please build it first: cd webui && npm run build"
    }


@app.get("/polyv-dashboard.html", response_class=HTMLResponse)
async def serve_polyv_html_dashboard(run_id: str | None = None):
    """Serve the Antigravity-style current HTML table dashboard."""
    data_root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data"))
    selected_run = run_id or latest_run_id(data_root)
    if not selected_run:
        raise HTTPException(status_code=404, detail="没有可用的雷达批次")
    return HTMLResponse(render_html_dashboard(data_root, selected_run))


@app.get("/polyv-evidence/{evidence_path:path}")
async def serve_polyv_evidence(evidence_path: str):
    """Serve only evidence files inside the local radar data directory."""
    data_root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data")).resolve()
    target = (data_root / evidence_path).resolve()
    try:
        target.relative_to(data_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="证据文件不存在") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="证据文件不存在")
    return FileResponse(target)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/env/check")
async def check_environment():
    """Check if MediaCrawler environment is configured correctly"""
    try:
        # Run uv run main.py --help command to check environment
        # Use PROJECT_ROOT so it works regardless of where uvicorn was started
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["uv", "run", "main.py", "--help"],
                    capture_output=True,
                    timeout=30.0,
                    cwd=str(PROJECT_ROOT)
                )
            )
            stdout, stderr = process.stdout, process.stderr  # bytes
        else:
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "main.py", "--help",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(PROJECT_ROOT)  # Project root directory
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0  # 30 seconds timeout
            )
        if process.returncode == 0:
            return {
                "success": True,
                "message": "MediaCrawler environment configured correctly",
                "output": stdout.decode("utf-8", errors="ignore")[:500]  # Truncate to first 500 characters
            }
        else:
            error_msg = stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")
            return {
                "success": False,
                "message": "Environment check failed",
                "error": error_msg[:500]
            }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": "Environment check timeout",
            "error": "Command execution exceeded 30 seconds"
        }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "uv command not found",
            "error": "Please ensure uv is installed and configured in system PATH"
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Environment check error",
            "error": f"{type(e).__name__}: {str(e) or 'Unknown'}"
        }


@app.get("/api/config/platforms")
async def get_platforms():
    """Get list of supported platforms"""
    return {
        "platforms": [
            {"value": "xhs", "label": "Xiaohongshu", "icon": "book-open"},
            {"value": "dy", "label": "Douyin", "icon": "music"},
            {"value": "ks", "label": "Kuaishou", "icon": "video"},
            {"value": "bili", "label": "Bilibili", "icon": "tv"},
            {"value": "wb", "label": "Weibo", "icon": "message-circle"},
            {"value": "tieba", "label": "Baidu Tieba", "icon": "messages-square"},
            {"value": "zhihu", "label": "Zhihu", "icon": "help-circle"},
        ]
    }


@app.get("/api/config/options")
async def get_config_options():
    """Get all configuration options"""
    return {
        "login_types": [
            {"value": "qrcode", "label": "QR Code Login"},
            {"value": "cookie", "label": "Cookie Login"},
        ],
        "crawler_types": [
            {"value": "search", "label": "Search Mode"},
            {"value": "detail", "label": "Detail Mode"},
            {"value": "creator", "label": "Creator Mode"},
        ],
        "save_options": [
            {"value": "jsonl", "label": "JSONL File"},
            {"value": "json", "label": "JSON File"},
            {"value": "csv", "label": "CSV File"},
            {"value": "excel", "label": "Excel File"},
            {"value": "sqlite", "label": "SQLite Database"},
            {"value": "db", "label": "MySQL Database"},
            {"value": "mongodb", "label": "MongoDB Database"},
        ],
    }


@app.get("/api/radar/summary")
async def radar_summary(run_id: str | None = None):
    """Read-only local POLYV radar summary; never sends or mutates browser state."""
    data_root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data"))
    store = RadarStore(data_root / "radar.sqlite3")
    store.initialize()
    selected_run = run_id or ""
    if not selected_run:
        row = store.connection.execute("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        selected_run = str(row[0]) if row else ""
    leads = store.load_leads(selected_run) if selected_run else []
    cleaned, filtered = clean_dashboard_leads(leads)
    queue = merge_dashboard_queue(
        store.load_outreach_queue(selected_run),
        load_dry_run_queue(data_root, selected_run) if selected_run else [],
    )
    attempts = store.connection.execute(
        "SELECT status, COUNT(*) AS count FROM outreach_attempts WHERE run_id = ? GROUP BY status",
        (selected_run,),
    ).fetchall()
    run_counts = store.connection.execute(
        """SELECT
               (SELECT COUNT(*) FROM run_contents WHERE run_id = ?) AS contents,
               (SELECT COUNT(*) FROM run_comments WHERE run_id = ?) AS comments""",
        (selected_run, selected_run),
    ).fetchone() if selected_run else None
    manual_candidates = load_manual_candidates(data_root, selected_run, limit=500)
    db_contents = int(run_counts["contents"]) if run_counts else 0
    db_comments = int(run_counts["comments"]) if run_counts else 0
    count_source = "sqlite_run_links"
    if db_contents == 0 and db_comments == 0 and manual_candidates:
        db_contents, db_comments = _manual_artifact_counts(manual_candidates)
        count_source = "manual_candidate_artifacts"
    dry_run_queue = [item for item in queue if item.get("source") == "dispatch_file"]
    manual_locator_verified = sum(item.get("locator_status") == "verified" for item in manual_candidates)
    manual_locator_failed = sum(
        bool(item.get("locator_status")) and item.get("locator_status") != "verified"
        for item in manual_candidates
    )
    file_verified = sum(
        bool(item.get("submitted", False) and item.get("verified", False))
        for item in dry_run_queue
    )
    manual_sent = sum(
        str(item.get("dispatch_status", "")) == "submitted_verified"
        for item in manual_candidates
    )
    demand_candidates = sum(item.score >= 4 and item.decision != "reject" for item in leads)
    if not leads and manual_candidates:
        demand_candidates = sum(
            int(item.get("rule_score", 0) or 0) >= 4
            and str(item.get("triage_label", "")) != "drop_low_signal"
            for item in manual_candidates
        )
    result = {
        "run_id": selected_run,
        "leads": len(leads),
        "raw_leads": len(leads),
        "cleaned_leads": len(cleaned),
        "filtered_leads": len(filtered),
        "manual_candidates": len(manual_candidates),
        "filtered_reasons": filter_reason_counts(filtered),
        "contents": db_contents,
        "comments": db_comments,
        "count_source": count_source,
        "demand_candidates": demand_candidates,
        "locator_verified": manual_locator_verified,
        "locator_failed": manual_locator_failed,
        "approved_queue": len([item for item in queue if item.get("lead_status") in {"approved", "queued"}]),
        "dry_run_queue": len(dry_run_queue),
        "dry_run_completed": sum(item.get("dry_run_status") in {"dry_run", "failed"} for item in dry_run_queue),
        "real_sent": max(sum(str(row["status"]) == "submitted_verified" for row in attempts) + file_verified, manual_sent),
        "status_events_raw": store.count_status_events(selected_run, distinct=False) if selected_run else 0,
        "status_events_distinct": store.count_status_events(selected_run, distinct=True) if selected_run else 0,
        "attempts": {str(row["status"]): int(row["count"]) for row in attempts},
    }
    store.close()
    return result


@app.get("/api/radar/runs")
async def radar_runs(limit: int = 30):
    """List selectable local radar batches with raw and cleaned counts."""
    data_root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data"))
    store = RadarStore(data_root / "radar.sqlite3")
    store.initialize()
    rows = store.connection.execute(
        "SELECT run_id, started_at, finished_at, status, platform_status FROM runs ORDER BY started_at DESC LIMIT ?",
        (max(1, min(limit, 100)),),
    ).fetchall()
    result = []
    for row in rows:
        run_id = str(row["run_id"])
        leads = store.load_leads(run_id)
        cleaned, filtered = clean_dashboard_leads(leads)
        counts = store.connection.execute(
            """SELECT
                   (SELECT COUNT(*) FROM run_contents WHERE run_id = ?) AS contents,
                   (SELECT COUNT(*) FROM run_comments WHERE run_id = ?) AS comments""",
            (run_id, run_id),
        ).fetchone()
        manual_candidates = load_manual_candidates(data_root, run_id)
        contents = int(counts["contents"])
        comments = int(counts["comments"])
        count_source = "sqlite_run_links"
        if contents == 0 and comments == 0 and manual_candidates:
            contents, comments = _manual_artifact_counts(manual_candidates)
            count_source = "manual_candidate_artifacts"
        result.append(
            {
                "run_id": run_id,
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "status": row["status"],
                "platform_status": row["platform_status"],
                "contents": contents,
                "comments": comments,
                "count_source": count_source,
                "raw_leads": len(leads),
                "cleaned_leads": len(cleaned),
                "filtered_leads": len(filtered),
                "manual_candidates": len(manual_candidates),
                "dry_run_queue": len(load_dry_run_queue(data_root, run_id)),
            }
        )
    store.close()
    return {"runs": result}


@app.get("/api/radar/leads")
async def radar_leads(run_id: str, limit: int = 100, view: str = "cleaned"):
    data_root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data"))
    store = RadarStore(data_root / "radar.sqlite3")
    store.initialize()
    raw = store.load_leads(run_id)
    cleaned, filtered = clean_dashboard_leads(raw)
    selected = raw if view == "all" else cleaned
    rows = [lead.to_dict() for lead in selected[: max(1, min(limit, 500))]]
    store.close()
    return {
        "run_id": run_id,
        "view": "all" if view == "all" else "cleaned",
        "leads": rows,
        "raw_count": len(raw),
        "cleaned_count": len(cleaned),
        "filtered_count": len(filtered),
        "filtered_reasons": filter_reason_counts(filtered),
    }


@app.get("/api/radar/manual-candidates")
async def radar_manual_candidates(run_id: str, limit: int = 50):
    data_root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data"))
    return {"run_id": run_id, "candidates": load_manual_candidates(data_root, run_id, limit)}


@app.get("/api/radar/queue")
async def radar_queue(run_id: str | None = None):
    data_root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data"))
    store = RadarStore(data_root / "radar.sqlite3")
    store.initialize()
    selected_run = run_id or ""
    rows = merge_dashboard_queue(
        store.load_outreach_queue(selected_run),
        load_dry_run_queue(data_root, selected_run) if selected_run else [],
    )
    store.close()
    return {"queue": rows}


# Mount static resources - must be placed after all routes
if os.path.exists(WEBUI_DIR):
    assets_dir = os.path.join(WEBUI_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    # Mount logos directory
    logos_dir = os.path.join(WEBUI_DIR, "logos")
    if os.path.exists(logos_dir):
        app.mount("/logos", StaticFiles(directory=logos_dir), name="logos")
    # Mount other static files (e.g., vite.svg)
    app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="webui-static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
