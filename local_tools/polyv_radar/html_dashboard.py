from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from .dashboard import load_manual_candidates


PLATFORM_NAMES = {
    "dy": "抖音",
    "xhs": "小红书",
    "bili": "B站",
    "zhihu": "知乎",
}


def _text(value: object) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def _link(value: object, label: str) -> str:
    url = str(value or "").strip()
    if not url:
        return "<span class='muted'>暂无</span>"
    return f"<a href='{_text(url)}' target='_blank' rel='noreferrer'>{_text(label)} ↗</a>"


def _evidence_link(data_root: Path, path_value: object) -> str:
    path = Path(str(path_value or ""))
    if not path.is_file():
        return "<span class='muted'>暂无截图</span>"
    try:
        relative = path.resolve().relative_to(data_root.resolve()).as_posix()
    except ValueError:
        return "<span class='muted'>截图路径不在数据目录</span>"
    return _link(f"/polyv-evidence/{quote(relative)}", "查看截图")


def _status(row: dict) -> tuple[str, str]:
    dispatch_status = str(row.get("dispatch_status") or row.get("dry_run_status") or "").strip()
    failure_code = str(row.get("failure_code") or row.get("send_reason_code") or "").strip()
    if dispatch_status == "submitted_verified" or (row.get("submitted") and row.get("verified")):
        return "sent", "已发送并回查"
    if failure_code == "target_url_normalization":
        return "blocked", "目标地址规范化失败"
    if failure_code == "page_not_found":
        return "blocked", "页面不存在，已归档"
    if failure_code == "content_unavailable":
        return "blocked", "内容已失效，已归档"
    if failure_code == "screenshot_evidence_timeout":
        return "blocked", "截图证据超时"
    if failure_code == "post_verification_missed":
        return "blocked", "帖子级回查未完成"
    if failure_code == "blocked_login_required":
        return "blocked", "登录态受限"
    if dispatch_status == "aborted_quality_gate":
        return "blocked", "已暂停发送"
    if dispatch_status == "pending_send":
        return "pending", "已定位待发送"
    if dispatch_status == "held":
        return "blocked", "待审不发送"
    if dispatch_status == "content_unavailable" or failure_code == "content_unavailable":
        return "blocked", "内容已失效，已归档"
    if dispatch_status == "page_not_found" or failure_code == "page_not_found":
        return "blocked", "页面不存在，已归档"
    if dispatch_status == "target_url_normalization" or failure_code == "target_url_normalization":
        return "blocked", "目标地址规范化失败"
    if dispatch_status == "screenshot_evidence_timeout" or failure_code == "screenshot_evidence_timeout":
        return "blocked", "截图证据超时"
    if dispatch_status == "target_not_found" or failure_code == "target_not_found":
        return "blocked", "目标未找到"
    if dispatch_status == "blocked_login_required" or failure_code == "blocked_login_required":
        return "blocked", "登录态受限"
    if dispatch_status == "failed":
        return "blocked", "发送失败，待复核"
    dry_run_status = str(row.get("dry_run_status", "")).strip()
    if dry_run_status == "dry_run":
        if row.get("target_matched") and row.get("draft_verified"):
            return "dry", "Dry-Run通过"
        return "blocked", "Dry-Run未验证"
    if dry_run_status == "failed":
        return "blocked", "Dry-Run失败"
    locator_status = str(row.get("locator_status", "")).strip()
    if locator_status == "verified":
        return "locator", "Ego Lite 已定位"
    if locator_status:
        return "blocked", f"定位{locator_status}"
    return "pending", "待重新定位"


def _dispatch_status(row: dict) -> tuple[str, str]:
    status = str(row.get("dispatch_status") or row.get("dry_run_status") or "").strip()
    labels = {
        "submitted_verified": ("sent", "已发送并回查"),
        "submitted_unverified": ("blocked", "已发送待回查"),
        "pending_send": ("pending", "已定位待发送"),
        "held": ("blocked", "待审不发送"),
        "aborted_quality_gate": ("blocked", "质量门暂停"),
        "content_unavailable": ("blocked", "内容已失效，已归档"),
        "page_not_found": ("blocked", "页面不存在，已归档"),
        "target_url_normalization": ("blocked", "目标地址规范化失败"),
        "screenshot_evidence_timeout": ("blocked", "截图证据超时"),
        "target_not_found": ("blocked", "目标未找到"),
        "blocked_login_required": ("blocked", "登录态受限"),
        "post_verification_missed": ("blocked", "帖子级回查未完成"),
        "dispatch_timeout": ("blocked", "调度超时"),
        "input_failed": ("blocked", "输入失败"),
        "click_failed": ("blocked", "点击失败"),
        "failed": ("blocked", "发送失败，待复核"),
        "dry_run": ("dry", "Dry-Run通过"),
    }
    code = str(row.get("failure_code") or "").strip()
    if code in labels:
        return labels[code]
    if status in labels:
        return labels[status]
    return "pending", status or "未进入发送"


