import json
from pathlib import Path

from local_tools.polyv_radar.zigo_keywords import build_keyword_registry


def test_keyword_registry_contains_material_provenance(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "manifest.json").write_text(json.dumps({"documents": [
        {"source_id": "sales-doc", "domain": "sales_agent", "file_name": "sales.pdf", "date": "2026-08"},
        {"source_id": "geo-doc", "domain": "geo", "file_name": "geo.pdf", "date": "2026-07"},
    ]}), encoding="utf-8")
    (knowledge / "chunks.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in [
            {"source_id": "sales-doc", "domain": "sales_agent", "page": 4, "text": "客户跟进 线索转化"},
            {"source_id": "geo-doc", "domain": "geo", "page": 8, "text": "AI搜索 品牌推荐"},
        ]), encoding="utf-8"
    )
    output = tmp_path / "zigo_keywords.json"
    result = build_keyword_registry(knowledge, output)
    assert result["version"].startswith("zigo-material-")
    rows = json.loads(output.read_text(encoding="utf-8"))["keywords"]
    registry = json.loads(output.read_text(encoding="utf-8"))
    assert registry["version"].startswith("zigo-material-")
    assert len(registry["taxonomy_sha256"]) == 64
    sales = [row for row in rows if row["product_domain"] == "sales_agent" and row["keyword"] == "客户跟进"]
    geo = [row for row in rows if row["product_domain"] == "geo" and row["keyword"] == "AI搜索"]
    assert sales[0]["derivation"] == "material_excerpt"
    assert sales[0]["source_pages"] == [4]
    assert sales[0]["source_file"] == "sales.pdf"
    assert geo[0]["source_id"] == "geo-doc"


def test_query_expansions_keep_scenario_and_buyer_provenance(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "manifest.json").write_text(json.dumps({"documents": [
        {"source_id": "sales-doc", "domain": "sales_agent", "file_name": "sales.pdf"},
        {"source_id": "geo-doc", "domain": "geo", "file_name": "geo.pdf"},
    ]}), encoding="utf-8")
    (knowledge / "chunks.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in [
            {"source_id": "sales-doc", "domain": "sales_agent", "page": 4, "text": "销售自动化 线索跟进"},
            {"source_id": "geo-doc", "domain": "geo", "page": 8, "text": "AI搜索 品牌信源"},
        ]), encoding="utf-8"
    )
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(json.dumps({
        "sales_agent": {"queries": [], "query_expansions": [
            {"keyword": "老板让我找销售自动化工具", "query_kind": "purchase_intent",
             "scenario": "销售自动化选型", "source_terms": ["销售自动化"]}
        ]},
        "geo": {"queries": [], "query_expansions": []},
    }), encoding="utf-8")
    output = tmp_path / "registry.json"
    build_keyword_registry(knowledge, output, taxonomy)
    registry = json.loads(output.read_text(encoding="utf-8"))
    row = registry["query_registry"][0]
    assert row["query_kind"] == "purchase_intent"
    assert row["scenario"] == "销售自动化选型"
    assert row["source_terms"] == ["销售自动化"]
    assert row["derivation"] == "material_backed_query"
    assert row["source_pages"] == [4]
