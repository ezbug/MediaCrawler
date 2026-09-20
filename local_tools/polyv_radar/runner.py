from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .adapters import normalize_comment, normalize_content
from .config import RadarConfig
from .models import CommentRecord, ContentRecord, LeadEvidence
from .report import render_report, write_report, write_verified_lead_artifacts
from .scoring import score_lead
from .storage import RadarStore
from .url_validation import dump_url_checks, validate_urls_with_ego
from .workflow import load_workflow_run


@dataclass
class CollectionResult:
    run_id: str
    store_path: Path
    platform_status: dict[str, dict]
    failures: dict[str, str]


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", value.strip())
    return re.sub(r"\s+", " ", value).strip(" .")[:80] or "未命名"


def build_crawl_command(
    repo_root: str | Path,
    platform: str,
    keyword: str,
    output_dir: str | Path,
    max_contents: int,
    max_comments: int,
    login_type: str = "qrcode",
    concurrency: int = 1,
    comments: bool = True,
    sub_comments: bool = True,
) -> list[str]:
    return [
        "uv",
        "run",
        "main.py",
        "--platform",
        platform,
        "--lt",
        login_type,
        "--type",
        "search",
        "--keywords",
        keyword,
        "--crawler_max_notes_count",
        str(max_contents),
        "--max_concurrency_num",
        str(concurrency),
        "--get_comment",
        "true" if comments else "false",
        "--get_sub_comment",
        "true" if sub_comments else "false",
        "--max_comments_count_singlenotes",
        str(max_comments),
        "--save_data_option",
        "jsonl",
        "--save_data_path",
        str(Path(output_dir).resolve()),
        "--enable_ip_proxy",
        "false",
    ]


def _crawler_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = ""
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def _read_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _output_status(
    output_dir: Path,
    platform: str,
    keyword: str,
    store: RadarStore,
    max_contents: int | None = None,
    max_comments: int | None = None,
    run_id: str | None = None,
) -> tuple[int, int]:
    return _ingest_output(output_dir, platform, keyword, store, max_contents, max_comments, run_id)


def _source_keyword(row: dict, fallback: str) -> str:
    value = row.get("source_keyword") or row.get("sourceKeyword") or fallback
    return str(value or fallback)


def _limit_by_source(rows: list[dict], limit: int | None, fallback: str) -> list[dict]:
    if limit is None:
        return rows
    counts: dict[str, int] = {}
    limited: list[dict] = []
    for row in rows:
        source = _source_keyword(row, fallback)
        if counts.get(source, 0) >= limit:
            continue
        counts[source] = counts.get(source, 0) + 1
        limited.append(row)
    return limited


