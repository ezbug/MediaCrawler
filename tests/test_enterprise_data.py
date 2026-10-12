from __future__ import annotations

import sqlite3

import pytest

from local_tools.enterprise_data.metrics import (
    hiring_activity_score,
    job_staleness_label,
    size_by_assets,
    size_by_employee,
)
from local_tools.enterprise_data.storage import EnterpriseStore

TABLES = (
    "company",
    "company_industry",
    "company_financial_year",
    "job_listing_snapshot",
    "job_dedup_group",
    "company_hiring_metrics",
    "data_evidence",
)


@pytest.fixture()
def store(tmp_path):
    store = EnterpriseStore(tmp_path / "enterprise.sqlite3")
    yield store
    store.close()


def test_initialize_creates_all_tables(store):
    rows = store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {row["name"] for row in rows}
    for table in TABLES:
        assert table in names


def test_company_upsert_dedupes_by_credit_code(store):
    first = store.upsert_company({"company_name": "测试科技有限公司", "unified_social_credit_code": "91110000TEST0001X"})
    second = store.upsert_company({"company_name": "测试科技有限公司（更名）", "unified_social_credit_code": "91110000TEST0001X"})
    assert first == second
    row = store.connection.execute("SELECT company_name FROM company WHERE company_id = ?", (first,)).fetchone()
    assert row["company_name"].endswith("（更名）")
    assert store.list_companies()[0]["company_id"] == first


def test_financial_growth_and_size_tiers(store):
    company_id = store.upsert_company({"company_name": "增长示例"})
    store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2024, "reporting_scope": "consolidated", "report_version": "annual-2024",
        "period_end": "2024-12-31", "employee_count": 800, "employee_count_type": "year_end",
        "employee_count_scope": "consolidated", "total_assets": "200000000.00", "currency": "CNY",
        "unit_original": "元", "total_assets_scope": "consolidated",
    })
    result = store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2025, "reporting_scope": "consolidated", "report_version": "annual-2025",
        "period_end": "2025-12-31", "employee_count": 1000, "employee_count_type": "year_end",
        "employee_count_scope": "consolidated", "total_assets": "250000000.00", "currency": "CNY",
        "unit_original": "元", "total_assets_scope": "consolidated",
    })
    assert result["employee_growth_yoy"] == pytest.approx(0.25)
    assert result["asset_growth_yoy"] == pytest.approx(0.25)
    assert result["growth_comparability_status"] == "comparable"
    assert result["size_by_employee"] == "LARGE"
    assert result["size_by_assets"] == "MEDIUM"


def test_first_year_has_no_growth_until_previous_exists(store):
    company_id = store.upsert_company({"company_name": "首年示例"})
    result = store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2025, "reporting_scope": "consolidated", "report_version": "annual-2025",
        "employee_count": 100, "employee_count_type": "year_end", "employee_count_scope": "consolidated",
        "total_assets": "10000000", "total_assets_scope": "consolidated",
    })
    assert result["employee_growth_yoy"] is None
    assert result["employee_growth_status"] == "missing"
    assert result["growth_comparability_status"] == "missing"


def test_zero_base_and_scope_mismatch_block_growth(store):
    company_id = store.upsert_company({"company_name": "口径示例"})
    store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2023, "reporting_scope": "consolidated", "report_version": "annual-2023",
        "employee_count": 0, "employee_count_type": "year_end", "employee_count_scope": "consolidated",
        "total_assets": "0", "total_assets_scope": "consolidated",
    })
    zero_base = store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2024, "reporting_scope": "consolidated", "report_version": "annual-2024",
        "employee_count": 120, "employee_count_type": "year_end", "employee_count_scope": "consolidated",
        "total_assets": "9000000", "total_assets_scope": "consolidated",
    })
    assert zero_base["employee_growth_status"] == "zero_base"
    assert zero_base["growth_comparability_status"] == "zero_base"

    mismatch = store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2025, "reporting_scope": "consolidated", "report_version": "annual-2025",
        "employee_count": 150, "employee_count_type": "year_end", "employee_count_scope": "parent",
        "total_assets": "9500000", "total_assets_scope": "consolidated",
    })
    assert mismatch["employee_growth_yoy"] is None
    assert mismatch["employee_growth_status"] == "not_comparable"
    assert mismatch["growth_comparability_status"] == "not_comparable"


