from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RadarConfig:
    data_root: Path
    platforms: list[str]
    keywords: dict[str, str]
    login_type: str = "qrcode"
    max_contents: int = 10
    max_comments: int = 20
    concurrency: int = 1
    comments: bool = True
    sub_comments: bool = True
    task_timeout_seconds: int = 180

    @property
    def category_by_keyword(self) -> dict[str, str]:
        return {keyword: category for category, keyword in self.keywords.items()}


def load_config(path: Path) -> RadarConfig:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)
    run = raw.get("run", {})
    keywords = {str(category): str(keyword) for category, keyword in raw.get("keywords", {}).items()}
    return RadarConfig(
        data_root=Path(run.get("data_root", "polyv-radar-data")).expanduser(),
        platforms=[str(platform) for platform in run.get("platforms", ["dy", "xhs", "bili", "zhihu"])],
        keywords=keywords,
        login_type=str(run.get("login_type", "qrcode")),
        max_contents=int(run.get("max_contents", 10)),
        max_comments=int(run.get("max_comments", 20)),
        concurrency=int(run.get("concurrency", 1)),
        comments=bool(run.get("comments", True)),
        sub_comments=bool(run.get("sub_comments", True)),
        task_timeout_seconds=int(run.get("task_timeout_seconds", 180)),
    )
