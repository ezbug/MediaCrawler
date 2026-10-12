"""把抓取到的企业数据导出为 Obsidian 笔记卡片（Poly 文件夹）。

- 企业邮箱探针 → `<vault>/Poly/email/<公司>.md`
- 企业档案（财务 + 招聘）→ `<vault>/Poly/company/<公司>.md`
- 索引 → `<vault>/Poly/Poly 索引.md`
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DOMAIN_BRAND = {
    "polyv.net": ("保利威", "企业直播与视频云"),
    "youzan.com": ("有赞", "私域电商 SaaS"),
    "weimob.com": ("微盟", "私域电商与智慧零售"),
    "xiaoe-tech.com": ("小鹅通", "知识付费与私域 SaaS"),
    "vhall.com": ("微吼", "企业直播"),
    "baijiayun.com": ("百家云", "企业直播与视频云"),
    "mudu.tv": ("目睹", "企业直播"),
    "yonyou.com": ("用友", "企业管理软件"),
    "kingdee.com": ("金蝶", "企业管理软件"),
    "neusoft.com": ("东软", "软件与信息服务"),
    "haier.com": ("海尔", "家电与工业互联网"),
    "midea.com": ("美的", "家电与工业技术"),
}

MAILBOX_FUNCTIONS = (
    ("investor", "投资者关系"), ("ir-", "投资者关系"), ("psirt", "安全响应"), ("security", "安全响应"),
    ("service", "客服"), ("contact", "商务 / 通用联系"), ("bd", "商务拓展"), ("market", "市场"),
    ("feedback", "产品反馈"), ("hr", "招聘"), ("complain", "投诉"), ("jubao", "举报"),
    ("anti-fraud", "反欺诈"), ("xiaoeks", "客服"),
)


def safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", str(name or "")).strip() or "未命名"


def mailbox_function(email: str) -> str:
    prefix = email.split("@")[0].lower()
    for key, label in MAILBOX_FUNCTIONS:
        if prefix.startswith(key):
            return label
    return "其他"


def _frontmatter(fields: dict, tags: list[str]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            value = json.dumps([str(item) for item in value], ensure_ascii=False)
        lines.append(f"{key}: {value}")
    lines.append("tags:")
    lines.extend(f"  - {tag}" for tag in tags)
    lines.append("---")
    return "\n".join(lines)


def export_email_cards(probe: list[dict], poly_root: Path, *, collected_at: str = "") -> list[Path]:
    out_dir = Path(poly_root) / "email"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for site in probe:
        domain = str(site.get("domain") or "").strip()
        emails = [str(item) for item in (site.get("emails") or [])]
        if not domain:
            continue
        brand, industry = DOMAIN_BRAND.get(domain, (domain, ""))
        pages = [page for page in (site.get("pages") or []) if page.get("emails")]
        first_page = {}
        for page in pages:
            for email in page["emails"]:
                first_page.setdefault(email, page)
        body = [
            _frontmatter({
                "type": "company-email",
                "company": brand,
                "domain": domain,
                "industry": industry,
                "email_count": len(emails),
                "emails": emails,
                "collected_at": collected_at or datetime.now().strftime("%Y-%m-%d"),
                "source": "企业邮箱探针 email-url-probe",
            }, ["Poly", "Poly/email"]),
            "",
            f"# {brand} · 企业邮箱",
            "",
            "> [!info] 卡片信息",
            f"> 官网：https://{domain}",
            f"> 邮箱数量：{len(emails)}",
            f"> 采集方式：官网公开页面（首页 + 联系/关于类页面）",
            "",
            "## 邮箱清单",
            "",
            "| 邮箱 | 职能 | 来源页面 |",
            "| --- | --- | --- |",
        ]
        if emails:
            for email in emails:
                page = first_page.get(email) or {}
                kind = page.get("kind") or ("首页" if (page.get("path") or "/") == "/" else "其他页面")
                body.append(f"| {email} | {mailbox_function(email)} | {kind} `{page.get('path') or '/'}` |")
        else:
            body.append("| （未在公开页面发现邮箱） | - | - |")
        body.extend(["", "## 来源页面", ""])
        if pages:
            for page in pages:
                body.append(f"- `{page.get('url') or page.get('path')}`：{len(page['emails'])} 个邮箱")
        else:
            body.append("- 无可访问的来源页面（页面可能要求登录或为 JS 渲染）")
        body.extend([
            "",
            "## 备注",
            "",
            "- 页脚邮箱会出现在全站多个页面；入库按「注册域 + 邮箱」去重。",
            "- 只记录公开商务邮箱，不采集个人邮箱。",
            "",
        ])
        path = out_dir / f"{safe_name(brand)}.md"
        path.write_text("\n".join(body), encoding="utf-8")
        written.append(path)
    return written


def _fetch(connection: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(sql, params)]


def export_company_cards(db_path: Path, poly_root: Path, *, stat_date: str = "") -> list[Path]:
    out_dir = Path(poly_root) / "company"
    out_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    written = []
    try:
        companies = _fetch(connection, "SELECT * FROM company ORDER BY company_name")
        for company in companies:
            company_id = company["company_id"]
            financials = _fetch(connection, "SELECT * FROM company_financial_year WHERE company_id = ? ORDER BY fiscal_year DESC", (company_id,))
            industries = _fetch(connection, "SELECT * FROM company_industry WHERE company_id = ? ORDER BY is_primary DESC", (company_id,))
            metrics = _fetch(connection, "SELECT * FROM company_hiring_metrics WHERE company_id = ? ORDER BY stat_date DESC LIMIT 1", (company_id,))
            jobs = _fetch(connection, "SELECT platform, job_title, city, employer_name FROM job_listing_snapshot WHERE company_id = ? AND (job_status IS NULL OR job_status = 'active') ORDER BY first_seen_at DESC LIMIT 10", (company_id,))
            evidence = _fetch(connection, "SELECT field_name, source_page, source_excerpt FROM data_evidence WHERE entity_id IN (SELECT financial_id FROM company_financial_year WHERE company_id = ?) LIMIT 5", (company_id,))
            if not (financials or metrics or jobs):
                continue
            industry_text = "；".join(
                f"{item['standard']} {item.get('code') or ''} {item.get('name') or ''}".strip()
                for item in industries
            ) or "—"
            latest_financial = financials[0] if financials else {}
            latest_metrics = metrics[0] if metrics else {}
            profile_fields = {
                "type": "company-profile",
                "company": company["company_name"],
                "company_id": company_id,
                "ticker": company.get("ticker"),
                "exchange": company.get("exchange"),
                "listing_status": company.get("listing_status"),
                "identity": company.get("identity_match_status"),
                "industry": industries[0].get("name") if industries else "",
            }
            if latest_financial.get("fiscal_year") is not None:
                profile_fields["fiscal_year"] = latest_financial["fiscal_year"]
            if latest_financial.get("employee_count") is not None:
                profile_fields["employee_count"] = latest_financial["employee_count"]
            if latest_financial.get("employee_growth_yoy") is not None:
                profile_fields["employee_growth_yoy"] = round(latest_financial["employee_growth_yoy"], 6)
            if latest_financial.get("total_assets") is not None:
                profile_fields["total_assets"] = float(latest_financial["total_assets"])
            if latest_financial.get("asset_growth_yoy") is not None:
                profile_fields["asset_growth_yoy"] = round(latest_financial["asset_growth_yoy"], 6)
            if latest_metrics.get("active_job_count") is not None:
                profile_fields["active_job_count"] = latest_metrics["active_job_count"]
            if latest_metrics.get("hiring_activity_score") is not None:
                profile_fields["hiring_activity_score"] = latest_metrics["hiring_activity_score"]
            if latest_metrics.get("stat_date"):
                profile_fields["hiring_stat_date"] = latest_metrics["stat_date"]
            profile_fields["updated_at"] = stat_date or datetime.now().strftime("%Y-%m-%d")
            body = [
                _frontmatter(profile_fields, ["Poly", "Poly/company"]),
                "",
                f"# {company['company_name']} · 企业数据卡",
                "",
                "> [!info] 基本信息",
                f"> 证券代码：{company.get('ticker') or '—'}（{company.get('exchange') or '—'}）",
                f"> 行业：{industry_text}",
                "",
            ]
            if financials:
                body.extend(["## 财务与规模", "", "| 财年 | 员工人数 | 人数同比 | 总资产(元) | 资产同比 | 员工规模 | 资产规模 | 口径 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
                for item in financials:
                    employee_growth = f"{item['employee_growth_yoy']:.1%}" if item.get("employee_growth_yoy") is not None else (item.get("employee_growth_status") or "—")
                    asset_growth = f"{item['asset_growth_yoy']:.1%}" if item.get("asset_growth_yoy") is not None else (item.get("asset_growth_status") or "—")
                    body.append(
                        f"| {item['fiscal_year']} | {item.get('employee_count') or '—'} | {employee_growth} | "
                        f"{item.get('total_assets') or '—'} | {asset_growth} | {item.get('size_by_employee') or '—'} | "
                        f"{item.get('size_by_assets') or '—'} | {item.get('reporting_scope') or '—'} |"
                    )
                body.append("")
            if metrics:
                latest = metrics[0]
                body.extend([
                    f"## 招聘强度（{latest['stat_date']}）",
                    "",
                    f"- 活跃职位：{latest.get('active_job_count')}｜独立需求组：{latest.get('unique_job_count')}｜平台覆盖：{latest.get('multi_platform_presence')}｜招聘活动指数：{latest.get('hiring_activity_score')}",
                    f"- 数据覆盖：职位人数披露率 {latest.get('hiring_count_coverage')}｜外包占比 {latest.get('outsourcing_job_ratio')}",
                    "",
                ])
            if jobs:
                body.extend(["## 岗位样本", ""])
                for job in jobs:
                    employer = f"（{job['employer_name']}）" if job.get("employer_name") else ""
                    body.append(f"- [{job['platform']}] {job['job_title']}{employer} · {job.get('city') or '—'}")
                body.append("")
            if evidence:
                body.extend(["## 数据证据", ""])
                for item in evidence:
                    body.append(f"- {item.get('field_name')}｜第 {item.get('source_page')} 页：{item.get('source_excerpt')}")
                body.append("")
            body.extend(["## 备注", "", "- 招聘数据来自招聘平台公开职位；财务数据来自年报（需人工复核口径）。", ""])
            path = out_dir / f"{safe_name(company['company_name'])}.md"
            path.write_text("\n".join(body), encoding="utf-8")
            written.append(path)
    finally:
        connection.close()
    return written


POLY_BASE_YAML = """filters: 'file.hasTag("Poly")'

