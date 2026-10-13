from __future__ import annotations

import json

from local_tools.enterprise_data.obsidian_export import (
    export_base,
    export_company_cards,
    export_email_cards,
    export_index,
    main,
    mailbox_function,
)
from local_tools.enterprise_data.storage import EnterpriseStore


def test_mailbox_function_labels():
    assert mailbox_function("security@xiaoe-tech.com") == "安全响应"
    assert mailbox_function("contact@vhall.com") == "商务 / 通用联系"
    assert mailbox_function("ir@yonyou.com") == "投资者关系"
    assert mailbox_function("finance@haier.com") == "财务"
    assert mailbox_function("privacy@mudu.tv") == "隐私合规"
    assert mailbox_function("unknown@example.com") == "其他"


def test_export_email_cards_writes_cards_for_all_domains(tmp_path):
    probe = [
        {
            "domain": "xiaoe-tech.com",
            "emails": ["contact@xiaoe-tech.com", "security@xiaoe-tech.com"],
            "pages": [
                {"url": "https://xiaoe-tech.com/", "path": "/", "kind": "首页", "emails": ["contact@xiaoe-tech.com"]},
                {"url": "https://xiaoe-tech.com/security", "path": "/security", "kind": "联系/关于", "emails": ["security@xiaoe-tech.com"]},
            ],
        },
        {"domain": "haier.com", "emails": [], "pages": []},
    ]
    written = export_email_cards(probe, tmp_path / "Poly", collected_at="2026-10-12")
    assert len(written) == 2
    xiaoe = (tmp_path / "Poly" / "email" / "小鹅通.md").read_text(encoding="utf-8")
    assert "type: company-email" in xiaoe
    assert "contact@xiaoe-tech.com" in xiaoe
    assert "安全响应" in xiaoe
    assert "collected_at: 2026-10-12" in xiaoe
    assert "email_count: 2" in xiaoe
    assert 'emails: ["contact@xiaoe-tech.com", "security@xiaoe-tech.com"]' in xiaoe
    haier = (tmp_path / "Poly" / "email" / "海尔.md").read_text(encoding="utf-8")
    assert "未发现可用邮箱" in haier


def test_export_company_cards_includes_financial_hiring_and_jobs(tmp_path):
    store = EnterpriseStore(tmp_path / "enterprise.sqlite3")
    company_id = store.upsert_company({"company_name": "示例科技", "ticker": "000001", "exchange": "SZSE"})
    store.add_industry(company_id, {"standard": "CSRC", "code": "C39", "name": "计算机", "is_primary": 1})
    store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2025, "reporting_scope": "consolidated", "report_version": "annual-2025",
        "employee_count": 1000, "employee_count_type": "year_end", "employee_count_scope": "consolidated",
        "total_assets": "100000000", "total_assets_scope": "consolidated",
        "evidence": [{"field_name": "employee_count", "source_page": 69, "source_excerpt": "员工共1,000人"}],
    })
    store.add_jobs(company_id, [
        {"platform": "liepin", "platform_job_id": "j1", "job_title": "客户经理", "city": "深圳", "first_seen_at": "2026-10-01T09:00:00+08:00"},
    ])
    store.compute_hiring_metrics(company_id, "2026-10-12")
    store.close()

    written = export_company_cards(tmp_path / "enterprise.sqlite3", tmp_path / "Poly", stat_date="2026-10-12")
    assert len(written) == 1
    card = written[0].read_text(encoding="utf-8")
    assert "type: company-profile" in card
    assert "CSRC C39 计算机" in card
    assert "| 2025 | 1000 |" in card
    assert "industry: 计算机" in card
    assert "fiscal_year: 2025" in card
    assert "employee_count: 1000" in card
    assert "active_job_count: 1" in card
    assert 'ticker: "000001"' in card
    assert "员工人数 | 人数同比 | 总资产 |" in card
    assert "招聘强度（2026-10-12）" in card
    assert "客户经理" in card
    assert "员工共1,000人" in card


def test_export_base_writes_table_views(tmp_path):
    path = export_base(tmp_path / "Poly")
    assert path.name == "Poly.base"
    content = path.read_text(encoding="utf-8")
    assert "name: 邮箱卡片" in content
    assert "name: 企业档案" in content
    assert "formula.employee_growth_text" in content
    assert 'employee_growth_yoy == 0, "0.0%"' in content
    assert 'file.hasTag("Poly/email")' in content
    assert 'file.hasTag("Poly/company")' in content


