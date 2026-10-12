"""Append-only incoming-reply signals for the cumulative business dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SIGNAL_FILENAME = "reply_signals.jsonl"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def signal_path(data_root: Path | str) -> Path:
    return Path(data_root) / SIGNAL_FILENAME


def _signal_key(payload: dict) -> str:
    parts = (
        _norm(payload.get("platform")),
        _norm(payload.get("target_url") or payload.get("url")),
        _norm(payload.get("target_author") or payload.get("author")),
        _norm(payload.get("quote")),
        str(int(payload.get("wave", 1) or 1)),
    )
    return "|".join(parts)


def load_reply_signals(data_root: Path | str) -> list[dict]:
    path = signal_path(data_root)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def append_reply_signal(data_root: Path | str, payload: dict) -> dict:
    """Append one reply event unless the same event already exists."""
    cleaned = dict(payload)
    cleaned["wave"] = int(cleaned.get("wave", 1) or 1)
    if not cleaned.get("observed_at"):
        cleaned["observed_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    cleaned["signal_key"] = _signal_key(cleaned)
    existing = {str(item.get("signal_key", "")) for item in load_reply_signals(data_root)}
    path = signal_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if cleaned["signal_key"] in existing:
        return {"written": False, "reason": "duplicate", "signal_key": cleaned["signal_key"], "path": str(path)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
    return {"written": True, "signal_key": cleaned["signal_key"], "path": str(path), "wave": cleaned["wave"]}


def merge_reply_signals(rows: list[dict], data_root: Path | str) -> list[dict]:
    """Attach the latest reply signal to matching dashboard rows."""
    signals = load_reply_signals(data_root)
    by_target: dict[tuple[str, str, str], list[dict]] = {}
    for signal in signals:
        key = (
            _norm(signal.get("platform")),
            _norm(signal.get("target_url") or signal.get("url")),
            _norm(signal.get("target_author") or signal.get("author")),
        )
        by_target.setdefault(key, []).append(signal)
    for row in rows:
        key = (
            _norm(row.get("platform")),
            _norm(row.get("target_url") or row.get("content_url") or row.get("url")),
            _norm(row.get("target_author") or row.get("author")),
        )
        items = sorted(by_target.get(key, []), key=lambda item: str(item.get("observed_at") or ""))
        if not items:
            continue
        latest = items[-1]
        row["received_reply"] = latest.get("quote", "")
        row["reply_wave"] = max(int(item.get("wave", 1) or 1) for item in items)
        row["second_wave_reply"] = row["reply_wave"] >= 2
        row["reply_signal"] = "second_wave_reply" if row["second_wave_reply"] else "first_wave_reply"
        # reply_author records WHO answered (may differ from the target author
        # when a brand account replies on a post-level target); fall back to the
        # legacy target fields when the signal predates this field.
        row["reply_author"] = (
            latest.get("reply_author") or latest.get("target_author") or latest.get("author") or ""
        )
        row["reply_observed_at"] = latest.get("observed_at") or ""
    return rows
