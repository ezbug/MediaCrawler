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
* Brand is part of the target identity. POLYV and ZigoAI keep separate stores
  and send ledgers, so identical-looking targets in the two brands are not
  merged in the combined board.
* A *send event* is a ledger row that was actually sent (``live`` mode and the
  click/legacy-submitted flag).  Duplicate events for the same target are
  reported explicitly rather than silently merged, so ``events`` and
  ``unique targets`` are both visible and self-explaining.
* Raw ledger rows are never modified or rewritten.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: `2026-09-23T14:32:48.123Z` -> captures (YYYY, MM, DD, hh, mm, ss)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})")

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


def load_zigo_send_logs(data_root: Path | str) -> list[dict]:
    """Project ZigoAI send logs into the dashboard's read-only row shape.

    ZigoAI deliberately keeps its own database and outreach files. This
    adapter is only for the combined dashboard and never writes either source.
    """
    root = Path(data_root)
    rows: list[dict] = []
    for path in sorted(root.glob("zigoai/**/outreach/*/send-log.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        platform = str(payload.get("platform") or "").casefold()
        platform = {
            "xiaohongshu": "xhs",
            "xhs": "xhs",
            "douyin": "dy",
            "bilibili": "bili",
            "zhihu": "zhihu",
        }.get(platform, platform or "unknown")
        recorded_at = payload.get("recorded_at") or ""
        for item in payload.get("records") or []:
            if not isinstance(item, dict):
                continue
            screenshots = item.get("screenshots") or {}
            screenshot_name = screenshots.get("recheck") or screenshots.get("after") or screenshots.get("before")
            screenshot = str(path.parent / screenshot_name) if screenshot_name else ""
            status = str(item.get("status") or "")
            rows.append({
                "brand": "zigo",
                "platform": platform,
                "timestamp": item.get("timestamp") or recorded_at,
                "target_author": item.get("author"),
                "target_quote": item.get("source_quote"),
                "target_url": item.get("content_url"),
                "comment_url": item.get("comment_url"),
                "native_comment_id": item.get("native_comment_id"),
                "candidate_id": item.get("candidate_id"),
                "reply_text": item.get("draft"),
                "source_type": item.get("source_type"),
                "mode": "live",
                "clicked": True,
                "submitted": True,
                "verified": status == "submitted_verified",
                "target_matched": True,
                "draft_verified": True,
                "screenshot": screenshot,
                "status": status,
                "notes": item.get("recheck") or item.get("submit_evidence"),
                "source_file": str(path),
                "product_domain": item.get("product_domain") or payload.get("product_domain") or "zigoai",
            })
    return rows


def load_combined_history(ledger_path: Path | str, data_root: Path | str) -> list[dict]:
    """Read POLYV and ZigoAI send sources without merging their stores."""
    history = load_history(ledger_path)
    projections = load_zigo_send_logs(data_root)
    def event_key(row):
        return tuple(str(row.get(key) or '') for key in ('platform', 'timestamp', 'target_author', 'target_url', 'target_quote', 'reply_text'))
    metadata = {event_key(row): row for row in projections}
    matched = set()
    for row in history:
        key = event_key(row)
        if key in metadata:
            row['brand'] = 'zigo'
            row['product_domain'] = metadata[key]['product_domain']
            if metadata[key].get('verified') is True:
                row['verified'] = True
                row['status'] = metadata[key]['status']
                row['screenshot'] = metadata[key]['screenshot'] or row.get('screenshot', '')
            matched.add(key)
    return history + [row for row in projections if event_key(row) not in matched]


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


def target_key(row: dict) -> tuple[str, str, str, str, str]:
    """THE dedupe key: brand + platform + author + url + original quote.

    Deliberately excluded:

    * the reply wording — rewording a draft must not create a new identity,
      otherwise the same target gets touched twice (this is exactly how 20
      targets received two different replies ~7-12h apart);
    * ``source_type`` — it is bookkeeping about the target, not part of its
      identity. Two runs that labelled the same target differently must still
      collapse. (Including it silently split 20 real duplicates back out.)
    """
    return (
        _norm(row.get("brand") or "polyv"),
        _norm(row.get("platform")),
        _norm(row.get("target_author")),
        _norm(row.get("target_url")),
        _norm(row.get("target_quote")),
    )


# --------------------------------------------------------------------------
# The single data view
# --------------------------------------------------------------------------

BRAND_LABELS = {"polyv": "POLYV", "zigo": "ZigoAI"}
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
    events = []
    for row in rows:
        if is_send_event(row):
            normalized = dict(row)
            normalized.setdefault("brand", "polyv")
            events.append(normalized)
    by_key: dict[tuple[str, str, str, str, str], dict] = {}
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


PAGE_CSS = (
    ':root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17202a;'
    'background:#f5f7fa}\n'
    '*{box-sizing:border-box}body{margin:0;padding:28px}main{max-width:1500px;margin:auto}\n'
    'h1{margin:0 0 8px;font-size:26px}p{color:#5b6573;margin:6px 0 20px}'
    '.metrics{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px;margin-bottom:18px}\n'
    '.metric{background:#fff;border:1px solid #dfe5ec;border-radius:8px;padding:15px}'
    '.metric strong{display:block;font-size:24px;margin-top:5px}'
    '.metric span{font-size:13px;color:#647181}\n'
    '.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}'
    '.toolbar input,.toolbar select{height:36px;border:1px solid #cfd7e1;border-radius:6px;'
    'background:#fff;padding:0 10px;font-size:14px}\n'
    '.table-wrap{background:#fff;border:1px solid #dfe5ec;border-radius:8px;overflow:auto}'
    'table{border-collapse:collapse;width:100%;min-width:2480px}'
    'th,td{border-bottom:1px solid #edf0f3;padding:11px 12px;text-align:left;vertical-align:top;font-size:13px}'
    'th{position:sticky;top:0;background:#f8fafc;color:#4d5968;z-index:1;white-space:nowrap}'
    '.quote{min-width:360px;max-width:520px;line-height:1.5}'
    '.reply{min-width:420px;max-width:620px;line-height:1.5;white-space:pre-wrap}'
    '.cell-wrap{min-width:180px;max-width:300px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}'
    '.url-cell{min-width:270px;max-width:390px}.url-line{display:flex;align-items:flex-start;gap:9px;min-width:240px;line-height:1.45}.url-line a{flex:0 0 auto;white-space:nowrap}.url-value{display:block;min-width:0;overflow-wrap:anywhere;word-break:break-word;color:#6b7280;font-size:12px}'
    '.proof{display:flex;flex-wrap:wrap;gap:4px;min-width:220px}.proof span{display:inline-block;border-radius:999px;padding:3px 7px;font-size:11px;background:#eef1f5;color:#657080}.proof .ok{background:#e7f6ec;color:#21733c}.proof .warn{background:#fff4db;color:#8a5b00}.proof .bad{background:#fdebec;color:#a12a36}'
    '.badge,.status{display:inline-block;border-radius:999px;padding:3px 8px;background:#e8f1ff;'
    'color:#245a9c;font-size:12px}.status{background:#e7f6ec;color:#21733c}'
    '.brand-badge{display:inline-block;border-radius:999px;padding:3px 8px;background:#f2eaff;'
    'color:#7046a5;font-size:12px}'
    'small{color:#6b7280}a{color:#2364aa;text-decoration:none}a:hover{text-decoration:underline}'
    '.note{background:#fffbe8;border:1px solid #f0df9b;border-radius:8px;padding:12px 14px;'
    'margin:0 0 16px;color:#6b5515;font-size:13px}\n'
    '@media(max-width:700px){body{padding:16px}.metrics{grid-template-columns:repeat(2,1fr)}h1{font-size:22px}}'
)

FILTER_SCRIPT = """const search=document.querySelector('#search'), brand=document.querySelector('#brand'), platform=document.querySelector('#platform'), body=document.querySelector('#rows'), visible=document.querySelector('#visible');
const metrics=window.DASHBOARD_METRICS||{};
function updateMetrics(){const activeMetrics=metrics[brand.value]||metrics.all||{}; const keys=['targets','events','group:dy','group:xhs','group:zhihu']; [...document.querySelectorAll('.metric strong')].forEach((node,index)=>{node.textContent=String(activeMetrics[keys[index]]??0);});}
function filter(){const q=search.value.trim().toLowerCase(), b=brand.value, p=platform.value; let n=0; [...body.rows].forEach(row=>{const hit=(!b||row.dataset.brand===b)&&(!p||row.dataset.platform===p)&&(!q||row.dataset.text.toLowerCase().includes(q));row.hidden=!hit;if(hit)n++;});updateMetrics();visible.textContent='当前显示 '+n+' 条';}
search.addEventListener('input',filter);brand.addEventListener('change',filter);platform.addEventListener('change',filter);filter();"""

#: Display grouping for the metric cards / filter dropdown. B站 shares the
#: 知乎 card because B站 carries no live sends in this ledger — the card label
#: stays honest by naming both platforms.
DISPLAY_GROUPS = [("dy", "抖音"), ("xhs", "小红书"), ("zhihu", "知乎 / B站", ("bili",))]


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _short(value: object, limit: int = 200) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _display_time(value: object) -> str:
    """ISO -> the dashboard's `2026/9/23 14:32:48` form (no timezone shift)."""
    raw = str(value or "")
    m = _ISO.match(raw)
    if not m:
        return raw
    year, month, day, hh, mm, ss = m.groups()
    return f"{year}/{int(month)}/{int(day)} {hh}:{mm}:{ss}"


def _status_cell(row: dict) -> str:
    verified = row.get("verified")
    clicked = row.get("clicked")
    if verified is True or (clicked is None and row.get("submitted") is True):
        return '<span class="status">已发送并回查</span><br><small>本地未记录对方回复</small>'
    if clicked is True:
        return '<span class="badge">已发送待回查</span><br><small>未核验到已发布文本</small>'
    return '<span class="badge">未发送</span>'


SOURCE_TYPE_LABELS = {
    "comment": "评论",
    "reply": "子评论",
    "comment_reply": "子评论",
    "answer": "回答",
    "post": "帖子",
    "content": "内容",
}


def _first_value(row: dict, *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def _cell_value(row: dict, *names: str, fallback: str = "未记录") -> str:
    value = _first_value(row, *names)
    return value if value else fallback


def _link(value: str, label: str) -> str:
    if not value:
        return "<small>未记录</small>"
    return f'<div class="url-line"><a href="{_esc(value)}" target="_blank" rel="noreferrer">{_esc(label)}</a><small class="url-value">{_esc(value)}</small></div>'


def _artifact_link(value: str, label: str) -> str:
    """Link a local evidence file through the API's guarded evidence route."""
    raw = str(value or "").strip()
    if not raw:
        return "<small>未记录</small>"
    if raw.startswith(("http://", "https://")):
        return _link(raw, label)
    marker = "/polyv-radar-data/"
    if marker in raw:
        api_link = _link("/polyv-evidence/" + raw.split(marker, 1)[1], label)
        local_path = Path(raw).expanduser()
        if local_path.is_file():
            local_link = _link(local_path.resolve().as_uri(), "本地文件")
            return f'<div class="url-cell">{api_link}{local_link}</div>'
        return api_link
    return f'<small class="cell-wrap">{_esc(raw)}</small>'


def _source_type(row: dict) -> str:
    raw = _first_value(row, "source_type")
    return SOURCE_TYPE_LABELS.get(raw.casefold(), raw) if raw else "未标注"


def _proof_badge(label: str, value: object, *, missing: str = "未记录") -> str:
    if value is True:
        return f'<span class="ok">{_esc(label)}✓</span>'
    if value is False:
        return f'<span class="bad">{_esc(label)}×</span>'
    return f'<span class="warn">{_esc(label)}{_esc(missing)}</span>'


def _proof_cell(row: dict) -> str:
    clicked = row.get("clicked")
    submitted = row.get("submitted")
    if clicked is None and submitted is not None:
        clicked = submitted
    return (
        '<div class="proof">'
        + _proof_badge("定位", row.get("target_matched"))
        + _proof_badge("草稿", row.get("draft_verified"))
        + _proof_badge("点击", clicked)
        + _proof_badge("提交", submitted)
        + _proof_badge("回查", row.get("verified"))
        + "</div>"
    )


def _response_cell(row: dict) -> str:
    value = _first_value(row, "received_reply", "inbound_reply", "response_text", "engagement")
    if value:
        return _esc(value)
    if any(row.get(name) is True for name in ("has_response", "engaged", "replied")):
        return '<span class="status">已记录回复</span>'
    return '<small>未记录</small>'


def _comment_locator(row: dict) -> tuple[str, str]:
    """Return the best available comment/answer locator without inventing an anchor."""
    direct = _first_value(row, "comment_url", "reply_url")
    if direct:
        return direct, "打开评论定位"
    content = _first_value(row, "target_url", "content_url", "url")
    if content and _source_type(row) in {"评论", "子评论"}:
        return content, "打开评论页（无独立锚点）"
    if content:
        return content, "打开目标页（类型未记录）"
    return "", "打开定位"



def display_groups(view: DashboardView) -> list[tuple[str, int]]:
    """Ordered metric cards. zhihu+bili share one card, as in the original layout."""
    subtotals = view.platform_subtotals()
    out = []
    for entry in DISPLAY_GROUPS:
        code, label = entry[0], entry[1]
        extra = entry[2] if len(entry) > 2 else ()
        count = subtotals.get(code, 0) + sum(subtotals.get(c, 0) for c in extra)
        out.append((label, count))
    return out


def render_cumulative_dashboard(view: DashboardView, generated_at: str, source_label: str) -> str:
    """Render the dashboard from ONE keyed view.

    Layout, CSS, column set, filter script and row markup match the original
    artifact; only the numbers change, and they all come from `view` so the
    header cards, the platform split and the table body cannot disagree.
    """
    groups = display_groups(view)
    rows = sorted(view.targets, key=lambda row: str(row.get("timestamp") or ""), reverse=True)

    brand_views = {"all": view}
    for brand in BRAND_LABELS:
        brand_views[brand] = build_view(
            [row for row in view.events if str(row.get("brand") or "polyv") == brand]
        )

    def metric_values(selected: DashboardView) -> dict[str, int]:
        values = {"targets": selected.target_count, "events": selected.event_count}
        for entry, (_label, count) in zip(DISPLAY_GROUPS, display_groups(selected)):
            values[f"group:{entry[0]}"] = count
        return values

    metrics_json = json.dumps(
        {key: metric_values(selected) for key, selected in brand_views.items()},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    cards = "\n".join(
        f'  <div class="metric"><span>{_esc(label)}</span><strong>{count}</strong></div>'
        for metric_key, label, count in [
            ("targets", "去重后发送线索", view.target_count),
            ("events", "原始已发送记录", view.event_count),
            *[(f"group:{entry[0]}", entry[1], count) for entry, (_label, count) in zip(DISPLAY_GROUPS, groups)],
        ]
    )

    options = "".join(
        f'<option value="{_esc(label)}">{_esc(label)}</option>' for label, _count in groups
    )

    brand_options = '<option value="">全部品牌</option>' + "".join(
        f'<option value="{_esc(code)}">{_esc(label)}</option>' for code, label in BRAND_LABELS.items()
    )

    body = "\n".join(
        f'<tr data-platform="{_esc(PLATFORM_LABELS.get(str(row.get("platform") or ""), str(row.get("platform") or "")))}" data-brand="{_esc(str(row.get("brand") or "polyv"))}"'
        f' data-text="{_esc(" ".join(part for part in [BRAND_LABELS.get(str(row.get("brand") or "polyv"), str(row.get("brand") or "")), PLATFORM_LABELS.get(str(row.get("platform") or ""), str(row.get("platform") or "")), _source_type(row), str(row.get("target_author") or ""), str(row.get("target_quote") or ""), str(row.get("reply_text") or ""), str(row.get("target_url") or "")] if part))}">\n'
        f'    <td>{index}</td>\n'
        f'    <td><span class="brand-badge">{_esc(BRAND_LABELS.get(str(row.get("brand") or "polyv"), str(row.get("brand") or "")))}</span></td>\n'
        f'    <td><span class="badge">{_esc(PLATFORM_LABELS.get(str(row.get("platform") or ""), str(row.get("platform") or "")))}</span></td>\n'
        f'    <td>{_esc(row.get("target_author"))}</td>\n'
        f'    <td class="quote">{_esc(_short(row.get("target_quote")))}</td>\n'
        f'    <td>{_esc(_display_time(row.get("timestamp")))}</td>\n'
        f'    <td class="url-cell">{_link(_first_value(row, "target_url", "content_url", "url"), "打开来源")}</td>\n'
        f'    <td>{_status_cell(row)}</td>\n'
        f'    <td class="cell-wrap">{_esc(_source_type(row))}</td>\n'
        f'    <td class="cell-wrap">{_esc(_cell_value(row, "title", "content_title", "event_type", "business_scene"))}</td>\n'
        f'    <td class="cell-wrap">{_esc(_cell_value(row, "author_url", "profile_url", "user_url"))}</td>\n'
        f'    <td class="cell-wrap">{_esc(_cell_value(row, "content_id", "native_content_id", "comment_id", "native_comment_id", "candidate_id"))}</td>\n'
        f'    <td class="url-cell">{_link(*_comment_locator(row))}</td>\n'
        f'    <td class="url-cell">{_artifact_link(_first_value(row, "screenshot", "evidence_path"), "查看截图")}</td>\n'
        f'    <td class="reply">{_esc(row.get("reply_text")) if row.get("reply_text") else "<small>未记录</small>"}</td>\n'
        f'    <td>{_proof_cell(row)}</td>\n'
        f'    <td class="cell-wrap">{_esc(_cell_value(row, "score", "qualification", "identity_confidence", "quality"))}</td>\n'
        f'    <td>{_response_cell(row)}</td>\n'
        f'    <td class="cell-wrap">{_esc(_cell_value(row, "failure_code", "failure_reason", "notes", "verification"))}</td>\n'
        f'  </tr>'
        for index, row in enumerate(rows, start=1)
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>POLYV + ZigoAI 全项目发送线索累计大板</title>
<style>
{PAGE_CSS}
</style>
</head>
<body><main>
<h1>POLYV + ZigoAI 全项目发送线索累计大板</h1>
<p>数据源：<code>{_esc(source_label)}</code>｜生成时间：{_esc(generated_at)}｜品牌分别读取，按品牌、平台、作者、来源链接和目标原话去重（不含回复文案、不含来源类型）</p>
<div class="note">“已发送并回查”只表示我方发送成功且页面回查通过。POLYV 与 ZigoAI 的数据库和发送账本保持独立；顶部统计和下表可用品牌筛选分别查看。当前全部视图：{view.event_count} 条原始已发送记录 − {view.duplicate_events} 条重复触达 = {view.target_count} 条去重后发送线索。</div>
<section class="metrics">
{cards}
</section>
<div class="toolbar"><input id="search" type="search" placeholder="搜索品牌、平台、来源类型、用户、原话、文案或链接"><select id="brand">{brand_options}</select><select id="platform"><option value="">全部平台</option>{options}</select><span id="visible" style="padding:9px 2px;color:#5b6573;font-size:13px"></span></div>
<div class="table-wrap"><table><thead><tr><th>#</th><th>品牌</th><th>平台</th><th>用户</th><th>原话</th><th>发送时间</th><th>来源</th><th>状态</th><th>来源类型</th><th>内容标题/业务场景</th><th>用户主页</th><th>目标 ID</th><th>评论 URL / 回答定位</th><th>发送证据</th><th>我方回复文案</th><th>发送链路</th><th>评分/质量</th><th>对方回复</th><th>失败/备注</th></tr></thead><tbody id="rows">
{body}
</tbody></table></div>
</main>
<script>
window.DASHBOARD_METRICS={metrics_json};
{FILTER_SCRIPT}
</script>
</body></html>
"""


def render_from_ledger(ledger_path: Path | str) -> tuple[str, DashboardView]:
    """Convenience: load a ledger and render the dashboard plus its view."""
    import datetime as _dt

    rows = load_history(ledger_path)
    view = build_view(rows)
    stamp = _dt.datetime.now().astimezone().strftime("%Y-%m-%d")
    return render_cumulative_dashboard(view, stamp, Path(ledger_path).name), view


def render_from_sources(ledger_path: Path | str, data_root: Path | str) -> tuple[str, DashboardView]:
    """Render the combined send board while keeping source stores separate."""
    import datetime as _dt

    rows = load_combined_history(ledger_path, data_root)
    view = build_view(rows)
    stamp = _dt.datetime.now().astimezone().strftime("%Y-%m-%d")
    return render_cumulative_dashboard(view, stamp, "reply_history.jsonl + zigoai/**/send-log.json"), view
