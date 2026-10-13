from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .locator import is_deliverable_lead
from .storage import RadarStore


def _key(run_id: str, lead) -> str:
    return ":".join((run_id, lead.platform, lead.content_id, lead.comment_id))


def _normalize(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _history_matches(item: dict, lead) -> bool:
    urls = {_normalize(lead.url), _normalize(lead.comment_url)} - {""}
    return (
        _normalize(item.get("platform")) == _normalize(lead.platform)
        and _normalize(item.get("target_url")) in urls
        and _normalize(item.get("target_author")) == _normalize(lead.user)
        and (
            not lead.quote
            or not item.get("target_quote")
            or _normalize(item.get("target_quote")) == _normalize(lead.quote)
        )
    )


def _verified_history_item(history: list[dict], lead) -> dict | None:
    for item in reversed(history):
        screenshot = str(item.get("screenshot", ""))
        if (
            _history_matches(item, lead)
            and item.get("mode") == "live"
            and item.get("submitted") is True
            and item.get("verified") is True
            and screenshot
            and Path(screenshot).is_file()
        ):
            return item
    return None


def build_cleaning_rows(config, run_id: str, reply_evidence_path: Path | None = None) -> list[dict]:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads(run_id)
    store.close()

    evidence_path = reply_evidence_path or (
        config.data_root / "locators" / f"{run_id}-reply-evidence" / "locator-output.json"
    )
    evidence_rows = []
    if evidence_path.is_file():
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence_rows = payload.get("results", []) if isinstance(payload, dict) else []
        except (OSError, json.JSONDecodeError):
            evidence_rows = []
    evidence_map = {
        ":".join(str(item.get(name, "")) for name in ("run_id", "platform", "content_id", "comment_id")): item
        for item in evidence_rows
        if isinstance(item, dict)
    }
    history = _load_jsonl(config.data_root / "reply_history.jsonl")
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for lead in leads:
        evidence = evidence_map.get(_key(run_id, lead), {})
        verified_history = _verified_history_item(history, lead)
        reply_status = str(evidence.get("reply_evidence_status", "not_checked"))
        if verified_history:
            send_evidence_status = "verified_sent"
            retry_status = "keep_verified"
            reason = "Ego Lite发送后重新找到完整回复文本，且截图存在"
        elif reply_status == "text_found":
            send_evidence_status = "reply_text_found_thread_unverified"
            retry_status = "do_not_resend_until_thread_verified"
            reason = "页面找到完整回复文本，但未同时定位到目标原评论"
        elif lead.locator_status != "verified":
            send_evidence_status = "no_reply_evidence"
            retry_status = "not_sent_target_not_found"
            reason = "目标作者和完整原话未能在当前页面唯一定位"
        elif lead.decision == "reject" or not is_deliverable_lead(lead, config.min_lead_score):
            send_evidence_status = "no_reply_evidence"
            retry_status = "not_sent_quality_gate"
            reason = "目标评论已定位，但当前规则未同时满足企业场景和项目/选型证据"
        else:
            send_evidence_status = "no_reply_evidence"
            retry_status = "ready_for_skill_retry"
            reason = "目标评论和交付门槛已通过，可进入 Skill 发送队列"
        rows.append(
            {
                "run_id": run_id,
                "platform": lead.platform,
                "content_id": lead.content_id,
                "comment_id": lead.comment_id,
                "url": lead.url,
                "comment_url": lead.comment_url,
                "user": lead.user,
                "quote": lead.quote,
                "stage": lead.stage,
                "decision": lead.decision,
                "score": lead.score,
                "locator_status": lead.locator_status,
                "reply_evidence_status": reply_status,
                "send_evidence_status": send_evidence_status,
                "retry_status": retry_status,
                "reason": reason,
                "reply_screenshot": (verified_history or {}).get("screenshot", ""),
                "checked_at": now,
            }
        )
    return rows


def write_cleaning_artifacts(config, run_id: str, rows: list[dict], output_suffix: str = "send-cleaned") -> dict:
    reports = config.data_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    suffix = f"-{output_suffix.strip('-')}" if output_suffix.strip("-") else ""
    jsonl_path = reports / f"{run_id}{suffix}.jsonl"
    markdown_path = reports / f"{run_id}{suffix}.md"
    jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    counts = Counter(row["send_evidence_status"] for row in rows)
    retry_counts = Counter(row["retry_status"] for row in rows)
    lines = [
        f"# POLYV 自动回复清洗：{run_id}",
        "",
        f"共 {len(rows)} 条。旧 pushed、旧截图和旧日志不单独视为真实发送证据。",
        "",
        "## 汇总",
        "",
        "| 状态 | 数量 |",
        "| --- | ---: |",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## 后续处理", "", "| 处理状态 | 数量 |", "| --- | ---: |"])
    for key, value in sorted(retry_counts.items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## 全部记录",
            "",
            "| 平台 | 线索ID | 用户 | 原始评论 | 定位 | 回复证据 | 处理 | 原因 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        def cell(value: object) -> str:
            return str(value or "").replace("|", "\\|").replace("\n", " ").strip()

        lines.append(
            f"| {cell(row['platform'])} | {cell(row['comment_id'])} | {cell(row['user'])} | "
            f"{cell(row['quote'])} | {cell(row['locator_status'])} | {cell(row['send_evidence_status'])} | "
            f"{cell(row['retry_status'])} | {cell(row['reason'])} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"jsonl": jsonl_path, "markdown": markdown_path, "counts": counts, "retry_counts": retry_counts}


def clean_store(config, run_id: str, reply_evidence_path: Path | None = None, output_suffix: str = "send-cleaned") -> dict:
    rows = build_cleaning_rows(config, run_id, reply_evidence_path)
    artifacts = write_cleaning_artifacts(config, run_id, rows, output_suffix)
    return {
        "run_id": run_id,
        "rows": len(rows),
        "jsonl_path": str(artifacts["jsonl"]),
        "markdown_path": str(artifacts["markdown"]),
        "send_evidence": dict(artifacts["counts"]),
        "retry_status": dict(artifacts["retry_counts"]),
    }
