import { useState, useEffect, useCallback, useRef } from 'react'

const API_BASE = '/api'

export interface FilterState {
  q?: string
  sources?: string[]
  types?: string[]
  secretTypes?: string[]
  triageStatuses?: string[]
  stale?: boolean
  sort?: string
  hasSecrets?: boolean
  page?: number
  groupBy?: string
  dateFrom?: string
  dateTo?: string
}

interface SecretTypeCount { type: string; count: number }
interface SourceCount { source: string; count: number }
interface TypeCount { content_type: string; count: number }
interface Stats {
  total: number; with_secrets: number; with_passwords: number; sources: number
  unreviewed?: number; reviewed?: number; false_positive?: number; escalated?: number
  unreviewed_all?: number; reviewed_all?: number; false_positive_all?: number; escalated_all?: number
  total_all?: number
}
export interface PasteResult {
  id: string; filename: string; source: string; content_type: string; size: number
  has_passwords: boolean; has_secrets: boolean
  secret_types: string[]
  secrets_detail: { type: string; line: number; match: string }[] | null
  first_seen: string; snippet: string
  triage_status?: string
  triage_note?: string
  triage_reviewer?: string
  triage_updated_at?: string | null
  triage_auto?: number
  triage_source?: string
  duplicate_count?: number
  modified_at?: string | null
}
interface SearchResult { total: number; page: number; per_page: number; total_pages: number; results: PasteResult[] }
interface GroupedResult {
  total: number
  group_by: string
  groups: { key: string; total: number; results: PasteResult[] }[]
}

interface IndexStatus {
  running: boolean
  current: number
  total: number
  phase: string
}

const defaultIndexStatus: IndexStatus = { running: false, current: 0, total: 0, phase: '' }

function queryString(state: FilterState): string {
  const qp = new URLSearchParams()
  if (state.q) qp.set('q', state.q)
  if (state.sources) state.sources.forEach(s => qp.append('source', s))
  if (state.types) state.types.forEach(t => qp.append('content_type', t))
  if (state.secretTypes) state.secretTypes.forEach(st => qp.append('secret_type', st))
  if (state.triageStatuses) state.triageStatuses.forEach(ts => qp.append('triage_status', ts))
  if (state.stale) qp.set('stale', 'true')
  if (state.sort) qp.set('sort', state.sort)
  if (state.hasSecrets) qp.set('has_secrets', 'true')
  if (state.groupBy) qp.set('group_by', state.groupBy)
  if (state.dateFrom) qp.set('date_from', state.dateFrom)
  if (state.dateTo) qp.set('date_to', state.dateTo)
  return qp.toString()
}

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(path)
    if (!r.ok) return null
    return await r.json() as T
  } catch {
    return null
  }
}