formulas:
  employee_growth_text: 'if(employee_growth_yoy, (employee_growth_yoy * 100).toFixed(1) + "%", "—")'
  asset_growth_text: 'if(asset_growth_yoy, (asset_growth_yoy * 100).toFixed(1) + "%", "—")'
  assets_yi_text: 'if(total_assets, (total_assets / 100000000).toFixed(2) + " 亿", "—")'

properties:
  file.name:
    displayName: 公司
  domain:
    displayName: 域名
  industry:
    displayName: 行业
  email_count:
    displayName: 邮箱数
  emails:
    displayName: 邮箱
  collected_at:
    displayName: 采集日期
  employee_count:
    displayName: 员工人数
  formula.employee_growth_text:
    displayName: 人数同比
  formula.assets_yi_text:
    displayName: 总资产
  formula.asset_growth_text:
    displayName: 资产同比
  active_job_count:
    displayName: 活跃职位
  hiring_activity_score:
    displayName: 招聘指数
  ticker:
    displayName: 证券代码
  listing_status:
    displayName: 上市状态
  updated_at:
    displayName: 更新日期

views:
  - type: table
    name: 邮箱卡片
    filters:
      and:
        - 'file.hasTag("Poly/email")'
    order:
      - file.name
      - domain
      - industry
      - email_count
      - emails
      - collected_at
    sort:
      - property: email_count
        direction: DESC
    summaries:
      email_count: Sum
  - type: table
    name: 企业档案
    filters:
      and:
        - 'file.hasTag("Poly/company")'
    order:
      - file.name
      - industry
      - employee_count
      - formula.employee_growth_text
      - formula.assets_yi_text
      - formula.asset_growth_text
      - active_job_count
      - hiring_activity_score
      - ticker
      - listing_status
      - updated_at
    sort:
      - property: employee_count
        direction: DESC
