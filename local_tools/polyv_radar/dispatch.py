from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .conversion_engine import build_conversion_pack
from .locator import is_deliverable_lead
from .models import LeadEvidence
from .skill_runtime import inspect_skill_runtime, require_skill_runtime
from .target_urls import dispatch_target_url, normalize_comment_url


AUTO_REPLY_SCRIPT = Path("/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply")
REPLY_HISTORY_PATH = Path("/Users/sexpistole111/Documents/workplace/polyv-radar-data/reply_history.jsonl")
SUPPORTED_PLATFORMS = {"dy", "xhs", "bili", "zhihu"}


@dataclass(frozen=True)
class DispatchItem:
    platform: str
    url: str
    author: str
    text: str
    content_id: str = ""
    comment_id: str = ""
    quote: str = ""
    content_url: str = ""
    comment_url: str = ""
    source_type: str = "comment"
    author_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "platform": self.platform,
            "url": self.url,
            "author": self.author,
            "text": self.text,
            "content_id": self.content_id,
            "comment_id": self.comment_id,
            "quote": self.quote,
            "content_url": self.content_url or self.url,
            "comment_url": self.comment_url,
            "source_type": self.source_type,
            "author_id": self.author_id,
        }


def _item_from_dict(value: dict) -> DispatchItem:
    comment_id = str(value.get("comment_id", "")).strip()
    source_value = str(value.get("source_type", "")).strip()
    source_type = source_value or ("post" if not comment_id and value.get("quote") else "comment")
    item = DispatchItem(
        platform=str(value.get("platform", "")).strip(),
        url=str(value.get("url", "")).strip(),
        author=str(value.get("author", "")).strip(),
        text=str(value.get("text", "")).strip(),
        content_id=str(value.get("content_id", "")).strip(),
        comment_id=comment_id,
        quote=str(value.get("quote", "")).strip(),
        content_url=str(value.get("content_url", "")).strip(),
        comment_url=str(value.get("comment_url", "")).strip(),
        source_type=source_type,
        author_id=str(value.get("author_id", value.get("user_id", ""))).strip(),
    )
    if item.platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"不支持的平台：{item.platform or '空值'}")
    if not item.url or not item.author or not item.text:
        raise ValueError("发送队列每条记录必须包含 platform、url、author 和 text")
    return item


def load_dispatch_queue(path: Path) -> list[DispatchItem]:
    rows: list[DispatchItem] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"发送队列第 {line_number} 行不是有效 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"发送队列第 {line_number} 行必须是对象")
        rows.append(_item_from_dict(value))
    return rows


def build_dispatch_queue(leads: Iterable[LeadEvidence], selection: str = "manual") -> list[DispatchItem]:
    if selection not in {"manual", "model"}:
        raise ValueError("selection 仅支持 manual 或 model")
    result: list[DispatchItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for lead in leads:
        accepted = lead.decision == "manual_confirmed" if selection == "manual" else (
            lead.stage == "model_reviewed" and lead.decision == "high_value"
        )
        if not accepted or lead.locator_status != "verified" or not lead.user or not lead.url:
            continue
        if selection == "model" and not is_deliverable_lead(lead):
            continue
        item = DispatchItem(
            platform=lead.platform,
            url=dispatch_target_url(lead.url, lead.comment_url, lead.source_type),
            author=lead.user,
            text=build_conversion_pack(lead).reply_text,
            content_id=lead.content_id,
            comment_id=lead.comment_id,
            quote=lead.quote,
            content_url=lead.url,
            comment_url=normalize_comment_url(lead.comment_url, lead.url, lead.source_type),
            source_type=lead.source_type or "comment",
            author_id=lead.author_id,
        )
        key = dispatch_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _normalize_dispatch_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _normalize_dispatch_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                 if key not in {"xsec_token", "xsec_source", "utm_source", "utm_medium", "utm_campaign", "utm_content"}]
        return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/") or "/", urlencode(query), parts.fragment))
    except ValueError:
        return _normalize_dispatch_text(raw)


