import { useState, useEffect, useCallback, useRef } from 'react'

const API_BASE = '/api'

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

  const paramsRef = useRef({ q: '', source: '', type: '', secretTypes: [] as string[] })

  const fetchPastes = useCallback(async (params: {
    q?: string; source?: string; type?: string; secretTypes?: string[]; hasSecrets?: boolean; page?: number
  }) => {
    setLoading(true)
    setError(null)
    try {
      const qp = new URLSearchParams()
      if (params.q) qp.set('q', params.q)
      if (params.source) qp.set('source', params.source)
      if (params.type) qp.set('content_type', params.type)
      if (params.secretTypes) params.secretTypes.forEach(st => qp.append('secret_type', st))
      if (params.hasSecrets) qp.set('has_secrets', 'true')
      qp.set('page', String(params.page || 1))
      qp.set('per_page', '50')

      const res = await fetch(`${API_BASE}/pastes?${qp}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: SearchResult = await res.json()
      setPastes(data.results)
      setTotal(data.total)
      setPage(data.page)
      setTotalPages(data.total_pages)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch pastes')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchSources = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/sources`); if (r.ok) setSources(await r.json()) } catch {}
  }, [])
  const fetchTypes = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/types`); if (r.ok) setTypes(await r.json()) } catch {}
  }, [])
  const fetchSecretTypes = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/secret-types`); if (r.ok) setSecretTypes(await r.json()) } catch {}
  }, [])
  const fetchStats = useCallback(async (params?: {
    q?: string; source?: string; type?: string; secretTypes?: string[]; hasSecrets?: boolean
  }) => {
    try {
      let url = `${API_BASE}/stats`
      if (params) {
        const qp = new URLSearchParams()
        if (params.q) qp.set('q', params.q)
        if (params.source) qp.set('source', params.source)
        if (params.type) qp.set('content_type', params.type)
        if (params.secretTypes) params.secretTypes.forEach(st => qp.append('secret_type', st))
        if (params.hasSecrets) qp.set('has_secrets', 'true')
        const qs = qp.toString()
        if (qs) url += '?' + qs
      }
      const r = await fetch(url); if (r.ok) setStats(await r.json())
    } catch {}
  }, [])

  useEffect(() => {
    fetchSources()
    fetchTypes()
    fetchSecretTypes()
    fetchStats()
    fetchPastes({ page: 1 })
  }, [fetchPastes, fetchSources, fetchTypes, fetchSecretTypes, fetchStats])

  const search = useCallback((
    q: string, source?: string, type_?: string,
    secretTypes?: string[], hasSecrets?: boolean, pg?: number
  ) => {
    paramsRef.current = {
      q, source: source || '', type: type_ || '', secretTypes: secretTypes || []
    }
    fetchPastes({ q, source, type: type_, secretTypes, hasSecrets, page: pg || 1 })
  }, [fetchPastes])

  return {
    pastes, total, page, totalPages, loading, error,
    sources, types, secretTypes, stats,
    search, fetchPastes, fetchSources, fetchTypes, fetchSecretTypes, fetchStats,
  }
}

export async function fetchPasteDetail(id: string): Promise<PasteResult | null> {
  try {
    const res = await fetch(`${API_BASE}/pastes/${encodeURIComponent(id)}`)
    if (!res.ok) return null
    return await res.json()
  } catch { return null }
}