def test_financial_evidence_is_linked(store):
    company_id = store.upsert_company({"company_name": "证据示例"})
    store.upsert_financial({
        "company_id": company_id, "fiscal_year": 2025, "reporting_scope": "consolidated", "report_version": "annual-2025",
        "employee_count": 500, "employee_count_type": "year_end", "employee_count_scope": "consolidated",
        "total_assets": "300000000", "total_assets_scope": "consolidated",
        "evidence": [{
            "field_name": "employee_count", "source_type": "annual_report", "source_page": "123",
            "source_url": "https://example.com/ar.pdf", "source_excerpt": "在职员工的数量合计 500",
            "extraction_method": "manual", "extraction_confidence": 0.95,
        }],
    })
    profile = store.company_profile(company_id)
    assert profile["evidence_count"] == 1


def test_financial_and_jobs_require_existing_company(store):
    with pytest.raises(ValueError):
        store.upsert_financial({
            "company_id": "missing-co", "fiscal_year": 2025, "reporting_scope": "consolidated",
            "report_version": "annual-2025", "employee_count": 10, "employee_count_scope": "consolidated",
            "total_assets": "100", "total_assets_scope": "consolidated",
        })
    with pytest.raises(ValueError):
        store.add_jobs("missing-co", [{"platform": "boss", "platform_job_id": "x1"}])


def test_jobs_import_and_hiring_metrics(store):
    company_id = store.upsert_company({"company_name": "招聘示例"})
    jobs = [
        {"platform": "boss", "platform_job_id": "b1", "job_title": "Java 开发工程师", "city": "广州", "recruitment_count": 5, "first_seen_at": "2026-10-01T09:00:00+08:00"},
        {"platform": "boss", "platform_job_id": "b2", "job_title": "产品经理", "city": "广州", "first_seen_at": "2026-10-05T09:00:00+08:00"},
        {"platform": "51job", "platform_job_id": "j1", "job_title": "Java 工程师", "city": "广州", "recruitment_count": 3, "first_seen_at": "2026-09-20T09:00:00+08:00"},
        {"platform": "51job", "platform_job_id": "j2", "job_title": "测试工程师", "city": "深圳", "job_status": "CLOSED_OR_UNAVAILABLE", "first_seen_at": "2026-08-01T09:00:00+08:00"},
    ]
    first = store.add_jobs(company_id, jobs)
    assert first == {"inserted": 4, "updated": 0, "total": 4}
    again = store.add_jobs(company_id, jobs[:1])
    assert again["updated"] == 1 and again["inserted"] == 0

    metrics = store.compute_hiring_metrics(company_id, "2026-10-12")
    assert metrics["active_job_count"] == 3
    assert metrics["closed_job_count_30d"] == 1
    assert metrics["explicit_hiring_slots"] == 8
    assert metrics["hiring_count_coverage"] == pytest.approx(2 / 3)
    assert metrics["multi_platform_presence"] == 2
    assert metrics["hiring_activity_score"] is not None

    repeat = store.compute_hiring_metrics(company_id, "2026-10-12")
    rows = store.connection.execute(
        "SELECT COUNT(*) AS n FROM company_hiring_metrics WHERE company_id = ?", (company_id,)
    ).fetchone()
    assert rows["n"] == 1 and repeat["active_job_count"] == 3


def test_metrics_helpers():
    assert size_by_employee(9) == "MICRO"
    assert size_by_employee(10) == "SMALL"
    assert size_by_employee(1000) == "LARGE"
    assert size_by_assets(4_000_000) == "MICRO"
    assert size_by_assets(6_000_000) == "SMALL"
    assert size_by_assets(600_000_000) == "LARGE"

    score, meta = hiring_activity_score({"new_jobs": 100, "explicit_slots": None, "activity": 50, "platform_breadth": None, "diversity": None})
    assert score == pytest.approx((100 * 0.30 + 50 * 0.20) / 0.50, abs=0.01)
    assert "explicit_slots" in meta["missing"]
    assert hiring_activity_score({"diversity": None})[0] is None

    assert job_staleness_label(age_days=75, times_seen=3) == "LONG_RUNNING"
    assert job_staleness_label(age_days=75, times_seen=1) == "POSSIBLE_STALE"
    assert job_staleness_label(age_days=5, closed=True) == "CLOSED_OR_UNAVAILABLE"
