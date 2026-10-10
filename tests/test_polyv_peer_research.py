from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from local_tools.polyv_radar.peer_research import (
    DIRECTIONS,
    PLATFORMS,
    build_peer_collect_config,
    build_peer_plan,
    load_peer_taxonomy,
    render_peer_plan_markdown,
    write_peer_plan,
)

TAXONOMY_PATH = (
    Path(__file__).resolve().parents[1]
    / "local_tools"
    / "polyv_radar"
    / "peer_research_taxonomy.json"
)


def minimal_taxonomy() -> dict:
    return {
        "schema": "polyv-peer-research",
        "version": "test",
        "platforms": {platform: {"name": platform} for platform in PLATFORMS},
        "directions": {
            "peer_discovery": {
                "name": "同行查找",
                "templates": ["{brand}", "{brand} 官方账号"],
                "category_templates": ["企业直播平台 排行榜"],
            },
            "peer_pricing": {
                "name": "同行价格",
                "templates": ["{brand} 价格"],
                "category_templates": [],
            },
            "peer_promotion": {
                "name": "宣传与私信话术",
                "templates": ["{brand} 私信"],
                "category_templates": [],
            },
        },
        "competitors": [
            {"brand": "微吼", "category": "企业直播", "priority": 1},
            {"brand": "小鹅通", "category": "知识付费与私域", "priority": 2},
            {"brand": "声网", "category": "云厂商与基础技术", "priority": 3},
        ],
        "evidence_rules": {"price": ["价格必须带来源链接"]},
        "compliance": {"forbidden": ["通过爬虫读取他人私信"]},
    }


def test_plan_expands_brand_platform_matrix():
    plan = build_peer_plan(
        minimal_taxonomy(),
        brands=["微吼"],
        directions=["peer_discovery"],
        platforms=["dy", "xhs"],
        now=datetime(2026, 10, 10, 12, 0, 0),
    )
    # 2 个品牌模板 x 2 个平台 + 1 个通用模板 x 2 个平台
    assert len(plan["queries"]) == 6
    assert {query["platform"] for query in plan["queries"]} == {"dy", "xhs"}
    assert plan["plan_id"] == "peer-plan-20261010-120000"
    assert plan["filters"]["brand_scope"] == "explicit"


def test_default_scope_keeps_priority_one_brands():
    plan = build_peer_plan(minimal_taxonomy(), directions=["peer_discovery"], platforms=["dy"])
    brands = {query["brand"] for query in plan["queries"] if query["brand"]}
    assert brands == {"微吼"}
    assert plan["filters"]["brand_scope"] == "priority1"


def test_all_brands_flag_includes_adjacent_and_infra():
    plan = build_peer_plan(
        minimal_taxonomy(),
        directions=["peer_discovery"],
        platforms=["dy"],
        include_all_brands=True,
    )
    brands = {query["brand"] for query in plan["queries"] if query["brand"]}
    assert brands == {"微吼", "小鹅通", "声网"}
    assert plan["filters"]["brand_scope"] == "all"


def test_unknown_direction_platform_and_brand_rejected():
    with pytest.raises(ValueError):
        build_peer_plan(minimal_taxonomy(), directions=["peer_unknown"])
    with pytest.raises(ValueError):
        build_peer_plan(minimal_taxonomy(), platforms=["weibo"])
    with pytest.raises(ValueError):
        build_peer_plan(minimal_taxonomy(), brands=["不存在的品牌"])


def test_duplicate_template_expansion_is_deduped():
    taxonomy = minimal_taxonomy()
    taxonomy["directions"]["peer_discovery"]["templates"] = ["{brand}", "{brand}"]
    plan = build_peer_plan(taxonomy, brands=["微吼"], directions=["peer_discovery"], platforms=["dy"])
    texts = [query["query"] for query in plan["queries"]]
    assert texts.count("微吼") == 1