def dispatch_key(value: DispatchItem | dict) -> tuple[str, str, str, str]:
    """Build a stable target identity that is independent of reply wording.

    Comment targets use the native comment ID when available. Content targets
    use the normalized content ID plus stable author ID/name. When native IDs
    are absent, the normalized URL, author and original quote are retained as
    the fallback identity. The reply text is deliberately excluded so changing
    wording cannot bypass duplicate-send protection.
    """
    if isinstance(value, DispatchItem):
        platform = value.platform
        url = value.url
        author = value.author
        content_id = value.content_id
        comment_id = value.comment_id
        quote = value.quote
        source_type = value.source_type
        author_id = value.author_id
        content_url = value.content_url
    else:
        platform = value.get("platform", "")
        url = value.get("url", value.get("target_url", ""))
        author = value.get("author", value.get("target_author", ""))
        content_id = value.get("content_id", "")
        comment_id = value.get("comment_id", value.get("native_comment_id", ""))
        quote = value.get("quote", value.get("original_text", ""))
        source_type = value.get("source_type", "comment")
        author_id = value.get("author_id", value.get("user_id", ""))
        content_url = value.get("content_url", "")
    identity_url = _normalize_dispatch_url(content_url or url)
    stable_author = _normalize_dispatch_text(author_id or author)
    if comment_id:
        identity = f"comment:{_normalize_dispatch_text(comment_id)}:{stable_author}:{_normalize_dispatch_text(content_id)}"
    elif content_id:
        identity = f"content:{_normalize_dispatch_text(content_id)}:{stable_author}:{identity_url}"
    else:
        identity = f"fallback:{identity_url}:{stable_author}:{_normalize_dispatch_text(quote)}"
    return tuple(
        _normalize_dispatch_text(part)
        for part in (platform, source_type, identity, _normalize_dispatch_url(url))
    )


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _result_blocks_retry(row: dict) -> bool:
    """Return whether a prior result should suppress a duplicate attempt."""
    status = str(row.get("status", row.get("lead_status", "")))
    return bool(row.get("submitted")) or status in {
        "dry_run",
        "submitted_verified",
        "submitted_unverified",
        "content_unavailable",
        "page_not_found",
    }


def classify_dispatch_failure(structured: dict | None, message: str) -> str:
    """Map browser failures to stable dashboard and retry categories."""
    status = str((structured or {}).get("status", "")).strip()
    if status:
        return status
    text = str(message or "")
    lowered = text.casefold()
    if any(token in lowered for token in ("页面不见了", "页面不存在", "内容不存在", "404", "not found", "视频不存在", "笔记不存在")):
        return "content_unavailable"
    if "截图失败" in text or "capturescreenshot" in lowered or "截图超时" in text:
        return "screenshot_evidence_timeout"
    if "未找到" in text and "评论" in text:
        return "target_not_found"
    if "登录" in text:
        return "blocked_login_required"
    return "failed"


def load_existing_dispatch_keys(data_root: Path) -> set[tuple[str, str, str, str]]:
    """Load successful and pending dispatch identities across all batches.

    Failed locator/input/page attempts remain retryable.  Pending queue rows
    are suppressed unless their latest result is an explicit failure, which
    keeps repeated preparation idempotent without hiding recoverable targets.
    """
    dispatch_root = Path(data_root) / "dispatch"
    result_by_key: dict[tuple[str, str, str, str], dict] = {}
    for path in sorted(dispatch_root.glob("dispatch-*.jsonl")):
        for row in _load_jsonl(path):
            key = dispatch_key(row)
            if key != ("", "", "", ""):
                result_by_key[key] = row

    existing: set[tuple[str, str, str, str]] = {
        key for key, row in result_by_key.items() if _result_blocks_retry(row)
    }

    for path in sorted(dispatch_root.glob("*.jsonl")):
        if path.name.startswith(("dispatch-", "audit-")):
            continue
        for row in _load_jsonl(path):
            key = dispatch_key(row)
            if key == ("", "", "", ""):
                continue
            latest = result_by_key.get(key)
            if latest is None or _result_blocks_retry(latest):
                existing.add(key)

    for row in _load_jsonl(Path(REPLY_HISTORY_PATH)):
        key = dispatch_key(row)
        if key != ("", "", "", "") and row.get("submitted") is True and row.get("mode") != "dry_run":
            existing.add(key)
    return existing


def filter_previously_queued(
    items: Iterable[DispatchItem], data_root: Path
) -> tuple[list[DispatchItem], list[dict]]:
    """Remove cross-batch duplicates and return an auditable skip list."""
    existing = load_existing_dispatch_keys(data_root)
    kept: list[DispatchItem] = []
    skipped: list[dict] = []
    for item in items:
        key = dispatch_key(item)
        if key in existing:
            skipped.append({
                **item.to_dict(),
                "reason": "already_queued_or_successfully_attempted",
                "dedupe_key": list(key),
            })
            continue
        existing.add(key)
        kept.append(item)
    return kept, skipped


