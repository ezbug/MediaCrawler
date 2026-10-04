"""Read-only customer campaign view within the existing radar dashboard."""
from __future__ import annotations

import html
import json
from urllib.parse import quote, urlsplit


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


def campaign_navigation(campaign_id: str = "", zigo_campaign_id: str = "") -> str:
    selected = _text(f"zigo:{zigo_campaign_id}" if zigo_campaign_id else f"polyv:{campaign_id}")
    return f'''<nav id="campaign-navigation" style="margin-bottom:16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
<a href="/polyv-dashboard.html">历史雷达</a>
<label>国庆客户活动 <select id="campaign-selector" data-selected="{selected}"><option value="">选择活动</option></select></label>
<span id="campaign-navigation-error" role="alert"></span></nav>
<script>
(() => {{
 const select = document.getElementById('campaign-selector');
 const error = document.getElementById('campaign-navigation-error');
 select.addEventListener('change', () => {{
   if (!select.value) return;
   const [kind, id] = select.value.split(':', 2);
   if (kind === 'zigo') location.href = '/polyv-dashboard.html?zigo_campaign_id=' + encodeURIComponent(id);
   else location.href = '/polyv-dashboard.html?campaign_id=' + encodeURIComponent(id);
 }});
 async function loadCampaigns() {{
   try {{
     const [polyvResponse, zigoResponse] = await Promise.all([
       fetch('/api/radar/campaigns', {{cache:'no-store'}}),
       fetch('/api/radar/zigo-campaigns', {{cache:'no-store'}}),
     ]);
     if (!polyvResponse.ok || !zigoResponse.ok) throw new Error('HTTP ' + (!polyvResponse.ok ? polyvResponse.status : zigoResponse.status));
     const [polyvData, zigoData] = await Promise.all([polyvResponse.json(), zigoResponse.json()]);
     const options = [new Option('选择活动', '')];
     for (const item of polyvData.campaigns) {{
       options.push(new Option('POLYV · ' + String(item.campaign_id) + ' · ' + String(item.sector || ''), 'polyv:' + String(item.campaign_id)));
     }}
     for (const item of zigoData.campaigns) {{
       options.push(new Option('ZigoAI · ' + String(item.campaign_id) + ' · ' + String(item.product_domain || ''), 'zigo:' + String(item.campaign_id)));
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


def _sources(row: dict) -> str:
    sources = row.get("sources") or ([row] if row.get("quote") or row.get("source_url") else row.get("evidence") or [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except ValueError:
            return _text(sources)
    if not isinstance(sources, list):
        sources = [sources]
    result = []
    for source in sources:
        if not isinstance(source, dict):
            result.append(_text(source))
            continue
        result.append(
            f'<div class="source">{_text(source.get("quote") or source.get("source_quote"))}'
            f'<div class="sub">发布日期：{_text(source.get("published_at") or source.get("source_date") or source.get("date") or "未知")}</div>'
            f'<div class="sub">核验时间：{_text(source.get("evidence", {}).get("checked_at") or "待确认")}</div>'
            f'{_link(source.get("url") or source.get("source_url") or source.get("content_url"))}</div>'
        )
    return "".join(result) or "待确认"


def _events(events: list[dict]) -> str:
    result = []
    for event in events:
        evidence = event.get("evidence") or {}
        result.append(
            f'<div class="source">{_text(event.get("status") or "pending")}'
            f'<div>{_text(evidence.get("other_quote") or evidence.get("quote"))}</div>'
            f'<div>{_text(evidence.get("own_quote"))}</div>'
            f'<div class="sub">{_text(evidence.get("actual_date"))}</div>'
            f'{_link(evidence.get("source_url"))}</div>'
        )
    return "".join(result)


def render_customer_campaign_dashboard(companies: list[dict], summary: dict, campaign_id: str) -> str:
    metrics = [
        ("qualified_companies", "已核验适配机构"), ("contacted_companies", "已联系企业"),
        ("replied_companies", "已回复企业"), ("effective_exchanges", "有效交流"),
        ("target_companies", "企业目标"), ("target_exchanges", "有效交流目标"),
        ("pending_companies", "待核机构"),
    ]
    counts = "".join(f'<div><span>{label}</span><strong>{_text(summary.get(key, 0))}</strong></div>' for key, label in metrics)
    rows = []
    for row in companies:
        identity = row.get("company_name") or row.get("name") or row.get("identity") or row.get("company_id")
        cells = [
            f'<strong>{_text(identity)}</strong><div class="sub">{_text(row.get("identity_status") or row.get("identity_type"))} · {_text(row.get("business_type"))}</div>'
            f'<div class="sub">{_text(row.get("official_domain") or row.get("official_organization_id"))}</div>'
            f'<div class="sub">{_text(row.get("status"))} · {_text(row.get("missing_evidence") or "")}</div>',
            _text(row.get("scenario")), _sources(row),
            _link(row.get("contact_entry_url") or row.get("contact_url"), row.get("contact_entry") or "联系入口") if row.get("contact_entry_url") or row.get("contact_url") else _text(row.get("contact_entry") or "待确认"),
            _text(row.get("fit_score")), _text(row.get("intent_score")),
            _text(row.get("fit_reason") or "待确认"),
            _text(row.get("evidence", {}).get("opening_question") or "待准备"),
            _events(row.get("outreach_events") or []) or _text(row.get("outreach") or row.get("outreach_status") or "暂无触达证据"),
            _events(row.get("reply_events") or []) or _text(row.get("reply_text") or row.get("reply") or row.get("reply_status") or "暂无回复证据"), _text(row.get("next_action")),
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    body = "".join(rows) or '<tr><td colspan="11">暂无企业记录</td></tr>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>POLYV 国庆客户活动 · {_text(campaign_id)}</title>
<style>
:root{{color-scheme:dark}} *{{box-sizing:border-box}} body{{margin:0;padding:24px;background:#0b0f19;color:#e5edf7;font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.wrap{{max-width:1800px;margin:auto}} a{{color:#67e8f9}} h1{{font-size:22px;margin:12px 0}} select{{max-width:100%;background:#111827;color:#e5edf7;padding:6px;border:1px solid #273449}}
.metrics{{display:flex;gap:24px;flex-wrap:wrap;padding:16px 0;border-block:1px solid #273449}} .metrics span,.sub{{display:block;color:#94a3b8}} .metrics strong{{font-size:24px}}
.table-wrap{{overflow:auto;margin-top:16px}} table{{border-collapse:collapse;width:100%;min-width:1150px}} th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #273449;padding:10px;overflow-wrap:anywhere;max-width:360px}} th{{background:#111827}} .source + .source{{margin-top:12px}} [role=alert]{{color:#fb7185}} #refresh-status{{color:#94a3b8}}
@media(max-width:800px){{body{{padding:12px}} h1{{font-size:18px}}}}
</style></head><body><div class="wrap">{campaign_navigation(campaign_id)}
<h1>POLYV 国庆客户活动 · {_text(campaign_id)}</h1>
<div id="refresh-error" role="alert"></div><div id="refresh-status" role="status"></div>
<section class="metrics" id="campaign-metrics">{counts}</section>
<div class="table-wrap"><table><thead><tr><th>企业身份</th><th>业务场景</th><th>来源原话 / 日期 / URL</th><th>联系入口</th><th>适配分</th><th>意向分</th><th>适配理由</th><th>开场草稿（未发送）</th><th>触达状态</th><th>回复</th><th>下一步</th></tr></thead>
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
