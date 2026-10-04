import json

from fastapi.testclient import TestClient
import pytest

from api.main import app
from local_tools.polyv_radar.zigo_campaign_dashboard import render_zigo_campaign_dashboard


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ZIGO_CAMPAIGN_DATA_ROOT", str(tmp_path / "zigo-runs"))
    return TestClient(app)


def _write_ledger(root, campaign="20261001-zigo-leads-10"):
    directory = root / campaign
    directory.mkdir(parents=True)
    records = [
        {"candidate_id": "c1", "author": "Buyer <one>", "evidence_layer": "comment_verified",
         "source_quote": "Need a GEO agency", "published_at": "2026-09-30T02:11:06Z",
         "content_url": "https://example.test/note", "reply_suggestion": "A draft", "sent": False,
         "reply_status": "draft_only_not_sent"},
        {"candidate_id": "c2", "author": "Buyer two", "evidence_layer": "content_buyer_verified",
         "source_quote": "Need GEO", "content_url": "https://example.test/other", "sent": False,
         "reply_status": "draft_only_not_sent"},
        {"candidate_id": "c3", "author": "Buyer three", "evidence_layer": "insufficient_evidence",
         "source_quote": "Unavailable", "content_url": "https://example.test/missing", "sent": False,
         "reply_status": "draft_only_pending_evidence", "verification_error": "note unavailable"},
    ]
    (directory / "verified-candidates.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n", encoding="utf-8"
    )
    return campaign


def test_zigo_board_reads_only_configured_ledger(client, tmp_path):
    root = tmp_path / "zigo-runs"
    campaign = _write_ledger(root)
    before = (root / campaign / "verified-candidates.jsonl").read_bytes()
    assert client.get("/api/radar/zigo-campaigns").json()["campaigns"] == [{
        "campaign_id": campaign, "brand": "ZigoAI", "product_domain": "可信 GEO", "source": "公开社媒需求证据"
    }]
    summary = client.get(f"/api/radar/zigo-campaigns/{campaign}/summary").json()
    assert summary == {
        "campaign_id": campaign, "brand": "ZigoAI", "product_domain": "可信 GEO", "total_leads": 3,
        "comment_verified": 1, "content_buyer_verified": 1, "pending_evidence": 1,
        "outreach_sent": 0, "replies": 0,
    }
    page = client.get(f"/api/radar/zigo-campaigns/{campaign}/dashboard.html")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "社媒账号线索不等于已核验企业主体" in page.text
    assert "已发送触达</span><strong>0" in page.text
    assert (root / campaign / "verified-candidates.jsonl").read_bytes() == before


def test_zigo_dashboard_escapes_dynamic_content_and_never_creates_missing_root(client, tmp_path):
    assert client.get("/api/radar/zigo-campaigns").json() == {"campaigns": []}
    assert client.get("/zigo-dashboard.html").status_code == 200
    assert not (tmp_path / "zigo-runs").exists()
    page = render_zigo_campaign_dashboard([
        {"author": '<img src=x onerror="alert(1)">', "identity_status": "account", "evidence_status": "ok",
         "source_quote": "<script>alert(1)</script>", "content_url": "javascript:alert(1)", "buyer_signal": "x",
         "reply_suggestion": "x", "outreach_status": "x", "reply_status": "x", "next_action": "x"},
    ], {"total_leads": '<img src=x onerror="alert(1)">'}, '</script><script>alert(1)</script>')
    assert '<img src=x onerror="alert(1)">' not in page
    assert 'href="javascript:' not in page
    assert "textContent" in page and "innerHTML" not in page


def test_zigo_routes_have_no_mutating_methods(client):
    for url in ("/api/radar/zigo-campaigns", "/api/radar/zigo-campaigns/missing/summary",
                "/api/radar/zigo-campaigns/missing/leads", "/api/radar/zigo-campaigns/missing/dashboard.html"):
        assert client.post(url).status_code == 405
