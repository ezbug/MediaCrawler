"""Campaign display contracts, including absent/uninitialized storage."""
import sqlite3
from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from api.main import app
from api.routers import customer_campaign as routes
from local_tools.polyv_radar.customer_campaign_dashboard import render_customer_campaign_dashboard


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYV_RADAR_DATA_ROOT", str(tmp_path / "radar"))
    return TestClient(app)


def test_absent_database_is_not_created(client, tmp_path):
    assert client.get("/api/radar/campaigns").json() == {"campaigns": []}
    for suffix in ("summary", "companies", "dashboard.html"):
        assert client.get(f"/api/radar/campaigns/national-day/{suffix}").status_code == 404
    assert not (tmp_path / "radar").exists()
    response = client.get("/polyv-dashboard.html")
    assert response.status_code == 200
    assert "campaign-selector" in response.text
    assert not (tmp_path / "radar").exists()


def test_refresh_keeps_campaign_query_and_marks_unknown_dates():
    page = render_customer_campaign_dashboard([
        dict(company_name="Example", source_url="https://example.test", quote="Training",
             evidence={"checked_at": "2026-10-03T12:00:00Z", "opening_question": "<draft>"}),
    ], {}, "national-day")
    assert "location.pathname + location.search" in page
    assert "发布日期：未知" in page
    assert "核验时间：2026-10-03T12:00:00Z" in page
    assert "&lt;draft&gt;" in page


def test_existing_database_is_not_migrated(client, tmp_path):
    root = tmp_path / "radar"
    root.mkdir()
    path = root / "radar.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE historical (value TEXT)")
    before = path.read_bytes()
    assert client.get("/api/radar/campaigns").json() == {"campaigns": []}
    assert client.get("/api/radar/campaigns/new/summary").status_code == 404
    assert path.read_bytes() == before