def test_export_index_reports_counts(tmp_path):
    path = export_index(tmp_path / "Poly", email_count=3, company_count=2, stat_date="2026-10-12")
    content = path.read_text(encoding="utf-8")
    assert "邮箱卡片：3 张" in content
    assert "企业卡片：2 张" in content
    assert "最近更新：2026-10-12" in content
    assert "![[Poly.base#邮箱卡片]]" in content
    assert "![[Poly.base#企业档案]]" in content


def test_main_end_to_end_with_probe_file(tmp_path, capsys):
    probe_path = tmp_path / "probe.json"
    probe_path.write_text(json.dumps([{"domain": "vhall.com", "emails": ["contact@vhall.com"], "pages": []}]), encoding="utf-8")
    rc = main(["--vault", str(tmp_path), "--email-probe", str(probe_path), "--stat-date", "2026-10-12"])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["email_cards"] == 1
    assert (tmp_path / "Poly" / "Poly.base").exists()
    assert (tmp_path / "Poly" / "Poly 索引.md").exists()


def test_email_card_excludes_invalid_and_renders_send_log(tmp_path):
    probe = [{
        "domain": "example.com",
        "emails": ["a@example.com", "dead@example.com"],
        "pages": [{"url": "https://example.com/", "path": "/", "kind": "首页", "emails": ["a@example.com", "dead@example.com"]}],
    }]
    deliverability = {"example.com": [
        {"email": "dead@example.com", "status": "invalid", "checked_at": "2026-10-13", "evidence": "551 rejected"},
        {"email": "hr@example.com", "status": "verified", "checked_at": "2026-10-13", "evidence": "RCPT 250 Ok"},
    ]}
    send_log = [{
        "attempted_at": "2026-10-13T14:41:00+08:00",
        "to": "hr@example.com",
        "subject": "测试主题",
        "result": "sent",
        "greeting": "负责培训的老师",
    }]
    written = export_email_cards(
        probe, tmp_path / "Poly", collected_at="2026-10-13",
        deliverability=deliverability, send_log=send_log,
    )
    card = written[0].read_text(encoding="utf-8")
    frontmatter = card.split("---")[1]
    assert "dead@example.com" not in frontmatter
    assert 'emails: ["a@example.com", "hr@example.com"]' in card
    assert "email_count: 2" in card
    assert "## 送达性验证" in card
    assert "已失效" in card
    assert "## 发送记录" in card
    assert "已发送" in card


def test_email_card_renders_outreach_drafts_and_gates(tmp_path):
    probe = [{
        "domain": "example.com",
        "emails": ["training@example.com"],
        "pages": [{"url": "https://example.com/", "path": "/", "kind": "首页", "emails": ["training@example.com"]}],
    }]
    drafts = {
        "example.com": [{
            "to": "training@example.com",
            "subject": "关于伙伴培训的三点反馈",
            "greeting": "负责培训的老师",
            "hook": "看到贵司 10 月 23 日举办训练营，先预祝顺利。",
            "body": "负责培训的老师，您好：\n\n看到贵司 10 月 23 日举办训练营，先预祝顺利。",
            "audit": {"status": "passed", "reasons": []},
            "evidence_url": "https://example.com/event",
        }],
    }
    written = export_email_cards(probe, tmp_path / "Poly", collected_at="2026-10-13", drafts=drafts)
    card = written[0].read_text(encoding="utf-8")
    assert "## 待发邮件（五门版 · 未发送）" in card
    assert "### 关于伙伴培训的三点反馈" in card
    assert "- 五门：通过" in card
    assert "[来源原文](https://example.com/event)" in card
    assert "> [!quote]- 邮件全文" in card
    assert "> 负责培训的老师，您好：" in card


def test_no_drafts_section_without_outreach_data(tmp_path):
    probe = [{"domain": "example.com", "emails": ["a@example.com"], "pages": []}]
    card = export_email_cards(probe, tmp_path / "Poly", collected_at="2026-10-13")[0].read_text(encoding="utf-8")
    assert "待发邮件" not in card
