from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .conversion_engine import build_conversion_pack
from .locator import is_deliverable_lead
from .models import LeadEvidence
from .status import transition
from .storage import RadarStore
from .target_urls import dispatch_target_url, normalize_comment_url
from .url_validation import validate_url, validate_urls_with_ego


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
    repo_root: Path | None = None,
    taskspace: int | None = None,
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
    old_stage = lead.stage or "discovered"
    if old_stage == "legacy_unverified":
        store.close()
        raise ValueError("历史未验证记录必须先重新完成证据核验和模型复核，不能直接审批")
    if not is_deliverable_lead(lead, config.min_lead_score):
        store.close()
        raise ValueError("线索未通过最终证据门槛：需有真实作者、企业场景和项目/选型证据")
    if taskspace is not None:
        if taskspace <= 0:
            store.close()
            raise ValueError("审批使用 Ego Lite URL 校验时，TaskSpace 必须为正整数")
        checks, log = validate_urls_with_ego(
            [lead.url],
            repo_root or Path.cwd(),
            config.data_root / "url-checks" / run_id,
            taskspace=taskspace,
        )
        url_check = checks.get(lead.url, {
            "url": lead.url,
            "status": "error",
            "reason": log or "Ego Lite未返回URL校验结果",
        })
    else:
        url_check = url_checker(lead.url)
    if url_check.get("status") != "ok":
        store.close()
        raise ValueError(f"内容URL未通过可访问性验证: {url_check.get('reason', 'unknown')}")
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
    source_type = approved.source_type or "comment"
    comment_url = normalize_comment_url(approved.comment_url, approved.url, source_type)
    queue_id = store.queue_outreach({
        "run_id": run_id,
        "platform": approved.platform,
        "content_id": approved.content_id,
        "comment_id": approved.comment_id,
        "lead_status": "approved",
        "target_url": dispatch_target_url(approved.url, comment_url, source_type),
        "content_url": approved.url,
        "comment_url": comment_url,
        "source_type": source_type,
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
