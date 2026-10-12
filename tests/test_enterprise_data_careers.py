from __future__ import annotations

from local_tools.enterprise_data.careers_extract import (
    anchor_jobs,
    detect_ats,
    discover_careers_links,
    extract_careers_page,
    json_ld_jobs,
    parse_html,
    is_ats_root,
)

JSON_LD_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"高级后端工程师","datePosted":"2026-09-01",
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"深圳"}},
 "url":"/jobs/123"}
</script>
<script type="application/ld+json">
{"@graph":[{"@type":"JobPosting","title":"产品经理","datePosted":"2026-09-10",
 "jobLocation":[{"address":{"addressLocality":"广州"}}],"url":"/jobs/456"}]}
</script>
</head><body>
<a href="/jobs/789">测试工程师 招3人</a>
<a href="/about">关于我们</a>
</body></html>
"""

ANCHOR_HTML = """
<html><body>
<a href="/jobs/1">Java 开发工程师 招5人</a>
<a href="/jobs/2">运营专员</a>
<a href="/news">公司新闻</a>
<a href="/join">加入我们</a>
</body></html>
"""


def test_json_ld_extraction_reads_postings():
    collector = parse_html(JSON_LD_HTML)
    jobs = json_ld_jobs(collector, "https://example.com/careers")
    assert {job["job_title"] for job in jobs} == {"高级后端工程师", "产品经理"}
    backend = next(job for job in jobs if job["job_title"] == "高级后端工程师")
    assert backend["city"] == "深圳"
    assert backend["publish_date"] == "2026-09-01"
    assert backend["job_url"] == "https://example.com/jobs/123"
    assert backend["extraction_method"] == "json-ld"
    assert backend["platform"] == "careers"


def test_json_ld_takes_precedence_over_anchor_fallback():
    result = extract_careers_page(JSON_LD_HTML, "https://example.com/careers")
    assert result["extraction_method"] == "json-ld"
    assert len(result["jobs"]) == 2


def test_anchor_fallback_detects_titles_and_headcount():
    result = extract_careers_page(ANCHOR_HTML, "https://example.com/")
    assert result["extraction_method"] == "anchor"
    titles = [job["job_title"] for job in result["jobs"]]
    assert "Java 开发工程师" in titles
    java = next(job for job in result["jobs"] if job["job_title"] == "Java 开发工程师")
    assert java["recruitment_count"] == 5
    assert java["raw_hiring_text"] == "招5人"
    assert all("公司新闻" not in title for title in titles)


def test_anchor_jobs_ignore_non_role_links():
    collector = parse_html(ANCHOR_HTML)
    titles = [job["job_title"] for job in anchor_jobs(collector, "https://example.com/")]
    assert "加入我们" not in titles


def test_discover_careers_links_finds_join_page():
    collector = parse_html(ANCHOR_HTML)
    links = discover_careers_links(collector, "https://example.com/")
    assert "https://example.com/join" in links


def test_empty_page_warns_about_js_rendering():
    result = extract_careers_page("<html><body><div id='app'></div></body></html>", "https://example.com/careers")
    assert result["jobs"] == []
    assert result["extraction_method"] == "none"
    assert any("JS" in warning for warning in result["warnings"])


def test_detect_ats_providers():
    links = ["https://app.mokahr.com/campus/x", "https://x.zhiye.com/jobs", "https://www.polyv.net/company/#join"]
    found = detect_ats(links)
    providers = {item["provider"] for item in found}
    assert providers == {"Moka", "北森"}
    assert all(item["url"].startswith("https://") for item in found)


def test_page_with_ats_link_warns():
    html = "<html><body><a href=\"https://app.mokahr.com/campus/x\">招聘管理系统</a></body></html>"
    result = extract_careers_page(html, "https://example.com/careers")
    assert result["ats_candidates"][0]["provider"] == "Moka"
    assert any("第三方招聘系统" in warning for warning in result["warnings"])


def test_ats_root_page_is_not_treated_as_job_list():
    assert is_ats_root("https://www.mokahr.com/")
    assert not is_ats_root("https://app.mokahr.com/apply/polyv/123")
    html = "<html><body><a href='/features/talentpool'>企业人才库运营</a></body></html>"
    result = extract_careers_page(html, "https://www.mokahr.com/")
    assert result["jobs"] == []
    assert result["extraction_method"] == "ats_render_required"
