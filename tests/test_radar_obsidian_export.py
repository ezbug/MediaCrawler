"""Obsidian export must mirror the cumulative dashboard view exactly.

The vault is a read-only projection of the same keyed view the HTML board
uses. These tests pin the contract: one note per de-duplicated target,
marker-guarded cleanup, wave/score enrichment, and create-once layout files.
"""

from __future__ import annotations

import json
from pathlib import Path

from local_tools.polyv_radar.cumulative_dashboard import build_view, load_combined_history
from local_tools.polyv_radar.obsidian_export import (
    GENERATED_BY,
    export_to_vault,
    load_lead_index,
)


def _row(**overrides) -> dict:
    base = {
        "timestamp": "2026-09-20T09:00:00.000Z",
        "platform": "zhihu",
        "target_url": "https://zhuanlan.zhihu.com/p/1",
        "target_author": "阿尔法",
        "target_quote": "有没有防录屏的视频分享平台？",
        "reply_text": "想问问具体咋样的？我之前也有类似问题",
        "source_type": "comment",
        "mode": "live",
        "clicked": True,
        "submitted": True,
        "verified": True,
    }
    base.update(overrides)
    return base


def _write_ledger(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _note_for(notes_dir: Path, author: str) -> str:
    matches = sorted(notes_dir.glob(f"*{author}*.md"))
    assert matches, f"no note for {author}: {[p.name for p in notes_dir.glob('*.md')]}"
    return matches[0].read_text(encoding="utf-8")


def test_export_counts_match_dashboard_view(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    ledger = data_root / "reply_history.jsonl"
    _write_ledger(
        ledger,
        [
            _row(),
            _row(
                target_author="贝塔",
                target_quote="培训平台怎么选",
                timestamp="2026-09-21T09:00:00.000Z",
                verified=False,
            ),
            _row(timestamp="2026-09-22T09:00:00.000Z"),
        ],
    )

    stats = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    view = build_view(load_combined_history(ledger, data_root))

    assert stats["target_count"] == view.target_count == 2
    assert stats["event_count"] == 3
    assert stats["duplicate_events"] == 1
    assert stats["verified_count"] == 1
    assert stats["unverified_count"] == 1

    notes_dir = Path(stats["notes_dir"])
    assert len(list(notes_dir.glob("*.md"))) == 2
    note = _note_for(notes_dir, "阿尔法")
    assert f'generated_by: "{GENERATED_BY}"' in note
    assert "duplicate_events: 1" in note
    assert "已发送并回查" in note
    unverified = _note_for(notes_dir, "贝塔")
    assert "已发送待回查" in unverified


def test_export_is_idempotent_and_cleans_only_generated_notes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    ledger = data_root / "reply_history.jsonl"
    _write_ledger(
        ledger,
        [
            _row(),
            _row(target_author="贝塔", target_quote="培训平台怎么选", timestamp="2026-09-21T09:00:00.000Z"),
        ],
    )

    first = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    second = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    assert second["notes_written"] == first["notes_written"] == 2
    assert second["notes_removed"] == 0

    notes_dir = Path(second["notes_dir"])
    manual = notes_dir / "手写笔记.md"
    manual.write_text("keep me", encoding="utf-8")

    _write_ledger(ledger, [_row()])
    third = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    assert third["notes_removed"] == 1
    assert manual.read_text(encoding="utf-8") == "keep me"
    assert len(list(notes_dir.glob("*.md"))) == 2


def test_reply_signal_marks_second_wave(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    ledger = data_root / "reply_history.jsonl"
    _write_ledger(ledger, [_row()])
    (data_root / "reply_signals.jsonl").write_text(
        json.dumps(
            {
                "platform": "zhihu",
                "target_url": "https://zhuanlan.zhihu.com/p/1",
                "target_author": "阿尔法",
                "reply_author": "小鹅通官方",
                "quote": "对方第二次回复",
                "wave": 2,
                "observed_at": "2026-10-12T03:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    stats = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    assert stats["second_wave_count"] == 1
    note = _note_for(Path(stats["notes_dir"]), "阿尔法")
    assert "reply_wave: 2" in note
    assert "小鹅通官方" in note
    assert "对方第二次回复" in note
    assert (Path(stats["vault_dir"]) / "雷达总览.base").read_text(encoding="utf-8").count("二次回复待设计") >= 1


def test_score_enrichment_comes_from_lead_file(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    ledger = data_root / "reply_history.jsonl"
    _write_ledger(ledger, [_row(target_quote="想找企业培训平台，问下报价")])
    reports = data_root / "reports"
    reports.mkdir()
    (reports / "20261012-new10-dy-sales-leads.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "platform": "zhihu",
                        "author": "阿尔法",
                        "quote": "想找企业培训平台，问下报价",
                        "rule_score": 4,
                        "need_type": "企业培训",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert load_lead_index(data_root)
    stats = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    assert stats["scored_count"] == 1
    note = _note_for(Path(stats["notes_dir"]), "阿尔法")
    assert "score: 4" in note
    assert "评分：4" in note


def test_structured_notes_are_serialized_as_json(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    ledger = data_root / "reply_history.jsonl"
    _write_ledger(ledger, [_row(notes={"posted_text": False, "target_relation": False})])

    stats = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    note = _note_for(Path(stats["notes_dir"]), "阿尔法")
    assert '"posted_text": false' in note


def test_unscored_note_omits_score_property(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    ledger = data_root / "reply_history.jsonl"
    _write_ledger(ledger, [_row()])

    stats = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    note = _note_for(Path(stats["notes_dir"]), "阿尔法")
    frontmatter = note.split("---", 2)[1]
    assert "score:" not in frontmatter


def test_layout_files_are_create_once_unless_forced(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    ledger = data_root / "reply_history.jsonl"
    _write_ledger(ledger, [_row()])

    stats = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    base = Path(stats["vault_dir"]) / "雷达总览.base"
    assert stats["layout_written"] == {"base": True, "index": True}
    base.write_text("filters: 'custom'\n", encoding="utf-8")

    again = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault")
    assert again["layout_written"] == {"base": False, "index": False}
    assert base.read_text(encoding="utf-8") == "filters: 'custom'\n"

    forced = export_to_vault(ledger, data_root, vault_root=tmp_path / "vault", force_layout=True)
    assert forced["layout_written"] == {"base": True, "index": True}
    assert "views:" in base.read_text(encoding="utf-8")
