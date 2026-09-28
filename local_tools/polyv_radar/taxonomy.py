from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


TAXONOMY_TIERS = (
    "tier1_primary",
    "tier2_verify_demand",
    "tier3_experimental",
)


@dataclass(frozen=True)
class TaxonomySnapshot:
    path: Path
    version: str
    updated_at: str
    search_formula: dict[str, Any]
    queries_by_tier: dict[str, tuple[str, ...]]
    scenes_by_tier: dict[str, tuple[str, ...]]
    intent_dimensions: dict[str, tuple[str, ...]]
    negative_terms: tuple[str, ...]
    business_scenarios: dict[str, dict[str, Any]]
    compliance_boundary: dict[str, Any]

    @property
    def query_count(self) -> int:
        return sum(len(values) for values in self.queries_by_tier.values())

    def query_map(self, tiers: Iterable[str] = TAXONOMY_TIERS) -> dict[str, str]:
        """Return stable labels mapped to normalized search text.

        Antigravity stores the three-part query with ``+`` separators. The
        platform search boxes receive the same query as whitespace-separated
        terms, while the original taxonomy snapshot remains unchanged.
        """
        result: dict[str, str] = {}
        for tier in tiers:
            if tier not in TAXONOMY_TIERS:
                raise ValueError(f"未知的 Antigravity 词库层级: {tier}")
            for index, raw_query in enumerate(self.queries_by_tier.get(tier, ()), start=1):
                query = normalize_query(raw_query)
                if not query:
                    continue
                result[f"taxonomy:{tier}:{index:02d}"] = query
        return result


def normalize_query(value: str) -> str:
    return re.sub(r"\s*\+\s*", " ", str(value or "")).strip()


def load_taxonomy(path: Path) -> TaxonomySnapshot:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    keyword_taxonomy = raw.get("keyword_taxonomy", {})
    queries_by_tier = {
        tier: tuple(str(item) for item in keyword_taxonomy.get(tier, {}).get("recommended_search_queries", []))
        for tier in TAXONOMY_TIERS
    }
    scenes_by_tier = {
        tier: tuple(str(item) for item in keyword_taxonomy.get(tier, {}).get("scenes", []))
        for tier in TAXONOMY_TIERS
    }
    intent_dimensions = {
        str(name): tuple(str(item) for item in values)
        for name, values in raw.get("intent_signal_dimensions", {}).items()
        if isinstance(values, list)
    }
    negative_terms = tuple(
        str(item) for item in raw.get("negative_filtering_keywords", {}).get("exclude_words", [])
    )
    scenarios = raw.get("six_core_business_scenarios", {})
    if not isinstance(scenarios, dict):
        scenarios = {}
    boundary = raw.get("compliance_and_truth_boundary", {})
    if not isinstance(boundary, dict):
        boundary = {}
    return TaxonomySnapshot(
        path=Path(path),
        version=str(raw.get("version", "")),
        updated_at=str(raw.get("updated_at", "")),
        search_formula=dict(raw.get("search_formula", {})),
        queries_by_tier=queries_by_tier,
        scenes_by_tier=scenes_by_tier,
        intent_dimensions=intent_dimensions,
        negative_terms=negative_terms,
        business_scenarios={str(key): dict(value) for key, value in scenarios.items() if isinstance(value, dict)},
        compliance_boundary=boundary,
    )
