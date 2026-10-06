"""Read-only ZigoAI social-lead business board renderer."""
from __future__ import annotations

import html
import json
from urllib.parse import urlsplit


def _text(value: object) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(str(value if value is not None else ""), quote=True)


def _link(value: object, label: object = "打开来源") -> str:
    url = str(value or "").strip()
    try:
        valid = urlsplit(url).scheme.lower() in {"http", "https"}
    except ValueError:
        valid = False
    if not valid:
        return _text(label if url else "待确认")
    return f'<a href="{_text(url)}" target="_blank" rel="noopener noreferrer">{_text(label)}</a>'


def zigo_campaign_navigation(campaign_id: str = "") -> str:
    selected = _text(campaign_id)
    return f'''<nav id="zigo-campaign-navigation" style="margin-bottom:16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
<a href="/polyv-dashboard.html">POLYV 客户活动</a>
<label>ZigoAI 可信 GEO 线索活动 <select id="zigo-campaign-selector" data-selected="{selected}"><option value="">选择活动</option></select></label>
<span id="zigo-campaign-navigation-error" role="alert"></span></nav>
<script>
(() => {{
 const select = document.getElementById('zigo-campaign-selector');
 const error = document.getElementById('zigo-campaign-navigation-error');
 select.addEventListener('change', () => {{
   if (select.value) location.href = '/polyv-dashboard.html?zigo_campaign_id=' + encodeURIComponent(select.value);
 }});
 async function loadCampaigns() {{
   try {{
     const response = await fetch('/api/radar/zigo-campaigns', {{cache:'no-store'}});
     if (!response.ok) throw new Error('HTTP ' + response.status);
     const data = await response.json();
     const options = [new Option('选择活动', '')];
     for (const item of data.campaigns) {{
       options.push(new Option(String(item.campaign_id) + ' · ' + String(item.product_domain), String(item.campaign_id)));
     }}
     select.replaceChildren(...options);
     select.value = select.dataset.selected;
     error.textContent = '';
   }} catch (err) {{ error.textContent = '活动列表读取失败：' + err.message; }}
 }}
 loadCampaigns();
 setInterval(loadCampaigns, 5000);
}})();
</script>'''


def render_zigo_campaign_dashboard(leads: list[dict], summary: dict, campaign_id: str) -> str:
    metrics = [
        ("total_leads", "社媒线索"), ("comment_verified", "评论级已核验"),
        ("content_buyer_verified", "内容级需求已核验"), ("pending_evidence", "待补证据"),
        ("outreach_sent", "已发送触达"), ("submission_pending", "发布待核验"), ("replies", "已收到回复"),
    ]
    counts = "".join(
        f'<div><span>{label}</span><strong>{_text(summary.get(key, 0))}</strong></div>'
        for key, label in metrics
    )
    rows = []
    for lead in leads:
        cells = [
            f'<strong>{_text(lead.get("author"))}</strong><div class="sub">{_text(lead.get("identity_status"))}</div>',
            _text(lead.get("evidence_status")),
            f'<div>{_text(lead.get("source_quote"))}</div><div class="sub">发布时间：{_text(lead.get("published_at") or "未取得")}</div>{_link(lead.get("content_url"))}',
            _text(lead.get("buyer_signal")),
            _text(lead.get("reply_suggestion") or "未准备"),
            _text(lead.get("outreach_status")),
            _text(lead.get("reply_status")),
            _text(lead.get("next_action")),
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    body = "".join(rows) or '<tr><td colspan="8">暂无社媒线索</td></tr>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZigoAI 可信 GEO 社媒线索活动 · {_text(campaign_id)}</title>
<style>
:root{{color-scheme:dark}} *{{box-sizing:border-box}} body{{margin:0;padding:24px;background:#0b0f19;color:#e5edf7;font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.wrap{{max-width:1800px;margin:auto}} a{{color:#67e8f9}} h1{{font-size:22px;margin:12px 0}} p{{color:#cbd5e1}} select{{max-width:100%;background:#111827;color:#e5edf7;padding:6px;border:1px solid #273449}}
.metrics{{display:flex;gap:24px;flex-wrap:wrap;padding:16px 0;border-block:1px solid #273449}} .metrics span,.sub{{display:block;color:#94a3b8}} .metrics strong{{font-size:24px}}
.table-wrap{{overflow:auto;margin-top:16px}} table{{border-collapse:collapse;width:100%;min-width:1150px}} th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #273449;padding:10px;overflow-wrap:anywhere;max-width:360px}} th{{background:#111827}} [role=alert]{{color:#fb7185}} #refresh-status{{color:#94a3b8}}
@media(max-width:800px){{body{{padding:12px}} h1{{font-size:18px}}}}
</style></head><body><div class="wrap">{zigo_campaign_navigation(campaign_id)}
<h1>ZigoAI 可信 GEO · 社媒买方线索活动</h1>
<p>社媒账号线索不等于已核验企业主体；页面汇总公开需求证据、回复文案和发布状态；点击提交不等于发布成功。</p>
<div id="refresh-error" role="alert"></div><div id="refresh-status" role="status"></div>
<section class="metrics" id="campaign-metrics">{counts}</section>
<div class="table-wrap"><table><thead><tr><th>账号身份</th><th>证据层级</th><th>来源原话 / 日期 / URL</th><th>买方信号</th><th>回复文案</th><th>触达状态</th><th>回复状态</th><th>下一步</th></tr></thead>
<tbody id="campaign-rows">{body}</tbody></table></div></div>
<script>
(() => {{
 let refreshing = false;
 async function refresh() {{
   if (refreshing) return;
   refreshing = true;
   try {{
     const response = await fetch(location.pathname + location.search, {{cache:'no-store'}});
     if (!response.ok) throw new Error('HTTP ' + response.status);
     const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
     for (const id of ['campaign-metrics', 'campaign-rows']) {{
       const updated = doc.getElementById(id);
       if (!updated) throw new Error('活动数据格式异常');
       document.getElementById(id).replaceChildren(...updated.childNodes);
     }}
     document.getElementById('refresh-error').textContent = '';
     document.getElementById('refresh-status').textContent = '更新于 ' + new Date().toLocaleTimeString();
   }} catch (err) {{ document.getElementById('refresh-error').textContent = '刷新失败，当前显示上次数据：' + err.message; }}
   finally {{ refreshing = false; }}
 }}
 setInterval(refresh, 5000);
}})();
</script></body></html>'''
