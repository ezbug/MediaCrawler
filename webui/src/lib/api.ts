import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Types
export interface CrawlerConfig {
  platform: string
  login_type: string
  crawler_type: string
  keywords: string
  start_page: number
  enable_comments: boolean
  enable_sub_comments: boolean
  save_option: string
  cookies: string
  headless: boolean
}

export interface CrawlerStatus {
  status: 'idle' | 'running' | 'stopping' | 'error'
  platform: string | null
  crawler_type: string | null
  started_at: string | null
  error_message: string | null
}

export interface LogEntry {
  id: number
  timestamp: string
  level: 'info' | 'warning' | 'error' | 'success' | 'debug'
  message: string
}

export interface DataFile {
  name: string
  path: string
  size: number
  modified_at: number
  record_count: number | null
  type: string
}

export interface FilePreviewResponse {
  data: Record<string, unknown>[]
  total: number
  columns?: string[]
}

export interface Platform {
  value: string
  label: string
  icon: string
}

export interface ConfigOption {
  value: string
  label: string
}

// API functions
export const crawlerApi = {
  start: (config: CrawlerConfig) => api.post('/crawler/start', config),
  stop: () => api.post('/crawler/stop'),
  getStatus: () => api.get<CrawlerStatus>('/crawler/status'),
  getLogs: (limit = 100) => api.get<{ logs: LogEntry[] }>('/crawler/logs', { params: { limit } }),
}

export const dataApi = {
  getFiles: (platform?: string, fileType?: string) =>
    api.get<{ files: DataFile[] }>('/data/files', { params: { platform, file_type: fileType } }),
  getFileContent: (path: string, limit = 100) =>
    api.get<FilePreviewResponse>('/data/files/' + path, { params: { preview: true, limit } }),
  getStats: () => api.get('/data/stats'),
  getDownloadUrl: (path: string) => `/api/data/download/${path}`,
}

export const configApi = {
  getPlatforms: () => api.get<{ platforms: Platform[] }>('/config/platforms'),
  getOptions: () =>
    api.get<{
      login_types: ConfigOption[]
      crawler_types: ConfigOption[]
      save_options: ConfigOption[]
    }>('/config/options'),
}

export interface EnvCheckResult {
  success: boolean
  message: string
  output?: string
  error?: string
}

export const envApi = {
  check: () => api.get<EnvCheckResult>('/env/check'),
}

export interface RadarSummary {
  run_id: string
  leads: number
  raw_leads: number
  cleaned_leads: number
  filtered_leads: number
  manual_candidates: number
  filtered_reasons: Record<string, number>
  contents: number
  comments: number
  demand_candidates: number
  locator_verified: number
  approved_queue: number
  dry_run_queue: number
  dry_run_completed: number
  real_sent: number
  status_events_raw: number
  status_events_distinct: number
  attempts: Record<string, number>
}

export interface RadarRun {
  run_id: string
  started_at: string
  finished_at: string | null
  status: string
  platform_status: string
  contents: number
  comments: number
  raw_leads: number
  cleaned_leads: number
  filtered_leads: number
  dry_run_queue: number
}

export interface RadarLead {
  platform: string
  user: string
  quote: string
  score: number
  stage: string
  decision: string
  url: string
  comment_url?: string
  locator_status: string
  event_type?: string
  identity_confidence?: string
}

export interface RadarQueueItem {
  queue_id: string | number
  run_id?: string
  platform: string
  url: string
  author: string
  text: string
  quote?: string
  lead_status?: string
  source?: string
  selection?: string
  dry_run_status?: string
  screenshot?: string
  submitted?: boolean
}

export interface RadarManualCandidate {
  candidate_id: string
  platform: string
  triage_label: string
  candidate_kind: string
  freshness: string
  source_role: string
  user: string
  quote: string
  rule_score: number
  recommended_action: string
  content_url: string
  comment_url: string
  locator_status?: string
  locator_method?: string
  locator_url?: string
  locator_reason?: string
  screenshot_path?: string
  reply_evidence_status?: string
}

export const radarApi = {
  getRuns: (limit = 30) => api.get<{ runs: RadarRun[] }>('/radar/runs', { params: { limit } }),
  getSummary: (runId?: string) => api.get<RadarSummary>('/radar/summary', { params: runId ? { run_id: runId } : {} }),
  getLeads: (runId: string, limit = 20, view: 'cleaned' | 'all' = 'cleaned') =>
    api.get<{ run_id: string; leads: RadarLead[]; raw_count: number; cleaned_count: number; filtered_count: number }>('/radar/leads', { params: { run_id: runId, limit, view } }),
  getQueue: (runId: string) => api.get<{ queue: RadarQueueItem[] }>('/radar/queue', { params: { run_id: runId } }),
  getManualCandidates: (runId: string, limit = 50) => api.get<{ run_id: string; candidates: RadarManualCandidate[] }>('/radar/manual-candidates', { params: { run_id: runId, limit } }),
}

export default api
