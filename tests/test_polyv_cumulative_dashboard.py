"""Cumulative dashboard must derive every number from one data view.

Regression cover for the 102-vs-103 defect: the legacy file counted the header
with ``(platform, author, url)`` but the table body with
``(platform, author, url, quote)``, so the top line and the rows disagreed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from local_tools.polyv_radar.cumulative_dashboard import (
    build_view,
    is_send_event,
    load_history,
    render_cumulative_dashboard,
    render_from_ledger,
    target_key,
)

REAL_LEDGER = Path("/Users/sexpistole111/Documents/workplace/polyv-radar-data/reply_history.jsonl")


def _row(**overrides) -> dict:
    base = {
        "timestamp": "2026-09-20T09:49:10.977Z",
        "platform": "zhihu",
        "target_url": "https://zhuanlan.zhihu.com/p/1",
        "target_author": "lumina",
        "target_quote": "有没有防录屏的视频分享平台？",
        "reply_text": "第一版文案",
        "source_type": "comment",
        "mode": "live",
        "clicked": True,
        "submitted": True,
        "verified": True,
        "status": "submitted_verified",
    }
    base.update(overrides)
    return base


def _write_ledger(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "reply_history.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def _parse_counts(html_text: str) -> tuple[int, int]:
    """Return (header target count, number of table data rows)."""
    header = re.search(r"<span>去重后发送线索</span><strong>(\d+)</strong>", html_text)
    assert header, "header target count not found"
    body = html_text.split('<tbody id="rows">', 1)[1].split("</tbody>", 1)[0]
    return int(header.group(1)), body.count("<tr data-platform=")


def _cards(html_text: str) -> dict:
    """The metric cards as {label: value} — every number the page shows."""
    return {label: int(value) for label, value in re.findall(
        r'<div class="metric"><span>([^<]+)</span><strong>(\d+)</strong></div>', html_text
    )}


# --- the defect -----------------------------------------------------------


def test_header_table_and_subtotals_agree(tmp_path: Path) -> None:
    rows = [
        _row(platform="zhihu", target_author="a", target_url="u1", target_quote="q1"),
        _row(platform="zhihu", target_author="b", target_url="u2", target_quote="q2"),
        _row(platform="xhs", target_author="c", target_url="u3", target_quote="q3"),
    ]
    html_text, view = render_from_ledger(_write_ledger(tmp_path, rows))

    header, table_rows = _parse_counts(html_text)
    assert header == 3
    assert table_rows == 3
    assert header == view.target_count
    assert sum(view.platform_subtotals().values()) == view.target_count

    # every number on the page must reconcile with the same view
    cards = _cards(html_text)
    platform_cards = {k: v for k, v in cards.items()
                      if k not in ("去重后发送线索", "原始已发送记录")}
    assert sum(platform_cards.values()) == view.target_count
    assert cards["原始已发送记录"] - view.duplicate_events == cards["去重后发送线索"]


def test_layout_keeps_the_original_template(tmp_path: Path) -> None:
    """The corrected dashboard must not lose the original look/behaviour."""
    rows = [_row(platform="zhihu", target_author="a", target_url="u1", target_quote="q1")]
    html_text, _ = render_from_ledger(_write_ledger(tmp_path, rows))

    # original CSS + structure
    assert "max-width:1500px" in html_text
    assert '.badge,.status{display:inline-block;border-radius:999px' in html_text
    assert '<section class="metrics">' in html_text
    assert '<div class="toolbar">' in html_text
    assert '<div class="table-wrap">' in html_text
    # original 7 columns, in the original order
    for header_cell in ("<th>#</th>", "<th>平台</th>", "<th>用户</th>", "<th>原话</th>",
                        "<th>发送时间</th>", "<th>来源</th>", "<th>状态</th>"):
        assert header_cell in html_text
    # original row markup: platform badge, quote class, status pill, source link
    assert '<span class="badge">知乎</span>' in html_text
    assert '<td class="quote">q1</td>' in html_text
    assert '<span class="status">已发送并回查</span>' in html_text
    assert 'target="_blank" rel="noreferrer">打开来源</a>' in html_text
    # original client-side filter script and its hooks
    assert "const search=document.querySelector('#search')" in html_text
    assert "current" not in html_text  # no leftover placeholder text


def test_dashboard_exposes_send_and_evidence_fields(tmp_path: Path) -> None:
    row = _row(
        source_type="comment",
        target_matched=True,
        draft_verified=True,
        comment_url="https://www.zhihu.com/question/1#comment-2",
        author_url="https://www.zhihu.com/people/lumina",
        native_comment_id="comment-2",
        title="企业培训平台选型",
        reply_text="围绕人数、权限和交付方式做选型表。",
        screenshot="/tmp/reply-preview.png",
    )
    html_text, _ = render_from_ledger(_write_ledger(tmp_path, [row]))

    for header_cell in (
        "<th>来源类型</th>",
        "<th>内容标题/业务场景</th>",
        "<th>用户主页</th>",
        "<th>目标 ID</th>",
        "<th>评论 URL / 回答定位</th>",
        "<th>发送证据</th>",
        "<th>我方回复文案</th>",
        "<th>发送链路</th>",
        "<th>对方回复</th>",
    ):
        assert header_cell in html_text
    assert "企业培训平台选型" in html_text
    assert "围绕人数、权限和交付方式做选型表。" in html_text
    assert "comment-2" in html_text
    assert "定位✓" in html_text
    assert "草稿✓" in html_text
    assert "回查✓" in html_text


def test_platform_filter_uses_platform_labels_not_counts(tmp_path: Path) -> None:
    html_text, _ = render_from_ledger(_write_ledger(tmp_path, [
        _row(platform="dy"),
        _row(platform="xhs", target_url="u2"),
    ]))
    assert '<option value="抖音">抖音</option>' in html_text
    assert '<option value="小红书">小红书</option>' in html_text
    assert '<option value="知乎 / B站">知乎 / B站</option>' in html_text
    assert '<option value="2">2</option>' not in html_text


def test_comment_locator_falls_back_to_content_page_without_claiming_anchor(tmp_path: Path) -> None:
    row = _row(source_type="comment", comment_url="")
    html_text, _ = render_from_ledger(_write_ledger(tmp_path, [row]))
    assert "打开评论页（无独立锚点）" in html_text
    assert "https://zhuanlan.zhihu.com/p/1" in html_text


def test_missing_extended_fields_are_explicitly_unrecorded(tmp_path: Path) -> None:
    html_text, _ = render_from_ledger(_write_ledger(tmp_path, [_row()]))
    assert html_text.count("未记录") >= 5


def test_single_author_on_two_pages_is_two_targets(tmp_path: Path) -> None:
    rows = [
        _row(target_author="Poon", target_url="u1", target_quote="q1"),
        _row(target_author="Poon", target_url="u2", target_quote="q2"),
    ]
    html_text, view = render_from_ledger(_write_ledger(tmp_path, rows))
    assert view.target_count == 2
    assert _parse_counts(html_text) == (2, 2)


def test_same_page_two_distinct_quotes_are_two_targets(tmp_path: Path) -> None:
    """The exact case behind the legacy 102 -> 103 delta."""
    rows = [
        _row(
            target_author="lumina",
            target_url="https://zhuanlan.zhihu.com/p/1989299790115275469",
            target_quote="同学，这种‘切屏录制’的情况确实防不胜防。",
        ),
        _row(
            target_author="lumina",
            target_url="https://zhuanlan.zhihu.com/p/1989299790115275469",
            target_quote="有没有防录屏的视频分享平台？",
        ),
    ]
    view = build_view(rows)
    assert view.target_count == 2
    assert view.event_count == 2
    assert view.duplicate_events == 0


# --- dedupe independent of wording ---------------------------------------


def test_reworded_reply_collapses_to_one_target(tmp_path: Path) -> None:
    rows = [
        _row(reply_text="第一版文案", timestamp="2026-09-22T03:20:53.204Z"),
        _row(reply_text="第二版完全不同的文案", timestamp="2026-09-22T15:15:44.711Z"),
    ]
    view = build_view(rows)
    assert view.event_count == 2
    assert view.target_count == 1
    assert view.duplicate_events == 1

    html_text, _ = render_from_ledger(_write_ledger(tmp_path, rows))
    header, table_rows = _parse_counts(html_text)
    assert (header, table_rows) == (1, 1)
    cards = _cards(html_text)
    assert cards["原始已发送记录"] == 2
    assert cards["去重后发送线索"] == 1
    # the note states the arithmetic explicitly
    assert "2 条原始已发送记录 − 1 条重复触达 = 1 条去重后发送线索" in html_text


def test_target_key_ignores_reply_text() -> None:
    a = _row(reply_text="文案甲")
    b = _row(reply_text="文案乙")
    assert target_key(a) == target_key(b)


def test_target_key_separates_different_quotes() -> None:
    a = _row(target_quote="预算多少")
    b = _row(target_quote="另一个问题")
    assert target_key(a) != target_key(b)


def test_source_type_does_not_split_target_identity() -> None:
    """Regression: labelling the same target differently must not hide a dup.

    Including source_type in the dedupe key silently re-split 20 genuine
    duplicate touches back out of the live ledger (123 targets instead of 103).
    """
    a = _row(source_type="comment")
    b = _row(source_type="reply")
    assert target_key(a) == target_key(b)
    view = build_view([a, b])
    assert view.event_count == 2
    assert view.target_count == 1
    assert view.duplicate_events == 1


# --- event selection ------------------------------------------------------


def test_dry_run_rows_are_not_send_events() -> None:
    rows = [
        _row(mode="dry_run", clicked=False, submitted=False, verified=False),
        _row(),
    ]
    view = build_view(rows)
    assert view.event_count == 1
    assert view.target_count == 1


def test_rows_without_clicked_field_fall_back_to_submitted() -> None:
    legacy = _row()
    legacy.pop("clicked")
    assert is_send_event(legacy) is True

    not_clicked = _row(clicked=False, submitted=False, verified=False)
    assert is_send_event(not_clicked) is False


def test_clicked_but_unverified_still_counts_as_a_send_event() -> None:
    """Result unclear must not silently drop the target from the ledger view."""
    row = _row(clicked=True, submitted=True, verified=False, status="submitted_unverified")
    assert is_send_event(row) is True
    view = build_view([row])
    assert view.target_count == 1


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "reply_history.jsonl"
    path.write_text(
        json.dumps(_row(), ensure_ascii=False) + "\n" + "{not json\n" + "\n",
        encoding="utf-8",
    )
    assert len(load_history(path)) == 1


# --- real ledger contract -------------------------------------------------


@pytest.mark.skipif(not REAL_LEDGER.is_file(), reason="live ledger not present")
def test_live_ledger_view_is_self_consistent() -> None:
    rows = load_history(REAL_LEDGER)
    view = build_view(rows)
    recon = view.reconciliation()

    # events - duplicates == unique targets, by construction
    assert recon["send_events"] - recon["duplicate_events"] == recon["unique_targets"]
    assert sum(view.platform_subtotals().values()) == view.target_count

    html_text = render_cumulative_dashboard(view, "test", "reply_history.jsonl")
    header, table_rows = _parse_counts(html_text)
    assert header == view.target_count == table_rows


@pytest.mark.skipif(not REAL_LEDGER.is_file(), reason="live ledger not present")
def test_live_ledger_header_no_longer_disagrees_with_table() -> None:
    """The legacy artefact had header 102 vs 103 rows. That must not recur."""
    view = build_view(load_history(REAL_LEDGER))
    html_text = render_cumulative_dashboard(view, "test", "reply_history.jsonl")
    header, table_rows = _parse_counts(html_text)
    assert header == table_rows