def test_configured_store_only_and_snapshot_is_read_only(client, tmp_path, monkeypatch):
    root = tmp_path / "radar"
    root.mkdir()
    path = root / "radar.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
        CREATE TABLE polyv_customer_campaigns (campaign_id TEXT, brand TEXT, sector TEXT, target_companies INTEGER, target_exchanges INTEGER);
        INSERT INTO polyv_customer_campaigns VALUES ('national-day', 'POLYV', 'training', 100, 2);
        CREATE TABLE companies (campaign_id TEXT, company_id TEXT, company_name TEXT);
        INSERT INTO companies VALUES ('national-day', 'p1', 'POLYV enterprise');
        INSERT INTO companies VALUES ('zigo-other', 'z1', 'Zigo enterprise');
        CREATE TABLE polyv_campaign_events (campaign_id TEXT, company_id TEXT, event_type TEXT, payload TEXT, event_id TEXT);
        """)
    def list_companies(store, campaign_id):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store.connection.execute("CREATE TABLE accidental_write (id INTEGER)")
        return [dict(row) for row in store.connection.execute("SELECT * FROM companies WHERE campaign_id = ?", (campaign_id,))]
    def campaign_summary(store, campaign_id):
        count = len(list_companies(store, campaign_id))
        return dict(qualified_companies=count, contacted_companies=0, replied_companies=0,
                    effective_exchanges=0, target_companies=100, target_exchanges=2, pending_companies=count)
    monkeypatch.setattr(routes, "_storage_module", lambda: SimpleNamespace(list_companies=list_companies, campaign_summary=campaign_summary))
    before = path.read_bytes()
    assert client.get("/api/radar/campaigns").json()["campaigns"][0]["sector"] == "training"
    response = client.get("/api/radar/campaigns/national-day/summary", params={"db_path": str(tmp_path / "evil.sqlite3"), "brand": "zigo"})
    assert response.json()["qualified_companies"] == 1
    assert response.json()["target_companies"] == 100
    assert response.json()["target_exchanges"] == 2
    assert client.get("/api/radar/campaigns/national-day/companies").json()["companies"][0]["company_name"] == "POLYV enterprise"
    for url in ("/api/radar/campaigns/national-day/dashboard.html", "/polyv-dashboard.html?campaign_id=national-day"):
        page = client.get(url)
        assert page.status_code == 200
        assert "POLYV enterprise" in page.text
        assert "Zigo enterprise" not in page.text
    assert client.get("/api/radar/campaigns/zigo-missing/summary").status_code == 404
    assert path.read_bytes() == before
    assert not (tmp_path / "evil.sqlite3").exists()
    assert not (root / "zigoai").exists()


def test_html_escapes_every_dynamic_field_and_rejects_active_urls():
    attack = '<img src=x onerror="alert(1)">'
    row = dict(company_name=attack, scenario=attack, contact_entry=attack,
               contact_url="javascript:alert(1)", fit_score=attack, intent_score=attack,
               outreach=attack, reply=attack, next_action=attack,
               sources=[dict(quote=attack, date=attack, url='https://example.test/" onclick="alert(1)'),
                        dict(quote=attack, url="data:text/html,<script>alert(1)</script>")])
    page = render_customer_campaign_dashboard([row], {"qualified_companies": attack}, '</script><script>alert(1)</script>')
    assert attack not in page
    assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in page
    assert 'href="javascript:' not in page
    assert 'href="data:' not in page
    assert 'href="https://example.test/&quot; onclick=&quot;alert(1)"' in page
    assert '</script><script>alert(1)</script>' not in page
    assert "setInterval(refresh, 5000)" in page
    assert "刷新失败" in page
    assert "textContent" in page
    assert "innerHTML" not in page
    for label in ("企业身份", "业务场景", "来源原话 / 日期 / URL", "联系入口", "适配分", "意向分", "触达状态", "回复", "下一步", "企业目标", "有效交流目标"):
        assert label in page


def test_history_dashboard_keeps_existing_render(client, monkeypatch):
    import api.main as main
    monkeypatch.setattr(main, "latest_history_run", lambda: "history")
    monkeypatch.setattr(main, "render_html_dashboard", lambda *args: '<html><body><table id="historical">Zigo and POLYV history</table></body></html>')
    page = client.get("/polyv-dashboard.html")
    assert '<table id="historical">Zigo and POLYV history</table>' in page.text
    assert "campaign-selector" in page.text


def test_database_failures_are_visible_without_exposing_paths(client, tmp_path):
    root = tmp_path / "radar"
    root.mkdir()
    (root / "radar.sqlite3").write_text("corrupt database")
    response = client.get("/api/radar/campaigns")
    assert response.status_code == 503
    assert "读取失败" in response.text
    assert str(tmp_path) not in response.text


def test_real_storage_funnel_and_evidence_are_campaign_scoped(client, tmp_path, monkeypatch):
    from local_tools.polyv_radar.customer_campaign import (
        initialize_campaign, upsert_company, link_outreach, record_exchange,
    )
    from local_tools.polyv_radar.storage import RadarStore
    from local_tools.polyv_radar.zigo_store import ZigoStore

    root = tmp_path / "radar"
    store = RadarStore(root / "radar.sqlite3")
    initialize_campaign(store, "national-day", "training")
    initialize_campaign(store, "other-campaign", "events", target_companies=50)
    payload = dict(company_id="enterprise", company_name="Enterprise", business_type="enterprise",
                   scenario="employee training", quote="Need a training platform", source_verified=True,
                   source_url="https://example.test/demand", published_at="2026-09-30",
                   contact_entry_url="https://example.test/contact", fit_reason="training fit",
                   identity_status="verified", official_domain="enterprise.test", fit_score=8, intent_score=7,
                   next_action="Review requirements")
    upsert_company(store, "national-day", payload)
    upsert_company(store, "national-day", {"company_id": "pending", "company_name": "Pending enterprise"})
    for index in range(3):
        upsert_company(store, "other-campaign", {**payload, "company_id": f"other-{index}", "official_domain": f"other-{index}.test"})
    evidence = dict(source_url="https://example.test/discussion", actual_date=date.today().isoformat(),
                    own_account_id="ours", other_account_id="customer", platform="zhihu",
                    submitted=True, verified=True, own_account=True, target_relation=True,
                    quote="What training scope do you need?")
    link_outreach(store, "national-day", "enterprise", evidence)
    record_exchange(store, "national-day", {**evidence, "company_id": "enterprise", "source_verified": True,
                    "other_quote": "We need training for 500 employees", "own_quote": "We can scope account permissions",
                    "substantive_business_response": True})
    store.close()
    zigo = ZigoStore(root / "zigoai" / "radar.sqlite3")
    zigo.initialize()
    zigo.ingest_run("zigo-run", "geo", [{"platform": "xhs", "content_id": "z1", "title": "Zigo demand",
                    "url": "https://example.test/zigo", "source_type": "post"}], [])
    zigo.close()
    before = {path: path.read_bytes() for path in root.rglob("*.sqlite3")}
    def forbidden_initialize(*args, **kwargs):
        raise AssertionError("GET must not initialize or migrate")
    monkeypatch.setattr(RadarStore, "initialize", forbidden_initialize)
    monkeypatch.setattr(ZigoStore, "initialize", forbidden_initialize)
    result = client.get("/api/radar/campaigns/national-day/summary").json()
    assert result == dict(campaign_id="national-day", brand="POLYV", sector="training", target_companies=100,
                         target_exchanges=2, qualified_companies=1, contacted_companies=1, replied_companies=1,
                         effective_exchanges=1, pending_companies=1)
    assert client.get("/api/radar/campaigns/other-campaign/summary").json()["qualified_companies"] == 3
    companies = client.get("/api/radar/campaigns/national-day/companies").json()["companies"]
    enterprise = next(row for row in companies if row["company_id"] == "enterprise")
    assert len(enterprise["outreach_events"]) == len(enterprise["reply_events"]) == 1
    page = client.get("/api/radar/campaigns/national-day/dashboard.html")
    assert page.status_code == 200
    for text in ("Need a training platform", "2026-09-30", "https://example.test/demand",
                 "https://example.test/contact", "We need training for 500 employees", "What training scope do you need?",
                 "Review requirements", "enterprise.test"):
        assert text in page.text
    assert "Zigo demand" not in page.text
    assert page.headers["cache-control"] == "no-store"
    assert {path: path.read_bytes() for path in before} == before


def test_activity_routes_have_no_mutating_methods(client):
    for url in ("/api/radar/campaigns", "/api/radar/campaigns/national-day/summary",
                "/api/radar/campaigns/national-day/companies", "/api/radar/campaigns/national-day/dashboard.html"):
        assert client.post(url).status_code == 405
