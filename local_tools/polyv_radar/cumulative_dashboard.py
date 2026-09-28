"""Cumulative sent-leads dashboard — single data view.

The legacy dashboard had two different dedupe keys in one file: the header
counted ``(platform, author, url)`` while the table body counted
``(platform, author, url, quote)``.  On the 2026-09-28 ledger that produced a
header of 102 and 103 table rows, with per-platform subtotals that matched
neither.

This module derives **every** number from one keyed view, so the top-line
total, the per-platform subtotals and the table body can never disagree again.

Design rules
------------
* One dedupe key (:func:`target_key`) is used for the header, the subtotals and
  the rows.
* A *send event* is a ledger row that was actually sent (``live`` mode and the
  click/legacy-submitted flag).  Duplicate events for the same target are
  reported explicitly rather than silently merged, so ``events`` and
  ``unique targets`` are both visible and self-explaining.
* Raw ledger rows are never modified or rewritten.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Ledger loading
# --------------------------------------------------------------------------


def load_history(path: Path | str) -> list[dict]:
    """Load a JSONL ledger, skipping blank and unparseable lines."""
    rows: list[dict] = []
    p = Path(path)
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def is_send_event(row: dict) -> bool:
    """Whether a ledger row represents an actual send attempt that went out.

    New rows record ``clicked`` explicitly (the click and its verification are
    now separate fields).  Legacy rows predate that field and only have
    ``submitted``, which historically mirrored ``verified``.  Either is accepted
    so old and new rows can live in the same view.
    """
    if str(row.get("mode") or "") != "live":
        return False
    if "clicked" in row:
        return row.get("clicked") is True
    return row.get("submitted") is True


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def target_key(row: dict) -> tuple[str, str, str, str]:
    """THE dedupe key: platform + author + url + original quote.

    Deliberately excluded:

    * the reply wording — rewording a draft must not create a new identity,
      otherwise the same target gets touched twice (this is exactly how 20
      targets received two different replies ~7-12h apart);
    * ``source_type`` — it is bookkeeping about the target, not part of its
      identity. Two runs that labelled the same target differently must still
      collapse. (Including it silently split 20 real duplicates back out.)
    """
    return (
        _norm(row.get("platform")),
        _norm(row.get("target_author")),
        _norm(row.get("target_url")),
        _norm(row.get("target_quote")),
    )


# --------------------------------------------------------------------------
# The single data view
# --------------------------------------------------------------------------

PLATFORM_LABELS = {"dy": "抖音", "xhs": "小红书", "zhihu": "知乎", "bili": "B站"}


@dataclass
class DashboardView:
    events: list[dict] = field(default_factory=list)
    targets: list[dict] = field(default_factory=list)
    duplicate_events: int = 0

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def target_count(self) -> int:
        return len(self.targets)

    def platform_subtotals(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.targets:
            key = str(row.get("platform") or "")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def platform_label(self, code: str) -> str:
        return PLATFORM_LABELS.get(code, code or "未知")

    def reconciliation(self) -> dict[str, int]:
        """Self-explaining arithmetic: events - duplicates == unique targets."""
        return {
            "send_events": self.event_count,
            "duplicate_events": self.duplicate_events,
            "unique_targets": self.target_count,
        }


def build_view(rows: list[dict]) -> DashboardView:
    """Collapse raw ledger rows into the one keyed view every number comes from."""
    events = [row for row in rows if is_send_event(row)]
    by_key: dict[tuple[str, str, str, str], dict] = {}
    duplicate_events = 0
    for row in sorted(events, key=lambda item: str(item.get("timestamp") or "")):
        key = target_key(row)
        if key in by_key:
            duplicate_events += 1
            prior = by_key[key]
            prior.setdefault("_duplicate_of", []).append(row.get("timestamp"))
            continue
        by_key[key] = dict(row)
    view = DashboardView(events=events, targets=list(by_key.values()), duplicate_events=duplicate_events)
    return view


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _short(value: object, limit: int = 90) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_cumulative_dashboard(view: DashboardView, generated_at: str, source_label: str) -> str:
    """Render header + subtotals + table from the SAME view object."""
    subtotals = view.platform_subtotals()
    recon = view.reconciliation()
    targets = sorted(
        view.targets,
        key=lambda row: str(row.get("timestamp") or ""),
        reverse=True,
    )

    stat_cards = [
        ("去重后发送线索", view.target_count),
        ("原始已发送记录", view.event_count),
        ("重复触达记录", view.duplicate_events),
    ]
    for code in sorted(subtotals):
        stat_cards.append((view.platform_label(code), subtotals[code]))

    cards_html = "\n".join(
        f'      <div class="metric"><span class="metric-value">{value}</span>'
        f'<span class="metric-label">{_esc(label)}</span></div>'
        for label, value in stat_cards
    )

    subtotal_html = " + ".join(
        f"{view.platform_label(code)} {count}" for code, count in sorted(subtotals.items())
    )

    rows_html = []
    for index, row in enumerate(targets, start=1):
        status = row.get("status") or ("已发送并回查" if row.get("verified") else "已发送待回查")
        rows_html.append(
            "      <tr"
            f' data-platform="{_esc(row.get("platform"))}">'
            f"<td>{index}</td>"
            f"<td>{_esc(view.platform_label(str(row.get('platform') or '')))}</td>"
            f"<td>{_esc(row.get('target_author'))}</td>"
            f"<td>{_esc(_short(row.get('target_quote')))}</td>"
            f"<td>{_esc(str(row.get('timestamp') or '').replace('T', ' ')[:19])}</td>"
            f'<td><a href="{_esc(row.get("target_url"))}" target="_blank" rel="noreferrer">打开来源</a></td>'
            f"<td>{_esc(status)}</td>"
            "</tr>"
        )
    table_html = "\n".join(rows_html)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>POLYV 全项目发送线索累计大板</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; padding: 28px 18px 60px; background: #f7f3ea; color: #2b2b2b;
         font-family: "PingFang SC", "Kaiti SC", -apple-system, "Helvetica Neue", Arial, sans-serif; }}
  .wrap {{ max-width: 1080px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin: 0 0 6px; letter-spacing: .5px; }}
  .meta {{ color: #7a7266; font-size: 13px; margin-bottom: 18px; line-height: 1.7; }}
  .metrics {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0 8px; }}
  .metric {{ background: #fffaf1; border-radius: 10px; padding: 14px 18px; min-width: 118px;
             box-shadow: 0 1px 3px rgba(90, 70, 40, .12); }}
  .metric-value {{ display: block; font-size: 26px; font-weight: 600; color: #8a5a2b; }}
  .metric-label {{ display: block; font-size: 12px; color: #7a7266; margin-top: 4px; }}
  .recon {{ background: #fffaf1; border-left: 3px solid #c9a227; border-radius: 8px;
            padding: 12px 16px; font-size: 13px; line-height: 1.8; color: #5c5449; margin: 16px 0 22px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fffaf1; border-radius: 10px;
           overflow: hidden; box-shadow: 0 1px 3px rgba(90, 70, 40, .12); }}
  th, td {{ border-bottom: 1px solid #efe6d6; padding: 10px 12px; font-size: 13px; text-align: left; vertical-align: top; }}
  th {{ background: #f3ead9; font-weight: 600; color: #6b4f2a; }}
  a {{ color: #8a5a2b; }}
  @media (max-width: 430px) {{
    body {{ padding: 18px 10px 40px; }}
    .metric {{ flex: 1 1 44%; min-width: 0; padding: 11px 12px; }}
    .metric-value {{ font-size: 21px; }}
    table {{ display: block; overflow-x: auto; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1>POLYV 全项目发送线索累计大板</h1>
  <div class="meta">
    数据源：{_esc(source_label)} ｜ 生成时间：{_esc(generated_at)}<br>
    去重键：平台 + 作者 + 来源链接 + 目标原话（<strong>不含回复文案、不含来源类型</strong>）。
  </div>

  <div class="metrics">
{cards_html}
  </div>

  <div class="recon">
    <strong>计数自洽：</strong>原始已发送记录 {recon['send_events']} − 重复触达 {recon['duplicate_events']}
    = 去重后发送线索 {recon['unique_targets']}。平台小计：{_esc(subtotal_html)}（合计 {view.target_count}）。
    顶部数字、平台小计与下表行数均来自同一个去重视图。
  </div>

  <table>
    <thead>
      <tr><th>#</th><th>平台</th><th>用户</th><th>原话</th><th>发送时间</th><th>来源</th><th>状态</th></tr>
    </thead>
    <tbody>
{table_html}
    </tbody>
  </table>
</div>
</body>
</html>
"""


def render_from_ledger(ledger_path: Path | str) -> tuple[str, DashboardView]:
    """Convenience: load a ledger and render the dashboard plus its view."""
    import datetime as _dt

    rows = load_history(ledger_path)
    view = build_view(rows)
    stamp = _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    return render_cumulative_dashboard(view, stamp, Path(ledger_path).name), view
