from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _git_revision(worktree: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _count_priority(rows: list[dict[str, Any]], pending_pool: int = 0) -> dict[str, int]:
    counted = [row for row in rows if row.get("counts_toward_20") is True]
    priorities = Counter(str(row.get("sales_priority") or row.get("priority") or "待核") for row in counted)
    return {
        "P0": priorities.get("P0", 0),
        "P1": priorities.get("P1", 0),
        "P2": priorities.get("P2", 0),
        "待核": pending_pool,
    }


def build_takeover(data_root: Path, campaign: str = "polyv-100") -> dict[str, Any]:
    work_dir = data_root / "grok-work" / campaign
    sync_path = work_dir / "grok-to-codex-latest.json"
    sync_md_path = work_dir / "grok-to-codex-latest.md"
    ledger_path = work_dir / "demand-leads-20-ledger.json"
    if not sync_path.exists():
        raise FileNotFoundError(f"Grok sync JSON missing: {sync_path}")
    if not ledger_path.exists():
        raise FileNotFoundError(f"demand ledger missing: {ledger_path}")

    sync = _read_json(sync_path)
    ledger = _read_json(ledger_path)
    rows = ledger.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"ledger rows must be a list: {ledger_path}")
    row_dicts = [row for row in rows if isinstance(row, dict)]
    counted_rows = [row for row in row_dicts if row.get("counts_toward_20") is True]
    bucket_counts = Counter(str(row.get("bucket") or "") for row in row_dicts)
    priority_counts = _count_priority(row_dicts, bucket_counts.get("待核", 0))
    declared_counts = ledger.get("counts") if isinstance(ledger.get("counts"), dict) else {}
    dashboard_path = work_dir / "dashboard-status.json"
    dashboard = _read_json(dashboard_path) if dashboard_path.exists() else {}

    deliverables: list[dict[str, Any]] = []
    for item in sync.get("deliverables", []):
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = Path(str(item["path"]))
        exists = path.exists()
        actual_hash = _sha256(path) if exists else None
        expected_hash = item.get("sha256")
        deliverables.append(
            {
                "name": item.get("name", path.name),
                "path": str(path),
                "exists": exists,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "hash_match": bool(exists and expected_hash and actual_hash == expected_hash),
                "record_count": item.get("record_count"),
            }
        )

    sync_valid = all(item["exists"] and item["hash_match"] for item in deliverables)
    counts = {
        "counted_institutional": len(counted_rows),
        "ledger_total_rows": len(row_dicts),
        "pending_review_pool": bucket_counts.get("待核", 0),
        "filtered": bucket_counts.get("过滤", 0),
        "social_qualified_100": int((sync.get("social_100") or {}).get("qualified_count", 0)),
        "social_sent_verified": int(
            (sync.get("social_100") or {}).get(
                "sent_verified",
                dashboard.get("已发送", 0),
            )
        ),
    }
    result = {
        "schema": "codex-polyv-takeover.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "campaign": campaign,
        "project": {
            "worktree": "/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit",
            "branch": "codex/polyv-antigravity-inherit",
            "data_root": str(data_root),
            "git_revision": _git_revision(
                Path("/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit")
            ),
        },
        "source": {
            "grok_sync_json": str(sync_path),
            "grok_sync_markdown": str(sync_md_path),
            "grok_sync_sha256": _sha256(sync_path),
            "ledger_sha256": _sha256(ledger_path),
        },
        "verification": {
            "grok_deliverables_hashes_match": sync_valid,
            "declared_counts": declared_counts,
            "recomputed_counts": counts,
            "recomputed_priority_counts": priority_counts,
            "counted_rows_match_declared_20": len(counted_rows) == 20,
            "social_funnel_frozen": counts["social_qualified_100"] == 0,
        },
        "priority_counts": priority_counts,
        "counts": counts,
        "open_issues": sync.get("open_issues", []),
        "next_actions": sync.get("suggested_next_steps_for_codex", []),
        "deliverables": deliverables,
        "policy": {
            "institutional_leads_do_not_count_toward_social_100": True,
            "social_funnel_status": "frozen",
            "external_contact": "not executed",
        },
    }
    result["ready"] = bool(
        sync_valid
        and result["verification"]["counted_rows_match_declared_20"]
        and result["verification"]["social_funnel_frozen"]
    )
    return result


def write_takeover(data_root: Path, campaign: str = "polyv-100") -> tuple[Path, Path, dict[str, Any]]:
    result = build_takeover(data_root, campaign)
    out_dir = data_root / "grok-work" / campaign
    json_path = out_dir / "codex-takeover-latest.json"
    markdown_path = out_dir / "codex-takeover-latest.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    priority = result["priority_counts"]
    counts = result["counts"]
    issues = result["open_issues"] or ["无"]
    next_actions = result["next_actions"] or ["无"]
    lines = [
        "# Codex 接管基线",
        "",
        f"- 生成时间：`{result['generated_at']}`",
        f"- Git SHA：`{result['project']['git_revision'] or 'unknown'}`",
        f"- 交接状态：`{'READY' if result['ready'] else 'BLOCKED'}`",
        f"- Grok 同步哈希校验：`{'通过' if result['verification']['grok_deliverables_hashes_match'] else '失败'}`",
        "",
        "## 计数",
        "",
        f"- 机构需求计入：**{counts['counted_institutional']}**",
        f"- P0/P1/P2/待核：**{priority['P0']} / {priority['P1']} / {priority['P2']} / {priority['待核']}**",
        f"- 社媒合格计数：**{counts['social_qualified_100']}**",
        f"- 社媒已发送回查：**{counts['social_sent_verified']}**",
        f"- 社媒漏斗：**冻结**",
        "",
        "## 交付文件",
        "",
    ]
    for item in result["deliverables"]:
        state = "通过" if item["hash_match"] else "失败"
        lines.append(f"- `{item['path']}`：{state}，SHA-256 `{item['actual_sha256'] or 'missing'}`")
    lines.extend(["", "## 未解决问题", ""])
    lines.extend(f"- {issue}" for issue in issues)
    lines.extend(["", "## 下一步", ""])
    lines.extend(f"- {action}" for action in next_actions)
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "机构需求不补社媒100条；本次没有执行评论、私信、点赞、关注或其他外联。",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path, result