def _ingest_output_details(
    output_dir: Path,
    platform: str,
    keyword: str,
    store: RadarStore,
    max_contents: int | None = None,
    max_comments: int | None = None,
    run_id: str | None = None,
) -> dict:
    content_rows: list[dict] = []
    comment_rows: list[dict] = []
    for path in sorted(output_dir.rglob("*.jsonl")):
        name = path.name.lower()
        if "comment" in name:
            comment_rows.extend(_read_jsonl(path))
        elif "content" in name or "video" in name or "note" in name:
            content_rows.extend(_read_jsonl(path))

    content_rows = _limit_by_source(content_rows, max_contents, keyword)
    contents = [
        item
        for item in (
            normalize_content(platform, row, _source_keyword(row, keyword))
            for row in content_rows
        )
        if item
    ]
    content_source_by_id = {item.content_id: item.source_keywords[0] for item in contents if item.source_keywords}
    if max_comments is not None:
        comment_counts: dict[str, int] = {}
        limited_comments: list[dict] = []
        for row in comment_rows:
            content_id = str(row.get("aweme_id") or row.get("note_id") or row.get("video_id") or row.get("content_id") or "")
            source = _source_keyword(row, content_source_by_id.get(content_id, keyword))
            count_key = f"{source}\x1f{content_id}"
            if comment_counts.get(count_key, 0) >= max_comments:
                continue
            comment_counts[count_key] = comment_counts.get(count_key, 0) + 1
            limited_comments.append(row)
        comment_rows = limited_comments
    comments = [
        item
        for item in (
            normalize_comment(
                platform,
                row,
                source_keyword=_source_keyword(
                    row,
                    content_source_by_id.get(
                        str(row.get("aweme_id") or row.get("note_id") or row.get("video_id") or row.get("content_id") or ""),
                        keyword,
                    ),
                ),
            )
            for row in comment_rows
        )
        if item
    ]
    unique_contents = {(item.platform, item.content_id): item for item in contents}
    unique_comments = {(item.platform, item.comment_id): item for item in comments}
    for content in unique_contents.values():
        store.upsert_content(content, run_id=run_id)
    for comment in unique_comments.values():
        store.upsert_comment(comment, run_id=run_id)

    by_keyword: dict[str, dict[str, int]] = {}
    for row in content_rows:
        source = _source_keyword(row, keyword)
        item = by_keyword.setdefault(source, {"raw_contents": 0, "raw_comments": 0, "dedup_contents": 0, "dedup_comments": 0})
        item["raw_contents"] += 1
    for row in comment_rows:
        content_id = str(row.get("aweme_id") or row.get("note_id") or row.get("video_id") or row.get("content_id") or "")
        source = _source_keyword(row, content_source_by_id.get(content_id, keyword))
        item = by_keyword.setdefault(source, {"raw_contents": 0, "raw_comments": 0, "dedup_contents": 0, "dedup_comments": 0})
        item["raw_comments"] += 1
    for item in unique_contents.values():
        source = item.source_keywords[0] if item.source_keywords else keyword
        by_keyword.setdefault(source, {"raw_contents": 0, "raw_comments": 0, "dedup_contents": 0, "dedup_comments": 0})["dedup_contents"] += 1
    for item in unique_comments.values():
        by_keyword.setdefault(item.source_keyword or keyword, {"raw_contents": 0, "raw_comments": 0, "dedup_contents": 0, "dedup_comments": 0})["dedup_comments"] += 1
    return {
        "raw_contents": len(content_rows),
        "raw_comments": len(comment_rows),
        "dedup_contents": len(unique_contents),
        "dedup_comments": len(unique_comments),
        "by_keyword": by_keyword,
    }


def _ingest_output(
    output_dir: Path,
    platform: str,
    keyword: str,
    store: RadarStore,
    max_contents: int | None = None,
    max_comments: int | None = None,
    run_id: str | None = None,
) -> tuple[int, int]:
    details = _ingest_output_details(output_dir, platform, keyword, store, max_contents, max_comments, run_id)
    return details["dedup_contents"], details["dedup_comments"]


def _task_record(
    run_id: str,
    platform: str,
    keyword: str,
    backend: str,
    started: datetime,
    finished: datetime,
    stats: dict | None = None,
    status: str = "success",
    error: str = "",
    fallback_backend: str = "",
    fallback_reason: str = "",
) -> dict:
    stats = stats or {}
    return {
        "run_id": run_id,
        "platform": platform,
        "keyword": keyword,
        "backend": backend,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": max(0.0, (finished - started).total_seconds()),
        "raw_contents": stats.get("raw_contents", 0),
        "raw_comments": stats.get("raw_comments", 0),
        "dedup_contents": stats.get("dedup_contents", 0),
        "dedup_comments": stats.get("dedup_comments", 0),
        "status": status,
        "error": error[-500:],
        "fallback_backend": fallback_backend,
        "fallback_reason": fallback_reason[-500:],
    }


def _save_run(store: RadarStore, run_id: str, started: datetime, platform_status: dict, failures: dict[str, str]) -> None:
    final_status = "success" if not failures else "partial"
    store.save_run(run_id, final_status, platform_status, started.isoformat(), datetime.now(timezone.utc).isoformat())


