"""企业邮箱 SMTP RCPT 送达性验证（只握手，不发信）。

对每个域名的公开邮箱做 RCPT TO 校验：250/251 记为 verified，5xx 记为 invalid，
超时/拒连/需要策略记为 unknown。结果合并进 email-deliverability.json 结构。
"""
from __future__ import annotations

import json
import smtplib
import socket
from pathlib import Path


def mx_hosts(domain: str) -> list[str]:
    import subprocess

    try:
        out = subprocess.run(["dig", "+short", "MX", domain], capture_output=True, text=True, timeout=15).stdout
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            rows.append((int(parts[0]) if parts[0].isdigit() else 99, parts[-1].rstrip(".")))
    return [host for _prio, host in sorted(rows)]


def verify(email: str, sender: str = "postmaster@example.com", timeout: int = 15) -> tuple[str, str]:
    domain = email.partition("@")[2]
    hosts = mx_hosts(domain)
    if not hosts:
        return "unknown", "未找到 MX 记录"
    last = ""
    for host in hosts[:2]:
        try:
            with smtplib.SMTP(host, 25, timeout=timeout) as client:
                client.ehlo_or_helo_if_needed()
                code, message = client.mail(sender)
                if code >= 400:
                    last = f"MAIL FROM 被拒：{code}"
                    continue
                code, message = client.rcpt(email)
                text = message.decode("utf-8", "ignore") if isinstance(message, bytes) else str(message)
                if code in (250, 251):
                    return "verified", f"RCPT {code} {text[:80]}".strip()
                if 500 <= code < 600:
                    lower = text.lower()
                    if any(marker in lower for marker in (
                        "spam", "spf", "blocked", "blacklist", "dnsbl", "authentication is required",
                        "behaviour", "behavior", "service permanently unavailable", "policy",
                    )):
                        return "blocked", f"RCPT {code} {text[:80]}".strip()
                    return "invalid", f"RCPT {code} {text[:80]}".strip()
                last = f"RCPT {code} {text[:80]}"
        except (smtplib.SMTPException, socket.error, OSError) as exc:
            last = f"{type(exc).__name__}: {str(exc)[:80]}"
    return "unknown", last or "未获得明确应答"


def main(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(description="企业邮箱 SMTP RCPT 验证")
    parser.add_argument("--emails", required=True, help="JSON：{domain: [email, ...]} 或 probe 结果列表")
    parser.add_argument("--out", required=True, help="输出 deliverability JSON")
    parser.add_argument("--merge", help="已有的 deliverability JSON（合并保留历史）")
    parser.add_argument("--domain", action="append", help="按域名探测角色邮箱，可重复")
    parser.add_argument("--roles", nargs="+", default=["training", "hr", "events", "market", "pr", "ir", "contact"])
    args = parser.parse_args(argv)

    raw = json.loads(Path(args.emails).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        site_map = {str(site.get("domain")): [str(e) for e in (site.get("emails") or [])] for site in raw}
    else:
        site_map = {str(k): [str(e) for e in v] for k, v in raw.items()}

    merged: dict[str, list] = {}
    if args.merge and Path(args.merge).exists():
        existing = json.loads(Path(args.merge).read_text(encoding="utf-8"))
        merged = existing.get("domains") if isinstance(existing, dict) and "domains" in existing else existing
    today = date.today().isoformat()
    for domain in args.domain or []:
        bucket = site_map.setdefault(domain, [])
        for role in args.roles:
            email = f"{role}@{domain}"
            if email not in bucket:
                bucket.append(email)
    for domain, emails in site_map.items():
        entries = {str(item.get("email")): item for item in merged.get(domain, [])}
        for email in emails:
            status, evidence = verify(email)
            entries[email] = {"email": email, "status": status, "checked_at": today, "evidence": evidence}
            print(json.dumps({"domain": domain, "email": email, "status": status, "evidence": evidence}, ensure_ascii=False))
        merged[domain] = list(entries.values())
    out = {"checked_at": today, "method": "SMTP RCPT 验证（只握手，不发信）", "domains": merged}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