def render_html_dashboard(data_root: Path, run_id: str, limit: int = 200) -> str:
    rows = load_manual_candidates(data_root, run_id, limit)
    counts = Counter(str(row.get("triage_label", "conditional")) for row in rows)
    locator_counts = Counter(str(row.get("locator_status", "pending")) for row in rows)
    dry_run_counts = Counter(str(row.get("dry_run_status", "pending")) for row in rows)
    dispatch_counts = Counter(str(row.get("dispatch_status") or row.get("dry_run_status") or "pending") for row in rows)
    failure_statuses = {
        "failed", "screenshot_evidence_timeout", "target_not_found", "post_verification_missed",
        "target_url_normalization", "page_not_found", "dispatch_timeout", "input_failed", "click_failed",
    }
    failure_count = sum(dispatch_counts.get(status, 0) for status in failure_statuses)
    platforms = Counter(PLATFORM_NAMES.get(str(row.get("platform", "")), str(row.get("platform", "未知"))) for row in rows)
    payload = json.dumps(
        [
            {
                "platform": PLATFORM_NAMES.get(str(row.get("platform", "")), str(row.get("platform", "未知"))),
                "user": row.get("user", ""),
                "published_at": row.get("published_at", ""),
                "freshness": row.get("freshness", ""),
                "triage_label": row.get("triage_label", ""),
                "quote": row.get("quote", ""),
                "source_role": row.get("source_role", ""),
                "locator_status": row.get("locator_status", ""),
                "reply_draft": row.get("reply_draft") or row.get("reply_text", ""),
                "content_url": row.get("content_url", ""),
                "locator_url": row.get("locator_url") or row.get("comment_url", ""),
                "screenshot_path": row.get("screenshot_path", ""),
                "dry_run_status": row.get("dry_run_status", ""),
                "target_matched": row.get("target_matched", False),
                "draft_verified": row.get("draft_verified", False),
                "candidate_id": row.get("candidate_id", ""),
                "dispatch_status": row.get("dispatch_status", ""),
                "send_reason": row.get("send_reason", ""),
                "failure_code": row.get("failure_code", ""),
                "content_state": row.get("content_state", ""),
                "submitted": row.get("submitted", False),
                "verified": row.get("verified", False),
            }
            for row in rows
        ],
        ensure_ascii=False,
    )
    body_rows: list[str] = []
    for index, row in enumerate(rows, 1):
        status_class, status_label = _status(row)
        platform = PLATFORM_NAMES.get(str(row.get("platform", "")), str(row.get("platform", "未知")))
        body_rows.append(
            "<tr>"
            f"<td class='index'>{index}</td>"
            f"<td><span class='platform'>{_text(platform)}</span></td>"
            f"<td><strong>{_text(row.get('user') or '未识别用户')}</strong><div class='sub'>{_text(row.get('author_id'))}</div></td>"
            f"<td><span class='freshness'>{_text(row.get('freshness') or 'unknown')}</span><div class='sub'>{_text(row.get('published_at') or '时间未知')}</div></td>"
            f"<td><span class='triage'>{_text(row.get('triage_label') or 'conditional')}</span><div class='sub'>规则分 {int(row.get('rule_score') or 0)} · {_text(row.get('candidate_kind'))}</div></td>"
            f"<td class='quote'>“{_text(row.get('quote'))}”</td>"
            f"<td><span class='role'>{_text(row.get('source_role') or 'unknown')}</span><div class='sub'>{_text(row.get('event_type') or row.get('category') or '未分类')}</div></td>"
            f"<td><span class='status {status_class}'>{_text(status_label)}</span><div class='sub'>{_text(row.get('locator_method'))}</div></td>"
            f"<td><span class='status {_dispatch_status(row)[0]}'>{_text(_dispatch_status(row)[1])}</span><div class='sub'>{_text(row.get('failure_code') or row.get('send_reason') or '')}</div></td>"
            f"<td class='draft'>{_text(row.get('reply_draft') or row.get('reply_text') or '当前记录暂无草稿；先完成人工判断')}</td>"
            f"<td>{_evidence_link(data_root, row.get('screenshot_path'))}</td>"
            f"<td>{_link(row.get('locator_url') or row.get('comment_url') or row.get('content_url'), '打开定位')}<br>{_link(row.get('content_url'), '打开内容')}</td>"
            "</tr>"
        )
    platform_buttons = "".join(
        f"<button id='platform-{_text(name)}' onclick=\"filterRows('platform', {json.dumps(name, ensure_ascii=False)})\">{_text(name)} ({count})</button>"
        for name, count in sorted(platforms.items())
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>POLYV 需求候选 HTML 大板</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0b0f19; --panel:#111827; --line:#273449; --text:#e5edf7; --muted:#94a3b8; --cyan:#67e8f9; --green:#6ee7b7; --amber:#fbbf24; --red:#fb7185; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; padding:24px; background:var(--bg); color:var(--text); font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .wrap {{ max-width:1800px; margin:auto; }} .head {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-start; padding:20px; border:1px solid var(--line); background:#111827dd; border-radius:14px; }}
    h1 {{ margin:0; font-size:22px; }} h2 {{ margin:0 0 12px; font-size:15px; }} .sub,.muted {{ color:var(--muted); font-size:11px; }} .note {{ color:var(--muted); margin-top:7px; }}
    .stats {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; }} .stat {{ min-width:125px; padding:10px 12px; background:#172033; border:1px solid var(--line); border-radius:8px; }} .stat b {{ display:block; font-size:20px; color:var(--cyan); }}
    .toolbar {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }} button {{ color:var(--text); background:#172033; border:1px solid var(--line); border-radius:7px; padding:7px 10px; cursor:pointer; }} button.active {{ border-color:var(--cyan); color:var(--cyan); }}
    .table-wrap {{ overflow:auto; max-height:calc(100vh - 260px); border:1px solid var(--line); border-radius:12px; background:#0f172a; }} table {{ width:100%; min-width:1660px; border-collapse:collapse; }} th {{ position:sticky; top:0; z-index:2; background:#1a2639; color:#cbd5e1; text-align:left; white-space:nowrap; }} th,td {{ padding:11px 10px; border-bottom:1px solid #202d42; vertical-align:top; }} tr:hover {{ background:#172033; }} .index {{ color:var(--muted); text-align:center; width:40px; }}
    .platform,.freshness,.triage,.role,.status {{ display:inline-block; padding:3px 7px; border-radius:5px; border:1px solid #334155; background:#172033; white-space:nowrap; }} .platform {{ color:var(--cyan); }} .freshness {{ color:var(--green); }} .triage {{ color:#c4b5fd; }} .role {{ color:#fcd34d; }} .status.locator,.status.dry,.status.sent {{ color:var(--green); border-color:#166534; }} .status.pending {{ color:var(--amber); }} .status.blocked {{ color:var(--red); }} .quote {{ max-width:300px; color:#dbeafe; }} .draft {{ max-width:360px; color:#cbd5e1; }} a {{ color:#93c5fd; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
    @media (max-width:800px) {{ body {{ padding:12px; }} .head {{ display:block; }} h1 {{ font-size:18px; }} }}
  </style>
</head>
<body>
<main class="wrap">
  <section class="head"><div><h1>POLYV 需求候选 HTML 大板</h1><div class="note">当前批次：{_text(run_id)} · 数据来自现有雷达和 Ego Lite 定位结果</div><div class="note">发送状态与定位状态分开记录：已发送必须有回查证据；暂停、待审和待发送记录不会被当作已发送。</div></div><div class="sub">最后生成：{_text(__import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'))}</div></section>
  <section class="stats">
    <div class="stat">记录总数<b>{len(rows)}</b></div><div class="stat">定位通过<b>{locator_counts.get('verified', 0)}</b></div><div class="stat">已发送并回查<b>{dispatch_counts.get('submitted_verified', 0)}</b></div><div class="stat">已暂停发送<b>{dispatch_counts.get('aborted_quality_gate', 0)}</b></div><div class="stat">内容已失效<b>{dispatch_counts.get('content_unavailable', 0)}</b></div><div class="stat">发送失败<b>{failure_count}</b></div><div class="stat">待发送<b>{dispatch_counts.get('pending_send', 0)}</b></div><div class="stat">待审不发送<b>{dispatch_counts.get('held', 0)}</b></div><div class="stat">当前跟进<b>{counts.get('keep_current', 0)}</b></div><div class="stat">历史唤醒<b>{counts.get('keep_reactivation', 0)}</b></div>
  </section>
  <section class="toolbar"><button id="all" class="active" onclick="filterRows('all')">全部 ({len(rows)})</button>{platform_buttons}<button id="verified" onclick="filterRows('verified')">定位通过 ({locator_counts.get('verified', 0)})</button><button id="sent" onclick="filterRows('sent')">已发送 ({dispatch_counts.get('submitted_verified', 0)})</button><button id="paused" onclick="filterRows('paused')">已暂停 ({dispatch_counts.get('aborted_quality_gate', 0)})</button><button id="content_unavailable" onclick="filterRows('content_unavailable')">内容失效 ({dispatch_counts.get('content_unavailable', 0)})</button><button id="send_failed" onclick="filterRows('send_failed')">发送问题 ({failure_count})</button><button id="pending_send" onclick="filterRows('pending_send')">待发送 ({dispatch_counts.get('pending_send', 0)})</button><button id="held" onclick="filterRows('held')">待审不发送 ({dispatch_counts.get('held', 0)})</button><button id="dry_run" onclick="filterRows('dry_run')">Dry-Run通过 ({dry_run_counts.get('dry_run', 0)})</button><button id="dry_failed" onclick="filterRows('dry_failed')">Dry-Run失败 ({dry_run_counts.get('failed', 0)})</button><button id="current" onclick="filterRows('current')">当前跟进 ({counts.get('keep_current', 0)})</button><button id="historical" onclick="filterRows('historical')">历史唤醒 ({counts.get('keep_reactivation', 0)})</button></section>
  <section class="table-wrap"><table><thead><tr><th>#</th><th>平台</th><th>用户</th><th>时间层</th><th>建议分类</th><th>完整原话</th><th>来源与业务</th><th>定位状态</th><th>发送状态</th><th>回复草稿</th><th>截图</th><th>链接</th></tr></thead><tbody id="rows">{''.join(body_rows)}</tbody></table></section>
</main>
<script>
const data={payload};
function filterRows(kind, value='') {{ document.querySelectorAll('button').forEach(x=>x.classList.remove('active')); const id=kind==='platform'?'platform-'+value:kind; document.getElementById(id)?.classList.add('active'); document.querySelectorAll('#rows tr').forEach((row,i)=>{{const item=data[i]; const sendStatus=item.dispatch_status||item.dry_run_status||''; let show=kind==='all'||(kind==='platform'&&item.platform===value)||(kind==='verified'&&item.locator_status==='verified')||(kind==='sent'&&sendStatus==='submitted_verified')||(kind==='paused'&&sendStatus==='aborted_quality_gate')||(kind==='content_unavailable'&&sendStatus==='content_unavailable')||(kind==='send_failed'&&['failed','screenshot_evidence_timeout','target_not_found','post_verification_missed'].includes(sendStatus))||(kind==='pending_send'&&sendStatus==='pending_send')||(kind==='held'&&sendStatus==='held')||(kind==='dry_run'&&item.dry_run_status==='dry_run'&&item.target_matched&&item.draft_verified)||(kind==='dry_failed'&&item.dry_run_status==='failed')||(kind==='current'&&item.triage_label==='keep_current')||(kind==='historical'&&item.triage_label==='keep_reactivation'); row.style.display=show?'':'none';}}); }}
</script>
</body></html>"""


def latest_run_id(data_root: Path) -> str:
    from .storage import RadarStore

    store = RadarStore(Path(data_root) / "radar.sqlite3")
    store.initialize()
    row = store.connection.execute(
        "SELECT run_id FROM runs WHERE run_id NOT LIKE 'legacy-%' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    store.close()
    return str(row[0]) if row else ""
