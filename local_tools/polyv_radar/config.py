from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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
    excluded_author_names: tuple[str, ...] = ()
    collector_backend: str = "native"
    platform_collectors: dict[str, str] = field(default_factory=dict)
    platform_workers: int = 1

    @property
    def category_by_keyword(self) -> dict[str, str]:
        mapping = {keyword: category for category, keyword in self.keywords.items()}
        for plat_map in self.platform_keywords.values():
            for category, keyword in plat_map.items():
                mapping[keyword] = category
        return mapping

    def get_keywords_for_platform(self, platform: str) -> dict[str, str]:
        if platform in self.platform_keywords:
            return self.platform_keywords[platform]
        return self.keywords

    def get_collector_for_platform(self, platform: str) -> str:
        return self.platform_collectors.get(platform, self.collector_backend)


def load_config(path: Path) -> RadarConfig:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)
    run = raw.get("run", {})
    keywords = {str(category): str(keyword) for category, keyword in raw.get("keywords", {}).items()}
    platform_keywords = {}
    for plat in ("dy", "xhs", "bili", "zhihu"):
        plat_section = raw.get(f"keywords_{plat}", {})
        if plat_section:
            platform_keywords[plat] = {str(k): str(v) for k, v in plat_section.items()}
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
        excluded_author_names=tuple(str(item) for item in raw.get("filters", {}).get("excluded_author_names", [])),
        collector_backend=str(run.get("collector_backend", "ego")),
        platform_collectors={str(k): str(v) for k, v in run.get("platform_collectors", {}).items()},
        platform_workers=max(1, int(run.get("platform_workers", 1))),
    )
