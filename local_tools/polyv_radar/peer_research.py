"""同行调查查询计划（离线生成）。

把同行词库展开为可执行的查询计划：同行查找、同行价格、宣传与私信话术，
覆盖已部署的四个平台（dy/xhs/bili/zhihu）。本模块只做规划：不打开浏览器、
不访问网络、不写入平台；执行时复用现有 Ego Lite 采集入口。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SCHEMA = "polyv-peer-research"
PLAN_SCHEMA = "polyv-peer-research-plan"
PLAN_VERSION = "0.1.0"
DIRECTIONS = ("peer_discovery", "peer_pricing", "peer_promotion")
PLATFORMS = ("dy", "xhs", "bili", "zhihu")


def load_peer_taxonomy(path: Path) -> dict:
    """读取并校验同行调查词库。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"不是同行调查词库: {path}")
    directions = payload.get("directions") or {}
    unknown = sorted(set(directions) - set(DIRECTIONS))
    if unknown:
        raise ValueError("词库包含未知方向: " + ", ".join(unknown))
    competitors = payload.get("competitors") or []
    if not competitors:
        raise ValueError("词库缺少 competitors 品牌列表")
    if any(not item.get("brand") for item in competitors):
        raise ValueError("存在缺少 brand 的同行记录")
    return payload


def _ordered_selection(requested, allowed, label):
    if not requested:
        return list(allowed)
    unknown = sorted(set(requested) - set(allowed))
    if unknown:
        raise ValueError(f"未知{label}: {', '.join(unknown)}")
    wanted = set(requested)
    return [item for item in allowed if item in wanted]


def build_peer_plan(
    taxonomy: dict,
    *,
    brands: list[str] | None = None,
    directions: list[str] | None = None,
    platforms: list[str] | None = None,
    include_all_brands: bool = False,
    max_queries: int = 0,
    now: datetime | None = None,
) -> dict:
    """展开同行调查查询计划。默认只规划一级优先级品牌。"""
    direction_order = _ordered_selection(directions, DIRECTIONS, "方向")
    platform_order = _ordered_selection(platforms, PLATFORMS, "平台")

    competitors = list(taxonomy.get("competitors") or [])
    known_brands = {str(item["brand"]) for item in competitors}
    if brands:
        unknown = sorted(set(brands) - known_brands)
        if unknown:
            raise ValueError("未知同行品牌: " + ", ".join(unknown))
        wanted = set(brands)
        selected = [item for item in competitors if str(item["brand"]) in wanted]
        brand_scope = "explicit"
    elif include_all_brands:
        selected = competitors
        brand_scope = "all"
    else:
        selected = [item for item in competitors if int(item.get("priority", 1)) == 1]
        brand_scope = "priority1"

    definitions = taxonomy.get("directions") or {}
    queries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(query: str, *, brand, brand_category, direction: str, platform: str, template: str) -> None:
        text = " ".join(str(query).split())
        if not text:
            return
        key = (platform, text)
        if key in seen:
            return
        seen.add(key)
        queries.append(
            {
                "query": text,
                "brand": brand,
                "brand_category": brand_category,
                "direction": direction,
                "platform": platform,
                "template": template,
            }
        )

    for direction in direction_order:
        definition = definitions.get(direction) or {}
        for competitor in selected:
            brand = str(competitor["brand"])
            for template in definition.get("templates") or []:
                text = str(template).replace("{brand}", brand)
                for platform in platform_order:
                    add(
                        text,
                        brand=brand,
                        brand_category=competitor.get("category"),
                        direction=direction,
                        platform=platform,
                        template=str(template),
                    )
        for template in definition.get("category_templates") or []:
            for platform in platform_order:
                add(
                    str(template),
                    brand=None,
                    brand_category=None,
                    direction=direction,
                    platform=platform,
                    template=str(template),
                )

    truncated = False
    if max_queries and max_queries > 0 and len(queries) > max_queries:
        queries = queries[:max_queries]
        truncated = True

    primary_template = None
    discovery_templates = (definitions.get("peer_discovery") or {}).get("templates") or []
    if discovery_templates:
        primary_template = str(discovery_templates[0])
    first_batch: list[dict] = []
    for query in queries:
        if len(first_batch) >= 12:
            break
        if query["direction"] != "peer_discovery" or query["platform"] not in ("dy", "xhs"):
            continue
        if primary_template and query["template"] != primary_template:
            continue
        first_batch.append(query)
    if not first_batch:
        first_batch = queries[:12]

    moment = now or datetime.now()
    plan_id = moment.strftime("peer-plan-%Y%m%d-%H%M%S")
    stats = {
        "queries": len(queries),
        "brands": len(selected),
        "by_direction": {key: sum(1 for query in queries if query["direction"] == key) for key in direction_order},
        "by_platform": {key: sum(1 for query in queries if query["platform"] == key) for key in platform_order},
        "by_brand": {
            str(item["brand"]): sum(1 for query in queries if query["brand"] == str(item["brand"]))
            for item in selected
        },
    }
    return {
        "schema": PLAN_SCHEMA,
        "schema_version": PLAN_VERSION,
        "plan_id": plan_id,
        "generated_at": moment.isoformat(timespec="seconds"),
        "source_taxonomy": {
            "version": taxonomy.get("version"),
            "updated_at": taxonomy.get("updated_at"),
        },
        "filters": {
            "brands": [str(item["brand"]) for item in selected],
            "brand_scope": brand_scope,
            "directions": direction_order,
            "platforms": platform_order,
            "max_queries": max_queries,
            "truncated": truncated,
        },
        "direction_labels": {key: (definitions.get(key) or {}).get("name", key) for key in direction_order},
        "stats": stats,
        "recommended_first_batch": first_batch,
        "queries": queries,
        "evidence_rules": taxonomy.get("evidence_rules") or {},
        "compliance": taxonomy.get("compliance") or {},
    }


