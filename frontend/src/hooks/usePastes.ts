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

function buildStatsUrl(state: FilterState): string {
  const qp = new URLSearchParams()
  if (state.q) qp.set('q', state.q)
  if (state.source) qp.set('source', state.source)
  if (state.type) qp.set('content_type', state.type)
  if (state.secretTypes) state.secretTypes.forEach(st => qp.append('secret_type', st))
  if (state.hasSecrets) qp.set('has_secrets', 'true')
  const qs = qp.toString()
  return qs ? `${API_BASE}/stats?${qs}` : `${API_BASE}/stats`
}

function buildPastesUrl(state: FilterState): string {
  const qp = new URLSearchParams()
  if (state.q) qp.set('q', state.q)
  if (state.source) qp.set('source', state.source)
  if (state.type) qp.set('content_type', state.type)
  if (state.secretTypes) state.secretTypes.forEach(st => qp.append('secret_type', st))
  if (state.hasSecrets) qp.set('has_secrets', 'true')
  qp.set('page', String(state.page || 1))
  qp.set('per_page', '50')
  return `${API_BASE}/pastes?${qp}`
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

  const pastesReqId = useRef(0)
  const statsReqId = useRef(0)

  const fetchPastes = useCallback(async (state: FilterState) => {
    const reqId = ++pastesReqId.current
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(buildPastesUrl(state))
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
    try {
      const r = await fetch(buildStatsUrl(state || {}))
      if (r.ok) {
        const data = await r.json()
        if (statsReqId.current === reqId) setStats(data)
      }
    } catch {}
  }, [])

  const applyFilters = useCallback((state: FilterState) => {
    fetchPastes(state)
    fetchStats(state)
  }, [fetchPastes, fetchStats])

  const fetchSources = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/sources`); if (r.ok) setSources(await r.json()) } catch {}
  }, [])
  const fetchTypes = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/types`); if (r.ok) setTypes(await r.json()) } catch {}
  }, [])
  const fetchSecretTypes = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/secret-types`); if (r.ok) setSecretTypes(await r.json()) } catch {}
  }, [])

  useEffect(() => {
    fetchSources()
    fetchTypes()
    fetchSecretTypes()
    fetchPastes({ page: 1 })
    fetchStats({})
  }, [fetchSources, fetchTypes, fetchSecretTypes, fetchPastes, fetchStats])

  return {
    pastes, total, page, totalPages, loading, error,
    sources, types, secretTypes, stats,
    applyFilters, fetchStats, fetchSources, fetchTypes, fetchSecretTypes,
  }
}

export async function fetchPasteDetail(id: string): Promise<PasteResult | null> {
  try {
    const res = await fetch(`${API_BASE}/pastes/${encodeURIComponent(id)}`)
    if (!res.ok) return null
    return await res.json()
  } catch { return null }
}