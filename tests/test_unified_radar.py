from pathlib import Path

from local_tools.polyv_radar.unified_radar import UnifiedRadarReader
from local_tools.polyv_radar.zigo_store import ZigoStore


def test_unified_reader_reports_brand_and_domain_separately(tmp_path: Path):
    polyv_root = tmp_path / "polyv"
    zigo_root = tmp_path / "zigo"
    zigo = ZigoStore(zigo_root / "radar.sqlite3")
    zigo.initialize()
    zigo.ingest_run("zigo-run", "sales_agent", [{"platform": "dy", "content_id": "p1", "title": "t", "url": "https://example.test/p1", "author": "a", "source_type": "post"}], [])
    zigo.close()
    reader = UnifiedRadarReader(polyv_root, zigo_root / "radar.sqlite3")

    assert reader.summary("zigo", "sales_agent")["contents"] == 1
    assert reader.summary("zigo", "geo")["contents"] == 0
    assert reader.summary("all")["brands"] == {"polyv": 0, "zigo": 1}
    assert reader.runs("zigo")[0]["product_domain"] == "sales_agent"
