"""批量招聘强度采集：对多个目标公司跑 采集→入库→去重→标签→指标，并生成对比报告。"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .job_collect import PLATFORM_URLS, collect_jobs
from .job_dedup import dedupe_jobs, label_jobs

DEFAULT_PAGES = {"boss": "p1", "liepin": "p2", "zhaopin": "p3"}


def parse_target(name: str) -> dict:
    """把品牌名转成批次目标（company_id 使用 brand- 前缀，标注身份未核验）。"""
    clean = name.strip()
    if not clean:
        raise ValueError("目标公司名不能为空")
    slug = re.sub(r"[\s/]+", "", clean)
    return {
        "company_id": f"brand-{slug}",
        "company_name": clean,
        "query": clean,
        "employer_filter": clean,
    }


def run_hiring_batch(
    store,
    targets: list[dict],
    *,
    taskspace: int,
    platforms: list[str],
    pages: dict[str, str] | None = None,
    max_jobs: int = 20,
    stat_date: str | None = None,
    output: Path | None = None,
    collector=None,
) -> dict:
    collect = collector or collect_jobs
    pages = {**DEFAULT_PAGES, **(pages or {})}
    stat_date = stat_date or datetime.now().strftime("%Y-%m-%d")
    results = []
    for target in targets:
        store.upsert_company({
            "company_id": target["company_id"],
            "company_name": target["company_name"],
            "identity_match_status": "brand_unverified",
        })
        per_platform: dict[str, dict] = {}
        for platform in platforms:
            template = PLATFORM_URLS.get(f"{platform}-search")
            entry: dict = {"url": None}
            if not template:
                entry["error"] = f"没有 {platform} 的搜索模板"
                per_platform[platform] = entry
                continue
            from urllib.parse import quote

            url = template.format(query=quote(target["query"]))
            entry["url"] = url
            try:
                payload = collect(
                    company_id=target["company_id"], url=url, taskspace=taskspace,
                    platform=platform, page=pages.get(platform, "p1"),
                    max_jobs=max_jobs, employer_filter=target.get("employer_filter", ""),
                )
                added = store.add_jobs(target["company_id"], payload["jobs"])
                entry.update({"collected": len(payload["jobs"]), **added,
                              "warnings": payload["_extraction"].get("warnings", [])})
            except Exception as exc:  # noqa: BLE001 - 批量任务记录错误继续
                entry["error"] = str(exc)[:200]
            per_platform[platform] = entry
        dedupe_jobs(store, target["company_id"])
        label_jobs(store, target["company_id"], stat_date)
        metrics = store.compute_hiring_metrics(target["company_id"], stat_date)
        top_jobs = [dict(row)["job_title"] for row in store.connection.execute(
            """
            SELECT job_title FROM job_listing_snapshot
            WHERE company_id = ? AND (job_status IS NULL OR job_status = 'active')
            ORDER BY first_seen_at DESC LIMIT 8
            """,
            (target["company_id"],),
        )]
        results.append({"target": target, "platforms": per_platform, "metrics": metrics, "top_jobs": top_jobs})
    report = render_report(results, stat_date, platforms)
    if output:
        Path(output).write_text(report + "\n", encoding="utf-8")
    return {"stat_date": stat_date, "targets": len(targets), "results": results, "report": str(output) if output else None}


def render_report(results: list[dict], stat_date: str, platforms: list[str]) -> str:
    header = "| 公司 | 活跃职位 | 独立需求组 | 平台覆盖 | 招聘活动指数 | " + " | ".join(platforms) + " |"
    divider = "| --- | --- | --- | --- | --- | " + " | ".join("---" for _ in platforms) + " |"
    lines = [
        f"# 同行招聘强度对比（{stat_date}）",
        "",
        "口径：招聘平台公开职位；活跃职位=在招记录，独立需求组=去重后的招聘需求；",
        "招聘活动指数为 0-100 规则分（新增职位/明确人数/近期活跃/平台覆盖/职能多样性），不代表真实招聘人数。",
        "",
        header,
        divider,
    ]
    for item in results:
        metrics = item["metrics"]
        cells = [
            item["target"]["company_name"],
            str(metrics.get("active_job_count")),
            str(metrics.get("unique_job_count")),
            str(metrics.get("multi_platform_presence")),
            str(metrics.get("hiring_activity_score")),
        ]
        for platform in platforms:
            entry = item["platforms"].get(platform) or {}
            if entry.get("error"):
                cells.append("错误")
            else:
                cells.append(str(entry.get("collected", 0)))
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## 各公司职位样本", ""])
    for item in results:
        lines.append(f"### {item['target']['company_name']}")
        lines.append("")
        if item["top_jobs"]:
            for title in item["top_jobs"]:
                lines.append(f"- {title}")
        else:
            lines.append("- 无")
        warnings = [w for entry in item["platforms"].values() for w in (entry.get("warnings") or [])]
        if warnings:
            lines.append(f"- 数据提示：{'；'.join(sorted(set(warnings))[:3])}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .storage import EnterpriseStore

    parser = argparse.ArgumentParser(description="批量招聘强度采集（Ego Lite，只读）")
    parser.add_argument("--db", required=True)
    parser.add_argument("--taskspace", type=int, required=True)
    parser.add_argument("--target", action="append", required=True, help="目标公司名，可重复")
    parser.add_argument("--platform", action="append", help="平台：liepin/boss/zhaopin，可重复；默认 liepin")
    parser.add_argument("--max-jobs", type=int, default=20)
    parser.add_argument("--stat-date", default="")
    parser.add_argument("--output", required=True, help="对比报告 Markdown 输出路径")
    args = parser.parse_args(argv)

    store = EnterpriseStore(args.db)
    try:
        payload = run_hiring_batch(
            store,
            [parse_target(name) for name in args.target],
            taskspace=args.taskspace,
            platforms=[p.lower() for p in (args.platform or ["liepin"])],
            max_jobs=args.max_jobs,
            stat_date=args.stat_date or None,
            output=Path(args.output),
        )
    finally:
        store.close()
    summary = {
        "stat_date": payload["stat_date"],
        "report": payload["report"],
        "companies": [
            {
                "name": item["target"]["company_name"],
                "active_jobs": item["metrics"].get("active_job_count"),
                "unique_jobs": item["metrics"].get("unique_job_count"),
                "platforms": item["metrics"].get("multi_platform_presence"),
                "score": item["metrics"].get("hiring_activity_score"),
            }
            for item in payload["results"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