"""


def export_base(poly_root: Path) -> Path:
    poly_root = Path(poly_root)
    poly_root.mkdir(parents=True, exist_ok=True)
    path = poly_root / "Poly.base"
    path.write_text(POLY_BASE_YAML, encoding="utf-8")
    return path


def export_index(poly_root: Path, *, email_count: int, company_count: int, stat_date: str = "") -> Path:
    poly_root = Path(poly_root)
    poly_root.mkdir(parents=True, exist_ok=True)
    today = stat_date or datetime.now().strftime("%Y-%m-%d")
    body = [
        _frontmatter({"type": "index", "updated_at": today}, ["Poly"]),
        "",
        "# Poly · 数据索引",
        "",
        "> [!info] 结构",
        "> `Poly/email`：企业公开邮箱卡片（官网探针）",
        "> `Poly/company`：企业档案卡片（年报财务 + 招聘强度）",
        "",
        f"- 邮箱卡片：{email_count} 张",
        f"- 企业卡片：{company_count} 张",
        f"- 最近更新：{today}",
        "",
        "## 邮箱卡片",
        "",
        "![[Poly.base#邮箱卡片]]",
        "",
        "## 企业档案",
        "",
        "![[Poly.base#企业档案]]",
        "",
        "## 数据来源",
        "",
        "- 企业邮箱：官网公开页面探针（`email-url-probe`）",
        "- 财务与规模：上市公司年报 PDF 抽取（PyMuPDF，需人工复核）",
        "- 招聘强度：BOSS 直聘 / 猎聘 公开职位（Ego Lite 采集）",
        "",
    ]
    path = poly_root / "Poly 索引.md"
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="导出企业数据到 Obsidian Poly 文件夹")
    parser.add_argument("--vault", required=True, help="Obsidian vault 根目录")
    parser.add_argument("--email-probe", help="email-url-probe JSON 路径")
    parser.add_argument("--db", help="enterprise.sqlite3 路径")
    parser.add_argument("--stat-date", default="")
    args = parser.parse_args(argv)

    poly_root = Path(args.vault) / "Poly"
    written: list[Path] = []
    email_count = 0
    if args.email_probe:
        probe = json.loads(Path(args.email_probe).read_text(encoding="utf-8"))
        cards = export_email_cards(probe, poly_root, collected_at=args.stat_date)
        email_count = len(cards)
        written.extend(cards)
    company_count = 0
    if args.db:
        cards = export_company_cards(Path(args.db), poly_root, stat_date=args.stat_date)
        company_count = len(cards)
        written.extend(cards)
    base = export_base(poly_root)
    written.append(base)
    index = export_index(poly_root, email_count=email_count, company_count=company_count, stat_date=args.stat_date)
    written.append(index)
    print(json.dumps({
        "poly_root": str(poly_root),
        "email_cards": email_count,
        "company_cards": company_count,
        "base": str(base),
        "index": str(index),
        "files": [str(path) for path in written],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
