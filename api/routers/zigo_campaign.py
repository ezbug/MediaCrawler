"""Read-only routes for the ZigoAI GEO social-lead business board."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from local_tools.polyv_radar.zigo_campaign import DEFAULT_ROOT, list_campaigns, load_campaign
from local_tools.polyv_radar.zigo_campaign_dashboard import render_zigo_campaign_dashboard


router = APIRouter(prefix="/radar/zigo-campaigns", tags=["zigo customer campaigns"])


def campaign_root() -> Path:
    return Path(os.environ.get("ZIGO_CAMPAIGN_DATA_ROOT", str(DEFAULT_ROOT)))


def latest_campaign() -> str:
    campaigns = list_campaigns(campaign_root())
    return campaigns[-1]["campaign_id"] if campaigns else ""


def _campaign_or_404(campaign_id: str) -> tuple[list[dict], dict]:
    try:
        return load_campaign(campaign_root(), campaign_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "ZigoAI 线索活动不存在") from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "ZigoAI 线索活动数据读取失败") from exc


@router.get("")
def campaigns():
    return {"campaigns": list_campaigns(campaign_root())}


@router.get("/{campaign_id}/summary")
def summary(campaign_id: str):
    _, result = _campaign_or_404(campaign_id)
    return result


@router.get("/{campaign_id}/leads")
def leads(campaign_id: str):
    result, _ = _campaign_or_404(campaign_id)
    return {"campaign_id": campaign_id, "leads": result}


@router.get("/{campaign_id}/dashboard.html", response_class=HTMLResponse)
def dashboard(campaign_id: str):
    records, result = _campaign_or_404(campaign_id)
    return HTMLResponse(render_zigo_campaign_dashboard(records, result, campaign_id), headers={"Cache-Control": "no-store"})
