"""Writing recomputed priorities back into the institutional ledger.

The merge must be additive (the original band survives), idempotent (re-running
never clobbers the preserved original), and scoped (unverified rows untouched).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from local_tools.polyv_radar.apply_institutional_priorities import (
    DEFAULT_BUCKET,
    apply_priorities,
)
from local_tools.polyv_radar.institutional_priority import (
    CLOSED_AWARDED,
    EXPIRED_OPEN,
    PENDING,
)

TODAY = dt.date(2026, 9, 29)


def _row(**overrides) -> dict:
    base = {
        "id": "lead-x",
        "bucket": DEFAULT_BUCKET,
        "counts_toward_20": True,
        "subject": "某单位",
        "source_url": "https://example.com/x",
        "deadline": "2026-10-05",
        "project_status": "招标进行中",
        "demand_quote": "需要直播平台",
        "polyv_match": "强匹配",
        "winner": "",
        "sales_priority": "P2",
    }
    base.update(overrides)
    return base


def _ledger(rows) -> dict:
    return {
        "schema_version": 1,
        "rows": rows,
        "counts": {"total": len(rows)},
        "sales_priority_counts": {"P0": 5, "P1": 7, "P2": 8, "待核_pool": 26},
    }


# --- scope -----------------------------------------------------------------


def test_only_the_scope_bucket_is_touched() -> None:
    ledger = _ledger([
        _row(id="counted", deadline="2026-09-30"),
        _row(id="pending", bucket="待核", deadline="2026-09-30", sales_priority=None),
        _row(id="filtered", bucket="过滤", deadline="2026-09-30", sales_priority=None),
    ])
    updated, summary = apply_priorities(ledger, TODAY)

    assert summary["scope_rows"] == 1
    by_id = {r["id"]: r for r in updated["rows"]}
    assert by_id["counted"]["pipeline_state"] == "active"
    # out-of-scope rows gain none of the new fields
    for other in ("pending", "filtered"):
        assert "pipeline_state" not in by_id[other]
        assert "sales_priority_original" not in by_id[other]
        assert "priority_basis" not in by_id[other]


def test_input_document_is_not_mutated() -> None:
    row = _row()
    ledger = _ledger([row])
    snapshot = copy.deepcopy(ledger)
    apply_priorities(ledger, TODAY)
    assert ledger == snapshot


# --- additive + idempotent -------------------------------------------------


def test_original_band_is_preserved() -> None:
    updated, _ = apply_priorities(_ledger([_row(sales_priority="P0", deadline="2026-06-01")]), TODAY)
    row = updated["rows"][0]
    assert row["sales_priority_original"] == "P0"
    assert row["sales_priority"] is None          # past deadline, no winner
    assert row["pipeline_state"] == EXPIRED_OPEN


def test_reapplying_never_clobbers_the_preserved_original() -> None:
    first, _ = apply_priorities(_ledger([_row(sales_priority="P0", deadline="2026-06-01")]), TODAY)
    second, _ = apply_priorities(first, TODAY)
    assert second["rows"][0]["sales_priority_original"] == "P0"

    # and re-running on its own output is a no-op apart from the timestamp
    third, _ = apply_priorities(second, TODAY)
    for key in ("sales_priority", "pipeline_state", "sales_priority_original", "priority_basis"):
        assert third["rows"][0][key] == second["rows"][0][key]


def test_original_is_taken_from_the_first_live_value_not_the_merged_one() -> None:
    """A second run must not record the merged (null) value as the original."""
    first, _ = apply_priorities(_ledger([_row(sales_priority="P1", deadline="2026-05-01")]), TODAY)
    assert first["rows"][0]["sales_priority_original"] == "P1"
    second, _ = apply_priorities(first, TODAY)
    assert second["rows"][0]["sales_priority_original"] == "P1"


def test_reapplying_a_merged_ledger_reports_no_change() -> None:
    """Terminal rows store sales_priority=null, so their effective band is the
    pipeline_state. Reading it as "未分级" made every merged row look changed,
    which rewrote the ledger (and bumped its timestamp) on every run."""
    merged, first = apply_priorities(_ledger([
        _row(id="near", deadline="2026-09-30"),
        _row(id="expired", deadline="2026-06-01"),
        _row(id="awarded", deadline="2026-06-01", winner="某公司"),
        _row(id="undated", deadline="待定"),
    ]), TODAY)
    assert first["changed_count"] == 4          # from the pre-merge state

    _again, second = apply_priorities(merged, TODAY)
    assert second["changed_count"] == 0, second["changed"]
    assert second["before"] == second["after"]


# --- banding applied -------------------------------------------------------


def test_active_rows_get_a_band_and_terminal_rows_do_not() -> None:
    updated, summary = apply_priorities(_ledger([
        _row(id="near", deadline="2026-09-30"),                    # D=1  -> P0
        _row(id="mid", deadline="2026-10-08"),                     # D=9  -> P1
        _row(id="far", deadline="2026-12-01"),                     # D=63 -> P2
        _row(id="expired", deadline="2026-06-01"),                 # -> null
        _row(id="awarded", deadline="2026-06-01", winner="某公司"),  # -> null
        _row(id="undated", deadline="待定"),                        # -> null
    ]), TODAY)
    by_id = {r["id"]: r for r in updated["rows"]}

    assert by_id["near"]["sales_priority"] == "P0"
    assert by_id["mid"]["sales_priority"] == "P1"
    assert by_id["far"]["sales_priority"] == "P2"
    for terminal, state in (("expired", EXPIRED_OPEN), ("awarded", CLOSED_AWARDED), ("undated", PENDING)):
        assert by_id[terminal]["sales_priority"] is None
        assert by_id[terminal]["pipeline_state"] == state

    assert summary["actionable_count"] == 3


def test_every_scoped_row_carries_a_basis_string() -> None:
    updated, _ = apply_priorities(_ledger([
        _row(id="a", deadline="2026-09-30"),
        _row(id="b", deadline="2026-06-01"),
        _row(id="c", deadline="2026-06-01", winner="某公司"),
        _row(id="d", deadline="待定"),
    ]), TODAY)
    for row in updated["rows"]:
        assert isinstance(row["priority_basis"], str) and row["priority_basis"]
    bases = {r["id"]: r["priority_basis"] for r in updated["rows"]}
    assert "1 day" in bases["a"]
    assert "no recorded winner" in bases["b"]
    assert "winner already recorded" in bases["c"]
    assert "unparseable" in bases["d"]


# --- counts block ---------------------------------------------------------


def test_counts_block_is_updated_and_sums_to_scope() -> None:
    updated, summary = apply_priorities(_ledger([
        _row(id="near", deadline="2026-09-30"),
        _row(id="mid", deadline="2026-10-08"),
        _row(id="expired", deadline="2026-06-01"),
    ]), TODAY)
    counts = updated["sales_priority_counts"]
    assert counts == {"P0": 1, "P1": 1, EXPIRED_OPEN: 1}
    assert sum(counts.values()) == summary["scope_rows"]


def test_previous_counts_block_is_preserved_once() -> None:
    first, _ = apply_priorities(_ledger([_row(deadline="2026-09-30")]), TODAY)
    assert first["sales_priority_counts_before_recompute"] == {
        "P0": 5, "P1": 7, "P2": 8, "待核_pool": 26,
    }
    first["sales_priority_counts"] = {"bogus": 1}   # simulate drift
    second, _ = apply_priorities(first, TODAY)
    # the preserved snapshot is written once and not overwritten by later runs
    assert second["sales_priority_counts_before_recompute"] == {
        "P0": 5, "P1": 7, "P2": 8, "待核_pool": 26,
    }


def test_unrelated_top_level_keys_survive() -> None:
    updated, _ = apply_priorities(_ledger([_row()]), TODAY)
    assert updated["schema_version"] == 1
    assert updated["counts"] == {"total": 1}


def test_other_row_fields_are_preserved() -> None:
    updated, _ = apply_priorities(_ledger([_row(demand_quote="需要直播平台", polyv_match="强匹配")]), TODAY)
    row = updated["rows"][0]
    assert row["demand_quote"] == "需要直播平台"
    assert row["polyv_match"] == "强匹配"
    assert row["counts_toward_20"] is True
    assert row["source_url"] == "https://example.com/x"


# --- the live ledger contract --------------------------------------------


LEDGER = Path("/Users/sexpistole111/Documents/workplace/polyv-radar-data"
              "/grok-work/polyv-100/demand-leads-20-ledger.json")


@pytest.mark.skipif(not LEDGER.is_file(), reason="institutional ledger not present")
def test_live_ledger_merge_is_consistent() -> None:
    """Check the merge against the real ledger, merged or not yet merged."""
    on_disk = json.loads(LEDGER.read_text(encoding="utf-8"))

    if "priority_recompute" not in on_disk:
        # not merged yet: the merge must be correct and must not touch the input
        snapshot = copy.deepcopy(on_disk)
        updated, summary = apply_priorities(on_disk, TODAY)
        assert on_disk == snapshot, "apply_priorities mutated the input document"
        assert summary["scope_rows"] == 20
        assert summary["actionable_count"] == 5
        assert sum(updated["sales_priority_counts"].values()) == 20
    else:
        # already merged: re-running must be a no-op on the meaningful fields
        updated, summary = apply_priorities(on_disk, TODAY)
        assert summary["scope_rows"] == 20
        assert summary["actionable_count"] == 5
        for before, after in zip(on_disk["rows"], updated["rows"]):
            for key in ("sales_priority", "pipeline_state",
                        "sales_priority_original", "priority_basis"):
                assert before.get(key) == after.get(key), f"{before.get('id')}::{key} drifts"

    # structural invariants hold in both states
    assert len(on_disk["rows"]) == 99
    scoped = [r for r in on_disk["rows"] if r.get("bucket") == DEFAULT_BUCKET]
    assert len(scoped) == 20
    untouched = [r for r in on_disk["rows"] if r.get("bucket") != DEFAULT_BUCKET]
    assert all("pipeline_state" not in r for r in untouched)
