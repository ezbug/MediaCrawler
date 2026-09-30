from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from local_tools.polyv_radar.zigo_store import ZigoStore


def test_unified_api_reads_zigo_database_without_exposing_path(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    zigo_db = data_root / "zigoai" / "radar.sqlite3"
    store = ZigoStore(zigo_db)
    store.initialize()
    store.ingest_run("api-run", "geo", [{"platform": "xhs", "content_id": "p1", "title": "AI品牌", "url": "https://example.test/p1", "source_type": "post"}], [])
    store.close()
    monkeypatch.setenv("POLYV_RADAR_DATA_ROOT", str(data_root))
    monkeypatch.setenv("ZIGO_RADAR_DB", str(zigo_db))
    client = TestClient(app)

    response = client.get("/api/radar/unified/summary", params={"brand": "zigo", "product_domain": "geo"})
    assert response.status_code == 200
    assert response.json()["contents"] == 1
    assert "radar.sqlite3" not in response.text
    assert client.get("/api/radar/unified/runs", params={"brand": "zigo"}).json()["runs"][0]["run_id"] == "api-run"
