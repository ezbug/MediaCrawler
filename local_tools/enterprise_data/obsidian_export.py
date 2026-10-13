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
    ("investor", "投资者关系"), ("ir", "投资者关系"), ("finance", "财务"), ("psirt", "安全响应"), ("security", "安全响应"),
    ("service", "客服"), ("contact", "商务 / 通用联系"), ("bd", "商务拓展"), ("market", "市场"),
    ("events", "市场活动"), ("feedback", "产品反馈"), ("hr", "招聘"), ("training", "培训"), ("complain", "投诉"), ("jubao", "举报"),
    ("anti-fraud", "反欺诈"), ("privacy", "隐私合规"), ("xiaoeks", "客服"), ("pr", "公关"),
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


def export_email_cards(
    probe: list[dict],
    poly_root: Path,
    *,
    collected_at: str = "",
    deliverability: dict | None = None,
    send_log: list[dict] | None = None,
    drafts: dict[str, list[dict]] | None = None,
) -> list[Path]:
    out_dir = Path(poly_root) / "email"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    deliverability = deliverability or {}
    send_log = send_log or []
    drafts = drafts or {}
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
        deliv_entries = list(deliverability.get(domain, []))
        invalid = {str(entry.get("email") or "").lower() for entry in deliv_entries if entry.get("status") == "invalid"}
        usable = [email for email in emails if email.lower() not in invalid]
        known = {email.lower() for email in usable}
        for entry in deliv_entries:
            email = str(entry.get("email") or "")
            if entry.get("status") != "verified" or not email or email.lower() in known or email.lower() in invalid:
                continue
            usable.append(email)
            known.add(email.lower())
            first_page.setdefault(email, {"kind": "送达性验证", "path": "SMTP RCPT"})
        domain_log = [
            record for record in send_log
            if str(record.get("to") or "").lower().endswith("@" + domain.lower())
        ]
        body = [
            _frontmatter({
                "type": "company-email",
                "company": brand,
                "domain": domain,
                "industry": industry,
                "email_count": len(usable),
                "emails": usable,
                "collected_at": collected_at or datetime.now().strftime("%Y-%m-%d"),
                "source": "企业邮箱探针 email-url-probe",
            }, ["Poly", "Poly/email"]),
            "",
            f"# {brand} · 企业邮箱",
            "",
            "> [!info] 卡片信息",
            f"> 官网：https://{domain}",
            f"> 邮箱数量：{len(usable)}（仅可用邮箱；失效记录见下）",
            f"> 采集方式：官网公开页面（首页 + 联系/关于类页面）",
            "",
            "## 邮箱清单",
            "",
            "| 邮箱 | 职能 | 来源页面 |",
            "| --- | --- | --- |",
        ]
        if usable:
            for email in usable:
                page = first_page.get(email) or {}
                kind = page.get("kind") or ("首页" if (page.get("path") or "/") == "/" else "其他页面")
                body.append(f"| {email} | {mailbox_function(email)} | {kind} `{page.get('path') or '/'}` |")
        else:
            body.append("| （未发现可用邮箱） | - | - |")
        body.extend(["", "## 来源页面", ""])
        if pages:
            for page in pages:
                body.append(f"- `{page.get('url') or page.get('path')}`：{len(page['emails'])} 个邮箱")
        else:
            body.append("- 无可访问的来源页面（页面可能要求登录或为 JS 渲染）")
        if deliv_entries:
            status_labels = {"verified": "已验证可用", "invalid": "已失效", "bounced": "退信"}
            body.extend(["", "## 送达性验证", ""])
            for entry in deliv_entries:
                status = status_labels.get(str(entry.get("status")), str(entry.get("status") or "未验证"))
                details = "，".join(
                    part for part in (str(entry.get("checked_at") or "").strip(), str(entry.get("evidence") or "").strip()) if part
                )
                suffix = f"（{details}）" if details else ""
                body.append(f"- {entry.get('email')}：{status}{suffix}")
            body.append("")
        if domain_log:
            result_labels = {"sent": "已发送", "bounced": "退信", "pending": "待确认"}
            body.extend(["", "## 发送记录", ""])
            for record in sorted(domain_log, key=lambda item: str(item.get("attempted_at") or ""), reverse=True):
                when = str(record.get("attempted_at") or "").replace("T", " ")[:16]
                result = result_labels.get(str(record.get("result")), str(record.get("result") or ""))
                line = f"- {when} 发送至 {record.get('to')}｜主题《{record.get('subject')}》｜状态：{result}"
                if record.get("greeting"):
                    line += f"｜称呼：{record['greeting']}"
                if record.get("result") == "bounced" and record.get("bounce"):
                    line += f"｜{record['bounce']}"
                body.append(line)
            body.append("")
        domain_drafts = drafts.get(domain.lower()) or []
        if domain_drafts:
            body.extend(["", "## 待发邮件（五门版 · 未发送）", ""])
            body.append("> 五门：真实钩子 / 公司与事件匹配 / 业务相关 / 职能对口 / 成稿完整。发送后本节保留，结果见「发送记录」。")
            for draft in domain_drafts:
                audit = draft.get("audit") or {}
                status = "通过" if audit.get("status") == "passed" else "拦截"
                reasons = "、".join(str(item) for item in (audit.get("reasons") or []))
                hook = str(draft.get("hook") or "")
                body.extend(["", f"### {draft.get('subject')}", ""])
                body.append(f"- 收件箱：{draft.get('to')}")
                body.append(f"- 称呼：{draft.get('greeting')}")
                if hook:
                    body.append(f"- 活动钩子：{hook}")
                    if draft.get("evidence_url"):
                        body.append(f"- 证据：[来源原文]({draft['evidence_url']})")
                else:
                    body.append("- 活动钩子：无（60 天窗口内未找到可核验活动，未使用未经核实的日期）")
                body.append(f"- 五门：{status}" + (f"（{reasons}）" if reasons else ""))
                body.extend(["", "> [!quote]- 邮件全文"])
                for line in str(draft.get("body") or "").splitlines():
                    body.append(f"> {line}" if line else ">")
            body.append("")
        body.extend([
            "",
            "## 备注",
            "",
            "- 页脚邮箱会出现在全站多个页面；入库按「注册域 + 邮箱」去重。",
            "- 只记录公开商务邮箱，不采集个人邮箱。",
            "- frontmatter 只列可用邮箱；失效与验证状态、发送记录见上方对应小节。",
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
            evidence = _fetch(connection, "SELECT field_name, source_page, source_url, source_excerpt FROM data_evidence WHERE entity_id IN (SELECT financial_id FROM company_financial_year WHERE company_id = ?) ORDER BY created_at DESC LIMIT 5", (company_id,))
            claims = _fetch(connection, "SELECT field_name, source_url, source_excerpt, observed_at FROM data_evidence WHERE entity_type = 'company' AND entity_id = ? ORDER BY created_at DESC LIMIT 6", (company_id,))
            if not (financials or metrics or jobs):
                continue
            industry_text = "；".join(
                f"{item['standard']} {item.get('code') or ''} {item.get('name') or ''}".strip()
                for item in industries
            ) or "—"
            latest_financial = financials[0] if financials else {}
            latest_metrics = metrics[0] if metrics else {}
            ticker = company.get("ticker")
            profile_fields = {
                "type": "company-profile",
                "company": company["company_name"],
                "company_id": company_id,
                "ticker": f'"{ticker}"' if ticker else "",
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
            if latest_financial.get("currency"):
                profile_fields["currency"] = latest_financial["currency"]
            if latest_financial.get("asset_growth_yoy") is not None:
                profile_fields["asset_growth_yoy"] = round(latest_financial["asset_growth_yoy"], 6)
            if latest_metrics.get("active_job_count") is not None:
                profile_fields["active_job_count"] = latest_metrics["active_job_count"]
            if latest_metrics.get("hiring_activity_score") is not None:
                profile_fields["hiring_activity_score"] = latest_metrics["hiring_activity_score"]
            if latest_metrics.get("stat_date"):
                profile_fields["hiring_stat_date"] = latest_metrics["stat_date"]
            if claims:
                profile_fields["employee_scale"] = claims[0]["source_excerpt"]
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
                body.extend(["## 财务与规模", "", "| 财年 | 员工人数 | 人数同比 | 总资产 | 资产同比 | 员工规模 | 资产规模 | 口径 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
                for item in financials:
                    employee_growth = f"{item['employee_growth_yoy']:.1%}" if item.get("employee_growth_yoy") is not None else (item.get("employee_growth_status") or "—")
                    asset_growth = f"{item['asset_growth_yoy']:.1%}" if item.get("asset_growth_yoy") is not None else (item.get("asset_growth_status") or "—")
                    if item.get("total_assets") is None:
                        assets_text = "—"
                    else:
                        currency = (item.get("currency") or "").strip()
                        assets_text = f"{currency} {float(item['total_assets']):,.2f}".strip()
                    body.append(
                        f"| {item['fiscal_year']} | {item.get('employee_count') or '—'} | {employee_growth} | "
                        f"{assets_text} | {asset_growth} | {item.get('size_by_employee') or '—'} | "
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
                    page = str(item.get("source_page") or "").strip()
                    label = f"第 {page} 页" if page.isdigit() else (page or "来源")
                    url = str(item.get("source_url") or "").strip()
                    link = f"（[来源]({url})）" if url else ""
                    body.append(f"- {item.get('field_name')}｜{label}：{item.get('source_excerpt')}{link}")
                body.append("")
            if claims:
                body.extend(["## 公开规模声明（未审计）", ""])
                for item in claims:
                    url = str(item.get("source_url") or "").strip()
                    link = f"（[来源]({url})）" if url else ""
                    observed = str(item.get("observed_at") or "").strip()
                    when = f"，{observed[:10]}" if observed else ""
                    body.append(f"- {item.get('field_name')}：{item.get('source_excerpt')}{link}{when}")
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
  employee_growth_text: 'if(employee_growth_yoy == 0, "0.0%", if(employee_growth_yoy, (employee_growth_yoy * 100).toFixed(1) + "%", "—"))'
  asset_growth_text: 'if(asset_growth_yoy == 0, "0.0%", if(asset_growth_yoy, (asset_growth_yoy * 100).toFixed(1) + "%", "—"))'
  assets_yi_text: 'if(total_assets, if(currency == "USD", "US$ " + (total_assets / 1000000).toFixed(1) + "M", (total_assets / 100000000).toFixed(2) + " 亿"), "—")'

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
  currency:
    displayName: 币种
  employee_scale:
    displayName: 规模（宣称）
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
      - employee_scale
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
    parser.add_argument("--deliverability", help="邮箱可达性 JSON（domain 到条目列表）")
    parser.add_argument("--send-log", help="发送台账 JSONL 路径")
    parser.add_argument("--outreach-review", help="活动评审目录（pending-emails-v2.json / audit-results.json / events.json）")
    parser.add_argument("--db", help="enterprise.sqlite3 路径")
    parser.add_argument("--stat-date", default="")
    args = parser.parse_args(argv)

    poly_root = Path(args.vault) / "Poly"
    written: list[Path] = []
    email_count = 0
    if args.email_probe:
        probe = json.loads(Path(args.email_probe).read_text(encoding="utf-8"))
        deliverability: dict[str, list] = {}
        if args.deliverability:
            raw = json.loads(Path(args.deliverability).read_text(encoding="utf-8"))
            domain_map = raw.get("domains") if isinstance(raw, dict) and "domains" in raw else raw
            if isinstance(domain_map, dict):
                for domain_name, entries in domain_map.items():
                    if isinstance(entries, list):
                        deliverability[str(domain_name)] = entries
        send_log: list[dict] = []
        if args.send_log:
            for line in Path(args.send_log).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    send_log.append(json.loads(line))
        drafts_by_domain: dict[str, list[dict]] = {}
        if args.outreach_review:
            review_dir = Path(args.outreach_review)
            emails: list[dict] = []
            for name in ("pending-emails-v2.json", "pending-emails.json"):
                candidate = review_dir / name
                if candidate.exists():
                    emails = json.loads(candidate.read_text(encoding="utf-8"))
                    break
            audits: dict[str, dict] = {}
            audit_path = review_dir / "audit-results.json"
            if audit_path.exists():
                for check in json.loads(audit_path.read_text(encoding="utf-8")).get("checks", []):
                    audits[str(check.get("company") or "")] = check
            events: dict[str, dict] = {}
            events_path = review_dir / "events.json"
            if events_path.exists():
                for event in json.loads(events_path.read_text(encoding="utf-8")):
                    events[str(event.get("event_id") or "")] = event
            for mail in emails:
                to = str(mail.get("to") or "")
                domain_name = to.partition("@")[2].lower()
                if not domain_name:
                    continue
                event = events.get(str(mail.get("event_id") or "")) or {}
                drafts_by_domain.setdefault(domain_name, []).append({
                    "to": to,
                    "subject": mail.get("subject"),
                    "greeting": str(mail.get("body") or "").split("，您好：")[0],
                    "hook": mail.get("hook") or "",
                    "body": mail.get("body") or "",
                    "audit": audits.get(str(mail.get("company") or "")) or {},
                    "evidence_url": event.get("source_url") or "",
                })
        cards = export_email_cards(
            probe,
            poly_root,
            collected_at=args.stat_date,
            deliverability=deliverability,
            send_log=send_log,
            drafts=drafts_by_domain,
        )
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
