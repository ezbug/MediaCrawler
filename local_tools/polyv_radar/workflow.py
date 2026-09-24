from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKFLOW_NAME = "polyv-leads"
WORKFLOW_VERSION = "1"


def _workflow_dir(data_root: Path, run_id: str) -> Path:
    return Path(data_root) / "workflow-runs" / run_id


def save_workflow_run(data_root: Path, run_id: str, payload: dict[str, Any]) -> Path:
    destination = _workflow_dir(data_root, run_id)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "workflow-run.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_workflow_candidate(data_root: Path, run_id: str, platforms: list[dict[str, Any]]) -> Path:
    destination = _workflow_dir(data_root, run_id)
    destination.mkdir(parents=True, exist_ok=True)
    candidate = {
        "workflow_name": WORKFLOW_NAME,
        "workflow_version": WORKFLOW_VERSION,
        "run_id": run_id,
        "status": "pending_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "promotion_policy": "manual_review_and_test_required",
        "steps": [
            "preflight",
            "snapshot_before_navigation",
            "batch_keywords_on_one_platform_page",
            "extract_dom_data_with_page_evaluate",
            "snapshot_after_each_keyword",
            "persist_jsonl_and_run_record",
        ],
        "platforms": platforms,
    }
    path = destination / "workflow-candidate.json"
    path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_workflow_run(data_root: Path, run_id: str) -> dict[str, Any] | None:
    path = _workflow_dir(data_root, run_id) / "workflow-run.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
