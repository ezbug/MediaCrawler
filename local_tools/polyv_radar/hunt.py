from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import RadarConfig
from .locator import locate_store, select_deliverable_leads
from .pipeline import enrich_store, prefilter_store, review_store
from .report import write_verified_lead_artifacts
from .runner import analyze_store, collect, ingest_existing_run, report_store
from .storage import RadarStore


LONG_TAIL_KEYWORDS = {
    "dy": {
        "第一人称培训询价": "我们公司 员工培训 平台 报价",
        "第一人称活动筹备": "我们公司 发布会 直播 平台",
        "老板找方案": "老板让我找 直播平台 报价",
        "活动人数与并发": "公司活动 3000人直播 平台支持并发",
    },
    "xhs": {
        "第一人称活动筹备": "我们公司 活动 直播 平台 报价",
        "第一人称培训选型": "我们公司 员工培训 平台",
        "安全需求": "公司课程 防下载 防录屏 平台",
        "接口需求": "公司APP 接入直播 SDK 报价",
    },
    "bili": {
        "第一人称并发项目": "我们公司 3000人 活动 平台 并发",
        "第一人称私有化": "我们公司 视频 私有化部署 项目报价",
        "培训交付": "公司员工培训平台 供应商 交付周期",
        "安全集成": "公司课程防盗录 加密播放器 API 集成",
    },
    "zhihu": {
        "第一人称预算报价": "我们公司 活动 平台 预算 报价",
        "项目周期": "我们公司下个月发布会 平台 服务商",
        "第一人称培训选型": "我们公司 员工培训平台 供应商",
        "并发接口": "公司直播平台 支持3000人 API 接入",
    },
}


def _with_long_tail(config: RadarConfig) -> RadarConfig:
    merged: dict[str, dict[str, str]] = {}
    remaining = 15
    for platform in config.platforms:
        if remaining <= 0:
            break
        values = LONG_TAIL_KEYWORDS.get(platform, {})
        selected = list(values.items())[:remaining]
        if selected:
            merged[platform] = dict(selected)
            remaining -= len(selected)
    return replace(config, platform_keywords=merged)


def _process_run(
    config: RadarConfig,
    repo_root: Path,
    run_id: str,
    collector: str,
    taskspace: int,
    max_candidates: int,
    codex: str,
    skip_crawl: bool,
) -> dict:
    if skip_crawl:
        ingest_existing_run(config, run_id)
    else:
        collect(config, repo_root, collector=collector, run_id=run_id, taskspace=taskspace)
    analyze_store(config, run_id)
    prefilter_store(config, run_id, max_candidates)
    enrichment = enrich_store(config, repo_root, run_id, taskspace=taskspace)
    review = review_store(config, run_id, codex=codex)
    locator = locate_store(config, repo_root, run_id, max_candidates, taskspace)
    report_path = report_store(config, run_id, f"hunt-{run_id.split('-')[-1] or 'wave'}", taskspace=taskspace)
    return {
        "run_id": run_id,
        "enrichment": enrichment,
        "review": review,
        "locator": locator,
        "report_path": str(report_path),
    }


def _has_completed_locator_stage(config: RadarConfig, run_id: str, max_candidates: int) -> bool:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads(run_id)
    locators = store.load_comment_locators(run_id)
    store.close()
    if not leads or not locators:
        return False
    eligible_count = min(max_candidates, sum(1 for lead in leads if lead.score >= config.min_lead_score and lead.decision != "reject"))
    return len(locators) >= eligible_count and all(item.get("status") not in {"pending", "error"} for item in locators)


def _reused_stage_result(config: RadarConfig, run_id: str) -> dict:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    locators = store.load_comment_locators(run_id)
    store.close()
    counts = {"candidates": len(locators), "verified": 0, "not_found": 0, "blocked": 0, "ambiguous": 0, "error": 0}
    for item in locators:
        status = str(item.get("status", "error"))
        counts[status] = int(counts.get(status, 0)) + 1
    return {
        "run_id": run_id,
        "enrichment": {"status": "reused"},
        "review": {"status": "reused"},
        "locator": counts,
        "report_path": str(config.data_root / "reports" / f"{run_id}.md"),
    }


def run_hunt(
    config: RadarConfig,
    repo_root: Path,
    collector: str = "ego",
    taskspace: int | None = None,
    target_leads: int = 20,
    max_candidates: int = 80,
    max_batches: int = 2,
    run_id: str | None = None,
    codex: str = "codex",
) -> dict:
    if collector != "ego":
        raise ValueError("hunt 为保护登录态，当前只允许使用 Ego Lite collector=ego")
    if taskspace is None or int(taskspace) <= 0:
        raise ValueError("hunt 必须显式传入 --taskspace；不使用固定会话")
    target_leads = max(0, int(target_leads))
    max_candidates = max(1, int(max_candidates))
    max_batches = max(1, min(2, int(max_batches)))
    first_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_ids: list[str] = []
    stage_results: list[dict] = []
    all_leads = []
    all_locators = []

    for wave in range(max_batches):
        current_run_id = first_run_id if wave == 0 else f"{first_run_id}-wave{wave + 1}"
        current_config = config if wave == 0 else _with_long_tail(config)
        if run_id and wave == 0 and _has_completed_locator_stage(current_config, current_run_id, max_candidates):
            result = _reused_stage_result(current_config, current_run_id)
        else:
            result = _process_run(
                current_config,
                repo_root,
                current_run_id,
                collector,
                taskspace,
                max_candidates,
                codex,
                skip_crawl=bool(run_id and wave == 0),
            )
        run_ids.append(current_run_id)
        stage_results.append(result)
        store = RadarStore(current_config.data_root / "radar.sqlite3")
        store.initialize()
        all_leads.extend(store.load_leads(current_run_id))
        all_locators.extend(store.load_comment_locators(current_run_id))
        store.close()
        selected = select_deliverable_leads(all_leads, target_leads, config.min_lead_score)
        if len(selected) >= target_leads:
            break

    selected = select_deliverable_leads(all_leads, target_leads, config.min_lead_score)
    artifacts = write_verified_lead_artifacts(
        config.data_root,
        first_run_id,
        selected,
        all_locators,
    )
    return {
        "run_id": first_run_id,
        "run_ids": run_ids,
        "target_leads": target_leads,
        "verified_count": len(selected),
        "candidate_count": len(all_leads),
        "stage_results": stage_results,
        "verified_report": str(artifacts["markdown"]),
        "verified_jsonl": str(artifacts["jsonl"]),
        "locator_checks": str(artifacts["locators"]),
    }
