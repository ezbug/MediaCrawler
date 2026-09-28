from __future__ import annotations

import json
from pathlib import Path

from local_tools.polyv_radar.takeover import build_takeover, write_takeover


def _fixture(tmp_path: Path) -> Path:
    work_dir = tmp_path / "grok-work" / "polyv-100"
    work_dir.mkdir(parents=True)
    rows = [
        {"id": "p0", "counts_toward_20": True, "sales_priority": "P0", "bucket": "可核验需求线索"},
        {"id": "p1", "counts_toward_20": True, "sales_priority": "P1", "bucket": "可核验需求线索"},
        {"id": "p2", "counts_toward_20": True, "sales_priority": "P2", "bucket": "可核验需求线索"},
        {"id": "pending", "counts_toward_20": False, "bucket": "待核"},
    ]
    ledger = work_dir / "demand-leads-20-ledger.json"
    ledger.write_text(json.dumps({"rows": rows, "counts": {"计入20条": 3}}, ensure_ascii=False), encoding="utf-8")
    deliverable = work_dir / "demand-leads-20-followup.csv"
    deliverable.write_text("id\n", encoding="utf-8")
    sync = {
        "social_100": {"qualified_count": 0, "sent_verified": 2},
        "deliverables": [
            {
                "path": str(ledger),
                "sha256": "placeholder",
                "record_count": 3,
            },
            {
                "path": str(deliverable),
                "sha256": "placeholder",
                "record_count": 3,
            },
        ],
        "open_issues": ["fixture"],
        "suggested_next_steps_for_codex": ["test"],
    }
    import hashlib

    for item in sync["deliverables"]:
        item["sha256"] = hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
    (work_dir / "grok-to-codex-latest.json").write_text(json.dumps(sync), encoding="utf-8")
    (work_dir / "grok-to-codex-latest.md").write_text("sync", encoding="utf-8")
    (work_dir / "dashboard-status.json").write_text(json.dumps({"已发送": 3}), encoding="utf-8")
    return tmp_path


def test_build_takeover_recomputes_counts_and_hashes(tmp_path: Path):
    result = build_takeover(_fixture(tmp_path))
    assert result["ready"] is False
    assert result["counts"]["counted_institutional"] == 3
    assert result["priority_counts"] == {"P0": 1, "P1": 1, "P2": 1, "待核": 1}
    assert result["verification"]["grok_deliverables_hashes_match"] is True
    assert result["counts"]["social_sent_verified"] == 2


def test_write_takeover_creates_codex_artifacts(tmp_path: Path):
    json_path, markdown_path, result = write_takeover(_fixture(tmp_path))
    assert json_path.exists()
    assert markdown_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema"] == "codex-polyv-takeover.v1"
    assert "Codex 接管基线" in markdown_path.read_text(encoding="utf-8")
