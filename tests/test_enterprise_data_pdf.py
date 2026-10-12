from __future__ import annotations

import pymupdf
import pytest

from local_tools.enterprise_data.pdf_extract import (
    extract_annual_report,
    find_asset_candidates,
    find_employee_candidates,
    read_pages,
)
from local_tools.enterprise_data.storage import EnterpriseStore


def _write_pdf(path, page_texts: list[str]):
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        y = 72
        for line in text.split("\n"):
            page.insert_text((72, y), line, fontname="china-s", fontsize=11)
            y += 18
    document.save(str(path))
    document.close()


@pytest.fixture()
def sample_pdf(tmp_path):
    path = tmp_path / "annual-report-sample.pdf"
    _write_pdf(path, [
        "示例科技股份有限公司\n2025 年年度报告",
        "第八节 董事、监事、高级管理人员和员工情况\n在职员工的数量合计 1,234人\n母公司在职员工的数量 456人\n主要子公司在职员工的数量 778人",
        "合并资产负债表\n单位：元\n流动资产合计 8,000,000,000.00\n资产总计 25,000,000,000.00 20,000,000,000.00",
        "母公司资产负债表\n单位：元\n资产总计 10,000,000,000.00 9,000,000,000.00",
    ])
    return path


def test_read_pages_returns_text_layer(sample_pdf):
    pages = read_pages(sample_pdf)
    assert len(pages) == 4
    assert "在职员工的数量合计" in pages[1]["text"]


def test_find_employee_ignores_parent_and_subsidiary_breakdown(sample_pdf):
    candidates = find_employee_candidates(read_pages(sample_pdf))
    assert [item["value"] for item in candidates] == [1234]
    assert candidates[0]["page"] == 2
    assert candidates[0]["confidence"] >= 0.95


def test_find_assets_prefers_consolidated_scope(sample_pdf):
    candidates = find_asset_candidates(read_pages(sample_pdf))
    scopes = {item["scope"] for item in candidates}
    assert scopes == {"consolidated", "parent"}
    consolidated = next(item for item in candidates if item["scope"] == "consolidated")
    assert consolidated["value_text"] == "25,000,000,000.00"
    assert consolidated["unit"] == "元"


def test_extract_annual_report_builds_import_ready_candidate(sample_pdf):
    payload = extract_annual_report(sample_pdf, company_id="c-sample", fiscal_year=2025)
    assert payload["employee_count"] == 1234
    assert payload["employee_count_scope"] == "consolidated"
    assert payload["total_assets"] == "25000000000.00"
    assert payload["total_assets_scope"] == "consolidated"
    assert payload["unit_original"] == "元"
    assert payload["report_version"] == "annual-2025"
    pages = {item["field_name"]: item["source_page"] for item in payload["evidence"]}
    assert pages == {"employee_count": "2", "total_assets": "3"}
    assert payload["_extraction"]["needs_review"] is True
    assert any("多个口径" in warning for warning in payload["_extraction"]["warnings"])


def test_scanned_or_empty_pdf_reports_warnings(tmp_path):
    path = tmp_path / "scanned.pdf"
    _write_pdf(path, ["", ""])
    payload = extract_annual_report(path, company_id="c-empty", fiscal_year=2025)
    assert payload["employee_count"] is None
    assert payload["total_assets"] is None
    joined = " | ".join(payload["_extraction"]["warnings"])
    assert "扫描件" in joined
    assert "未找到员工人数候选" in joined
    assert "未找到资产总计候选" in joined


def test_missing_unit_is_flagged_and_value_kept(tmp_path):
    path = tmp_path / "no-unit.pdf"
    _write_pdf(path, [
        "合并资产负债表\n资产总计 12,345,678.90 11,000,000.00",
    ])
    payload = extract_annual_report(path, company_id="c-nounit", fiscal_year=2025)
    assert payload["total_assets"] == "12,345,678.90"
    assert payload["unit_original"] is None
    assert any("单位" in warning for warning in payload["_extraction"]["warnings"])


def test_real_world_phrasing_and_unit_conversion(tmp_path):
    path = tmp_path / "cjk-report.pdf"
    _write_pdf(path, [
        "3.1.7 本集团员工情况\n截至2025年12月31日，本集团员工共65,095人（其中母公司总人数为55,879人）",
        "合并资产负债表\n人民币千元\n资产总计 217,739,375 207,323,230",
    ])
    payload = extract_annual_report(path, company_id="c-real", fiscal_year=2025)
    assert payload["employee_count"] == 65095
    assert payload["total_assets"] == "217739375000.00"
    assert payload["unit_original"] == "千元"
    assert payload["total_assets_scope"] == "consolidated"
    assert payload["_extraction"]["total_assets_raw_text"] == "217,739,375"
    assert any("千元" in warning for warning in payload["_extraction"]["warnings"])


def test_extracted_candidate_imports_into_store(tmp_path, sample_pdf):
    store = EnterpriseStore(tmp_path / "enterprise.sqlite3")
    company_id = store.upsert_company({"company_name": "示例科技股份有限公司", "ticker": "000001"})
    payload = extract_annual_report(sample_pdf, company_id=company_id, fiscal_year=2025, period_end="2025-12-31")
    result = store.upsert_financial(payload)
    assert result["employee_growth_status"] == "missing"  # 只有一年数据
    profile = store.company_profile(company_id)
    record = profile["financials"][0]
    assert record["employee_count"] == 1234
    assert record["total_assets"] == "25000000000.00"
    assert record["size_by_employee"] == "LARGE"
    assert record["size_by_assets"] == "LARGE"
    assert profile["evidence_count"] == 2
    store.close()
