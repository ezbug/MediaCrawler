from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .taxonomy import TAXONOMY_TIERS, TaxonomySnapshot, load_taxonomy


@dataclass(frozen=True)
class RadarConfig:
    data_root: Path
    platforms: list[str]
    keywords: dict[str, str]
    platform_keywords: dict[str, dict[str, str]] = field(default_factory=dict)
    login_type: str = "qrcode"
    max_contents: int = 10
    max_comments: int = 20
    concurrency: int = 1
    comments: bool = True
    sub_comments: bool = True
    task_timeout_seconds: int = 180
    min_lead_score: int = 4
    recent_days: int = 90
    max_lead_age_days: int = 730
    excluded_author_names: tuple[str, ...] = ()
    collector_backend: str = "ego"
    platform_collectors: dict[str, str] = field(default_factory=dict)
    platform_workers: int = 1
    taxonomy_enabled: bool = False
    taxonomy_tiers: tuple[str, ...] = ()
    taxonomy_snapshot: TaxonomySnapshot | None = None
    taxonomy_keywords: dict[str, str] = field(default_factory=dict)
    taxonomy_negative_terms: tuple[str, ...] = ()
    taxonomy_intent_terms: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def category_by_keyword(self) -> dict[str, str]:
        mapping = {keyword: category for category, keyword in self.keywords.items()}
        for platform in self.platforms:
            for category, keyword in self.get_keywords_for_platform(platform).items():
                mapping[keyword] = category
        return mapping

    def get_keywords_for_platform(self, platform: str) -> dict[str, str]:
        merged = dict(self.platform_keywords.get(platform, self.keywords))
        if self.taxonomy_enabled and self.taxonomy_keywords:
            existing_queries = set(merged.values())
            for category, query in self.taxonomy_keywords.items():
                if query not in existing_queries:
                    merged[category] = query
                    existing_queries.add(query)
        return merged

    def get_collector_for_platform(self, platform: str) -> str:
        return self.platform_collectors.get(platform, self.collector_backend)


def load_config(path: Path) -> RadarConfig:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    run = raw.get("run", {})
    keywords = {str(category): str(keyword) for category, keyword in raw.get("keywords", {}).items()}
    platform_keywords = {}
    for plat in ("dy", "xhs", "bili", "zhihu"):
        plat_section = raw.get(f"keywords_{plat}", {})
        if plat_section:
            platform_keywords[plat] = {str(k): str(v) for k, v in plat_section.items()}
    collector_backend = str(run.get("collector_backend", "ego"))
    platform_collectors = {str(k): str(v) for k, v in run.get("platform_collectors", {}).items()}
    invalid_collectors = sorted(
        {value for value in (collector_backend, *platform_collectors.values()) if value != "ego"}
    )
    if invalid_collectors:
        raise ValueError(
            "POLYV 雷达的页面操作只能使用 Ego Lite collector=ego；"
            f"不支持: {', '.join(invalid_collectors)}"
        )

    taxonomy_enabled = bool(run.get("taxonomy_enabled", True))
    taxonomy_path_value = run.get("taxonomy_path")
    if taxonomy_path_value:
        taxonomy_path = Path(str(taxonomy_path_value)).expanduser()
        if not taxonomy_path.is_absolute():
            config_relative = config_path.parent / taxonomy_path
            taxonomy_path = config_relative if config_relative.exists() else Path.cwd() / taxonomy_path
    else:
        taxonomy_path = Path(__file__).with_name("polyv_radar_keyword_taxonomy.json")
    taxonomy_snapshot = load_taxonomy(taxonomy_path) if taxonomy_enabled else None
    raw_tiers = run.get("taxonomy_tiers", list(TAXONOMY_TIERS))
    taxonomy_tiers = tuple(str(item) for item in raw_tiers)
    unknown_tiers = sorted(set(taxonomy_tiers) - set(TAXONOMY_TIERS))
    if unknown_tiers:
        raise ValueError(f"未知的 Antigravity 词库层级: {', '.join(unknown_tiers)}")
    taxonomy_keywords = taxonomy_snapshot.query_map(taxonomy_tiers) if taxonomy_snapshot else {}
    taxonomy_negative_terms = taxonomy_snapshot.negative_terms if taxonomy_snapshot else ()
    taxonomy_intent_terms = taxonomy_snapshot.intent_dimensions if taxonomy_snapshot else {}
    return RadarConfig(
        data_root=Path(run.get("data_root", "polyv-radar-data")).expanduser(),
        platforms=[str(platform) for platform in run.get("platforms", ["dy", "xhs", "bili", "zhihu"])],
        keywords=keywords,
        platform_keywords=platform_keywords,
        login_type=str(run.get("login_type", "qrcode")),
        max_contents=int(run.get("max_contents", 10)),
        max_comments=int(run.get("max_comments", 20)),
        concurrency=int(run.get("concurrency", 1)),
        comments=bool(run.get("comments", True)),
        sub_comments=bool(run.get("sub_comments", True)),
        task_timeout_seconds=int(run.get("task_timeout_seconds", 180)),
        min_lead_score=int(run.get("min_lead_score", 4)),
        recent_days=max(1, int(run.get("recent_days", 90))),
        max_lead_age_days=max(1, int(run.get("max_lead_age_days", 730))),
        excluded_author_names=tuple(str(item) for item in raw.get("filters", {}).get("excluded_author_names", [])),
        collector_backend=collector_backend,
        platform_collectors=platform_collectors,
        platform_workers=max(1, int(run.get("platform_workers", 1))),
        taxonomy_enabled=taxonomy_enabled,
        taxonomy_tiers=taxonomy_tiers,
        taxonomy_snapshot=taxonomy_snapshot,
        taxonomy_keywords=taxonomy_keywords,
        taxonomy_negative_terms=taxonomy_negative_terms,
        taxonomy_intent_terms=taxonomy_intent_terms,
    )