export function usePastes() {
  const [pastes, setPastes] = useState<PasteResult[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState<SourceCount[]>([])
  const [types, setTypes] = useState<TypeCount[]>([])
  const [secretTypes, setSecretTypes] = useState<SecretTypeCount[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [version, setVersion] = useState('')
  const [lastReindexResult, setLastReindexResult] = useState<{indexed: number; deleted: number; total: number; skipped: number} | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [indexStatus, setIndexStatus] = useState<IndexStatus>(defaultIndexStatus)
  const [groupedData, setGroupedData] = useState<GroupedResult | null>(null)

  const pastesReqId = useRef(0)
  const statsReqId = useRef(0)
  const runningRef = useRef(false)
  const reindexTriggeredRef = useRef(false)
  // Last applied filter state, so background refreshes (e.g. after an index
  // run) keep the active filters instead of silently resetting the counters.
  const lastFilterRef = useRef<FilterState>({ page: 1 })

  const fetchPastes = useCallback(async (state: FilterState) => {
    const reqId = ++pastesReqId.current
    setLoading(true)
    setError(null)
    setGroupedData(null)  // clear any stale grouped data
    const qs = queryString(state)
    const url = `${API_BASE}/pastes?${qs}${qs ? '&' : ''}page=${state.page || 1}&per_page=50`
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: SearchResult = await res.json()
      if (pastesReqId.current !== reqId) return
      setPastes(data.results)
      setTotal(data.total)
      setPage(data.page)
      setTotalPages(data.total_pages)
    } catch (e: unknown) {
      if (pastesReqId.current !== reqId) return
      setError(e instanceof Error ? e.message : 'Failed to fetch pastes')
    } finally {
      if (pastesReqId.current === reqId) setLoading(false)
    }
  }, [])

  const fetchStats = useCallback(async (state?: FilterState) => {
    const reqId = ++statsReqId.current
    const qs = state ? queryString(state) : ''
    const data = await fetchJson<Stats>(`${API_BASE}/stats${qs ? `?${qs}` : ''}`)
    if (data && statsReqId.current === reqId) setStats(data)
  }, [])

  const fetchGroupedPastes = useCallback(async (state: FilterState) => {
    const reqId = ++pastesReqId.current
    setLoading(true)
    setError(null)
    setGroupedData(null)
    const qs = queryString(state)
    const url = `${API_BASE}/pastes?${qs}`
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: GroupedResult = await res.json()
      if (pastesReqId.current !== reqId) return
      setGroupedData(data)
      setTotal(data.total)
    } catch (e: unknown) {
      if (pastesReqId.current !== reqId) return
      setError(e instanceof Error ? e.message : 'Failed to fetch pastes')
    } finally {
      if (pastesReqId.current === reqId) setLoading(false)
    }
  }, [])

  const applyFilters = useCallback((state: FilterState) => {
    if (runningRef.current) return
    lastFilterRef.current = state
    if (state.groupBy) {
      fetchGroupedPastes(state)
    } else {
      fetchPastes(state)
    }
    fetchStats(state)
  }, [fetchPastes, fetchGroupedPastes, fetchStats])

  const fetchSources = useCallback(async (typeFilter?: string[]) => {
    const qs = typeFilter && typeFilter.length > 0 ? `?content_type=${encodeURIComponent(typeFilter[0])}` : ''
    const data = await fetchJson<SourceCount[]>(`${API_BASE}/sources${qs}`)
    if (data) setSources(data)
  }, [])

  const fetchTypes = useCallback(async (sourceFilter?: string[]) => {
    const qs = sourceFilter && sourceFilter.length > 0 ? `?source=${encodeURIComponent(sourceFilter[0])}` : ''
    const data = await fetchJson<TypeCount[]>(`${API_BASE}/types${qs}`)
    if (data) setTypes(data)
  }, [])

  const fetchSecretTypes = useCallback(async (sourceFilter?: string[], typeFilter?: string[]) => {
    const params: string[] = []
    if (sourceFilter && sourceFilter.length > 0) params.push(`source=${encodeURIComponent(sourceFilter[0])}`)
    if (typeFilter && typeFilter.length > 0) params.push(`content_type=${encodeURIComponent(typeFilter[0])}`)
    const qs = params.length > 0 ? `?${params.join('&')}` : ''
    const data = await fetchJson<SecretTypeCount[]>(`${API_BASE}/secret-types${qs}`)
    if (data) setSecretTypes(data)
  }, [])

  // Poll index status adaptively: every 3s while indexing or before the first
  // successful load (so a restart shows the overlay promptly), then every 60s
  // once idle. A fixed 60s interval meant one failed poll after a restart
  // delayed the loading screen by a full minute.
  useEffect(() => {
    let cancelled = false
    let timeout: ReturnType<typeof setTimeout>
    let dataLoaded = false
    let wasRunning = false

    const poll = async () => {
      const data = await fetchJson<IndexStatus>(`${API_BASE}/index-status`)
      if (!cancelled && data) {
        // If a manual reindex was triggered since the last poll, force wasRunning
        // to true so we detect completion even if the poll missed the running window.
        if (reindexTriggeredRef.current) {
          reindexTriggeredRef.current = false
          wasRunning = true
        }
        const justFinished = wasRunning && !data.running
        wasRunning = data.running
        setIndexStatus(data)
        runningRef.current = data.running
        // Fetch initial data only once the indexer is idle
        if (!data.running && !dataLoaded) {
          dataLoaded = true
          const [s, t, st, v] = await Promise.all([
            fetchJson<SourceCount[]>(`${API_BASE}/sources`),
            fetchJson<TypeCount[]>(`${API_BASE}/types`),
            fetchJson<SecretTypeCount[]>(`${API_BASE}/secret-types`),
            fetchJson<{ version: string }>(`${API_BASE}/version`),
          ])
          if (!cancelled) {
            if (s) setSources(s)
            if (t) setTypes(t)
            if (st) setSecretTypes(st)
            if (v) setVersion(v.version)
            fetchPastes({ ...lastFilterRef.current, page: 1 })
            fetchStats(lastFilterRef.current)
          }
        }
        // Index just completed — refresh data and show result
        if (justFinished && dataLoaded) {
          fetchPastes({ ...lastFilterRef.current, page: 1 })
          fetchStats(lastFilterRef.current)
          Promise.all([
            fetchJson<SourceCount[]>(`${API_BASE}/sources`),
            fetchJson<TypeCount[]>(`${API_BASE}/types`),
            fetchJson<SecretTypeCount[]>(`${API_BASE}/secret-types`),
            fetchJson<{ version: string }>(`${API_BASE}/version`),
            fetchJson<{indexed:number;deleted:number;total:number;skipped:number}>(`${API_BASE}/last-reindex`),
          ]).then(([s, t, st, v, last]) => {
            if (!cancelled) {
              if (s) setSources(s)
              if (t) setTypes(t)
              if (st) setSecretTypes(st)
              if (v) setVersion(v.version)
              if (last) setLastReindexResult(last)
            }
          })
        }
      }
      if (!cancelled) {
        // Fast retry while indexing, before the first load, or when the request
        // failed (data is null) — e.g. the backend was still starting up.
        const fast = !dataLoaded || !data || data.running || wasRunning
        timeout = setTimeout(poll, fast ? 3000 : 60000)
      }
    }

    poll()

    return () => {
      cancelled = true
      if (timeout) clearTimeout(timeout)
    }
  }, [fetchPastes, fetchStats])

  const triggerReindex = useCallback(async (mode: string = 'standard') => {
    reindexTriggeredRef.current = true
    setIndexStatus({ running: true, current: 0, total: 0, phase: 'indexing' })
    runningRef.current = true
    fetch(`${API_BASE}/reindex?mode=${mode}`, { method: 'POST' }).catch(() => {})
    // Immediate status poll so the overlay shows real progress right away
    const status = await fetchJson<IndexStatus>(`${API_BASE}/index-status`)
    if (status && status.running) {
      setIndexStatus(status)
      runningRef.current = true
    }
  }, [])

  return {
    pastes, total, page, totalPages, loading, error,
    sources, types, secretTypes, stats, indexStatus, version,
    lastReindexResult, groupedData,
    applyFilters, fetchStats, triggerReindex, fetchSources, fetchTypes, fetchSecretTypes,
  }
}

export async function fetchPasteDetail(id: string): Promise<PasteResult | null> {
  return fetchJson<PasteResult>(`${API_BASE}/pastes/${encodeURIComponent(id)}`)
}

export interface TriageState {
  triage_status: string
  triage_note: string
  triage_reviewer: string
  triage_updated_at: string | null
}

export async function updateTriage(
  id: string,
  payload: { status?: string; note?: string },
): Promise<TriageState> {
  const res = await fetch(`${API_BASE}/pastes/${encodeURIComponent(id)}/triage`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data as TriageState
}

export async function applyTriageToIdentical(
  id: string,
  payload: { status: string; note?: string },
): Promise<{ updated: number }> {
  const res = await fetch(`${API_BASE}/pastes/${encodeURIComponent(id)}/triage/identical`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data as { updated: number }
}