"""Read-only event collection, review, and gated Gmail entry point."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .outreach_gate import audit_batch, audit_email, digest, extract_events, today, write_json


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ego(script, function, args, timeout=1200):
    source = f"const m = await import({json.dumps(Path(__file__).with_name(script).as_uri())}); console.log(JSON.stringify(await m.{function}(...{json.dumps(args)})));"
    result = subprocess.run(["ego-browser", "nodejs", "-e", source], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1000:])
    return result.stdout + result.stderr


def main(argv=None):
    parser = argparse.ArgumentParser(description="POLYV activities and mandatory email review")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--taskspace", type=int, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--emails", required=True)
    draft = sub.add_parser("generate")
    draft.add_argument("--request", required=True, help="Structured email with a {hook} in body")
    send = sub.add_parser("send")
    send.add_argument("--email", required=True)
    send.add_argument("--taskspace", type=int, required=True)
    send.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)
    config, output = load(args.config), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    events_path = output / "events.json"
    if args.command == "collect":
        subprocess.run(["/Users/sexpistole111/.local/bin/jev-ego-preflight"], check=True, capture_output=True)
        captures_path = output / "source-captures.json"
        ego("ego_events.mjs", "collect", [str(Path(args.config).resolve()), args.taskspace, str(captures_path.resolve())])
        captures = load(captures_path)
        events = {}
        for capture in captures["captures"]:
            company = next(c for c in config["companies"] if c["id"] == capture["company_id"])
            for event in extract_events(capture, company, today()):
                events[event["event_id"]] = event
        write_json(events_path, list(events.values()))
        write_json(output / "history" / f"{today().isoformat()}-{digest(captures)[:12]}.json", captures)
        result = {"date": today().isoformat(), "events": len(events), "sources": len(captures["captures"]), "errors": captures["errors"]}
        write_json(output / "collection-status.json", result)
    elif args.command == "audit":
        result = audit_batch(load(args.emails), load(events_path), config["companies"], output)
    elif args.command == "generate":
        mail = load(args.request)
        event = next(e for e in load(events_path) if e["event_id"] == mail["event_id"])
        mail.update({k: event[k] for k in ("company_id", "company", "event_name", "event_date", "business_line")})
        mail["hook"] = f"预祝{event['company']}于{event['event_date']}举办的{event['event_name']}顺利举行。"
        if mail["body"].count("{hook}") != 1:
            raise ValueError("body requires exactly one {hook}")
        mail["body"] = mail["body"].replace("{hook}", mail["hook"])
        write_json(output / "generated-email.json", mail)
        result = audit_batch([mail], load(events_path), config["companies"], output)
    else:
        mail = load(args.email)
        if args.submit and not config.get("obsidian_sync"):
            raise ValueError("submit requires local obsidian_sync configuration")
        batch = audit_batch([mail], load(events_path), config["companies"], output)
        result = batch["checks"][0]
        write_json(output / "send-preflight.json", result)
        if result["status"] != "passed":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        history_path = output / "send-attempts.jsonl"
        if history_path.exists() and any(json.loads(line)["email_hash"] == digest(mail) for line in history_path.read_text().splitlines()):
            raise ValueError("prior_send_attempt_requires_manual_review")
        canonical = json.dumps(mail, ensure_ascii=False, sort_keys=True)
        # Canonical mail is also the mail passed to JS; hashes cover all editable fields.
        write_json(output / "send-packet.json", {"mail": json.loads(canonical), "audit": result, "canonical_email": canonical})
        if args.submit:
            with history_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"email_hash": digest(mail), "status": "attempt_started", "date": today().isoformat()}) + "\n")
        response = ego("ego_gmail_gate.mjs", "send", [str((output / "send-packet.json").resolve()), args.taskspace, args.submit], timeout=120)
        write_json(output / "gmail-result.json", {"email_id": result["email_id"], "response": response})
        if args.submit:
            from datetime import datetime
            from .outreach_gate import TZ

            receipt = None
            for line in response.splitlines():
                try:
                    candidate = json.loads(line)
                    if isinstance(candidate, dict) and candidate.get("email_id") == result["email_id"]:
                        receipt = candidate
                except ValueError:
                    continue
            if not receipt or receipt.get("status") != "sent_ui_confirmed":
                raise RuntimeError("send_result_unverified_no_retry")
            send_log = output.parent / "email-send-log.jsonl"
            with send_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "attempted_at": datetime.now(TZ).isoformat(), "to": mail["to"],
                    "subject": mail["subject"], "result": "sent", "email_id": result["email_id"],
                    "email_hash": result["email_hash"], "variant": "A-100",
                    "audit": str(output / "send-preflight.json"),
                    "delivery_check": "Gmail UI confirmed; delivery not yet established",
                }, ensure_ascii=False) + "\n")
            sync = config.get("obsidian_sync")
            if sync:
                subprocess.run([
                    "uv", "run", "python", "-m", "local_tools.enterprise_data.obsidian_export",
                    "--vault", sync["vault"], "--email-probe", sync["email_probe"],
                    "--deliverability", str(output.parent / "email-deliverability.json"),
                    "--send-log", str(send_log), "--db", sync["db"],
                    "--stat-date", today().isoformat(),
                ], check=True, capture_output=True, text=True)
        result["browser_result"] = response
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
