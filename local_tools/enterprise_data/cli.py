"""企业数据归纳系统命令行入口。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .storage import EnterpriseStore

DEFAULT_DB = "/Users/sexpistole111/Documents/workplace/polyv-radar-data/enterprise/enterprise.sqlite3"


def _load(path: str) -> dict | list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="企业数据归纳系统（年报财务 + 招聘职位）")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite 路径，默认 {DEFAULT_DB}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="创建/迁移数据库")

    p_company = sub.add_parser("import-company", help="导入企业主数据（JSON 对象）")
    p_company.add_argument("--json", required=True)

    p_financial = sub.add_parser("import-financial", help="导入年报财务数据（JSON 对象）")
    p_financial.add_argument("--json", required=True)

    p_jobs = sub.add_parser("import-jobs", help="导入职位快照（JSON：company_id + jobs[]）")
    p_jobs.add_argument("--json", required=True)

    p_metrics = sub.add_parser("metrics", help="计算招聘指标")
    p_metrics.add_argument("--company-id", required=True)
    p_metrics.add_argument("--stat-date", required=True)
    p_metrics.add_argument("--window-days", type=int, default=30)

    p_report = sub.add_parser("report", help="输出企业画像")
    p_report.add_argument("--company-id", required=True)

    p_extract = sub.add_parser("extract-annual-report", help="从年报 PDF 抽取财务候选（需人工复核）")
    p_extract.add_argument("--pdf", required=True)
    p_extract.add_argument("--company-id", required=True)
    p_extract.add_argument("--fiscal-year", type=int, required=True)
    p_extract.add_argument("--report-version", default="")
    p_extract.add_argument("--period-end", default="")
    p_extract.add_argument("--output")

    p_careers = sub.add_parser("extract-careers", help="从企业官网招聘页抽取职位（官方来源，只读）")
    p_careers.add_argument("--company-id", required=True)
    p_careers.add_argument("--url", help="直接指定招聘页 URL")
    p_careers.add_argument("--site", help="公司域名；自动发现招聘页链接")
    p_careers.add_argument("--output")

    p_dedupe = sub.add_parser("dedupe-jobs", help="职位去重分组（job_dedup_group）")
    p_dedupe.add_argument("--company-id", required=True)
    p_dedupe.add_argument("--threshold", type=float, default=0.85)

    p_label = sub.add_parser("label-jobs", help="职位风险标签（僵尸/外包）")
    p_label.add_argument("--company-id", required=True)
    p_label.add_argument("--stat-date", required=True)

    sub.add_parser("list", help="列出企业")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract-annual-report":
        from .pdf_extract import main as extract_main

        return extract_main([
            "--pdf", args.pdf,
            "--company-id", args.company_id,
            "--fiscal-year", str(args.fiscal_year),
            *(["--report-version", args.report_version] if args.report_version else []),
            *(["--period-end", args.period_end] if args.period_end else []),
            *(["--output", args.output] if args.output else []),
        ])
    if args.command == "extract-careers":
        from .careers_extract import main as careers_main

        return careers_main([
            "--company-id", args.company_id,
            *(["--url", args.url] if args.url else []),
            *(["--site", args.site] if args.site else []),
            *(["--output", args.output] if args.output else []),
        ])
    store = EnterpriseStore(args.db)
    if args.command == "init":
        payload = {"db": str(store.path), "status": "initialized"}
    elif args.command == "import-company":
        data = _load(args.json)
        company_id = store.upsert_company(data)
        if data.get("industries"):
            for item in data["industries"]:
                store.add_industry(company_id, item)
        payload = {"company_id": company_id, "status": "imported"}
    elif args.command == "import-financial":
        payload = store.upsert_financial(_load(args.json))
    elif args.command == "import-jobs":
        data = _load(args.json)
        payload = store.add_jobs(str(data.get("company_id") or ""), list(data.get("jobs") or []))
    elif args.command == "metrics":
        payload = store.compute_hiring_metrics(args.company_id, args.stat_date, args.window_days)
    elif args.command == "report":
        payload = store.company_profile(args.company_id)
    elif args.command == "dedupe-jobs":
        from .job_dedup import dedupe_jobs

        payload = dedupe_jobs(store, args.company_id, threshold=args.threshold)
    elif args.command == "label-jobs":
        from .job_dedup import label_jobs

        payload = label_jobs(store, args.company_id, args.stat_date)
    else:
        payload = {"companies": store.list_companies()}
    store.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
