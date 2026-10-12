"""职位去重分组与状态标签。

- dedupe_jobs：同公司 + 同城市 + 标题相似度达阈值 → 合并为一个独立招聘需求组
  （job_dedup_group），招聘人数按“组内各来源最大值”聚合，不做简单相加。
- label_jobs：按在招时长与文本特征打风险标签（不删除记录）。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from difflib import SequenceMatcher

from .metrics import job_staleness_label

PUNCTUATION = re.compile(r"[\s（）()【】\[\]/、，,·\-—_]+")
OUTSOURCING_HINTS = ("外包", "驻场", "派遣", "劳务", "兼职", "实习中介")


def normalize_title(title: str) -> str:
    return PUNCTUATION.sub("", str(title or "").lower())


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _group_id(company_id: str, city: str, normalized_title: str) -> str:
    digest = hashlib.sha1(f"{company_id}|{city}|{normalized_title}".encode("utf-8")).hexdigest()[:14]
    return f"g-{digest}"


def dedupe_jobs(store, company_id: str, threshold: float = 0.85) -> dict:
    rows = [dict(row) for row in store.connection.execute(
        """
        SELECT * FROM job_listing_snapshot
        WHERE company_id = ? AND (job_status IS NULL OR job_status != 'CLOSED_OR_UNAVAILABLE')
        """,
        (company_id,),
    )]
    clusters: list[dict] = []
    for row in rows:
        norm = normalize_title(row.get("job_title"))
        city = str(row.get("city") or "").strip()
        target = None
        for cluster in clusters:
            if cluster["city"] != city:
                continue
            if title_similarity(norm, cluster["normalized_title"]) >= threshold:
                target = cluster
                break
        if target is None:
            clusters.append({"normalized_title": norm, "city": city, "jobs": [row]})
        else:
            target["jobs"].append(row)

    stamp = datetime.now().isoformat(timespec="seconds")
    groups_created = 0
    for cluster in clusters:
        group_id = _group_id(company_id, cluster["city"], cluster["normalized_title"])
        counts = {row["platform"]: row["recruitment_count"] for row in cluster["jobs"] if row.get("recruitment_count") is not None}
        deduped_count = max(counts.values()) if counts else None
        similarities = [
            title_similarity(cluster["normalized_title"], normalize_title(row.get("job_title")))
            for row in cluster["jobs"][1:]
        ]
        confidence = min(similarities) if similarities else 1.0
        count_confidence = "none"
        if counts:
            count_confidence = "single_source" if len(counts) == 1 else ("consistent" if len(set(counts.values())) == 1 else "mixed")
        store.connection.execute(
            """
            INSERT INTO job_dedup_group (
              dedup_group_id, company_id, normalized_title, location_scope, source_job_ids,
              recruitment_count_deduped, recruitment_count_raw_by_source, recruitment_count_confidence,
              recruitment_count_aggregation_method, dedup_confidence, review_status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(dedup_group_id) DO UPDATE SET
              normalized_title=excluded.normalized_title,
              location_scope=excluded.location_scope,
              source_job_ids=excluded.source_job_ids,
              recruitment_count_deduped=excluded.recruitment_count_deduped,
              recruitment_count_raw_by_source=excluded.recruitment_count_raw_by_source,
              recruitment_count_confidence=excluded.recruitment_count_confidence,
              recruitment_count_aggregation_method=excluded.recruitment_count_aggregation_method,
              dedup_confidence=excluded.dedup_confidence,
              review_status=excluded.review_status,
              updated_at=excluded.updated_at
            """,
            (
                group_id, company_id, cluster["normalized_title"], cluster["city"],
                json.dumps([row["snapshot_id"] for row in cluster["jobs"]], ensure_ascii=False),
                deduped_count, json.dumps(counts, ensure_ascii=False), count_confidence,
                "max_of_sources" if counts else "none", round(confidence, 4),
                "auto" if confidence >= 0.95 else "pending", stamp, stamp,
            ),
        )
        for row in cluster["jobs"]:
            store.connection.execute(
                "UPDATE job_listing_snapshot SET dedup_group_id = ? WHERE snapshot_id = ?",
                (group_id, row["snapshot_id"]),
            )
        groups_created += 1
    store.connection.commit()
    return {"company_id": company_id, "jobs": len(rows), "groups": groups_created, "threshold": threshold}


def label_jobs(store, company_id: str, stat_date: str) -> dict:
    rows = [dict(row) for row in store.connection.execute(
        "SELECT * FROM job_listing_snapshot WHERE company_id = ?", (company_id,)
    )]
    today = datetime.strptime(stat_date, "%Y-%m-%d")
    labels: dict[str, int] = {}
    for row in rows:
        age_days = None
        seen = str(row.get("first_seen_at") or "")[:10]
        if seen:
            try:
                age_days = (today - datetime.strptime(seen, "%Y-%m-%d")).days
            except ValueError:
                age_days = None
        text = f"{row.get('job_title') or ''}{row.get('raw_hiring_text') or ''}"
        label = job_staleness_label(
            age_days=age_days,
            times_seen=2 if (row.get("updated_at") or "") != (row.get("created_at") or "") else 1,
            outsourcing_hint=any(hint in text for hint in OUTSOURCING_HINTS),
            closed=(row.get("job_status") or "") == "CLOSED_OR_UNAVAILABLE",
        )
        store.connection.execute(
            "UPDATE job_listing_snapshot SET staleness_label = ? WHERE snapshot_id = ?",
            (label, row["snapshot_id"]),
        )
        labels[label] = labels.get(label, 0) + 1
    store.connection.commit()
    return {"company_id": company_id, "stat_date": stat_date, "labels": labels}
