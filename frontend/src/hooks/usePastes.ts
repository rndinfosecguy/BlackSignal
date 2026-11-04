import { useState, useEffect, useCallback, useRef } from 'react'

const API_BASE = '/api'

export interface FilterState {
  q?: string
  source?: string
  type?: string
  secretTypes?: string[]
  hasSecrets?: boolean
  page?: number
}

interface SecretTypeCount { type: string; count: number }
interface SourceCount { source: string; count: number }
interface TypeCount { content_type: string; count: number }
interface Stats { total: number; with_secrets: number; with_passwords: number; sources: number }
interface PasteResult {
  id: string; filename: string; source: string; content_type: string; size: number
  has_passwords: boolean; has_secrets: boolean
  secret_types: string[]
  secrets_detail: { type: string; line: number; match: string }[] | null
  first_seen: string; snippet: string
}
interface SearchResult { total: number; page: number; per_page: number; total_pages: number; results: PasteResult[] }

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
  if (state.source) qp.set('source', state.source)
  if (state.type) qp.set('content_type', state.type)
  if (state.secretTypes) state.secretTypes.forEach(st => qp.append('secret_type', st))
  if (state.hasSecrets) qp.set('has_secrets', 'true')
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
  const [error, setError] = useState<string | null>(null)
  const [indexStatus, setIndexStatus] = useState<IndexStatus>(defaultIndexStatus)

  const pastesReqId = useRef(0)
  const statsReqId = useRef(0)
  const runningRef = useRef(false)

  const fetchPastes = useCallback(async (state: FilterState) => {
    const reqId = ++pastesReqId.current
    setLoading(true)
    setError(null)
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

  const applyFilters = useCallback((state: FilterState) => {
    if (runningRef.current) return
    fetchPastes(state)
    fetchStats(state)
  }, [fetchPastes, fetchStats])

  // Poll index status every 60s; fetch initial data once when the indexer is idle
  useEffect(() => {
    let cancelled = false
    let timeout: ReturnType<typeof setTimeout>
    let dataLoaded = false

    const poll = async () => {
      const data = await fetchJson<IndexStatus>(`${API_BASE}/index-status`)
      if (!cancelled && data) {
        setIndexStatus(data)
        runningRef.current = data.running
        // Fetch initial data only once the indexer is idle
        if (!data.running && !dataLoaded) {
          dataLoaded = true
          const [s, t, st] = await Promise.all([
            fetchJson<SourceCount[]>(`${API_BASE}/sources`),
            fetchJson<TypeCount[]>(`${API_BASE}/types`),
            fetchJson<SecretTypeCount[]>(`${API_BASE}/secret-types`),
          ])
          if (!cancelled) {
            if (s) setSources(s)
            if (t) setTypes(t)
            if (st) setSecretTypes(st)
            fetchPastes({ page: 1 })
            fetchStats({})
          }
        }
      }
      if (!cancelled) timeout = setTimeout(poll, 60000)
    }

    poll()

    return () => {
      cancelled = true
      if (timeout) clearTimeout(timeout)
    }
  }, [fetchPastes, fetchStats])

  const triggerReindex = useCallback(async () => {
    setIndexStatus({ running: true, current: 0, total: 0, phase: 'indexing' })
    runningRef.current = true
    fetch(`${API_BASE}/reindex`, { method: 'POST' }).catch(() => {})
    // Immediate status poll so the overlay shows real progress right away
    const status = await fetchJson<IndexStatus>(`${API_BASE}/index-status`)
    if (status) {
      setIndexStatus(status)
      runningRef.current = status.running
    }
  }, [])

  return {
    pastes, total, page, totalPages, loading, error,
    sources, types, secretTypes, stats, indexStatus,
    applyFilters, triggerReindex,
  }
}

export async function fetchPasteDetail(id: string): Promise<PasteResult | null> {
  return fetchJson<PasteResult>(`${API_BASE}/pastes/${encodeURIComponent(id)}`)
}