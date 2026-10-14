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
    "业绩说明会": ("ir_live", {"ir"}),
    "投资者日": ("ir_live", {"ir"}),
    "股东大会": ("irrelevant", set()),
    "分红": ("irrelevant", set()),
    "训练营": ("enterprise_training", {"training"}),
    "培训": ("enterprise_training", {"training"}),
    "研修": ("enterprise_training", {"training"}),
    "发布会": ("enterprise_live", {"marketing"}),
    "展会": ("enterprise_live", {"marketing"}),
    "展览": ("enterprise_live", {"marketing"}),
    "峰会": ("enterprise_live", {"marketing"}),
    "大会": ("enterprise_live", {"marketing"}),
    "论坛": ("enterprise_live", {"marketing"}),
    "沙龙": ("enterprise_live", {"marketing"}),
    "研讨会": ("enterprise_live", {"marketing"}),
    "体验会": ("enterprise_live", {"marketing"}),
    "开放日": ("enterprise_live", {"marketing"}),
    "巡展": ("enterprise_live", {"marketing"}),
    "招商会": ("enterprise_live", {"marketing"}),
    "订货会": ("enterprise_live", {"marketing"}),
}
_EVENT_KEYS = sorted(EVENTS, key=len, reverse=True)
CARD_MARKERS = ("活动时间", "会议时间", "举办时间", "活动日期")
VALID_BUSINESS = {"enterprise_live", "enterprise_training", "private_live", "sdk", "ir_live"}
ROLE_PREFIXES = {"training": "training", "hr": "training", "ir": "ir",
                 "finance": "ir", "events": "marketing", "pr": "marketing",
                 "market": "marketing", "marketing": "marketing",
                 "sales": "business", "bd": "business", "business": "business",
                 "info": "business", "contact": "business", "hq": "business"}
VALID_ROLES = {"training", "marketing", "ir", "business"}
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


def _match_kind(text: str) -> str | None:
    return next((key for key in _EVENT_KEYS if key in text), None)


def clean_event_name(name: str) -> str:
    match = DATE_RE.search(name)
    if match:
        name = name[: match.start()]
    return name.strip(" ·—-–—·.。:：|、")


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _official_cards(capture: dict, target: dict, as_of: date) -> list[dict]:
    """Official activity pages: event card = title line followed by a time line."""
    if not host_allowed(capture.get("url", ""), target.get("official_domains", [])):
        return []
    title = capture.get("title", "")
    aliases = target.get("aliases", []) + [target["name"]]
    if not any(name in title for name in aliases):
        return []
    lines = [line.strip() for line in capture.get("text", "").splitlines()]
    rows = []
    for index, line in enumerate(lines):
        if not line.startswith(CARD_MARKERS):
            continue
        match = DATE_RE.search(line)
        if not match or not match.group(1):
            continue
        try:
            event_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        if not as_of <= event_date <= as_of + timedelta(days=60):
            continue
        name = ""
        for back in range(index - 1, max(-1, index - 6), -1):
            candidate = lines[back]
            if not candidate or candidate.startswith(CARD_MARKERS + ("活动地点",)):
                continue
            name = candidate
            break
        clean = clean_event_name(name)
        if not 2 <= len(clean) <= 100:
            continue
        kind = _match_kind(clean) or _match_kind(name)
        if not kind:
            continue
        business, roles = EVENTS[kind]
        event_id = digest([target["id"], event_date.isoformat(), clean])[:24]
        rows.append({
            "event_id": event_id, "company_id": target["id"], "company": target["name"],
            "event_name": clean, "event_date": event_date.isoformat(),
            "business_line": business, "recipient_roles": sorted(roles),
            "source_url": capture["url"],
            "source_quote": f"{name}｜{line}".strip("｜"),
            "company_attribution": "official_activity_card",
            "capture_hash": digest(capture), "capture": capture,
        })
    return rows


