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
    locator_status = str(row.get("locator_status", "")).strip()
    if locator_status == "verified":
        return "locator", "Ego Lite 已定位"
    if locator_status:
        return "blocked", f"定位{locator_status}"
    return "pending", "待重新定位"


def render_html_dashboard(data_root: Path, run_id: str, limit: int = 200) -> str:
    rows = load_manual_candidates(data_root, run_id, limit)
    counts = Counter(str(row.get("triage_label", "conditional")) for row in rows)
    locator_counts = Counter(str(row.get("locator_status", "pending")) for row in rows)
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
                "reply_draft": row.get("reply_draft", ""),
                "content_url": row.get("content_url", ""),
                "locator_url": row.get("locator_url") or row.get("comment_url", ""),
                "screenshot_path": row.get("screenshot_path", ""),
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
            f"<td class='draft'>{_text(row.get('reply_draft') or '当前记录暂无草稿；先完成人工判断')}</td>"
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
    .platform,.freshness,.triage,.role,.status {{ display:inline-block; padding:3px 7px; border-radius:5px; border:1px solid #334155; background:#172033; white-space:nowrap; }} .platform {{ color:var(--cyan); }} .freshness {{ color:var(--green); }} .triage {{ color:#c4b5fd; }} .role {{ color:#fcd34d; }} .status.locator {{ color:var(--green); border-color:#166534; }} .status.pending {{ color:var(--amber); }} .status.blocked {{ color:var(--red); }} .quote {{ max-width:300px; color:#dbeafe; }} .draft {{ max-width:360px; color:#cbd5e1; }} a {{ color:#93c5fd; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
    @media (max-width:800px) {{ body {{ padding:12px; }} .head {{ display:block; }} h1 {{ font-size:18px; }} }}
  </style>
</head>
<body>
<main class="wrap">
  <section class="head"><div><h1>POLYV 需求候选 HTML 大板</h1><div class="note">当前批次：{_text(run_id)} · 数据来自现有雷达和 Ego Lite 定位结果</div><div class="note">当前表格只展示需求候选与人工待处理记录；回复均为草稿，未发送，不把历史截图或旧状态当作发送证据。</div></div><div class="sub">最后生成：{_text(__import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'))}</div></section>
  <section class="stats">
    <div class="stat">记录总数<b>{len(rows)}</b></div><div class="stat">定位通过<b>{locator_counts.get('verified', 0)}</b></div><div class="stat">当前跟进<b>{counts.get('keep_current', 0)}</b></div><div class="stat">历史唤醒<b>{counts.get('keep_reactivation', 0)}</b></div><div class="stat">有条件保留<b>{counts.get('conditional', 0)}</b></div><div class="stat">待定位<b>{len(rows) - locator_counts.get('verified', 0)}</b></div>
  </section>
  <section class="toolbar"><button id="all" class="active" onclick="filterRows('all')">全部 ({len(rows)})</button>{platform_buttons}<button id="verified" onclick="filterRows('verified')">定位通过 ({locator_counts.get('verified', 0)})</button><button id="current" onclick="filterRows('current')">当前跟进 ({counts.get('keep_current', 0)})</button><button id="historical" onclick="filterRows('historical')">历史唤醒 ({counts.get('keep_reactivation', 0)})</button></section>
  <section class="table-wrap"><table><thead><tr><th>#</th><th>平台</th><th>用户</th><th>时间层</th><th>建议分类</th><th>完整原话</th><th>来源与业务</th><th>定位状态</th><th>回复草稿</th><th>截图</th><th>链接</th></tr></thead><tbody id="rows">{''.join(body_rows)}</tbody></table></section>
</main>
<script>
const data={payload};
function filterRows(kind, value='') {{ document.querySelectorAll('button').forEach(x=>x.classList.remove('active')); const id=kind==='platform'?'platform-'+value:kind; document.getElementById(id)?.classList.add('active'); document.querySelectorAll('#rows tr').forEach((row,i)=>{{const item=data[i]; let show=kind==='all'||(kind==='platform'&&item.platform===value)||(kind==='verified'&&item.locator_status==='verified')||(kind==='current'&&item.triage_label==='keep_current')||(kind==='historical'&&item.triage_label==='keep_reactivation'); row.style.display=show?'':'none';}}); }}
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
