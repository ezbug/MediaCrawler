from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .conversion_engine import build_conversion_pack
from .models import LeadEvidence
from .status import transition
from .storage import RadarStore
from .url_validation import validate_url


def _matches_lead(lead: LeadEvidence, lead_id: str) -> bool:
    expected = str(lead_id).strip()
    candidates = {
        lead.comment_id,
        lead.content_id,
        lead.comment_id.removeprefix("legacy:"),
    }
    return expected in candidates


def approve_lead(
    config,
    run_id: str,
    lead_id: str,
    approved_by: str = "user",
    draft_text: str = "",
    url_checker=validate_url,
) -> dict:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads(run_id)
    lead = next((item for item in leads if _matches_lead(item, lead_id)), None)
    if lead is None:
        store.close()
        raise ValueError(f"未找到线索: {lead_id}")
    if lead.locator_status != "verified":
        store.close()
        raise ValueError("只有 locator_status=verified 的记录才允许审批")
    url_check = url_checker(lead.url)
    if url_check.get("status") != "ok":
        store.close()
        raise ValueError(f"内容URL未通过可访问性验证: {url_check.get('reason', 'unknown')}")
    old_stage = lead.stage or "discovered"
    if old_stage == "legacy_unverified":
        store.close()
        raise ValueError("历史未验证记录必须先重新完成证据核验和模型复核，不能直接审批")
    transition(old_stage, "approved", "人工审批且定位、URL均已验证")
    text = draft_text.strip() or build_conversion_pack(lead).reply_text
    approved = LeadEvidence(
        **{
            **lead.to_dict(),
            "stage": "approved",
            "decision": "manual_confirmed",
            "outreach": text,
            "locator_reason": "人工审批前通过定位和URL验证",
        }
    )
    store.save_leads(run_id, [approved if item is lead else item for item in leads])
    store.add_status_event(
        run_id, lead.platform, lead.content_id, lead.comment_id, "approved", old_stage,
        approved_by, "人工审批；允许进入预批准队列", {"lead_id": lead_id, "url_check": url_check},
    )
    queue_id = store.queue_outreach({
        "run_id": run_id,
        "platform": approved.platform,
        "content_id": approved.content_id,
        "comment_id": approved.comment_id,
        "lead_status": "approved",
        "target_url": approved.comment_url or approved.url,
        "target_author": approved.user,
        "draft_text": text,
        "locator_status": approved.locator_status,
        "url_status": url_check.get("status", ""),
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    })
    store.close()
    return {
        "run_id": run_id,
        "lead_id": lead_id,
        "queue_id": queue_id,
        "status": "approved",
        "url_check": url_check,
    }