def write_dispatch_audit(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_dispatch_queue(path: Path, items: Iterable[DispatchItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n" for item in items),
        encoding="utf-8",
    )


def build_dispatch_command(item: DispatchItem, taskspace: int, submit: bool, page: str = "p1") -> list[str]:
    if taskspace <= 0:
        raise ValueError("必须提供有效的 Ego Lite TaskSpace 编号")
    command = [
        str(AUTO_REPLY_SCRIPT),
        "--taskspace", str(taskspace),
        "--page", page,
        "--platform", item.platform,
        "--url", item.url,
        "--author", item.author,
        "--text", item.text,
        "--source-type", item.source_type,
    ]
    if item.quote:
        command.extend(["--quote", item.quote])
    if submit:
        command.append("--submit")
    return command


def _history_size() -> int:
    try:
        return REPLY_HISTORY_PATH.stat().st_size
    except OSError:
        return 0


def _read_structured_result(previous_size: int, item: DispatchItem) -> dict | None:
    try:
        with REPLY_HISTORY_PATH.open("rb") as handle:
            handle.seek(previous_size)
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            value.get("platform") == item.platform
            and value.get("target_url") == item.url
            and value.get("target_author") == item.author
            and value.get("reply_text") == item.text
        ):
            return value
    return None


def dispatch_queue(
    items: Iterable[DispatchItem],
    taskspace: int,
    submit: bool = False,
    max_sends: int | None = None,
    cooldown_seconds: float = 30,
    page: str = "p1",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[dict]:
    if max_sends is not None and max_sends <= 0:
        raise ValueError("max_sends 必须大于 0")
    results: list[dict] = []
    runtime_status = require_skill_runtime() if submit else inspect_skill_runtime()
    last_sent_at: dict[str, float] = {}
    selected_items = list(items) if max_sends is None else list(items)[:max_sends]
    for item in selected_items:
        previous = last_sent_at.get(item.platform)
        if submit and previous is not None:
            wait_for = cooldown_seconds - (time.monotonic() - previous)
            if wait_for > 0:
                sleeper(wait_for)
        command = build_dispatch_command(item, taskspace, submit, page=page)
        history_size = _history_size()
        try:
            completed = runner(command, text=True, capture_output=True, check=False, timeout=180)
            structured = _read_structured_result(history_size, item)
            if not submit:
                status = "dry_run" if completed.returncode == 0 and (structured is None or structured.get("draft_verified", True)) else "failed"
            elif completed.returncode != 0:
                status = classify_dispatch_failure(structured, completed.stderr or completed.stdout)
            elif structured and structured.get("verified") is True:
                status = "submitted_verified"
            elif structured and structured.get("submitted") is True:
                status = "submitted_unverified"
            else:
                status = "submitted_unverified"
            result = {
                **item.to_dict(),
                "mode": "submit" if submit else "dry_run",
                "status": status,
                "lead_status": status,
                "submitted": bool((structured or {}).get("submitted", False)),
                "verified": bool((structured or {}).get("verified", False)),
                "draft_verified": bool((structured or {}).get("draft_verified", False)),
                "target_matched": bool((structured or {}).get("target_matched", False)),
                "returncode": completed.returncode,
                "structured_result": structured or {},
                "screenshot": (structured or {}).get("screenshot", ""),
                "message": (completed.stderr or completed.stdout or "").strip()[-1000:],
                "failure_code": status if status not in {"submitted_verified", "submitted_unverified", "dry_run"} else "",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "skill_runtime": runtime_status,
            }
            if submit and status == "submitted_verified":
                last_sent_at[item.platform] = time.monotonic()
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {
                **item.to_dict(),
                "mode": "submit" if submit else "dry_run",
                "status": "dispatch_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "failed",
                "submitted": False,
                "verified": False,
                "draft_verified": False,
                "target_matched": False,
                "returncode": -1,
                "message": str(exc),
                "failure_code": "dispatch_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "runner_error",
                "structured_result": {},
                "screenshot": "",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "skill_runtime": runtime_status,
            }
        results.append(result)
    return results


def write_dispatch_results(path: Path, results: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(result, ensure_ascii=False) + "\n" for result in results),
        encoding="utf-8",
    )
