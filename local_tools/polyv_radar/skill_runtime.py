from __future__ import annotations

import hashlib
from pathlib import Path


SKILL_RUNTIME_SCRIPT = Path("/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs")
REQUIRED_MARKERS = (
    "--source-type",
    "contentLevel",
    "screenshot_skipped",
    "submitted",
    "verified",
)


def inspect_skill_runtime(path: Path = SKILL_RUNTIME_SCRIPT) -> dict[str, object]:
    """Return an auditable snapshot of the external reply runtime.

    The skill is intentionally outside this repository.  A content hash and
    required behavior markers make the runtime used by a dispatch traceable
    without copying credentials or the skill into Git.
    """
    target = Path(path)
    if not target.is_file():
        return {"status": "missing", "path": str(target), "sha256": "", "missing_markers": list(REQUIRED_MARKERS)}
    try:
        content = target.read_bytes()
    except OSError as exc:
        return {"status": "unreadable", "path": str(target), "sha256": "", "error": str(exc)}
    missing = [marker for marker in REQUIRED_MARKERS if marker.encode("utf-8") not in content]
    return {
        "status": "ready" if not missing else "incomplete",
        "path": str(target),
        "sha256": hashlib.sha256(content).hexdigest(),
        "missing_markers": missing,
    }


def require_skill_runtime(path: Path = SKILL_RUNTIME_SCRIPT) -> dict[str, object]:
    status = inspect_skill_runtime(path)
    if status.get("status") != "ready":
        raise RuntimeError(
            "POLYV 自动回复运行时校验失败: "
            f"{status.get('status')} {status.get('missing_markers', '')}"
        )
    return status
