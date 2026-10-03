"""Customer campaigns: configured local database, strictly read-only."""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import sqlite3

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from local_tools.polyv_radar.customer_campaign_dashboard import render_customer_campaign_dashboard
from local_tools.polyv_radar.storage import RadarStore

router = APIRouter(prefix="/radar/campaigns", tags=["customer campaigns"])


@contextmanager
def _campaign_store():
    root = Path(os.environ.get("POLYV_RADAR_DATA_ROOT", "/Users/sexpistole111/Documents/workplace/polyv-radar-data"))
    path = root / "radar.sqlite3"
    if not path.is_file():
        yield None
        return
    # Bypass RadarStore's directory/DB-creating constructor and all migrations.
    store = RadarStore.__new__(RadarStore)
    store.path = path
    try:
        store.connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        store.connection.row_factory = sqlite3.Row
        store.connection.execute("PRAGMA query_only = ON")
        store.connection.execute("BEGIN")
    except sqlite3.Error as exc:
        if hasattr(store, "connection"):
            store.close()
        raise HTTPException(503, "活动数据库读取失败") from exc
    try:
        yield store
    except (sqlite3.Error, ValueError) as exc:
        raise HTTPException(503, "活动数据读取失败") from exc
    finally:
        store.close()


def _campaign_records(store: RadarStore | None) -> list[dict]:
    if store is None:
        return []
    if not store.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='polyv_customer_campaigns'"
    ).fetchone():
        return []
    return [dict(row) for row in store.connection.execute(
        "SELECT campaign_id, brand, sector, target_companies, target_exchanges "
        "FROM polyv_customer_campaigns WHERE brand='POLYV' ORDER BY campaign_id"
    )]


def latest_history_run() -> str:
    with _campaign_store() as store:
        if store is None or not store.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone():
            return ""
        row = store.connection.execute(
            "SELECT run_id FROM runs WHERE run_id NOT LIKE 'legacy-%' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else ""


def _require_campaign(store: RadarStore | None, campaign_id: str) -> None:
    if not any(row["campaign_id"] == campaign_id for row in _campaign_records(store)):
        raise HTTPException(404, "客户活动不存在或尚未初始化")


def _storage_module():
    try:
        return importlib.import_module("local_tools.polyv_radar.customer_campaign")
    except ImportError as exc:
        raise HTTPException(503, "客户活动存储模块尚未就绪") from exc


def _display_companies(store: RadarStore, campaign_id: str) -> list[dict]:
    rows = _storage_module().list_companies(store, campaign_id)
    by_id = {row["company_id"]: row for row in rows}
    for row in store.connection.execute(
        "SELECT company_id, event_type, payload FROM polyv_campaign_events WHERE campaign_id=? ORDER BY event_id",
        (campaign_id,),
    ):
        company = by_id.get(row["company_id"])
        if company is not None:
            field = "outreach_events" if row["event_type"] == "outreach" else "reply_events"
            company.setdefault(field, []).append(json.loads(row["payload"]))
    return rows


@router.get("")
def campaigns():
    with _campaign_store() as store:
        return {"campaigns": _campaign_records(store)}


@router.get("/{campaign_id}/summary")
def summary(campaign_id: str):
    with _campaign_store() as store:
        _require_campaign(store, campaign_id)
        return _storage_module().campaign_summary(store, campaign_id)


@router.get("/{campaign_id}/companies")
def companies(campaign_id: str):
    with _campaign_store() as store:
        _require_campaign(store, campaign_id)
        return {"campaign_id": campaign_id, "companies": _display_companies(store, campaign_id)}


@router.get("/{campaign_id}/dashboard.html", response_class=HTMLResponse)
def dashboard(campaign_id: str):
    with _campaign_store() as store:
        _require_campaign(store, campaign_id)
        module = _storage_module()
        page = render_customer_campaign_dashboard(
            _display_companies(store, campaign_id), module.campaign_summary(store, campaign_id), campaign_id
        )
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})
