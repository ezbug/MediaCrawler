"""Institutional demand lead priority banding.

The original P0/P1/P2 was a recency ranking by deadline, computed once when the
ledger was written. Two things must be recomputed on any given day:

1. **Urgency ages.** The band must be computed against *today*, not against a
   frozen date.
2. **Closed business must leave the pipeline.** A lead that is already awarded,
   or whose deadline has passed without an award, is not an actionable sales
   follow-up. Letting those keep occupying P0/P1/P2 makes the board look like it
   has work when it does not.

This module is deliberately pure: `today` is always injected, never read from the
clock, so results are reproducible and testable.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

#: distance-to-deadline bands, in days, applied when the deadline is in the future
BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 7, "P0"),        # 本周内截止
    (8, 30, "P1"),       # 一个月内截止
    (31, 10_000, "P2"),  # 更远
)

CLOSED_AWARDED = "closed_awarded"  # 已成交
EXPIRED_OPEN = "expired_open"      # 已过截止且未成交
PENDING = "pending"                # 日期无法解析，待人工核

ACTIVE_BANDS = ("P0", "P1", "P2")

_DATE_RE = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})")


def parse_deadline(*values: object) -> dt.date | None:
    """First parseable YYYY-MM-DD-ish date among the given strings, else None.

    Deadlines in the ledger are free text (``"2026-09-30 09:00"``,
    ``"异议截止：2025年1月21日"``, ``"已成交（响应截止曾为2026-06-26）"``). Only an
    explicit three-part date counts; anything else stays unparsed rather than
    being guessed from context.
    """
    for value in values:
        match = _DATE_RE.search(str(value or ""))
        if not match:
            continue
        year, month, day = (int(group) for group in match.groups())
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class Priority:
    band: str
    days_to_deadline: int | None
    deadline: dt.date | None


def classify(deadline: dt.date | None, awarded: bool, today: dt.date) -> Priority:
    """Band a single lead as of ``today``."""
    if deadline is None:
        return Priority(PENDING, None, None)
    days = (deadline - today).days
    if days < 0:
        return Priority(CLOSED_AWARDED if awarded else EXPIRED_OPEN, days, deadline)
    for low, high, label in BANDS:
        if low <= days <= high:
            return Priority(label, days, deadline)
    return Priority("P2", days, deadline)


def is_actionable(priority: Priority) -> bool:
    """Only future-deadline leads belong in the sales pipeline."""
    return priority.band in ACTIVE_BANDS


def recompute(rows, today: dt.date, deadline_fields=("deadline", "project_status"),
              winner_field="winner", priority_field="sales_priority"):
    """Return per-row dicts with the recomputed band, plus before/after counts.

    Accepts mappings; does not mutate the input rows.
    """
    out = []
    for row in rows:
        deadline = parse_deadline(*(row.get(f) for f in deadline_fields))
        awarded = bool(str(row.get(winner_field) or "").strip())
        result = classify(deadline, awarded, today)
        out.append({
            "row": row,
            "old_priority": str(row.get(priority_field) or "未分级"),
            "new_priority": result.band,
            "deadline": result.deadline,
            "days_to_deadline": result.days_to_deadline,
            "winner": row.get(winner_field) or None,
            "actionable": is_actionable(result),
        })
    return out


def counts(items) -> dict[str, int]:
    """Counts per band over ``recompute`` output (every row counted once)."""
    result: dict[str, int] = {}
    for item in items:
        result[item["new_priority"]] = result.get(item["new_priority"], 0) + 1
    return result


def actionable_sorted(items):
    """Actionable rows, soonest deadline first."""
    live = [i for i in items if i["actionable"]]
    live.sort(key=lambda i: i["days_to_deadline"] if i["days_to_deadline"] is not None else 10_000)
    return live
