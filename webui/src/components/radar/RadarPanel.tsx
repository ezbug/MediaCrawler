import { useEffect, useState } from 'react'
import { ExternalLink, RefreshCw, ShieldCheck } from 'lucide-react'
import { radarApi, type RadarLead, type RadarQueueItem, type RadarRun, type RadarSummary } from '@/lib/api'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

function stat(label: string, value: number, tone = 'text-cyber-text-primary') {
  return (
    <div className="rounded-md border border-white/10 bg-black/10 px-3 py-2">
      <div className="text-[11px] text-cyber-text-muted">{label}</div>
      <div className={`text-lg font-semibold ${tone}`}>{value}</div>
    </div>
  )
}

export function RadarPanel() {
  const [summary, setSummary] = useState<RadarSummary | null>(null)
  const [runs, setRuns] = useState<RadarRun[]>([])
  const [selectedRun, setSelectedRun] = useState('')
  const [leads, setLeads] = useState<RadarLead[]>([])
  const [queue, setQueue] = useState<RadarQueueItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async (runId?: string) => {
    setLoading(true)
    setError('')
    try {
      const [summaryResponse, runsResponse] = await Promise.all([
        radarApi.getSummary(runId || undefined),
        radarApi.getRuns(),
      ])
      const nextSummary = summaryResponse.data
      const nextRuns = runsResponse.data.runs
      const resolvedRun = runId || nextSummary.run_id
      setSummary(nextSummary)
      setRuns(nextRuns)
      setSelectedRun(resolvedRun)
      if (resolvedRun) {
        const [leadsResponse, queueResponse] = await Promise.all([
          radarApi.getLeads(resolvedRun, 20, 'cleaned'),
          radarApi.getQueue(resolvedRun),
        ])
        setLeads(leadsResponse.data.leads)
        setQueue(queueResponse.data.queue)
      } else {
        setLeads([])
        setQueue([])
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '雷达数据暂不可用')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  return (
    <section className="glass-panel flex-shrink-0 p-4" aria-label="POLYV 雷达">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-cyber-text-muted">POLYV RADAR</div>
          <div className="text-sm text-cyber-text-primary mt-1">批次、清洗结果与 Dry-Run 队列</div>
        </div>
        <button
          type="button"
          title="刷新雷达"
          aria-label="刷新雷达"
          onClick={() => void load(selectedRun)}
          className="p-2 rounded-md text-cyber-text-secondary hover:text-cyber-neon-green hover:bg-white/5 disabled:opacity-50"
          disabled={loading}
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="flex items-center gap-2 mb-3">
        <div className="text-xs text-cyber-text-muted whitespace-nowrap">当前批次</div>
        <Select value={selectedRun} onValueChange={(value) => { setSelectedRun(value); void load(value) }}>
          <SelectTrigger aria-label="选择雷达批次" className="max-w-xl">
            <SelectValue placeholder="选择批次" />
          </SelectTrigger>
          <SelectContent>
            {runs.map((run) => (
              <SelectItem key={run.run_id} value={run.run_id}>
                {run.run_id} · 内容 {run.contents} · 评论 {run.comments} · 清洗后 {run.cleaned_leads}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {error && <div className="text-xs text-amber-300 mb-3">{error}</div>}
      {summary && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2 mb-3">
            {stat('内容', summary.contents)}
            {stat('评论', summary.comments)}
            {stat('原始线索', summary.raw_leads)}
            {stat('清洗后候选', summary.cleaned_leads, 'text-cyber-neon-green')}
            {stat('已过滤', summary.filtered_leads, 'text-cyber-neon-orange')}
            {stat('定位通过', summary.locator_verified)}
            {stat('Dry-Run 队列', summary.dry_run_queue, 'text-cyber-neon-cyan')}
            {stat('真实发送', summary.real_sent)}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-cyber-text-muted mb-4">
            <span>需求候选 {summary.demand_candidates}</span>
            <span>Dry-Run 已执行 {summary.dry_run_completed}</span>
            <span>状态事件 {summary.status_events_distinct} / {summary.status_events_raw}</span>
          </div>
        </>
      )}

      <div className="grid xl:grid-cols-[1.15fr_0.85fr] gap-4">
        <div>
          <div className="text-xs text-cyber-text-muted mb-2">清洗后可核验候选</div>
          <div className="space-y-2 max-h-64 overflow-auto pr-1">
            {leads.map((lead, index) => (
              <div key={`${lead.platform}-${lead.url}-${index}`} className="flex items-start gap-3 border-t border-white/10 pt-2">
                <ShieldCheck size={15} className="mt-0.5 text-cyber-neon-green flex-shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-cyber-text-primary">{lead.user || '未识别用户'}</span>
                    <span className="text-cyber-neon-green">{lead.score}分</span>
                    <span className="text-cyber-text-muted">{lead.platform}</span>
                  </div>
                  <div className="text-xs text-cyber-text-secondary truncate mt-1">{lead.quote}</div>
                </div>
                {lead.url && (
                  <a href={lead.comment_url || lead.url} target="_blank" rel="noreferrer" title="打开原文" className="text-cyber-text-muted hover:text-cyber-neon-green">
                    <ExternalLink size={14} />
                  </a>
                )}
              </div>
            ))}
            {!loading && !leads.length && <div className="text-xs text-cyber-text-muted">当前批次清洗后暂无可核验候选</div>}
          </div>
        </div>

        <div>
          <div className="text-xs text-cyber-text-muted mb-2">当前 Dry-Run 队列</div>
          <div className="space-y-2 max-h-64 overflow-auto pr-1">
            {queue.map((item) => (
              <div key={String(item.queue_id)} className="border-t border-white/10 pt-2">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-cyber-text-primary">{item.author || '未识别用户'}</span>
                  <span className="text-cyber-neon-cyan">{item.dry_run_status || item.lead_status || '待执行'}</span>
                  <span className="text-cyber-text-muted">{item.platform}</span>
                </div>
                <div className="text-xs text-cyber-text-secondary truncate mt-1">{item.quote || item.text}</div>
              </div>
            ))}
            {!loading && !queue.length && <div className="text-xs text-cyber-text-muted">当前批次暂无 Dry-Run 队列</div>}
          </div>
        </div>
      </div>
    </section>
  )
}
