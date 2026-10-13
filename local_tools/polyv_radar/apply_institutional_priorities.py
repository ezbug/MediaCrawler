"""Write recomputed priorities back into the institutional ledger.

`institutional_priority.recompute` decides the bands; this module applies them to
the ledger document. The application is **additive and idempotent**:

* the pre-merge value is preserved once under ``sales_priority_original`` and is
  never overwritten on later runs;
* terminal leads (already awarded, or past deadline without an award) get
  ``sales_priority: null`` plus an explicit ``pipeline_state``, so a reader that
  filters ``sales_priority is not None`` sees exactly the actionable set;
* every other field, and every row outside the scope bucket, is left untouched.

The original ledger is never destroyed — the caller backs it up first (see
``scripts/apply_institutional_priorities.py``).
"""

from __future__ import annotations

import copy
import datetime as dt

from .institutional_priority import (
    CLOSED_AWARDED,
    EXPIRED_OPEN,
    PENDING,
    recompute,
)

DEFAULT_BUCKET = "可核验需求线索"
TERMINAL_STATES = (CLOSED_AWARDED, EXPIRED_OPEN, PENDING)
STATE_ACTIVE = "active"


def _basis(item: dict) -> str:
    """One-line human explanation of why this band was chosen."""
    band = item["new_priority"]
    days = item["days_to_deadline"]
    deadline = item["deadline"]
    if band == PENDING:
        return "deadline unparseable; needs human check"
    if band == CLOSED_AWARDED:
        return f"winner already recorded ({item['winner']}); deadline {deadline} passed"
    if band == EXPIRED_OPEN:
        return f"deadline {deadline} passed with no recorded winner"
    return f"deadline {deadline}, {days} day(s) remaining"


def _effective_current(row: dict) -> str:
    """How this row's band currently reads, whether or not it was merged before.

    A terminal row stores ``sales_priority: null`` plus a ``pipeline_state``; its
    effective band is the state, not "未分级". Getting this wrong makes every
    already-merged row look like it changed, so the ledger gets rewritten — and
    its timestamp bumped — on every run.
    """
    if "pipeline_state" in row:
        return str(row.get("sales_priority") or row.get("pipeline_state") or "未分级")
    return str(row.get("sales_priority") or "未分级")


def apply_priorities(ledger: dict, today: dt.date, bucket: str = DEFAULT_BUCKET) -> tuple[dict, dict]:
    """Return ``(updated_ledger, summary)``. The input document is not mutated."""
    updated = copy.deepcopy(ledger)
    rows = updated.get("rows") or []
    scoped = [r for r in rows if r.get("bucket") == bucket]

    items = recompute(scoped, today)

    before: dict[str, int] = {}
    after: dict[str, int] = {}
    changed: list[dict] = []

    for item in items:
        row = item["row"]
        old = _effective_current(row)
        before[old] = before.get(old, 0) + 1

        state = STATE_ACTIVE if item["actionable"] else item["new_priority"]
        new_value = item["new_priority"] if item["actionable"] else None
        new_label = str(new_value if new_value is not None else state)

        # preserve the pre-merge value exactly once
        if "sales_priority_original" not in row:
            row["sales_priority_original"] = row.get("sales_priority")

        row["sales_priority"] = new_value
        row["pipeline_state"] = state
        row["priority_recomputed_at"] = today.isoformat()
        row["priority_basis"] = _basis(item)

        after[new_label] = after.get(new_label, 0) + 1
        if old != new_label:
            changed.append({
                "id": row.get("id"),
                "subject": row.get("subject"),
                "before": old,
                "after": new_label,
                "pipeline_state": state,
                "deadline": item["deadline"].isoformat() if item["deadline"] else None,
                "days_to_deadline": item["days_to_deadline"],
            })

    # preserve the previous summary block once, then publish the current truth
    if "priority_recompute" not in updated:
        updated["sales_priority_counts_before_recompute"] = copy.deepcopy(
            updated.get("sales_priority_counts")
        )
    updated["sales_priority_counts"] = after
    updated["priority_recompute"] = {
        "applied_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "scope_bucket": bucket,
        "rule_module": "local_tools.polyv_radar.institutional_priority",
        "before": before,
        "after": after,
        "changed_count": len(changed),
        "actionable_count": sum(1 for i in items if i["actionable"]),
        "note": (
            "sales_priority 仅对仍可跟进的机会给出 P0/P1/P2；已成交/已截止/待核的行 "
            "sales_priority 置为 null 并以 pipeline_state 表达状态。"
            "原始分级保留在 sales_priority_original。"
        ),
    }

    summary = {
        "scope_rows": len(scoped),
        "before": before,
        "after": after,
        "changed_count": len(changed),
        "actionable_count": updated["priority_recompute"]["actionable_count"],
        "changed": changed,
    }
    return updated, summary
