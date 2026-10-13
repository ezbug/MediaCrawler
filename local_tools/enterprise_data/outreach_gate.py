"""Evidence-backed event extraction and mandatory cold-email review."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
EVENTS = {
    "业绩说明会": ("enterprise_live", {"ir"}),
    "投资者日": ("enterprise_live", {"ir"}),
    "新品发布会": ("enterprise_live", {"marketing"}),
    "发布会": ("enterprise_live", {"marketing"}),
    "展会": ("enterprise_live", {"marketing"}),
    "培训": ("enterprise_training", {"training"}),
    "客户大会": ("private_live", {"marketing"}),
    "伙伴大会": ("enterprise_training", {"marketing", "training"}),
    "技术开放日": ("sdk", {"marketing"}),
    "股东大会": ("irrelevant", set()),
    "分红": ("irrelevant", set()),
}
ROLE_PREFIXES = {"training": "training", "hr": "training", "ir": "ir",
                 "finance": "ir", "events": "marketing", "pr": "marketing",
                 "market": "marketing", "marketing": "marketing"}
DATE_RE = re.compile(r"(?<![\d:])(?:(20\d{2})\s*[年/-]\s*)?(0?[1-9]|1[0-2])\s*[月/-]\s*(0?[1-9]|[12]\d|3[01])\s*日?(?![\d:])")
MARKERS = re.compile(r"测试邮件|邮件测试|测试标记|测试版|\bTEST\b|\bTODO\b|\bTBD\b|Dry[- ]?Run|本稿|发送前|待确认|待填|\{[^\n]*?\}|\[(?:公司名|姓名|日期|收件人)\]|<[^>]*(?:COMPANY|DATE|姓名|公司|日期)[^>]*>", re.I)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def today() -> date:
    return datetime.now(TZ).date()


def host_allowed(url: str, domains: list[str]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and any(
        host == domain or host.endswith("." + domain) for domain in domains
    )


def extract_events(capture: dict, target: dict, as_of: date) -> list[dict]:
    """Only same-clause company/event/date assertions become evidence records."""
    if not host_allowed(capture.get("url", ""), target["source_domains"]):
        return []
    text = capture.get("text", "")
    aliases = target.get("aliases", []) + [target["name"]]
    title = capture.get("title", "")
    issuer_title = any(name in title for name in aliases) and "关于召开" in title
    title_kind = next((name for name in EVENTS if name in title), None)
    rows = {}
    clauses = re.split(r"[。！？;；]", text)
    if issuer_title:
        clauses += re.findall(r"会议召开时间[：:][^\n]{0,120}", text)
    for clause in clauses:
        explicit_company = any(name in clause for name in aliases)
        inherited_company = issuer_title and bool(re.search(r"公司计划于|公司将于|会议召开时间", clause))
        if not explicit_company and not inherited_company:
            continue
        kind = next((name for name in EVENTS if name in clause), None)
        if not kind and inherited_company and "会议召开时间" in clause:
            kind = title_kind
        if not kind:
            continue
        # A report publication date in the preceding clause is never an event date.
        dates = list(DATE_RE.finditer(clause))
        if len(dates) != 1 or not dates[0].group(1):
            continue
        match = dates[0]
        try:
            event_date = date(*(int(v) for v in match.groups()))
        except ValueError:
            continue
        if not as_of <= event_date <= as_of + timedelta(days=60):
            continue
        business, roles = EVENTS[kind]
        event_id = digest([target["id"], kind, event_date.isoformat()])[:24]
        rows[event_id] = {
            "event_id": event_id, "company_id": target["id"], "company": target["name"],
            "event_name": kind, "event_date": event_date.isoformat(),
            "business_line": business, "recipient_roles": sorted(roles),
            "source_url": capture["url"], "source_quote": clause.strip(),
            "company_attribution": "explicit_clause" if explicit_company else "issuer_announcement_title",
            "capture_hash": digest(capture), "capture": capture,
        }
    return list(rows.values())


def audit_email(mail: dict, events: list[dict], targets: list[dict], as_of: date) -> dict:
    reasons = []
    target = next((t for t in targets if t["id"] == mail.get("company_id")), None)
    event = next((e for e in events if e["event_id"] == mail.get("event_id")), None)
    subject, body, hook = (str(mail.get(k, "")) for k in ("subject", "body", "hook"))
    if not subject or not body or not hook or hook not in body:
        reasons.append("hook_missing_or_not_in_body")
    if MARKERS.search(subject + "\n" + body):
        reasons.append("template_or_internal_marker")
    if not target or mail.get("company") != target["name"]:
        reasons.append("company_unknown_or_mismatch")
    if not event:
        reasons.append("hook_evidence_missing")
    else:
        if event["company_id"] != mail.get("company_id"):
            reasons.append("company_event_mismatch")
        if mail.get("event_date") != event["event_date"] or mail.get("event_name") != event["event_name"]:
            reasons.append("event_name_or_date_mismatch")
        try:
            when = date.fromisoformat(event["event_date"])
            if not as_of <= when <= as_of + timedelta(days=60):
                reasons.append("event_outside_future_60_days")
            capture = event["capture"]
            captured_at = datetime.fromisoformat(capture["captured_at"]).astimezone(TZ)
            age = (as_of - captured_at.date()).days
            if age < 0 or age > 1:
                reasons.append("source_stale_recollect_required")
            if target and event not in extract_events(capture, target, as_of):
                reasons.append("source_assertion_not_reproducible")
            if event["capture_hash"] != digest(capture):
                reasons.append("source_integrity_mismatch")
        except (KeyError, ValueError, TypeError):
            reasons.append("source_invalid")
        if event.get("business_line") == "irrelevant" or mail.get("business_line") != event.get("business_line"):
            reasons.append("business_irrelevant_or_mismatch")
        dates = list(DATE_RE.finditer(hook))
        if not dates or any(
            (int(m.group(1) or as_of.year), int(m.group(2)), int(m.group(3))) != tuple(map(int, event["event_date"].split("-")))
            for m in dates
        ):
            reasons.append("hook_text_date_mismatch")
        if event["event_name"] not in hook or (target and not any(
            name in hook for name in [target["name"], *target.get("aliases", [])]
        )):
            reasons.append("hook_text_company_or_event_missing")
        prefix, _, domain = str(mail.get("to", "")).lower().partition("@")
        role = ROLE_PREFIXES.get(prefix)
        if (not target or domain not in target["mail_domains"] or not role
                or role != mail.get("recipient_role") or role not in event.get("recipient_roles", [])):
            reasons.append("recipient_function_mismatch")
    return {
        "email_id": mail.get("email_id") or digest(mail)[:24], "company": mail.get("company"),
        "to": mail.get("to"), "status": "blocked" if reasons else "passed",
        "reasons": sorted(set(reasons)), "evidence_urls": [event["source_url"]] if event else [],
        "email_hash": digest(mail), "audited_on": as_of.isoformat(),
        "manual_confirmation_required": bool(reasons),
    }


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def audit_batch(mails: list[dict], events: list[dict], targets: list[dict], output: Path,
                as_of: date | None = None) -> dict:
    checks = [audit_email(mail, events, targets, as_of or today()) for mail in mails]
    queue_path = output / "manual-confirmation-queue.json"
    previous = json.loads(queue_path.read_text()) if queue_path.exists() else []
    unresolved = {
        (item["email"].get("company_id"), item["email"].get("to"))
        for item in previous if not item.get("human_confirmed")
    }
    for mail, check in zip(mails, checks):
        if (mail.get("company_id"), mail.get("to")) in unresolved:
            check["status"] = "blocked"
            check["manual_confirmation_required"] = True
            check["reasons"] = sorted(set(check["reasons"] + ["previously_blocked_requires_user_confirmation"]))
    result = {"audited_on": (as_of or today()).isoformat(), "checks": checks,
              "passed": sum(c["status"] == "passed" for c in checks),
              "blocked": sum(c["status"] == "blocked" for c in checks)}
    write_json(output / "audit-results.json", result)
    current = [
        {"email": mail, "audit": check} for mail, check in zip(mails, checks)
        if check["status"] == "blocked"
    ]
    current_keys = {(item["email"].get("company_id"), item["email"].get("to")) for item in current}
    write_json(queue_path, current + [item for item in previous
        if (item["email"].get("company_id"), item["email"].get("to")) not in current_keys])
    return result
