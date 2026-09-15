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
from .report import render_report, write_report
from .scoring import score_lead
from .storage import RadarStore


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


def _ingest_output(
    output_dir: Path,
    platform: str,
    keyword: str,
    store: RadarStore,
    max_contents: int | None = None,
    max_comments: int | None = None,
    run_id: str | None = None,
) -> tuple[int, int]:
    content_rows: list[dict] = []
    comment_rows: list[dict] = []
    for path in sorted(output_dir.rglob("*.jsonl")):
        name = path.name.lower()
        if "comment" in name:
            comment_rows.extend(_read_jsonl(path))
        elif "content" in name or "video" in name:
            content_rows.extend(_read_jsonl(path))

    if max_contents is not None:
        content_rows = content_rows[:max_contents]
    contents = [item for item in (normalize_content(platform, row, keyword) for row in content_rows) if item]
    comments = [item for item in (normalize_comment(platform, row, source_keyword=keyword) for row in comment_rows) if item]
    if max_comments is not None:
        per_content_count: dict[str, int] = {}
        limited_comments: list[CommentRecord] = []
        for comment in comments:
            count = per_content_count.get(comment.content_id, 0)
            if count >= max_comments:
                continue
            limited_comments.append(comment)
            per_content_count[comment.content_id] = count + 1
        comments = limited_comments
    for content in contents:
        store.upsert_content(content, run_id=run_id)
    for comment in comments:
        store.upsert_comment(comment, run_id=run_id)
    return len(contents), len(comments)


def collect(config: RadarConfig, repo_root: Path, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> CollectionResult:
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    raw_root = config.data_root / "raw" / run_id
    store_path = config.data_root / "radar.sqlite3"
    store = RadarStore(store_path)
    store.initialize()
    platform_status: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for platform in config.platforms:
        status = {"status": "success", "contents": 0, "comments": 0, "tasks": 0}
        for keyword in config.get_keywords_for_platform(platform).values():
            status["tasks"] += 1
            output_dir = raw_root / platform / safe_name(keyword)
            output_dir.mkdir(parents=True, exist_ok=True)
            command = build_crawl_command(
                repo_root,
                platform,
                keyword,
                output_dir,
                config.max_contents,
                config.max_comments,
                config.login_type,
                config.concurrency,
                config.comments,
                config.sub_comments,
            )
            timed_out = False
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
                completed = subprocess.CompletedProcess(
                    command,
                    returncode=124,
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                )
            log_path = output_dir / "crawler.log"
            log_prefix = f"任务超过 {config.task_timeout_seconds} 秒，保留已落盘数据并继续。\n" if timed_out else ""
            log_path.write_text(
                log_prefix + _as_text(completed.stdout) + "\n" + _as_text(completed.stderr),
                encoding="utf-8",
            )
            contents, comments = _output_status(
                output_dir,
                platform,
                keyword,
                store,
                config.max_contents,
                config.max_comments,
                run_id,
            )
            status["contents"] += contents
            status["comments"] += comments
            if completed.returncode != 0:
                status["status"] = "partial"
                reason = "任务超时，已保留部分数据" if timed_out else _as_text(completed.stderr or completed.stdout or "退出码非零")
                failures[f"{platform}:{keyword}"] = _as_text(reason).strip()[-500:]
                continue
        platform_status[platform] = status
    final_status = "success" if not failures else "partial"
    store.save_run(run_id, final_status, platform_status, now.isoformat(), datetime.now(timezone.utc).isoformat())
    store.close()
    return CollectionResult(run_id, store_path, platform_status, failures)


def ingest_existing_run(config: RadarConfig, run_id: str) -> CollectionResult:
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
        plat_keywords = config.get_keywords_for_platform(platform) if hasattr(config, "get_keywords_for_platform") else config.keywords
        for keyword in plat_keywords.values():
            output_dir = raw_root / platform / safe_name(keyword)
            if not output_dir.exists():
                continue
            status["tasks"] += 1
            contents, comments = _output_status(
                output_dir,
                platform,
                keyword,
                store,
                config.max_contents,
                config.max_comments,
                run_id,
            )
            status["contents"] += contents
            status["comments"] += comments
        if status["tasks"] and status["contents"]:
            status["status"] = "success"
        if status["tasks"] and not status["contents"]:
            status["status"] = "partial"
            failures[platform] = "任务被中断或未完成，已恢复已落盘数据"
        platform_status[platform] = status
    now = datetime.now(timezone.utc).isoformat()
    final_status = "success" if all(item["status"] in {"success", "not_run"} for item in platform_status.values()) else "partial"
    store.save_run(run_id, final_status, platform_status, now, now)
    store.close()
    return CollectionResult(run_id, store_path, platform_status, failures)


def analyze_records(
    contents: Iterable[ContentRecord],
    comments: Iterable[CommentRecord],
    now: datetime | None = None,
    category_by_keyword: dict[str, str] | None = None,
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
                lead = score_lead(content, comment, now, category_hint)
                if lead.score >= 4:
                    key = (lead.platform, lead.content_id, _text_key(lead.user), _text_key(lead.quote))
                    existing = leads_by_key.get(key)
                    if existing is None or lead.score > existing.score:
                        leads_by_key[key] = lead
        else:
            category_hint = category_by_keyword.get(content.source_keywords[0]) if content.source_keywords else None
            lead = score_lead(content, None, now, category_hint)
            if lead.score >= 4:
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
    leads = analyze_records(store.iter_contents(run_id), store.iter_comments(run_id), now, config.category_by_keyword)
    store.save_leads(run_id, leads)
    write_review_queue(config.data_root / "review" / f"{run_id}.jsonl", leads)
    store.close()
    return leads


def report_store(config: RadarConfig, run_id: str, output_suffix: str = "") -> Path:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads(run_id)
    row = store.connection.execute("SELECT platform_status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    platform_status = json.loads(row[0]) if row else {}
    failures = {
        key: "未抓取到有效内容或需要登录"
        for key, value in platform_status.items()
        if value.get("contents", 0) == 0 and value.get("tasks", 0)
    }
    lead_author_keys = {(lead.platform, lead.author_id) for lead in leads if lead.author_id}
    profile_rows = store.load_profiles(run_id)
    counts = {
        "contents": len(store.iter_contents(run_id)),
        "comments": len(store.iter_comments(run_id)),
        "prefilter": len(leads),
        "threshold": config.min_lead_score,
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
    counts["query_stats"] = sorted(query_counts.values(), key=lambda item: (-item["leads"], -item["comments"], item["keyword"]))
    assessment_rows = store.connection.execute("SELECT payload FROM lead_assessments WHERE run_id = ?", (run_id,)).fetchall()
    for row in assessment_rows:
        payload = json.loads(row[0])
        if payload.get("decision") == "high_value" and payload.get("score", 0) >= config.min_lead_score:
            counts["high_value"] = counts.get("high_value", 0) + 1
        if payload.get("decision") == "review":
            counts["review"] = counts.get("review", 0) + 1
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
    write_report(report_path, render_report(run_id, leads, top_contents, platform_status, failures, counts))
    store.close()
    return report_path
