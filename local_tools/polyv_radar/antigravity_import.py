from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .models import CommentRecord, ContentRecord, LeadEvidence
from .storage import RadarStore


PLATFORM_MAP = {
    "抖音": "dy",
    "小红书": "xhs",
    "B站": "bili",
    "哔哩哔哩": "bili",
    "知乎": "zhihu",
}

SAFE_FILES = (
    "leads_master_data.json",
    "polyv_radar_keyword_taxonomy.json",
    "bili_auto_reply_tasks.json",
    "live_verification_result.json",
    "ocr_cache.json",
    "polyv_20_leads.md",
    "polyv_20_new_leads_batch3_report.md",
    "polyv_20_leads_dynamic_dashboard.md",
    "polyv_30_leads_dynamic_dashboard.md",
    "polyv_leads_interactive_dashboard.html",
    "polyv_10_personalized_outreach.md",
    "polyv_stealth_inbox_hook_cases.md",
    "inbox_consultant_conversion_playbook.md",
    "polyv_predicament_and_chatgpt_strategic_decision_report.md",
    "live_link_and_comment_verification_audit.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_safe_assets(source: Path, destination: Path) -> list[dict[str, str]]:
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, str]] = []
    for name in SAFE_FILES:
        source_file = source / name
        if not source_file.is_file():
            continue
        target = destination / name
        shutil.copy2(source_file, target)
        copied.append({"source": str(source_file), "destination": str(target), "sha256": _sha256(target)})
    screenshot_source = source / "screenshots"
    screenshot_destination = destination / "screenshots"
    if screenshot_source.is_dir():
        for source_file in sorted(screenshot_source.rglob("*.png")):
            relative = source_file.relative_to(screenshot_source)
            target = screenshot_destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
            copied.append({"source": str(source_file), "destination": str(target), "sha256": _sha256(target)})
    return copied


def _parse_date(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _content_id(url: str, fallback: str) -> str:
    path = urlsplit(url).path.strip("/")
    return path.split("/")[-1] or fallback


def _solution(scenario: str) -> str:
    text = str(scenario or "")
    if any(term in text for term in ("培训", "课程", "学习")):
        return "企业培训/视频点播/内容安全（能力需售前确认）"
    if any(term in text for term in ("会议", "大会", "发布", "活动", "直播")):
        return "企业活动视频云/活动承载/内容安全（能力需售前确认）"
    return "视频云或技术集成方向（能力需售前确认）"


def import_antigravity(
    source: Path,
    data_root: Path,
    session_id: str,
    store_path: Path | None = None,
) -> dict:
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"迁移源目录不存在: {source}")
    leads_path = source / "leads_master_data.json"
    rows = json.loads(leads_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("leads_master_data.json 必须是数组")

    import_id = f"legacy-antigravity-{session_id}"
    destination = Path(data_root) / "legacy" / f"antigravity-{session_id}"
    copied = _copy_safe_assets(source, destination)
    manifest_path = destination / "migration-manifest.json"
    run_id = import_id
    store = RadarStore(store_path or Path(data_root) / "radar.sqlite3")
    store.initialize()
    started = datetime.now(timezone.utc).isoformat()
    store.save_legacy_import({
        "import_id": import_id,
        "session_id": session_id,
        "source_path": str(source),
        "destination_path": str(destination),
        "manifest_path": str(manifest_path),
        "row_count": len(rows),
        "status": "started",
        "imported_at": started,
    })

    store.save_run(run_id, "legacy_imported", {"source": "antigravity", "rows": len(rows)}, started, started)
    imported_leads: list[LeadEvidence] = []
    counts: dict[str, int] = {}
    for row in rows:
        platform = PLATFORM_MAP.get(str(row.get("platform", "")), str(row.get("platform", "")).lower())
        if platform not in {"dy", "xhs", "bili", "zhihu"}:
            platform = "unknown"
        lead_id = str(row.get("id", "")) or f"ROW-{len(imported_leads) + 1:03d}"
        url = str(row.get("url", ""))
        content_id = _content_id(url, lead_id)
        comment_id = f"legacy:{lead_id}"
        quote = str(row.get("original_inquiry", "")).strip()
        user = str(row.get("user_name", "")).strip()
        scenario = str(row.get("scenario", "")).strip()
        original_status = str(row.get("status", "")).strip().lower()
        rejected = original_status == "invalidated"
        stage = "legacy_rejected" if rejected else "legacy_unverified"
        decision = "reject" if rejected else "legacy_unverified"
        rejection_reason = "Antigravity原状态为invalidated" if rejected else "历史状态未重新定位；截图、OCR和pushed标记不作为发送成功证据"
        published_at = _parse_date(str(row.get("pub_date", "")))
        content = ContentRecord(
            platform=platform,
            content_id=content_id,
            title=scenario,
            text=quote,
            url=url,
            author=user,
            published_at=published_at,
            source_keywords=[scenario] if scenario else [],
            content_type="legacy_antigravity",
        )
        comment = CommentRecord(
            platform=platform,
            comment_id=comment_id,
            content_id=content_id,
            text=quote,
            author=user,
            published_at=published_at,
            source_keyword=scenario,
            source_type="comment",
            published_at_raw=str(row.get("pub_date", "")),
        )
        store.upsert_content(content, run_id)
        store.upsert_comment(comment, run_id)
        lead = LeadEvidence(
            platform=platform,
            content_id=content_id,
            comment_id=comment_id,
            url=url,
            user=user,
            quote=quote,
            category=scenario,
            solution=_solution(scenario),
            score=0 if rejected else 4,
            reasons=[rejection_reason],
            evidence_sentences=[quote] if quote else [],
            outreach=str(row.get("stealth_hook_reply", "")),
            content_title=scenario,
            event_type=scenario,
            source_type="comment",
            locator_status="pending",
            locator_reason="历史导入未验证",
            stage=stage,
            decision=decision,
        )
        imported_leads.append(lead)
        counts[stage] = counts.get(stage, 0) + 1
        store.add_status_event(run_id, platform, content_id, comment_id, stage, "", "antigravity_import", rejection_reason, {"legacy_id": lead_id, "original_status": original_status})

    store.save_leads(run_id, imported_leads)
    finished = datetime.now(timezone.utc).isoformat()
    manifest = {
        "import_id": import_id,
        "session_id": session_id,
        "source": str(source),
        "destination": str(destination),
        "run_id": run_id,
        "row_count": len(rows),
        "stage_counts": counts,
        "source_file_sha256": _sha256(leads_path),
        "copied_files": copied,
        "excluded": [".env", "cookies", "binary OCR tools", "nested repositories", "credential-bearing logs"],
        "imported_at": finished,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    store.save_legacy_import({
        "import_id": import_id,
        "session_id": session_id,
        "source_path": str(source),
        "destination_path": str(destination),
        "manifest_path": str(manifest_path),
        "row_count": len(rows),
        "status": "completed",
        "imported_at": finished,
    })
    store.close()
    return {
        "import_id": import_id,
        "run_id": run_id,
        "rows": len(rows),
        "stage_counts": counts,
        "manifest_path": str(manifest_path),
        "submitted_verified": 0,
    }