def extract_events(capture: dict, target: dict, as_of: date) -> list[dict]:
    """Only same-clause company/event/date assertions become evidence records."""
    if not host_allowed(capture.get("url", ""), target["source_domains"]):
        return []
    text = capture.get("text", "")
    aliases = target.get("aliases", []) + [target["name"]]
    title = capture.get("title", "")
    issuer_title = any(name in title for name in aliases) and ("关于召开" in title or "公告" in title)
    title_kind = _match_kind(title)
    rows = {row["event_id"]: row for row in _official_cards(capture, target, as_of)}
    if issuer_title:
        announcements = re.finditer(
            r"(?:公司计划于|公司将于|拟于|将于|会议召开时间[：:])\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            text,
        )
        for match in announcements:
            window = text[match.end(): match.end() + 150]
            kind = _match_kind(window) or title_kind
            try:
                event_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
            if not kind or not as_of <= event_date <= as_of + timedelta(days=60):
                continue
            business, roles = EVENTS[kind]
            event_id = digest([target["id"], event_date.isoformat(), kind])[:24]
            quote = (text[max(0, match.start() - 10): match.end()].strip() + " " + window.split("\n", 1)[0]).strip()
            rows.setdefault(event_id, {
                "event_id": event_id, "company_id": target["id"], "company": target["name"],
                "event_name": kind, "event_date": event_date.isoformat(),
                "business_line": business, "recipient_roles": sorted(roles),
                "source_url": capture["url"], "source_quote": quote[:220],
                "company_attribution": "issuer_announcement",
                "capture_hash": digest(capture), "capture": capture,
            })
    clauses = re.split(r"[。！？;；]", text)
    if issuer_title:
        clauses += re.findall(r"会议召开时间[：:][^\n]{0,120}", text)
    for clause in clauses:
        explicit_company = any(name in clause for name in aliases)
        inherited_company = issuer_title and bool(re.search(r"公司计划于|公司将于|会议召开时间", clause))
        if not explicit_company and not inherited_company:
            continue
        kind = _match_kind(clause)
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
        event_id = digest([target["id"], event_date.isoformat(), kind])[:24]
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
    has_hook = bool(hook.strip())
    if not subject or not body:
        reasons.append("draft_incomplete")
    if has_hook and hook not in body:
        reasons.append("hook_missing_or_not_in_body")
    if has_hook and not event:
        reasons.append("hook_evidence_missing")
    if not has_hook and event:
        reasons.append("event_without_hook")
    if MARKERS.search(subject + "\n" + body):
        reasons.append("template_or_internal_marker")
    if not target or mail.get("company") != target["name"]:
        reasons.append("company_unknown_or_mismatch")
    prefix, _, domain = str(mail.get("to", "")).lower().partition("@")
    # 人工注释过的邮箱（例如官网公开的商务/渠道邮箱）以注释职能为准；未注释的邮箱仍按前缀推断。
    annotated = ((target or {}).get("mailboxes") or {}).get(str(mail.get("to") or "").lower()) or {}
    role = annotated.get("role") or ROLE_PREFIXES.get(prefix)
    if event and has_hook:
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
        if _squash(event["event_name"]) not in _squash(hook) or (target and not any(
            _squash(name) in _squash(hook) for name in [target["name"], *target.get("aliases", [])]
        )):
            reasons.append("hook_text_company_or_event_missing")
        if role not in event.get("recipient_roles", []):
            reasons.append("recipient_function_mismatch")
    if mail.get("business_line") not in VALID_BUSINESS:
        reasons.append("business_line_invalid")
    if not target or domain not in target.get("mail_domains", []) or not role or role != mail.get("recipient_role"):
        reasons.append("recipient_function_mismatch")
    return {
        "email_id": mail.get("email_id") or digest(mail)[:24], "company": mail.get("company"),
        "to": mail.get("to"), "status": "blocked" if reasons else "passed",
        "reasons": sorted(set(reasons)), "evidence_urls": [event["source_url"]] if event else [],
        "email_hash": digest(mail), "audited_on": as_of.isoformat(),
        "hook_status": "verified" if (has_hook and event) else ("missing_evidence" if has_hook else "none"),
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
