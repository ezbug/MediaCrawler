from __future__ import annotations

import pytest

from local_tools.enterprise_data.hiring_batch import parse_target, render_report, run_hiring_batch
from local_tools.enterprise_data.storage import EnterpriseStore


def test_parse_target_builds_brand_record():
    target = parse_target("微吼")
    assert target["company_id"] == "brand-微吼"
    assert target["query"] == "微吼"
    assert target["employer_filter"] == "微吼"
    with pytest.raises(ValueError):
        parse_target("   ")


def test_render_report_builds_comparison_table():
    results = [
        {
            "target": {"company_name": "微吼"},
            "metrics": {"active_job_count": 12, "unique_job_count": 11, "multi_platform_presence": 2, "hiring_activity_score": 80.0},
            "platforms": {"liepin": {"collected": 8}, "boss": {"collected": 4}},
            "top_jobs": ["AI 工程师", "销售经理"],
        }
    ]
    markdown = render_report(results, "2026-10-12", ["liepin", "boss"])
    assert "| 微吼 | 12 | 11 | 2 | 80.0 | 8 | 4 |" in markdown
    assert "AI 工程师" in markdown
    assert "不代表真实招聘人数" in markdown


def test_run_hiring_batch_with_fake_collector(tmp_path):
    store = EnterpriseStore(tmp_path / "enterprise.sqlite3")
    calls = []

    def fake_collect(**kwargs):
        calls.append(kwargs["platform"])
        return {
            "company_id": kwargs["company_id"],
            "jobs": [{
                "platform": kwargs["platform"], "platform_job_id": f"{kwargs['platform']}-1",
                "job_title": "AI 工程师", "city": "深圳", "employer_name": "微吼",
                "first_seen_at": "2026-10-11T09:00:00+08:00",
            }],
            "_extraction": {"warnings": []},
        }

    output = tmp_path / "report.md"
    payload = run_hiring_batch(
        store, [parse_target("微吼")], taskspace=3, platforms=["liepin", "boss"],
        stat_date="2026-10-12", output=output, collector=fake_collect,
    )
    assert calls == ["liepin", "boss"]
    assert output.exists()
    metrics = payload["results"][0]["metrics"]
    assert metrics["active_job_count"] == 2
    assert metrics["unique_job_count"] == 1  # 跨平台同标题同城市 → 合并为一个需求组
    assert metrics["multi_platform_presence"] == 2
    assert "微吼" in output.read_text(encoding="utf-8")
    store.close()