def _collect_native(
    config: RadarConfig,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
    run_id: str,
) -> CollectionResult:
    started_run = datetime.now(timezone.utc)
    raw_root = config.data_root / "raw" / run_id
    store_path = config.data_root / "radar.sqlite3"
    store = RadarStore(store_path)
    store.initialize()
    platform_status: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for platform in config.platforms:
        status = {"status": "success", "contents": 0, "comments": 0, "tasks": 0}
        keywords = list(config.get_keywords_for_platform(platform).values())
        status["tasks"] = len(keywords)
        if not keywords:
            platform_status[platform] = {**status, "status": "not_run"}
            continue
        output_dir = raw_root / platform / "__native_batch__"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = build_crawl_command(
            repo_root,
            platform,
            ",".join(keywords),
            output_dir,
            config.max_contents,
            config.max_comments,
            config.login_type,
            config.concurrency,
            config.comments,
            config.sub_comments,
        )
        task_started = datetime.now(timezone.utc)
        timed_out = False
        completed = None
        error = ""
        try:
            completed = runner(
                command,
                cwd=repo_root,
                env=_crawler_env(),
                capture_output=True,
                text=True,
                check=False,
                timeout=config.task_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            completed = subprocess.CompletedProcess(command, returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or "")
        except Exception as exc:
            completed = subprocess.CompletedProcess(command, returncode=1, stdout="", stderr=str(exc))
        finished = datetime.now(timezone.utc)
        log_prefix = f"任务超过 {config.task_timeout_seconds} 秒，保留已落盘数据并继续。\n" if timed_out else ""
        log_path = output_dir / "crawler.log"
        log_path.write_text(log_prefix + _as_text(getattr(completed, "stdout", "")) + "\n" + _as_text(getattr(completed, "stderr", "")), encoding="utf-8")
        try:
            details = _ingest_output_details(output_dir, platform, keywords[0], store, config.max_contents, config.max_comments, run_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            details = {"raw_contents": 0, "raw_comments": 0, "dedup_contents": 0, "dedup_comments": 0, "by_keyword": {}}
            error = f"输出解析失败: {exc}"
        status["contents"] = details["dedup_contents"]
        status["comments"] = details["dedup_comments"]
        returncode = int(getattr(completed, "returncode", 1))
        if timed_out:
            error = error or "任务超时，已保留部分数据"
        elif returncode != 0:
            error = error or _as_text(getattr(completed, "stderr", "") or getattr(completed, "stdout", "") or "退出码非零")
        if error:
            status["status"] = "partial"
            for keyword in keywords:
                failures[f"{platform}:{keyword}"] = error.strip()[-500:]
        for keyword in keywords:
            task_stats = details["by_keyword"].get(keyword, {})
            store.save_crawl_task(_task_record(run_id, platform, keyword, "native", task_started, finished, task_stats, "partial" if error else "success", error))
        platform_status[platform] = status
    _save_run(store, run_id, started_run, platform_status, failures)
    store.close()
    return CollectionResult(run_id, store_path, platform_status, failures)


def collect(
    config: RadarConfig,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    collector: str | None = None,
    run_id: str | None = None,
    taskspace: int | None = None,
) -> CollectionResult:
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    selected_modes = {
        platform: (collector or config.get_collector_for_platform(platform))
        for platform in config.platforms
    }
    invalid = sorted({value for value in selected_modes.values() if value != "ego"})
    if invalid:
        raise ValueError(
            "POLYV 雷达的页面操作只能使用 Ego Lite collector=ego；"
            f"不支持: {', '.join(invalid)}"
        )

    from .ego_crawl_all import run_ego_crawlers

    if taskspace is None or int(taskspace) <= 0:
        raise ValueError("collect 必须显式传入 --taskspace；所有浏览器操作统一使用用户提供的 Ego Lite 会话")

    started = datetime.now(timezone.utc)
    results = run_ego_crawlers(run_id, config.platforms, config, repo_root, config.data_root, int(taskspace))
    finished = datetime.now(timezone.utc)
    result = ingest_existing_run(config, run_id)
    store = RadarStore(result.store_path)
    store.initialize()
    workflow = load_workflow_run(config.data_root, run_id)
    workflow_tasks = [
        task
        for platform in (workflow or {}).get("platforms", [])
        for task in platform.get("tasks", [])
        if isinstance(task, dict)
    ]
    if workflow_tasks:
        for task in workflow_tasks:
            task_started = datetime.fromisoformat(str(task["started_at"]))
            task_finished = datetime.fromisoformat(str(task["finished_at"]))
            store.save_crawl_task(
                _task_record(
                    run_id,
                    str(task.get("platform", "")),
                    str(task.get("keyword", "")),
                    "ego",
                    task_started,
                    task_finished,
                    task,
                    "success" if task.get("status") == "success" else "partial",
                    str(task.get("error", "")),
                )
            )
    else:
        for platform, success in results.items():
            for keyword in config.get_keywords_for_platform(platform).values():
                store.save_crawl_task(
                    _task_record(
                        run_id,
                        platform,
                        keyword,
                        "ego",
                        started,
                        finished,
                        status="success" if success else "partial",
                        error="" if success else "Ego任务失败",
                    )
                )
    store.close()
    return result


def ingest_existing_run(
    config: RadarConfig,
    run_id: str,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> CollectionResult:
    """Recover JSONL already written by an interrupted or timed-out collection."""
    raw_root = config.data_root / "raw" / run_id
    store_path = config.data_root / "radar.sqlite3"
    store = RadarStore(store_path)
    store.initialize()
    platform_status: dict[str, dict] = {}
    failures: dict[str, str] = {}
    store.clear_run_links(run_id)
    for platform in config.platforms:
        status = {"status": "not_run", "contents": 0, "comments": 0, "tasks": 0}
        platform_root = raw_root / platform
        if platform_root.exists():
            keywords = list((config.get_keywords_for_platform(platform) if hasattr(config, "get_keywords_for_platform") else config.keywords).values())
            details = _ingest_output_details(
                platform_root,
                platform,
                keywords[0] if keywords else "",
                store,
                config.max_contents,
                config.max_comments,
                run_id,
            )
            status["contents"] = details["dedup_contents"]
            status["comments"] = details["dedup_comments"]
            status["tasks"] = len(details["by_keyword"]) or (1 if list(platform_root.rglob("*.jsonl")) else 0)
        if status["tasks"] and status["contents"]:
            status["status"] = "success"
        if status["tasks"] and not status["contents"]:
            status["status"] = "partial"
            failures[platform] = "任务被中断或未完成，已恢复已落盘数据"
        platform_status[platform] = status
    existing_run = store.connection.execute(
        "SELECT started_at, finished_at FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    preserved_started_at = existing_run["started_at"] if existing_run and existing_run["started_at"] else now
    preserved_finished_at = existing_run["finished_at"] if existing_run and existing_run["finished_at"] else now
    final_status = "success" if all(item["status"] in {"success", "not_run"} for item in platform_status.values()) else "partial"
    store.save_run(
        run_id,
        final_status,
        platform_status,
        started_at or preserved_started_at,
        finished_at or preserved_finished_at,
    )
    store.close()
    return CollectionResult(run_id, store_path, platform_status, failures)


def analyze_records(
    contents: Iterable[ContentRecord],
    comments: Iterable[CommentRecord],
    now: datetime | None = None,
    category_by_keyword: dict[str, str] | None = None,
    min_score: int = 4,
    recent_days: int = 90,
) -> list[LeadEvidence]:
    content_by_key = {(item.platform, item.content_id): item for item in contents}
    comments_by_content: dict[tuple[str, str], list[CommentRecord]] = {}
    for comment in comments:
        comments_by_content.setdefault((comment.platform, comment.content_id), []).append(comment)
    category_by_keyword = category_by_keyword or {}
    leads_by_key: dict[tuple[str, str, str, str], LeadEvidence] = {}
    for key, content in content_by_key.items():
        related_comments = comments_by_content.get(key, [])
        if related_comments:
            for comment in related_comments:
                category_hint = category_by_keyword.get(comment.source_keyword)
                lead = score_lead(content, comment, now, category_hint, recent_days)
                if lead.score >= min_score:
                    key = (lead.platform, lead.content_id, _text_key(lead.user), _text_key(lead.quote))
                    existing = leads_by_key.get(key)
                    if existing is None or lead.score > existing.score:
                        leads_by_key[key] = lead
        else:
            category_hint = category_by_keyword.get(content.source_keywords[0]) if content.source_keywords else None
            lead = score_lead(content, None, now, category_hint, recent_days)
            if lead.score >= min_score:
                key = (lead.platform, lead.content_id, _text_key(lead.user), _text_key(lead.quote))
                existing = leads_by_key.get(key)
                if existing is None or lead.score > existing.score:
                    leads_by_key[key] = lead
    return list(leads_by_key.values())


def _text_key(value: str) -> str:
    return "".join(str(value).casefold().split())


def write_review_queue(path: Path, leads: Iterable[LeadEvidence]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(lead.to_dict(), ensure_ascii=False) for lead in leads) + "\n",
        encoding="utf-8",
    )


def analyze_store(config: RadarConfig, run_id: str, now: datetime | None = None) -> list[LeadEvidence]:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = analyze_records(
        store.iter_contents(run_id),
        store.iter_comments(run_id),
        now,
        config.category_by_keyword,
        config.min_lead_score,
        config.recent_days,
    )
    store.save_leads(run_id, leads)
    write_review_queue(config.data_root / "review" / f"{run_id}.jsonl", leads)
    store.close()
    return leads


def report_store(config: RadarConfig, run_id: str, output_suffix: str = "", taskspace: int | None = None) -> Path:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads(run_id)
    from .locator import lead_exclusion_reason

    # Older batches predate profile fields and vendor filtering. Hydrate them
    # from the batch-scoped profile table before rendering any deliverable list.
    profile_map = {
        (row["platform"], row["author_id"]): row
        for row in store.load_profiles(run_id)
    }
    hydrated_leads = []
    for lead in leads:
        profile = profile_map.get((lead.platform, lead.author_id), {})
        hydrated = type(lead)(
            **{
                **lead.to_dict(),
                "company": profile.get("company", lead.company),
                "role": profile.get("role", lead.role),
                "profile_bio": profile.get("bio", lead.profile_bio),
                "profile_url": profile.get("author_url", lead.profile_url) or lead.profile_url,
                "author_url": profile.get("author_url", lead.author_url) or lead.author_url,
            }
        )
        exclusion = lead_exclusion_reason(hydrated)
        if exclusion and hydrated.decision != "reject":
            hydrated.decision = "reject"
            hydrated.stage = "model_rejected"
            hydrated.rejection_reason = exclusion
        hydrated_leads.append(hydrated)
    if hydrated_leads:
        store.save_leads(run_id, hydrated_leads)
    leads = hydrated_leads
    row = store.connection.execute("SELECT platform_status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    platform_status = json.loads(row[0]) if row else {}
    failures = {
        key: "未抓取到有效内容或需要登录"
        for key, value in platform_status.items()
        if isinstance(value, dict)
        and value.get("contents", 0) == 0
        and value.get("tasks", 0)
    }
    lead_author_keys = {(lead.platform, lead.author_id) for lead in leads if lead.author_id}
    profile_rows = store.load_profiles(run_id)
    run_row = store.connection.execute(
        "SELECT started_at, finished_at FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    wall_seconds = 0.0
    if run_row:
        try:
            wall_seconds = max(
                0.0,
                (datetime.fromisoformat(run_row["finished_at"]) - datetime.fromisoformat(run_row["started_at"])).total_seconds(),
            )
        except ValueError:
            wall_seconds = 0.0
    tasks = store.load_crawl_tasks(run_id)
    raw_contents = sum(int(item.get("raw_contents", 0) or 0) for item in tasks)
    raw_comments = sum(int(item.get("raw_comments", 0) or 0) for item in tasks)
    for platform, status in platform_status.items():
        if not isinstance(status, dict):
            continue
        platform_tasks = [item for item in tasks if item.get("platform") == platform]
        duration = max((float(item.get("duration_seconds", 0) or 0) for item in platform_tasks), default=0.0)
        if not duration and wall_seconds and len(platform_status) == 1:
            duration = wall_seconds
        per_minute = max(duration / 60, 1e-9)
        status["duration_seconds"] = duration
        status["contents_per_minute"] = status.get("contents", 0) / per_minute
        status["comments_per_minute"] = status.get("comments", 0) / per_minute
        status["raw_contents"] = sum(int(item.get("raw_contents", 0) or 0) for item in platform_tasks)
        status["raw_comments"] = sum(int(item.get("raw_comments", 0) or 0) for item in platform_tasks)
        status["backends"] = sorted({str(item.get("backend", "")) for item in platform_tasks if item.get("backend")})
    counts = {
        "contents": len(store.iter_contents(run_id)),
        "comments": len(store.iter_comments(run_id)),
        "raw_contents": raw_contents,
        "raw_comments": raw_comments,
        "prefilter": len(leads),
        "threshold": config.min_lead_score,
        "wall_seconds": wall_seconds,
        "profiles": len(
            {
                (row["platform"], row["author_id"])
                for row in profile_rows
                if (row["platform"], row["author_id"]) in lead_author_keys
            }
        ),
        "external_evidence": int(store.connection.execute("SELECT COUNT(*) FROM external_evidence WHERE run_id = ?", (run_id,)).fetchone()[0]),
    }
    query_counts: dict[str, dict[str, int]] = {}
    for content in store.iter_contents(run_id):
        for keyword in content.source_keywords:
            query_counts.setdefault(keyword, {"keyword": keyword, "contents": 0, "comments": 0, "leads": 0})["contents"] += 1
    for comment in store.iter_comments(run_id):
        item = query_counts.setdefault(comment.source_keyword, {"keyword": comment.source_keyword, "contents": 0, "comments": 0, "leads": 0})
        item["comments"] += 1
    content_by_key = {(lead.platform, lead.content_id) for lead in leads}
    for content in store.iter_contents(run_id):
        if (content.platform, content.content_id) not in content_by_key:
            continue
        for keyword in content.source_keywords:
            query_counts.setdefault(keyword, {"keyword": keyword, "contents": 0, "comments": 0, "leads": 0})["leads"] += 1
    for item in query_counts.values():
        item["candidate_rate"] = item["leads"] / item["contents"] if item["contents"] else 0.0
    counts["query_stats"] = sorted(query_counts.values(), key=lambda item: (-item["leads"], -item["comments"], item["keyword"]))
    assessment_rows = store.connection.execute("SELECT payload FROM lead_assessments WHERE run_id = ?", (run_id,)).fetchall()
    for row in assessment_rows:
        payload = json.loads(row[0])
        if payload.get("decision") == "high_value" and payload.get("score", 0) >= config.min_lead_score:
            counts["high_value"] = counts.get("high_value", 0) + 1
        if payload.get("decision") == "review":
            counts["review"] = counts.get("review", 0) + 1
        if payload.get("decision") == "manual_confirmed":
            counts["manual_confirmed"] = counts.get("manual_confirmed", 0) + 1
    counts["model_passed"] = counts.get("high_value", 0)
    counts["evidence_insufficient"] = counts.get("review", 0)
    counts["task_count"] = len(tasks)
    counts["status_events_raw"] = store.count_status_events(run_id, distinct=False)
    counts["status_events_distinct"] = store.count_status_events(run_id, distinct=True)
    from .locator import select_deliverable_leads

    counts["locator_verified"] = sum(1 for lead in leads if lead.locator_status == "verified")
    counts["deliverable"] = len(select_deliverable_leads(leads, 20, config.min_lead_score))
    report_urls = []
    for lead in leads:
        report_urls.extend([lead.url, lead.profile_url, lead.comment_url, *lead.evidence_urls])
    url_checks, url_check_log = validate_urls_with_ego(
        report_urls[:200],
        Path(__file__).resolve().parents[2],
        config.data_root / "url_checks" / run_id,
        taskspace=taskspace,
    )
    if url_check_log:
        failures["url_validation"] = url_check_log
    top_contents: list[LeadEvidence] = []
    by_content: dict[tuple[str, str], LeadEvidence] = {}
    for lead in leads:
        key = (lead.platform, lead.content_id)
        if key not in by_content or lead.score > by_content[key].score:
            by_content[key] = lead
    top_contents = sorted(
        (
            item
            for item in by_content.values()
            if item.score >= config.min_lead_score
            and item.stage == "model_reviewed"
            and item.decision == "high_value"
        ),
        key=lambda item: (-item.score, item.platform, item.content_id),
    )
    suffix = f"-{output_suffix.strip('-')}" if output_suffix.strip('-') else ""
    report_path = config.data_root / "reports" / f"{run_id}{suffix}.md"
    write_report(report_path, render_report(run_id, leads, top_contents, platform_status, failures, counts, url_checks))
    dump_url_checks(config.data_root / "reports" / f"{run_id}{suffix}-url-checks.json", url_checks)
    locator_checks = store.load_comment_locators(run_id)
    verified_leads = select_deliverable_leads(leads, 20, config.min_lead_score)
    write_verified_lead_artifacts(
        config.data_root,
        run_id,
        verified_leads,
        locator_checks,
        url_checks,
    )
    store.close()
    return report_path