def render_peer_plan_markdown(plan: dict) -> str:
    """把查询计划渲染成便于人工审阅的 Markdown。"""
    labels = plan.get("direction_labels") or {}
    lines = [
        f"# 同行调查查询计划 {plan['plan_id']}",
        "",
        f"- 生成时间：{plan['generated_at']}",
        f"- 品牌范围：{plan['filters']['brand_scope']}（{len(plan['filters']['brands'])} 个品牌）",
        f"- 查询总数：{plan['stats']['queries']}",
        "",
        "## 推荐首批（最多 12 条）",
        "",
    ]
    for query in plan["recommended_first_batch"]:
        lines.append(f"- {query['platform']} | {query['query']}")
    lines.extend(["", "## 全部查询", ""])
    for direction in plan["filters"]["directions"]:
        lines.append(f"### {labels.get(direction, direction)}（{direction}）")
        lines.append("")
        lines.append("| 平台 | 查询 | 品牌 |")
        lines.append("| --- | --- | --- |")
        for query in plan["queries"]:
            if query["direction"] != direction:
                continue
            brand = query["brand"] or "-"
            lines.append(f"| {query['platform']} | {query['query']} | {brand} |")
        lines.append("")
    rules = plan.get("evidence_rules") or {}
    if rules:
        lines.append("## 证据规则")
        lines.append("")
        for key, items in rules.items():
            for item in items:
                lines.append(f"- [{key}] {item}")
        lines.append("")
    compliance = plan.get("compliance") or {}
    forbidden = compliance.get("forbidden") or []
    if forbidden:
        lines.append("## 合规红线")
        lines.append("")
        for item in forbidden:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_peer_plan(plan: dict, output_dir: Path) -> dict[str, Path]:
    """写入 JSON 与 Markdown 两份计划文件，返回路径。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{plan['plan_id']}.json"
    markdown_path = output_dir / f"{plan['plan_id']}.md"
    json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_peer_plan_markdown(plan), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
