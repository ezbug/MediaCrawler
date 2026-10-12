from __future__ import annotations

from local_tools.enterprise_data.job_dedup import dedupe_jobs, label_jobs, normalize_title, title_similarity
from local_tools.enterprise_data.storage import EnterpriseStore


def _store(tmp_path) -> EnterpriseStore:
    return EnterpriseStore(tmp_path / "enterprise.sqlite3")


def test_normalize_and_similarity():
    assert normalize_title("Java 开发工程师（高级）") == "java开发工程师高级"
    assert title_similarity("java开发工程师", "java工程师") > 0.7
    assert title_similarity("java开发工程师", "产品经理") < 0.5


def test_dedupe_groups_cross_platform_and_keeps_cities_separate(tmp_path):
    store = _store(tmp_path)
    company_id = store.upsert_company({"company_name": "去重示例"})
    store.add_jobs(company_id, [
        {"platform": "boss", "platform_job_id": "a1", "job_title": "Java 开发工程师", "city": "深圳", "recruitment_count": 5},
        {"platform": "51job", "platform_job_id": "b1", "job_title": "Java工程师", "city": "深圳", "recruitment_count": 5},
        {"platform": "boss", "platform_job_id": "a2", "job_title": "Java 开发工程师", "city": "广州", "recruitment_count": 3},
        {"platform": "boss", "platform_job_id": "a3", "job_title": "产品经理", "city": "深圳"},
    ])
    result = dedupe_jobs(store, company_id)
    assert result == {"company_id": company_id, "jobs": 4, "groups": 3, "threshold": 0.85}

    groups = [dict(row) for row in store.connection.execute("SELECT * FROM job_dedup_group WHERE company_id = ?", (company_id,))]
    shenzhen_java = next(group for group in groups if group["location_scope"] == "深圳" and "java" in group["normalized_title"])
    assert shenzhen_java["recruitment_count_deduped"] == 5  # 多来源不叠加
    assert shenzhen_java["recruitment_count_confidence"] == "consistent"
    assert shenzhen_java["review_status"] == "pending"  # 标题不完全一致，需要人工确认

    jobs = [dict(row) for row in store.connection.execute("SELECT * FROM job_listing_snapshot WHERE company_id = ?", (company_id,))]
    assert all(job["dedup_group_id"] for job in jobs)


def test_metrics_use_dedup_groups(tmp_path):
    store = _store(tmp_path)
    company_id = store.upsert_company({"company_name": "指标示例"})
    store.add_jobs(company_id, [
        {"platform": "boss", "platform_job_id": "m1", "job_title": "Java 开发工程师", "city": "深圳", "recruitment_count": 5, "first_seen_at": "2026-10-01T09:00:00+08:00"},
        {"platform": "51job", "platform_job_id": "m2", "job_title": "Java工程师", "city": "深圳", "recruitment_count": 5, "first_seen_at": "2026-10-02T09:00:00+08:00"},
        {"platform": "boss", "platform_job_id": "m3", "job_title": "产品经理", "city": "深圳", "first_seen_at": "2026-10-03T09:00:00+08:00"},
    ])
    dedupe_jobs(store, company_id)
    metrics = store.compute_hiring_metrics(company_id, "2026-10-12")
    assert metrics["active_job_count"] == 3
    assert metrics["unique_job_count"] == 2
    assert metrics["explicit_hiring_slots"] == 5
    assert metrics["hiring_activity_score"] is not None


def test_label_jobs_marks_long_running_and_outsourcing(tmp_path):
    store = _store(tmp_path)
    company_id = store.upsert_company({"company_name": "标签示例"})
    store.add_jobs(company_id, [
        {"platform": "boss", "platform_job_id": "l1", "job_title": "客服专员", "city": "深圳", "first_seen_at": "2026-07-01T09:00:00+08:00"},
        {"platform": "boss", "platform_job_id": "l2", "job_title": "驻场运维工程师", "city": "深圳", "raw_hiring_text": "外包驻场", "first_seen_at": "2026-10-01T09:00:00+08:00"},
        {"platform": "boss", "platform_job_id": "l3", "job_title": "前端工程师", "city": "深圳", "first_seen_at": "2026-10-08T09:00:00+08:00"},
    ])
    result = label_jobs(store, company_id, "2026-10-12")
    assert result["labels"].get("LONG_RUNNING") == 1
    assert result["labels"].get("POSSIBLE_OUTSOURCING") == 1
    assert result["labels"].get("active") == 1

    metrics = store.compute_hiring_metrics(company_id, "2026-10-12")
    assert metrics["outsourcing_job_ratio"] == round(1 / 3, 6) or metrics["outsourcing_job_ratio"] == 1 / 3
