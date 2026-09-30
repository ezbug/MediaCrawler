import { useCallback, useEffect, useRef, useState } from 'react'
import { ExternalLink, Radio, RefreshCw, ShieldCheck } from 'lucide-react'
import { radarApi, type RadarManualCandidate, type RadarQueueItem, type UnifiedRadarRun, type UnifiedRadarSummary } from '@/lib/api'

type Brand = 'all' | 'polyv' | 'zigo'

function stat(label: string, value: number, tone = 'text-cyber-text-primary') {
  return <div className="rounded-md border border-white/10 bg-black/10 px-3 py-2"><div className="text-[11px] text-cyber-text-muted">{label}</div><div className={`text-lg font-semibold ${tone}`}>{value}</div></div>
}

function displayValue(value: unknown, fallback = '未提供') {
  return value === null || value === undefined || value === '' ? fallback : String(value)
}

export function RadarPanel() {
  const [brand, setBrand] = useState<Brand>('all')
  const [domain, setDomain] = useState('')
  const [summary, setSummary] = useState<UnifiedRadarSummary | null>(null)
  const [runs, setRuns] = useState<UnifiedRadarRun[]>([])
  const [runId, setRunId] = useState('')
  const [leads, setLeads] = useState<Array<Record<string, unknown>>>([])
  const [queue, setQueue] = useState<RadarQueueItem[]>([])
  const [manualCandidates, setManualCandidates] = useState<RadarManualCandidate[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [live, setLive] = useState(false)
  const socketRef = useRef<WebSocket | null>(null)

  const load = useCallback(async (nextRunId = runId) => {
    setLoading(true)
    setError('')
    try {
      const [summaryResponse, runsResponse] = await Promise.all([
        radarApi.getUnifiedSummary(brand, domain || undefined),
        radarApi.getUnifiedRuns(brand),
      ])
      const nextRuns = runsResponse.data.runs
      const selectedRun = nextRunId || nextRuns[0]?.run_id || ''
      setSummary(summaryResponse.data)
      setRuns(nextRuns)
      setRunId(selectedRun)
      const leadResponse = await radarApi.getUnifiedLeads(brand, domain || undefined, selectedRun || undefined, 50)
      setLeads(leadResponse.data.leads)
      if (brand === 'polyv' && selectedRun) {
        const [queueResponse, manualResponse] = await Promise.all([
          radarApi.getQueue(selectedRun),
          radarApi.getManualCandidates(selectedRun, 20),
        ])
        setQueue(queueResponse.data.queue)
        setManualCandidates(manualResponse.data.candidates)
      } else {
        setQueue([])
        setManualCandidates([])
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '统一雷达数据暂不可用')
    } finally {
      setLoading(false)
    }
  }, [brand, domain, runId])

  const loadRef = useRef(load)
  useEffect(() => { loadRef.current = load }, [load])

  useEffect(() => { void load('') }, [brand, domain])

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/radar`)
    socketRef.current = socket
    socket.onopen = () => setLive(true)
    socket.onclose = () => setLive(false)
    socket.onmessage = () => { void loadRef.current() }
    const fallback = window.setInterval(() => { void loadRef.current() }, 5000)
    return () => { window.clearInterval(fallback); socket.close(); socketRef.current = null }
  }, [])

  return (
    <section className="glass-panel flex-shrink-0 p-4 min-h-0" aria-label="POLYV 与 ZigoAI 统一雷达">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div><div className="text-xs uppercase tracking-[0.18em] text-cyber-text-muted">POLYV + ZIGOAI RADAR</div><div className="text-sm text-cyber-text-primary mt-1">双库独立存储，统一查看与实时刷新</div></div>
        <div className="flex items-center gap-2"><span className={live ? 'text-cyber-neon-green text-[11px]' : 'text-amber-300 text-[11px]'}><Radio size={13} className="inline mr-1" />{live ? '实时连接' : '定时刷新'}</span><button type="button" title="刷新统一雷达" aria-label="刷新统一雷达" onClick={() => void load()} className="p-2 rounded-md text-cyber-text-secondary hover:text-cyber-neon-green hover:bg-white/5 disabled:opacity-50" disabled={loading}><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /></button></div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-3">
        {(['all', 'polyv', 'zigo'] as Brand[]).map((value) => <button key={value} type="button" onClick={() => { setBrand(value); setDomain(''); setRunId('') }} className={`px-3 py-1.5 rounded-md text-xs border ${brand === value ? 'border-cyber-neon-green text-cyber-neon-green bg-white/10' : 'border-white/10 text-cyber-text-muted hover:text-cyber-text-primary'}`}>{value === 'all' ? '全部' : value === 'polyv' ? 'POLYV' : 'ZigoAI'}</button>)}
        {brand === 'zigo' && <select value={domain} onChange={(event) => { setDomain(event.target.value); setRunId('') }} aria-label="选择 ZigoAI 产品域" className="bg-black/20 border border-white/10 rounded-md text-xs px-2 py-1.5 text-cyber-text-primary"><option value="">全部产品域</option><option value="sales_agent">销冠成交智能体</option><option value="geo">可信 GEO</option></select>}
        <select value={runId} onChange={(event) => { setRunId(event.target.value); void load(event.target.value) }} aria-label="选择雷达批次" className="max-w-xl bg-black/20 border border-white/10 rounded-md text-xs px-2 py-1.5 text-cyber-text-primary"><option value="">最新批次</option>{runs.map((run) => <option key={`${run.brand}-${run.run_id}`} value={run.run_id}>{run.brand} · {run.product_domain} · {run.run_id}</option>)}</select>
      </div>

      {error && <div className="text-xs text-amber-300 mb-3">{error}</div>}
      {summary && <><div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2 mb-3">{stat('内容', summary.contents)}{stat('真实评论', summary.comments)}{stat('需求候选', summary.candidates, 'text-cyber-neon-green')}{stat('证据核验通过', summary.verified, 'text-cyber-neon-cyan')}{stat('批次', summary.runs)}{stat('POLYV内容', summary.brands.polyv)}{stat('ZigoAI内容', summary.brands.zigo)}{stat('独立数据库', 2, 'text-cyber-neon-green')}</div><div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-cyber-text-muted mb-4"><span>最后变更标识 {summary.last_updated}</span><span>库内更新时间由入库事务产生</span>{brand === 'zigo' && <span>发送功能：关闭</span>}</div></>}

      <div className="space-y-2 max-h-72 overflow-auto pr-1">
        {leads.map((lead, index) => { const sourceUrl = displayValue(lead.comment_url || lead.url, ''); return <div key={`${displayValue(lead.brand)}-${displayValue(lead.candidate_id || lead.url)}-${index}`} className="flex items-start gap-3 border-t border-white/10 pt-2"><ShieldCheck size={15} className="mt-0.5 text-cyber-neon-green flex-shrink-0" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2 text-xs"><span className="text-cyber-text-primary">{displayValue(lead.user || lead.author, '未识别用户')}</span><span className="text-cyber-neon-green">{displayValue(lead.score || lead.rule_score, '待评分')}分</span><span className="text-cyber-text-muted">{displayValue(lead.brand)} · {displayValue(lead.product_domain)}</span><span className="text-cyber-text-muted">{displayValue(lead.decision, '待核')}</span></div><div className="text-xs text-cyber-text-secondary line-clamp-2 mt-1">{displayValue(lead.quote || lead.text)}</div></div>{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer" title="打开原文" className="text-cyber-text-muted hover:text-cyber-neon-green"><ExternalLink size={14} /></a>}</div> })}
        {!loading && !leads.length && <div className="text-xs text-cyber-text-muted py-4">当前筛选暂无可显示候选，原始数据仍保留在对应数据库。</div>}
      </div>

      {brand === 'polyv' && <div className="grid xl:grid-cols-2 gap-4 mt-4"><div><div className="text-xs text-cyber-text-muted mb-2">POLYV Dry-Run / 发送队列</div><div className="space-y-2 max-h-40 overflow-auto">{queue.map((item) => <div key={String(item.queue_id)} className="border-t border-white/10 pt-2 text-xs"><span className="text-cyber-text-primary">{item.author || '未识别用户'}</span><span className="text-cyber-neon-cyan ml-2">{item.dry_run_status || item.lead_status || '待执行'}</span><div className="text-cyber-text-secondary truncate mt-1">{item.quote || item.text}</div></div>)}{!queue.length && <div className="text-xs text-cyber-text-muted">暂无队列记录</div>}</div></div><div><div className="text-xs text-cyber-text-muted mb-2">POLYV 人工待选</div><div className="space-y-2 max-h-40 overflow-auto">{manualCandidates.map((candidate) => <div key={candidate.candidate_id} className="border-t border-white/10 pt-2 text-xs"><span className="text-cyber-text-primary">{candidate.user || '未识别用户'}</span><span className="text-cyber-neon-cyan ml-2">{candidate.triage_label}</span><div className="text-cyber-text-secondary line-clamp-2 mt-1">{candidate.quote}</div></div>)}{!manualCandidates.length && <div className="text-xs text-cyber-text-muted">暂无人工待选记录</div>}</div></div></div>}
    </section>
  )
}