def test_max_queries_truncates_and_flags():
    plan = build_peer_plan(
        minimal_taxonomy(),
        directions=["peer_discovery"],
        platforms=["dy", "xhs"],
        include_all_brands=True,
        max_queries=3,
    )
    assert len(plan["queries"]) == 3
    assert plan["filters"]["truncated"] is True


def test_recommended_first_batch_prefers_discovery_on_dy_and_xhs():
    plan = build_peer_plan(
        minimal_taxonomy(),
        directions=["peer_discovery", "peer_pricing"],
        platforms=["dy", "xhs", "zhihu"],
    )
    assert plan["recommended_first_batch"]
    assert len(plan["recommended_first_batch"]) <= 12
    assert all(item["direction"] == "peer_discovery" for item in plan["recommended_first_batch"])
    assert {item["platform"] for item in plan["recommended_first_batch"]} <= {"dy", "xhs"}


def test_write_plan_writes_json_and_markdown(tmp_path):
    plan = build_peer_plan(
        minimal_taxonomy(),
        brands=["微吼"],
        directions=["peer_pricing"],
        platforms=["zhihu"],
        now=datetime(2026, 10, 10, 9, 30, 0),
    )
    paths = write_peer_plan(plan, tmp_path)
    assert paths["json"].name == "peer-plan-20261010-093000.json"
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["queries"] == plan["queries"]
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "微吼 价格" in markdown
    assert "同行价格" in markdown


def test_markdown_render_contains_evidence_and_compliance_sections():
    plan = build_peer_plan(
        minimal_taxonomy(),
        brands=["微吼"],
        directions=["peer_pricing"],
        platforms=["zhihu"],
        now=datetime(2026, 10, 10, 9, 30, 0),
    )
    markdown = render_peer_plan_markdown(plan)
    assert "证据规则" in markdown
    assert "合规红线" in markdown


def test_repository_taxonomy_is_valid_and_complete():
    taxonomy = load_peer_taxonomy(TAXONOMY_PATH)
    assert taxonomy["version"]
    for direction in DIRECTIONS:
        definition = taxonomy["directions"][direction]
        assert definition["templates"], direction
        assert definition["category_templates"], direction
    brands = [item["brand"] for item in taxonomy["competitors"]]
    assert len(brands) >= 10
    assert len(brands) == len(set(brands))
    assert any(int(item.get("priority", 1)) == 1 for item in taxonomy["competitors"])
    assert taxonomy["compliance"]["forbidden"]
    assert taxonomy["evidence_rules"]["price"]


def test_load_rejects_wrong_schema(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_peer_taxonomy(bad)


@dataclass
class FakeConfig:
    data_root: Path
    platforms: list
    keywords: dict
    platform_keywords: dict
    taxonomy_enabled: bool
    taxonomy_keywords: dict
    max_contents: int
    max_comments: int
    task_timeout_seconds: int


def test_peer_collect_config_isolates_peer_queries():
    config = FakeConfig(
        data_root=Path("/tmp/radar"),
        platforms=["dy", "xhs", "bili", "zhihu"],
        keywords={"企业直播": "企业直播平台推荐"},
        platform_keywords={"dy": {"年会": "公司年会直播 平台报价"}},
        taxonomy_enabled=True,
        taxonomy_keywords={"tier1": "员工大会 平台"},
        max_contents=15,
        max_comments=30,
        task_timeout_seconds=180,
    )
    plan = build_peer_plan(
        minimal_taxonomy(),
        brands=["微吼", "小鹅通"],
        directions=["peer_pricing"],
        platforms=["zhihu"],
    )
    peer = build_peer_collect_config(config, plan, max_contents=5, max_comments=8)
    assert peer.taxonomy_enabled is False
    assert peer.taxonomy_keywords == {}
    assert peer.keywords == {}
    assert set(peer.platform_keywords) == {"zhihu"}
    values = list(peer.platform_keywords["zhihu"].values())
    assert "微吼 价格" in values
    assert "小鹅通 价格" in values
    assert peer.max_contents == 5
    assert peer.max_comments == 8
    assert peer.platforms == ["zhihu"]
    assert peer.task_timeout_seconds == 180
