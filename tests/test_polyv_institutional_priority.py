"""Institutional priority banding must age with the calendar.

The frozen P0/P1/P2 let closed business keep occupying live priority slots, and
never re-banded as deadlines approached. These tests pin the rule.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from local_tools.polyv_radar.institutional_priority import (
    CLOSED_AWARDED,
    EXPIRED_OPEN,
    PENDING,
    actionable_sorted,
    classify,
    counts,
    is_actionable,
    parse_deadline,
    recompute,
)

TODAY = dt.date(2026, 9, 29)


def d(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


# --- deadline parsing -----------------------------------------------------


def test_parses_iso_and_cjk_dates() -> None:
    assert parse_deadline("2026-09-30 09:00") == d("2026-09-30")
    assert parse_deadline("异议截止：2025年1月21日") == d("2025-01-21")
    assert parse_deadline("截止时间为2025年4月29日") == d("2025-04-29")


def test_parses_date_out_of_free_text() -> None:
    """Deadline fields are prose; the first real date is the deadline."""
    assert parse_deadline("已成交（响应截止曾为2026-06-26）；服务期2026-06-19—2029") == d("2026-06-26")


def test_missing_or_unparseable_deadline_is_none_not_a_guess() -> None:
    assert parse_deadline(None) is None
    assert parse_deadline("") is None
    assert parse_deadline("递交时间待定") is None
    assert parse_deadline("2026-13-45") is None  # invalid month/day


def test_falls_back_to_second_field() -> None:
    assert parse_deadline("（无日期）", "比选已截止（2026-04-09）") == d("2026-04-09")


# --- banding --------------------------------------------------------------


@pytest.mark.parametrize("deadline,expected", [
    ("2026-09-29", "P0"),   # D = 0
    ("2026-09-30", "P0"),   # D = 1
    ("2026-10-06", "P0"),   # D = 7  (upper bound of P0)
    ("2026-10-07", "P1"),   # D = 8  (lower bound of P1)
    ("2026-10-29", "P1"),   # D = 30 (upper bound of P1)
    ("2026-10-30", "P2"),   # D = 31
    ("2027-03-01", "P2"),
])
def test_future_deadlines_band_by_days_remaining(deadline: str, expected: str) -> None:
    assert classify(d(deadline), awarded=False, today=TODAY).band == expected


def test_past_deadline_with_winner_is_closed_awarded() -> None:
    result = classify(d("2026-06-26"), awarded=True, today=TODAY)
    assert result.band == CLOSED_AWARDED
    assert result.days_to_deadline == -95
    assert is_actionable(result) is False


def test_past_deadline_without_winner_is_expired_open() -> None:
    result = classify(d("2026-09-14"), awarded=False, today=TODAY)
    assert result.band == EXPIRED_OPEN
    assert is_actionable(result) is False


def test_unknown_deadline_is_pending_and_not_actionable() -> None:
    result = classify(None, awarded=False, today=TODAY)
    assert result.band == PENDING
    assert result.days_to_deadline is None
    assert is_actionable(result) is False


def test_urgency_moves_with_today() -> None:
    """The same lead is P1 today, P0 two days later, expired nine days later."""
    deadline = d("2026-10-07")          # D = 8 as of 2026-09-29
    assert classify(deadline, False, TODAY).band == "P1"
    assert classify(deadline, False, TODAY + dt.timedelta(days=2)).band == "P0"
    assert classify(deadline, False, TODAY + dt.timedelta(days=9)).band == EXPIRED_OPEN


# --- pipeline hygiene -----------------------------------------------------


def _row(**overrides) -> dict:
    base = {
        "id": "lead-x",
        "bucket": "可核验需求线索",
        "deadline": "2026-10-05",
        "project_status": "招标进行中",
        "winner": "",
        "sales_priority": "P2",
    }
    base.update(overrides)
    return base


def test_closed_business_leaves_the_active_bands() -> None:
    rows = [
        _row(id="live-near", deadline="2026-09-30", sales_priority="P2"),
        _row(id="awarded", deadline="2026-06-01", winner="某公司", sales_priority="P0"),
        _row(id="expired", deadline="2026-08-01", sales_priority="P0"),
        _row(id="unknown", deadline="待定", sales_priority="P1"),
    ]
    items = recompute(rows, TODAY)
    by_id = {i["row"]["id"]: i for i in items}

    # the frozen P0/P1 slots held closed business; after recompute they do not
    assert by_id["live-near"]["new_priority"] == "P0"
    assert by_id["awarded"]["new_priority"] == CLOSED_AWARDED
    assert by_id["expired"]["new_priority"] == EXPIRED_OPEN
    assert by_id["unknown"]["new_priority"] == PENDING

    live = actionable_sorted(items)
    assert [i["row"]["id"] for i in live] == ["live-near"]


def test_counts_cover_every_row_exactly_once() -> None:
    rows = [
        _row(id="a", deadline="2026-09-30"),
        _row(id="b", deadline="2026-10-10"),
        _row(id="c", deadline="2026-06-01", winner="某公司"),
        _row(id="d", deadline="待定"),
    ]
    items = recompute(rows, TODAY)
    result = counts(items)
    assert sum(result.values()) == len(rows)
    assert result["P0"] == 1 and result["P1"] == 1
    assert result[CLOSED_AWARDED] == 1 and result[PENDING] == 1
    # no row is double-counted and no band is invented
    assert set(result) <= {"P0", "P1", "P2", CLOSED_AWARDED, EXPIRED_OPEN, PENDING}


def test_recompute_does_not_mutate_input_rows() -> None:
    row = _row(sales_priority="P0", deadline="2026-06-01", winner="某公司")
    snapshot = dict(row)
    recompute([row], TODAY)
    assert row == snapshot


def test_actionable_sorted_is_soonest_first() -> None:
    rows = [
        _row(id="far", deadline="2026-10-20"),
        _row(id="near", deadline="2026-09-30"),
        _row(id="mid", deadline="2026-10-05"),
    ]
    assert [i["row"]["id"] for i in actionable_sorted(recompute(rows, TODAY))] == ["near", "mid", "far"]


# --- the live ledger contract --------------------------------------------


LEDGER = Path("/Users/sexpistole111/Documents/workplace/polyv-radar-data"
              "/grok-work/polyv-100/demand-leads-20-ledger.json")


@pytest.mark.skipif(not LEDGER.is_file(), reason="institutional ledger not present")
def test_live_ledger_recompute_is_self_consistent() -> None:
    import json

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    rows = [r for r in ledger["rows"] if r.get("bucket") == "可核验需求线索"]
    items = recompute(rows, TODAY)

    assert len(items) == 20
    assert sum(counts(items).values()) == 20
    # closed business must not hold active slots
    for item in items:
        if item["winner"] or (item["days_to_deadline"] is not None and item["days_to_deadline"] < 0):
            assert not item["actionable"]
    assert len(actionable_sorted(items)) == 5
