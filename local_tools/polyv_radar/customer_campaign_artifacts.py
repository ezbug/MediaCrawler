"""Export the POLYV coursework from its database, without claiming target completion."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .customer_campaign import (
    campaign_summary, initialize_campaign, list_companies, record_exchange, upsert_company,
)
from .customer_campaign_dashboard import render_customer_campaign_dashboard
from .storage import RadarStore


def run_customer_campaign(config, args) -> dict:
    if config.product_profile != "polyv":
        raise ValueError("Customer campaign requires the POLYV database")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.campaign_id):
        raise ValueError("campaign-id must be a filename-safe identifier")
    if args.action in {"import", "exchange"} and not args.input:
        raise ValueError("--input is required for import/exchange")
    store = RadarStore(config.data_root / "radar.sqlite3")
    try:
        initialize_campaign(store, args.campaign_id, args.sector)
        if args.input:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            records = payload if isinstance(payload, list) else [payload]
            for record in records:
                if args.action == "import":
                    upsert_company(store, args.campaign_id, record)
                elif args.action == "exchange":
                    record_exchange(store, args.campaign_id, record)
        companies = list_companies(store, args.campaign_id)
        summary = campaign_summary(store, args.campaign_id)
        directory = config.data_root / "campaigns" / args.campaign_id
        directory.mkdir(parents=True, exist_ok=True)
        ledger_path = directory / "company-ledger.json"
        ledger_path.write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
        (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        fields = ["company_id", "company_name", "business_type", "scenario", "quote", "source_url",
                  "published_at", "contact_entry_url", "fit_reason", "fit_score", "intent_score", "status",
                  "reply_text", "next_action", "opening_question", "checked_at", "contact_verified"]
        with (directory / "customer-followup.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for company in companies:
                row = {key: company.get(key, "") for key in fields}
                evidence = company.get("evidence") or {}
                for key in ("opening_question", "checked_at", "contact_verified"):
                    row[key] = evidence.get(key, "")
                writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for key, value in row.items()})
        (directory / "customer-dashboard.html").write_text(
            render_customer_campaign_dashboard(companies, summary, args.campaign_id), encoding="utf-8")
        statement = "我选择企业管理培训与内训服务机构。公开课、跨地域企业内训和课程回放，是值得验证的视频应用场景。我希望了解机构目前如何交付线上课程、管理观看权限及评估学习效果，再判断保利威是否适配。聚焦同类客户，便于比较共同需求并调整开场方式。"
        (directory / "coursework.md").write_text(
            "# POLYV 国庆实战作业\n\n## 赛道说明\n\n" + statement
            + "\n\n## 经核验进度\n\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2)
            + "\n```\n\n## 复盘问题\n\n1. 客户目前怎样解决直播、视频或线上活动需求？\n2. 哪些场景是真需求？\n3. 根据实际交流，开场话术如何改进？\n\n以上三题等待实际交流证据后填写，不以模型推测替代客户回答。\n", encoding="utf-8")
        return {**summary, "ledger_path": str(ledger_path), "directory": str(directory)}
    finally:
        store.close()
