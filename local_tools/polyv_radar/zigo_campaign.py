"""Read the verified ZigoAI GEO social-lead ledger for the business board."""
from __future__ import annotations

import json
from pathlib import Path


DEFAULT_ROOT = Path("/Users/sexpistole111/Documents/workplace/polyv-radar-data/zigoai/geo/workflow-runs")
LEDGER_NAME = "verified-candidates.jsonl"


def list_campaigns(root: Path) -> list[dict]:
    if not root.is_dir():
        return []
    campaigns = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not (directory / LEDGER_NAME).is_file():
            continue
        campaigns.append({"campaign_id": directory.name, "brand": "ZigoAI", "product_domain": "可信 GEO", "source": "公开社媒需求证据"})
    return campaigns


def _ledger_path(root: Path, campaign_id: str) -> Path:
    if not campaign_id or Path(campaign_id).name != campaign_id:
        raise ValueError("invalid campaign id")
    path = root / campaign_id / LEDGER_NAME
    if not path.is_file():
        raise FileNotFoundError(campaign_id)
    return path


def _lead_status(record: dict) -> tuple[str, str, str]:
    layer = str(record.get("evidence_layer") or "insufficient_evidence")
    if layer == "comment_verified":
        return "评论级已核验", "评论中明确询问服务或案例", "人工核验业务主体与联系入口；草稿保持未发送"
    if layer == "content_buyer_verified":
        return "内容级需求已核验", "原帖表达 GEO 服务采购或筛选需求", "人工核验业务主体与联系入口；草稿保持未发送"
    return "待补证据", "本次未复核通过", "仅在原帖重新可公开访问时复核；本条不计入已核验"


def load_campaign(root: Path, campaign_id: str) -> tuple[list[dict], dict]:
    records = []
    for line in _ledger_path(root, campaign_id).read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("ledger record must be an object")
            records.append(value)
    leads = []
    for record in records:
        evidence_status, buyer_signal, next_action = _lead_status(record)
        sent = record.get("sent") is True
        reply_status = str(record.get("reply_status") or "draft_only_not_sent")
        pending_submission = record.get("submission_attempted") is True and record.get("publication_verified") is not True
        outreach_status = "已发送" if sent else "未发送；不具备自动触达资格"
        if sent:
            next_action = "原帖评论已核验发布；等待对方实质回复"
        if pending_submission:
            outreach_status = "曾点击提交；发布待核验"
            next_action = "核验我方账号、完整回复及目标关系；结果明确前不重发"
        if record.get("publication_observed") is True and record.get("target_relation_verified") is not True:
            outreach_status = "我方顶层评论已发布；未回复到指定评论下"
            next_action = "保留截图证据；本条不计指定评论回复成功，不重发"
        leads.append({
            "candidate_id": record.get("candidate_id"), "author": record.get("author"),
            "identity_status": "社媒账号；非企业主体核验", "evidence_status": evidence_status,
            "source_quote": record.get("source_quote"), "published_at": record.get("published_at"),
            "content_url": record.get("content_url"), "buyer_signal": buyer_signal,
            "reply_suggestion": record.get("reply_suggestion"),
            "outreach_status": outreach_status,
            "reply_status": "已有回复" if reply_status == "reply_verified" else "暂无回复证据",
            "next_action": next_action if evidence_status != "待补证据" else (record.get("verification_error") or next_action),
        })
    summary = {
        "campaign_id": campaign_id, "brand": "ZigoAI", "product_domain": "可信 GEO", "total_leads": len(leads),
        "comment_verified": sum(record.get("evidence_layer") == "comment_verified" for record in records),
        "content_buyer_verified": sum(record.get("evidence_layer") == "content_buyer_verified" for record in records),
        "pending_evidence": sum(record.get("evidence_layer") == "insufficient_evidence" for record in records),
        "outreach_sent": sum(record.get("sent") is True for record in records),
        "replies": sum(record.get("reply_status") == "reply_verified" for record in records),
    }
    summary["submission_pending"] = sum(record.get("submission_attempted") is True and record.get("publication_verified") is not True for record in records)
    observed = sum(record.get("publication_observed") is True for record in records)
    if observed:
        summary["publication_observed"] = observed
        summary["target_mismatch"] = sum(record.get("publication_observed") is True and record.get("target_relation_verified") is not True for record in records)
    return leads, summary
