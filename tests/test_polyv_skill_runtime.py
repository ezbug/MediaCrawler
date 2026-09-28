from __future__ import annotations

from pathlib import Path

from local_tools.polyv_radar.skill_runtime import inspect_skill_runtime


def test_skill_runtime_reports_missing_behavior_markers(tmp_path: Path) -> None:
    path = tmp_path / "auto_reply.mjs"
    path.write_text("export const run = true;", encoding="utf-8")

    result = inspect_skill_runtime(path)

    assert result["status"] == "incomplete"
    assert "--source-type" in result["missing_markers"]


def test_installed_skill_runtime_is_traceable() -> None:
    result = inspect_skill_runtime()

    assert result["status"] == "ready"
    assert len(str(result["sha256"])) == 64
