from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .conversion_engine import build_conversion_pack
from .locator import is_deliverable_lead
from .models import LeadEvidence


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

    def to_dict(self) -> dict[str, str]:
        return {
            "platform": self.platform,
            "url": self.url,
            "author": self.author,
            "text": self.text,
            "content_id": self.content_id,
            "comment_id": self.comment_id,
            "quote": self.quote,
        }


def _item_from_dict(value: dict) -> DispatchItem:
    item = DispatchItem(
        platform=str(value.get("platform", "")).strip(),
        url=str(value.get("url", "")).strip(),
        author=str(value.get("author", "")).strip(),
        text=str(value.get("text", "")).strip(),
        content_id=str(value.get("content_id", "")).strip(),
        comment_id=str(value.get("comment_id", "")).strip(),
        quote=str(value.get("quote", "")).strip(),
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
    seen: set[tuple[str, str, str]] = set()
    for lead in leads:
        accepted = lead.decision == "manual_confirmed" if selection == "manual" else (
            lead.stage == "model_reviewed" and lead.decision == "high_value"
        )
        if not accepted or lead.locator_status != "verified" or not lead.user or not lead.url:
            continue
        if selection == "model" and not is_deliverable_lead(lead):
            continue
        key = (lead.platform, lead.url, lead.user)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            DispatchItem(
                platform=lead.platform,
                url=lead.comment_url or lead.url,
                author=lead.user,
                text=build_conversion_pack(lead).reply_text,
                content_id=lead.content_id,
                comment_id=lead.comment_id,
                quote=lead.quote,
            )
        )
    return result


def write_dispatch_queue(path: Path, items: Iterable[DispatchItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n" for item in items),
        encoding="utf-8",
    )


def build_dispatch_command(item: DispatchItem, taskspace: int, submit: bool) -> list[str]:
    if taskspace <= 0:
        raise ValueError("必须提供有效的 Ego Lite TaskSpace 编号")
    command = [
        str(AUTO_REPLY_SCRIPT),
        "--taskspace", str(taskspace),
        "--platform", item.platform,
        "--url", item.url,
        "--author", item.author,
        "--text", item.text,
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
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[dict]:
    if max_sends is not None and max_sends <= 0:
        raise ValueError("max_sends 必须大于 0")
    results: list[dict] = []
    last_sent_at: dict[str, float] = {}
    selected_items = list(items) if max_sends is None else list(items)[:max_sends]
    for item in selected_items:
        previous = last_sent_at.get(item.platform)
        if submit and previous is not None:
            wait_for = cooldown_seconds - (time.monotonic() - previous)
            if wait_for > 0:
                sleeper(wait_for)
        command = build_dispatch_command(item, taskspace, submit)
        history_size = _history_size()
        try:
            completed = runner(command, text=True, capture_output=True, check=False, timeout=180)
            structured = _read_structured_result(history_size, item)
            if not submit:
                status = "dry_run" if completed.returncode == 0 and (structured is None or structured.get("draft_verified", True)) else "failed"
            elif completed.returncode != 0:
                status = str(structured.get("status")) if structured and structured.get("status") in {"blocked", "input_failed", "click_failed", "post_not_found"} else "failed"
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
                "returncode": completed.returncode,
                "structured_result": structured or {},
                "screenshot": (structured or {}).get("screenshot", ""),
                "message": (completed.stderr or completed.stdout or "").strip()[-1000:],
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
            if submit and status == "submitted_verified":
                last_sent_at[item.platform] = time.monotonic()
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {
                **item.to_dict(),
                "mode": "submit" if submit else "dry_run",
                "status": "failed",
                "returncode": -1,
                "message": str(exc),
                "structured_result": {},
                "screenshot": "",
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
        results.append(result)
    return results


def write_dispatch_results(path: Path, results: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(result, ensure_ascii=False) + "\n" for result in results),
        encoding="utf-8",
    )
