import { useEffect, useState } from 'react'
import { ExternalLink, RefreshCw, ShieldCheck } from 'lucide-react'
import { radarApi, type RadarLead, type RadarSummary } from '@/lib/api'

export function RadarPanel() {
  const [summary, setSummary] = useState<RadarSummary | null>(null)
  const [leads, setLeads] = useState<RadarLead[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const summaryResponse = await radarApi.getSummary()
      const nextSummary = summaryResponse.data
      setSummary(nextSummary)
      if (nextSummary.run_id) {
        const leadsResponse = await radarApi.getLeads(nextSummary.run_id, 20)
        setLeads(leadsResponse.data.leads)
      } else {
        setLeads([])
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
          <div className="text-sm text-cyber-text-primary mt-1">证据链与人工审批队列</div>
        </div>
        <button
          type="button"
          title="刷新雷达"
          aria-label="刷新雷达"
          onClick={() => void load()}
          className="p-2 rounded-md text-cyber-text-secondary hover:text-cyber-neon-green hover:bg-white/5 disabled:opacity-50"
          disabled={loading}
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
      {error && <div className="text-xs text-amber-300 mb-3">{error}</div>}
      {summary && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3">
          {[
            ['内容线索', summary.leads],
            ['需求候选', summary.demand_candidates],
            ['定位通过', summary.locator_verified],
            ['待审批', summary.approved_queue],
            ['已核验发送', summary.attempts.submitted_verified || 0],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-md border border-white/10 bg-black/10 px-3 py-2">
              <div className="text-[11px] text-cyber-text-muted">{label}</div>
              <div className="text-lg font-semibold text-cyber-text-primary">{value}</div>
            </div>
          ))}
          </div>
          <div className="text-[11px] text-cyber-text-muted mb-4">
            状态事件：{summary.status_events_raw} 原始行 / {summary.status_events_distinct} 个去重事件
          </div>
        </>
      )}
      <div className="space-y-2 max-h-64 overflow-auto pr-1">
        {leads.filter((lead) => lead.score >= 4 && lead.decision !== 'reject').map((lead, index) => (
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
        {!loading && !leads.length && <div className="text-xs text-cyber-text-muted">暂无可显示的需求候选</div>}
      </div>
    </section>
  )
}
