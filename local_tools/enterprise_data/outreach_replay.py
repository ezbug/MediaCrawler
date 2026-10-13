"""Re-audit the current legacy drafts without opening Gmail or sending."""
import argparse
import json
import re
from pathlib import Path

from .outreach_gate import audit_batch, audit_email, extract_events, today, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    output = root / "activity-review"
    targets = json.loads(Path(args.config).read_text())["companies"]
    events = json.loads((output / "events.json").read_text())
    mails = []
    for path in sorted((root / "company-emails-20261013").glob("*.md")):
        if path.name.startswith("00-"):
            continue
        text = path.read_text()
        target = next(t for t in targets if t["name"] in path.stem)
        body = text.split("## 正文", 1)[1].strip()
        hook = body.split("\n\n")[1].split("。", 1)[0] + "。"
        to = re.search(r"收件箱：([^（\s]+)", text)[1]
        event = next((e for e in events if e["company_id"] == target["id"]), {})
        mails.append({
            "company_id": target["id"], "company": target["name"], "to": to,
            "recipient_role": "training" if to.startswith("training@") else "marketing",
            "subject": re.search(r"主题：([^\n]+)", text)[1], "body": body, "hook": hook,
            "event_id": event.get("event_id", ""), "event_date": event.get("event_date", ""),
            "event_name": event.get("event_name", ""), "business_line": event.get("business_line", ""),
            "draft_source": str(path),
        })
    haier_text = (root / "email-haier-final-20261013.md").read_text()
    body = haier_text.split("## 定稿全文", 1)[1].split("## 发送文件", 1)[0].strip()
    subject, body = body.split("\n\n", 1)
    body = body.replace("负责企业用户联系的老师", "负责培训的老师")
    event = next(e for e in events if e["company_id"] == "haier")
    hook = body.split("\n\n")[1].split("。", 1)[0] + "。"
    incident = {"company_id": "haier", "company": "海尔智家", "to": "training@haier.com",
                "recipient_role": "training", "subject": subject.removeprefix("主题："),
                "body": body, "hook": hook, "event_id": event["event_id"],
                "event_name": event["event_name"], "event_date": event["event_date"],
                "business_line": event["business_line"], "historical_sent": True}
    # The six actual pending drafts remain a separate queue from the historical incident.
    write_json(output / "pending-emails.json", mails)
    result = audit_batch(mails, events, targets, output)
    event_hook = f"预祝海尔智家于{event['event_date']}举办的业绩说明会顺利举行。"
    normal = {**incident, "to": "finance@haier.com", "recipient_role": "ir", "hook": event_hook,
              "body": "负责投资者关系的老师，您好：\n\n" + event_hook + "\n可考虑远程互动和会后回放。", "historical_sent": False}
    bad_marker = {**normal, "body": normal["body"] + "\nTEST {{COMPANY}}"}
    cross = {**normal, "company_id": "midea", "company": "美的", "to": "ir@midea.com"}
    fixture_target = targets[0]
    fixture = {"company_id": "haier", "url": "https://www.haier.com/test-fixture", "title": "Synthetic test only",
               "text": "海尔智家将于2026年10月16日召开股东大会。", "captured_at": today().isoformat() + "T09:00:00+08:00"}
    irrelevant = extract_events(fixture, fixture_target, today())[0]
    unrelated_hook = "海尔智家2026年10月16日召开股东大会。"
    unrelated = {**normal, "event_id": irrelevant["event_id"], "event_name": "股东大会", "business_line": "irrelevant",
                 "body": unrelated_hook, "hook": unrelated_hook}
    checks = {
        "haier_actual_incident": audit_email(incident, events, targets, today()),
        "bad_test_marker": audit_email(bad_marker, events, targets, today()),
        "bad_cross_company": audit_email(cross, events, targets, today()),
        "bad_irrelevant_event_SYNTHETIC": audit_email(unrelated, [irrelevant], targets, today()),
        "normal_real_event_ir": audit_email(normal, events, targets, today()),
    }
    write_json(output / "acceptance-results.json", {
        "checks": checks, "facts": {
            "haier_report_published": "2026-08-28", "haier_briefing_scheduled": "2026-10-16",
            "evidence_url": event["source_url"],
            "correction": "Report publication and briefing are different events; incident fails recipient function.",
        }, "emails_sent": 0,
    })
    assert checks["normal_real_event_ir"]["status"] == "passed"
    assert all(v["status"] == "blocked" for k, v in checks.items() if k != "normal_real_event_ir")
    print(json.dumps({"pending": result, "acceptance": {k: v["status"] for k, v in checks.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
