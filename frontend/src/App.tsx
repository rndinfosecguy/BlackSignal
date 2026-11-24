import { useState, useCallback, useEffect, useRef } from 'react'
import { sourceColor, renderMarkdown } from './lib/utils'
import SearchBar from './components/SearchBar'
import FilterChips from './components/FilterChips'
import PasteCard from './components/PasteCard'
import PasteDetail from './components/PasteDetail'
import StatsDashboard from './components/StatsDashboard'
import Pagination from './components/Pagination'
import ConfigTab from './components/ConfigTab'
import { usePastes } from './hooks/usePastes'
import type { FilterState } from './hooks/usePastes'

type Overrides = Partial<FilterState>

export default function App() {
  const {
    pastes, total, page, totalPages, loading, error,
    sources, types, secretTypes, stats, indexStatus, version,
    lastReindexResult, groupedData,
    applyFilters, fetchStats, triggerReindex, fetchSources, fetchTypes, fetchSecretTypes,
  } = usePastes()

  const [query, setQuery] = useState('')
  const [activeSources, setActiveSources] = useState<string[]>([])
  const [activeTypes, setActiveTypes] = useState<string[]>([])
  const [activeSecretTypes, setActiveSecretTypes] = useState<string[]>([])
  const [hasSecrets, setHasSecrets] = useState(false)
  const [groupBy, setGroupBy] = useState('')
  const [detailId, setDetailId] = useState<string | null>(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // Computed filter state flags (used before the dashboard section)
  const [currentTab, setCurrentTab] = useState('dashboard')
  const [reindexToast, setReindexToast] = useState<string | null>(null)
  const [showLoadingOverlay, setShowLoadingOverlay] = useState(false)
  const [llmReportRunning, setLlmReportRunning] = useState(false)
  const [llmReportProgress, setLlmReportProgress] = useState<{ current: number; total: number; phase?: string } | null>(null)
  const [llmReportResult, setLlmReportResult] = useState<string | null>(null)
  const [llmReportError, setLlmReportError] = useState<string | null>(null)
  const [showLlmReport, setShowLlmReport] = useState(false)
  const [llmConfigured, setLlmConfigured] = useState(false)
  const [confirmLlmCancel, setConfirmLlmCancel] = useState(false)
  const reportPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Watch for new reindex results — show a toast until dismissed
  useEffect(() => {
    if (!lastReindexResult) return
    const parts: string[] = []
    if (lastReindexResult.indexed > 0) parts.push(`${lastReindexResult.indexed.toLocaleString()} new`)
    if (lastReindexResult.deleted > 0) parts.push(`${lastReindexResult.deleted.toLocaleString()} deleted`)
    if (lastReindexResult.skipped > 0) parts.push(`${lastReindexResult.skipped.toLocaleString()} skipped`)
    if (parts.length === 0) parts.push('no changes')
    setReindexToast(`Reindex complete: ${parts.join(', ')}`)
  }, [lastReindexResult])

  // Fetch LLM config status for the report button
  useEffect(() => {
    fetch('/api/llm/config')
      .then(r => r.json())
      .then(d => setLlmConfigured(d.configured))
      .catch(() => setLlmConfigured(false))
  }, [])

  // Show loading overlay when filters take > 1 second
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    if (loading) {
      timer = setTimeout(() => setShowLoadingOverlay(true), 1000)
    } else {
      setShowLoadingOverlay(false)
    }
    return () => { if (timer) clearTimeout(timer) }
  }, [loading])

  const applyAll = useCallback((overrides: Overrides) => {
    const nextQuery = overrides.q !== undefined ? overrides.q : query
    const nextSources = overrides.sources !== undefined ? overrides.sources : activeSources
    const nextTypes = overrides.types !== undefined ? overrides.types : activeTypes
    const nextSecretTypes = overrides.secretTypes !== undefined ? overrides.secretTypes : activeSecretTypes
    const nextHasSecrets = overrides.hasSecrets !== undefined ? overrides.hasSecrets : hasSecrets
    const nextGroupBy = overrides.groupBy !== undefined ? overrides.groupBy : groupBy
    const nextDateFrom = overrides.dateFrom !== undefined ? overrides.dateFrom : dateFrom
    const nextDateTo = overrides.dateTo !== undefined ? overrides.dateTo : dateTo

    const filterChanged =
      overrides.q !== undefined ||
      overrides.sources !== undefined ||
      overrides.types !== undefined ||
      overrides.secretTypes !== undefined ||
      overrides.hasSecrets !== undefined ||
      overrides.groupBy !== undefined ||
      overrides.dateFrom !== undefined ||
      overrides.dateTo !== undefined

    applyFilters({
      q: nextQuery,
      sources: nextSources,
      types: nextTypes,
      secretTypes: nextSecretTypes,
      hasSecrets: nextHasSecrets,
      groupBy: nextGroupBy,
      dateFrom: nextDateFrom,
      dateTo: nextDateTo,
      page: filterChanged ? 1 : (overrides.page ?? page),
    })
    if (nextGroupBy !== groupBy) setGroupBy(nextGroupBy)

    // Re-fetch filtered counts when source or type filter changes
    if (overrides.sources !== undefined || overrides.types !== undefined) {
      const hasSource = nextSources.length > 0
      const hasType = nextTypes.length > 0
      if (hasSource || hasType) {
        fetchTypes(nextSources)
        fetchSources(nextTypes)
        fetchSecretTypes(hasSource ? nextSources : undefined, hasType ? nextTypes : undefined)
      } else {
        fetchTypes()
        fetchSources()
        fetchSecretTypes()
      }
    }
  }, [applyFilters, fetchSources, fetchTypes, fetchSecretTypes, query, activeSources, activeTypes, activeSecretTypes, hasSecrets, groupBy, dateFrom, dateTo, page])

  const handleSearch = useCallback((q: string) => {
    setQuery(q)
    applyAll({ q })
  }, [applyAll])

  const handleFiltersBatch = useCallback((filters: { sources?: string[]; types?: string[]; secretTypes?: string[]; hasSecrets?: boolean; dateFrom?: string; dateTo?: string }) => {
    if (filters.sources !== undefined) setActiveSources(filters.sources)
    if (filters.types !== undefined) setActiveTypes(filters.types)
    if (filters.secretTypes !== undefined) setActiveSecretTypes(filters.secretTypes)
    if (filters.hasSecrets !== undefined) setHasSecrets(filters.hasSecrets)
    if (filters.dateFrom !== undefined) setDateFrom(filters.dateFrom)
    if (filters.dateTo !== undefined) setDateTo(filters.dateTo)
    applyAll({
      sources: filters.sources !== undefined ? filters.sources : activeSources,
      types: filters.types !== undefined ? filters.types : activeTypes,
      secretTypes: filters.secretTypes !== undefined ? filters.secretTypes : activeSecretTypes,
      hasSecrets: filters.hasSecrets !== undefined ? filters.hasSecrets : hasSecrets,
      dateFrom: filters.dateFrom !== undefined ? filters.dateFrom : dateFrom,
      dateTo: filters.dateTo !== undefined ? filters.dateTo : dateTo,
    })
  }, [applyAll, activeSources, activeTypes, activeSecretTypes, hasSecrets, dateFrom, dateTo])

  const handleSecretTypeToggle = useCallback((st: string) => {
    const next = activeSecretTypes.includes(st)
      ? activeSecretTypes.filter(x => x !== st)
      : [...activeSecretTypes, st]
    setActiveSecretTypes(next)
    applyAll({ secretTypes: next })
  }, [applyAll, activeSecretTypes])

  const handleSecretTypesBatch = useCallback((next: string[]) => {
    setActiveSecretTypes(next)
    applyAll({ secretTypes: next })
  }, [applyAll])

  const handleSecretTypeClear = useCallback(() => {
    setActiveSecretTypes([])
    applyAll({ secretTypes: [] })
  }, [applyAll])

  const handleHasSecretsToggle = useCallback(() => {
    const next = !hasSecrets
    setHasSecrets(next)
    applyAll({ hasSecrets: next })
  }, [applyAll, hasSecrets])

  const handlePageChange = useCallback((p: number) => {
    applyAll({ page: p })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [applyAll])

  const handleLlmReport = async () => {
    if (llmReportRunning) return
    // Re-check config in case the user updated it in the Config tab
    try {
      const cfgRes = await fetch('/api/llm/config')
      const cfgData = await cfgRes.json()
      if (!cfgData.configured) {
        setLlmConfigured(false)
        return
      }
      setLlmConfigured(true)
    } catch {
      setLlmConfigured(false)
      return
    }
    setLlmReportResult(null)
    setLlmReportError(null)
    setLlmReportRunning(true)
    setLlmReportProgress(null)
    setShowLlmReport(true)

    // Build the same query string as the export links
    const params: string[] = []
    if (query) params.push(`q=${encodeURIComponent(query)}`)
    activeSources.forEach(s => params.push(`source=${encodeURIComponent(s)}`))
    activeTypes.forEach(t => params.push(`content_type=${encodeURIComponent(t)}`))
    activeSecretTypes.forEach(st => params.push(`secret_type=${encodeURIComponent(st)}`))
    if (hasSecrets) params.push('has_secrets=true')
    if (dateFrom) params.push(`date_from=${encodeURIComponent(dateFrom)}`)
    if (dateTo) params.push(`date_to=${encodeURIComponent(dateTo)}`)

    try {
      const res = await fetch(`/api/llm/report${params.length > 0 ? '?' + params.join('&') : ''}`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      if (data.status === 'done') {
        setLlmReportResult(data.report)
        setLlmReportRunning(false)
        return
      }
      setLlmReportProgress({ current: 0, total: data.total, phase: 'analyzing' })

      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const pr = await fetch('/api/llm/report-status')
          const pd = await pr.json()
          if (pd.running) {
            setLlmReportProgress({ current: pd.current || 0, total: pd.total || 0, phase: pd.phase })
          } else {
            clearInterval(poll)
            setLlmReportRunning(false)
            if (pd.final_report) {
              setLlmReportResult(pd.final_report)
            } else if (pd.error) {
              setLlmReportError(pd.error)
            } else {
              setLlmReportError('Report generation failed')
            }
          }
        } catch {
          clearInterval(poll)
          setLlmReportRunning(false)
          setLlmReportError('Failed to poll report status')
        }
      }, 3000)
      reportPollRef.current = poll
    } catch (e: unknown) {
      setLlmReportError(e instanceof Error ? e.message : 'Failed to start report')
      setLlmReportRunning(false)
    }
  }

  const handleCloseLlmReport = () => {
    // If the report is still running without result, ask for confirmation
    if (llmReportRunning && llmReportResult === null && llmReportError === null) {
      setConfirmLlmCancel(true)
      return
    }
    if (reportPollRef.current) {
      clearInterval(reportPollRef.current)
      reportPollRef.current = null
    }
    setShowLlmReport(false)
    setLlmReportRunning(false)
  }

  const handleDownloadReport = () => {
    if (!llmReportResult) return
    // Download the ZIP bundle (report.md at root + per-paste analyses in pastes/)
    const a = document.createElement('a')
    a.href = '/api/llm/report-download'
    a.download = 'blacksignal-llm-report.zip'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const indexing = indexStatus.running

  const progressPct = indexStatus.total > 0
    ? Math.round((indexStatus.current / indexStatus.total) * 100)
    : 0

  // Dashboard computed values
  const topSecretType = secretTypes
    .filter(st => st.count > 0)
    .sort((a: any, b: any) => b.count - a.count)[0]
  const totalDetections = secretTypes.reduce((sum: number, st: any) => sum + (st.count || 0), 0)
  const personalTypes = ['personal_email','ssn','btc_address','eth_address','passport','name_dob']
  const personalSecretCount = secretTypes
    .filter((st: any) => personalTypes.includes(st.type))
    .reduce((sum: number, st: any) => sum + (st.count || 0), 0)
  const technicalSecretCount = secretTypes
    .filter((st: any) => !personalTypes.includes(st.type))
    .reduce((sum: number, st: any) => sum + (st.count || 0), 0)
  const personalSecretTypes = secretTypes.filter((st: any) => personalTypes.includes(st.type))
  const technicalSecretTypes = secretTypes.filter((st: any) => !personalTypes.includes(st.type))
  const topTechnicalType = technicalSecretTypes
    .filter(st => st.count > 0)
    .sort((a: any, b: any) => b.count - a.count)[0]
  const topPersonalType = personalSecretTypes
    .filter(st => st.count > 0)
    .sort((a: any, b: any) => b.count - a.count)[0]

  return (
    <div className="min-h-screen bg-[#0d0d0d]">
      {indexing ? (
        /* Full-screen indexing overlay whenever the indexer is active */
        <div className="min-h-screen flex flex-col items-center justify-center px-6">
          <img src="/bs_logo.png" alt="BlackSignal" className="h-24 mb-8 opacity-60" />
          <div className="w-full max-w-md">
            <div className="flex justify-between text-[13px] text-[#555555] mb-2">
              <span>Indexing pastes...</span>
              <span>
                {indexStatus.current > 0
                  ? `${indexStatus.current.toLocaleString()} / ${indexStatus.total.toLocaleString()} (${progressPct}%)`
                  : indexStatus.total > 0
                    ? `0 / ${indexStatus.total.toLocaleString()} (0%)`
                    : 'Scanning files...'}
              </span>
            </div>
            <div className="w-full h-2 bg-[#1a1a1a] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#ff004d] rounded-full transition-all duration-500 ease-out"
                style={{ width: `${indexStatus.total > 0 ? progressPct : 5}%` }}
              />
            </div>
            <p className="text-[12px] text-[#444444] text-center mt-3">
              Indexing in progress — the UI will appear automatically when ready
            </p>
          </div>
        </div>
      ) : (
        <div className="max-w-5xl mx-auto px-6 py-6">
          <header className="mb-6">
            <div className="flex items-center gap-6">
              <img src="/bs_logo.png" alt="BlackSignal" className="h-16 shrink-0" />
              <StatsDashboard stats={stats} />
            </div>
          </header>

          <div className="flex items-center gap-0 mb-5 border-b border-[#222222]">
            <button onClick={() => { fetchStats({}); setCurrentTab('dashboard') }}
              className={`text-sm px-4 py-2 ${currentTab === 'dashboard' ? 'text-[#00e5ff] border-b-2 border-[#00e5ff]' : 'text-[#555555] hover:text-[#777777]'} transition-all cursor-pointer`}>
              Dashboard
            </button>
            <button onClick={() => {
                fetchStats({ q: query, sources: activeSources, types: activeTypes, secretTypes: activeSecretTypes.length > 0 ? activeSecretTypes : undefined, hasSecrets, dateFrom, dateTo })
                fetch('/api/llm/config').then(r => r.json()).then(d => setLlmConfigured(d.configured)).catch(() => {})
                setCurrentTab('pastes')
              }}
              className={`text-sm px-4 py-2 ${currentTab === 'pastes' ? 'text-[#00e5ff] border-b-2 border-[#00e5ff]' : 'text-[#555555] hover:text-[#777777]'} transition-all cursor-pointer`}>
              Pastes
            </button>
            <button onClick={() => setCurrentTab('config')}
              className={`text-sm px-4 py-2 ${currentTab === 'config' ? 'text-[#00e5ff] border-b-2 border-[#00e5ff]' : 'text-[#555555] hover:text-[#777777]'} transition-all cursor-pointer`}>
              Config
            </button>
          </div>

          {reindexToast && (
            <div className="mb-4 bg-[#131313] border border-[#222222] rounded-lg px-4 py-3 shadow-lg flex items-center gap-3"
              style={{ borderLeft: '3px solid #00e5ff' }}>
              <div className="flex-1 text-xs text-[#888888]">{reindexToast}</div>
              <button onClick={() => setReindexToast(null)} className="text-[#666666] hover:text-[#ff004d] text-sm transition-all leading-none cursor-pointer">&times;</button>
            </div>
          )}

          {currentTab === 'pastes' && (
            <>
            <div className="mb-6 space-y-4">
              <SearchBar onSearch={handleSearch} loading={loading} />
              <FilterChips
                sources={sources}
                types={types}
                secretTypes={secretTypes}
                activeSources={activeSources}
                activeTypes={activeTypes}
                activeSecretTypes={activeSecretTypes}
                hasSecrets={hasSecrets}
                dateFrom={dateFrom}
                dateTo={dateTo}
                onSourcesChange={(s) => { setActiveSources(s); applyAll({ sources: s }) }}
                onTypesChange={(t) => { setActiveTypes(t); applyAll({ types: t }) }}
                onSecretTypeToggle={handleSecretTypeToggle}
                onSecretTypesBatch={handleSecretTypesBatch}
                onFiltersBatch={handleFiltersBatch}
                onSecretTypeClear={handleSecretTypeClear}
                onHasSecretsToggle={handleHasSecretsToggle}
                onDateFromChange={(d) => { setDateFrom(d); applyAll({ dateFrom: d }) }}
                onDateToChange={(d) => { setDateTo(d); applyAll({ dateTo: d }) }}
              />
            </div>

            <div className="space-y-3">
              {/* Group toggle + Export */}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap gap-2 items-center">
                  <span className="text-xs text-[#444444] mr-1">Group</span>
                  <button onClick={() => { setGroupBy(''); applyAll({ groupBy: '' }) }}
                    className={`text-xs px-3 py-1.5 rounded-md border transition-all cursor-pointer ${!groupBy ? 'border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/5' : 'border-[#222222] text-[#666666] hover:border-[#444444] hover:text-[#888888]'}`}>
                    None
                  </button>
                  <button onClick={() => { setGroupBy('source'); applyAll({ groupBy: 'source' }) }}
                    className={`text-xs px-3 py-1.5 rounded-md border transition-all cursor-pointer ${groupBy === 'source' ? 'border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/5' : 'border-[#222222] text-[#555555]'}`}>
                    Source
                  </button>
                  <button onClick={() => { setGroupBy('content_type'); applyAll({ groupBy: 'content_type' }) }}
                    className={`text-xs px-3 py-1.5 rounded-md border transition-all cursor-pointer ${groupBy === 'content_type' ? 'border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/5' : 'border-[#222222] text-[#555555]'}`}>
                    Type
                  </button>
                </div>
                <div className="flex flex-wrap gap-2 items-center">
                  <span className="text-xs text-[#444444] mr-1">Export</span>
                  <a href={`/api/pastes/export?format=csv${query ? `&q=${encodeURIComponent(query)}` : ''}${activeSources.map(s => `&source=${encodeURIComponent(s)}`).join('')}${activeTypes.map(t => `&content_type=${encodeURIComponent(t)}`).join('')}${hasSecrets ? '&has_secrets=true' : ''}${activeSecretTypes.map(st => `&secret_type=${encodeURIComponent(st)}`).join('')}${dateFrom ? `&date_from=${encodeURIComponent(dateFrom)}` : ''}${dateTo ? `&date_to=${encodeURIComponent(dateTo)}` : ''}`}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:border-[#444444] hover:text-[#888888] transition-all cursor-pointer no-underline">
                    CSV
                  </a>
                  <a href={`/api/pastes/export?format=json${query ? `&q=${encodeURIComponent(query)}` : ''}${activeSources.map(s => `&source=${encodeURIComponent(s)}`).join('')}${activeTypes.map(t => `&content_type=${encodeURIComponent(t)}`).join('')}${hasSecrets ? '&has_secrets=true' : ''}${activeSecretTypes.map(st => `&secret_type=${encodeURIComponent(st)}`).join('')}${dateFrom ? `&date_from=${encodeURIComponent(dateFrom)}` : ''}${dateTo ? `&date_to=${encodeURIComponent(dateTo)}` : ''}`}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:border-[#444444] hover:text-[#888888] transition-all cursor-pointer no-underline">
                    JSON
                  </a>
                  <span className="text-[#333333] text-xs">|</span>
                  <button onClick={handleLlmReport} disabled={llmReportRunning || !llmConfigured}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#ff004d]/40 text-[#ff004d] hover:bg-[#ff004d]/10 hover:border-[#ff004d] transition-all cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                    title={!llmConfigured ? 'Set up data/openrouter.json with your OpenRouter API key to enable' : ''}>
                    {llmReportRunning ? 'Generating...' : 'LLM Report'}
                  </button>
                </div>
              </div>

              {/* Loading overlay with liquid glass effect */}
              {showLoadingOverlay && (
                <div className="fixed inset-0 z-30 flex items-center justify-center bg-[#0d0d0d]/40"
                  style={{ backdropFilter: 'blur(3px)', WebkitBackdropFilter: 'blur(3px)' }}>
                  <div className="relative flex flex-col items-center gap-4">
                    {/* Spinner */}
                    <div className="w-10 h-10 rounded-full border-2 border-transparent border-t-[#00e5ff] border-r-[#00e5ff]/60 animate-spin"
                      style={{ animation: 'spin 0.8s linear infinite' }} />
                    <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
                    <div className="text-xs text-[#555555]">Loading...</div>
                  </div>
                </div>
              )}

              {loading && pastes.length === 0 && groupedData === null ? (
                <div className="flex items-center justify-center h-32 text-[#555555]">Loading pastes...</div>
              ) : error ? (
                <div className="flex items-center justify-center h-32"><span className="text-[#ff004d]">Error: {error}</span></div>
              ) : groupedData ? (
                <div className="space-y-4">
                  {groupedData.groups.map(g => (
                    <details key={g.key} className="bg-[#131313] border border-[#222222] rounded-lg p-3">
                      <summary className="text-xs font-medium cursor-pointer flex items-center gap-2"
                        style={{ color: groupBy === 'source' ? sourceColor(g.key) : '#00e5ff' }}>
                        <span>{g.key}</span>
                        <span className="text-[#555555]">({g.total.toLocaleString()})</span>
                      </summary>
                      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {g.results.map(p => <PasteCard key={`${p.source}:${p.id}`} {...p} onClick={setDetailId} />)}
                      </div>
                      {g.total > g.results.length && (
                        <button onClick={() => {
                          if (groupBy === 'source') { setActiveSources([g.key]); applyAll({ sources: [g.key] }) }
                          else { setActiveTypes([g.key]); applyAll({ types: [g.key] }) }
                        }}
                          className="w-full mt-2 text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#777777] hover:border-[#444444] transition-all cursor-pointer">
                          View all {g.total.toLocaleString()} results
                        </button>
                      )}
                    </details>
                  ))}
                </div>
              ) : pastes.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-[#555555]">No results found</div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {pastes.map(p => <PasteCard key={`${p.source}:${p.id}`} {...p} onClick={setDetailId} />)}
                </div>
              )}
            </div>

            {!groupedData && <Pagination page={page} totalPages={totalPages} total={total} onChange={handlePageChange} />}
            </>
          )}

          {currentTab === 'dashboard' && stats && (
            <div className="space-y-5">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-5 text-center">
                  <div className="text-xs text-[#888888] mb-2">Total findings</div>
                  <div className="text-2xl font-semibold text-[#ff004d]">{totalDetections.toLocaleString()}</div>
                  <div className="text-[11px] text-[#555555] mt-1">
                    in {stats.with_secrets.toLocaleString()} affected pastes
                  </div>
                </div>
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-5 text-center">
                  <div className="text-xs text-[#888888] mb-2">Technical</div>
                  <div className="text-2xl font-semibold text-[#00e5ff]">{technicalSecretCount.toLocaleString()}</div>
                  <div className="text-[11px] text-[#555555] mt-1">
                    {topTechnicalType?.type || '—'}: {topTechnicalType?.count.toLocaleString() || '0'}
                  </div>
                </div>
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-5 text-center">
                  <div className="text-xs text-[#888888] mb-2">Personal</div>
                  <div className="text-2xl font-semibold text-[#ffd700]">{personalSecretCount.toLocaleString()}</div>
                  <div className="text-[11px] text-[#555555] mt-1">
                    {topPersonalType?.type || '—'}: {topPersonalType?.count.toLocaleString() || '0'}
                  </div>
                </div>
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-5 text-center">
                  <div className="text-xs text-[#888888] mb-2">Detection types</div>
                  <div className="text-2xl font-semibold text-[#555555]">{secretTypes.filter((st: any) => st.count > 0).length.toLocaleString()}</div>
                  <div className="text-[11px] text-[#555555] mt-1">
                    different categories
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-4">
                  <div className="text-xs text-[#888888] font-medium mb-3 uppercase tracking-wider">Sources</div>
                  {sources.filter(s => s.count > 0).slice(0, 10).map(s => {
                    const pct = stats.total > 0 ? (s.count / stats.total * 100) : 0
                    return (
                      <div key={s.source} className="flex items-center gap-2 mb-1.5">
                        <span style={{ backgroundColor: sourceColor(s.source) }} className="w-2 h-2 rounded-full shrink-0" />
                        <span className="text-xs text-[#777777]">{s.source}</span>
                        <div className="flex-1 h-1.5 rounded-full bg-[#222222] overflow-hidden">
                          <div className="h-full bg-[#00e5ff] rounded-full" style={{ width: `${pct}%`, maxWidth: '100%' }} />
                        </div>
                        <span className="text-xs text-[#555555]">{s.count.toLocaleString()}</span>
                      </div>
                    )
                  })}
                </div>

                <div className="bg-[#131313] border border-[#222222] rounded-lg p-4">
                  <div className="text-xs text-[#888888] font-medium mb-3 uppercase tracking-wider">Content Types</div>
                  {types.filter(t => t.count > 0).slice(0, 10).map(t => {
                    const pct = stats.total > 0 ? (t.count / stats.total * 100) : 0
                    return (
                      <div key={t.content_type} className="flex items-center gap-2 mb-1.5">
                        <span className="w-2 h-2 rounded-full bg-[#555555]" />
                        <span className="text-xs text-[#777777]">{t.content_type}</span>
                        <div className="flex-1 h-1.5 rounded-full bg-[#222222] overflow-hidden">
                          <div className="h-full bg-[#00ff41] rounded-full" style={{ width: `${pct}%`, maxWidth: '100%' }} />
                        </div>
                        <span className="text-xs text-[#555555]">{t.count.toLocaleString()}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-4">
                  <div className="text-xs text-[#888888] font-medium mb-3 uppercase tracking-wider">Technical Detections</div>
                  {(() => {
                    const withCounts = technicalSecretTypes.filter((st: any) => st.count > 0)
                    const td = withCounts.reduce((s: number, st: any) => s + (st.count || 0), 0)
                    return withCounts.length > 0 ? withCounts.slice(0, 15).map((st: any) => {
                      const pct = td > 0 ? st.count / td * 100 : 0
                      return (
                        <div key={st.type} className="flex items-center gap-2 mb-1.5">
                          <span className="w-2 h-2 rounded-full bg-[#00e5ff]" />
                          <span className="text-xs text-[#777777]">{st.type}</span>
                          <div className="flex-1 h-1.5 rounded-full bg-[#222222] overflow-hidden">
                            <div className="h-full bg-[#00e5ff] rounded-full" style={{ width: `${pct}%`, maxWidth: '100%' }} />
                          </div>
                          <span className="text-xs text-[#555555]">{st.count.toLocaleString()}</span>
                        </div>
                      )
                    }) : <div className="text-xs text-[#555555]">No technical detections</div>
                  })()}
                </div>
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-4">
                  <div className="text-xs text-[#888888] font-medium mb-3 uppercase tracking-wider">Personal Detections</div>
                  {(() => {
                    const withCounts = personalSecretTypes.filter((st: any) => st.count > 0)
                    const pd = withCounts.reduce((s: number, st: any) => s + (st.count || 0), 0)
                    return withCounts.length > 0 ? withCounts.slice(0, 15).map((st: any) => {
                      const pct = pd > 0 ? st.count / pd * 100 : 0
                      return (
                        <div key={st.type} className="flex items-center gap-2 mb-1.5">
                          <span className="w-2 h-2 rounded-full bg-[#ffd700]" />
                          <span className="text-xs text-[#777777]">{st.type}</span>
                          <div className="flex-1 h-1.5 rounded-full bg-[#222222] overflow-hidden">
                            <div className="h-full bg-[#ffd700] rounded-full" style={{ width: `${pct}%`, maxWidth: '100%' }} />
                          </div>
                          <span className="text-xs text-[#555555]">{st.count.toLocaleString()}</span>
                        </div>
                      )
                    }) : <div className="text-xs text-[#555555]">No personal data detected</div>
                  })()}
                </div>
              </div>
            </div>
          )}

          {currentTab === 'config' && <ConfigTab onReindex={triggerReindex} />}
          <footer className="mt-10 pt-5 border-t border-[#1a1a1a] flex items-center justify-between gap-4">
            <div className="flex items-center gap-4 text-[12px] text-[#444444]">
              <span>BlackSignal &middot; Paste Intelligence System</span>
              <span className="text-[#555555]">|</span>
              <span className="text-[#555555]">FOR RESEARCH ONLY</span>
              {version && <><span className="text-[#555555]">|</span><span>{version}</span></>}
            </div>
            
          </footer>
        </div>
      )}

      {detailId && <PasteDetail id={detailId} onClose={() => setDetailId(null)} />}

      {/* LLM Report cancel confirmation */}
      {confirmLlmCancel && (
        <div onClick={() => setConfirmLlmCancel(false)}
          className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0d0d0d]/70 backdrop-blur-sm p-4">
          <div onClick={e => e.stopPropagation()}
            className="bg-[#131313] border border-[#222222] rounded-xl w-full max-w-sm p-6 text-center">
            <div className="text-sm font-medium mb-3" style={{ color: '#ff004d' }}>Cancel report generation?</div>
            <div className="text-xs text-[#555555] mb-5">
              The LLM report is still generating. Closing will cancel the analysis and you will lose progress.
            </div>
            <div className="flex items-center gap-3 justify-center">
              <button onClick={() => {
                // Tell the backend to cancel
                fetch('/api/llm/report-cancel', { method: 'POST' }).catch(() => {})
                setConfirmLlmCancel(false)
                if (reportPollRef.current) {
                  clearInterval(reportPollRef.current)
                  reportPollRef.current = null
                }
                setShowLlmReport(false)
                setLlmReportRunning(false)
              }}
                className="text-sm px-5 py-2 rounded-md transition-all cursor-pointer"
                style={{ border: '1px solid #ff004d', color: '#ff004d', backgroundColor: 'transparent' }}>
                Yes, cancel
              </button>
              <button onClick={() => setConfirmLlmCancel(false)}
                className="text-xs px-4 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                Continue
              </button>
            </div>
          </div>
        </div>
      )}

      {/* LLM Report modal */}
      {showLlmReport && (
        <div onClick={handleCloseLlmReport}
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#0d0d0d]/70 backdrop-blur-sm overflow-y-hidden p-4">
          <div onClick={e => e.stopPropagation()}
            className="bg-[#0d0d0d] border border-[#222222] rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-[#222222]">
              <div className="text-sm text-[#e8e8e8] font-medium">
                {llmReportRunning ? 'Generating LLM Report...' : 'LLM Security Report'}
              </div>
              <div className="flex items-center gap-2.5">
                {llmReportResult && (
                  <button onClick={handleDownloadReport}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#ff004d] hover:border-[#ff004d] transition-all cursor-pointer">
                    Download Report
                  </button>
                )}
                <button onClick={handleCloseLlmReport}
                  className="text-[#666666] hover:text-[#ff004d] text-lg transition-all leading-none cursor-pointer">&times;</button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-4 pb-4">
              {llmReportRunning && (
                <div className="py-8 text-center">
                  <div className="inline-block w-8 h-8 rounded-full border-2 border-transparent border-t-[#ff004d] border-r-[#ff004d]/60 animate-spin mb-3" />
                  <div className="text-sm text-[#555555] mb-2">
                    {llmReportProgress?.phase === 'aggregating'
                      ? 'Synthesizing final report...'
                      : 'Analyzing pastes with LLM...'}
                  </div>
                  {llmReportProgress && (
                    <div className="text-xs text-[#444444]">
                      {llmReportProgress.current} / {llmReportProgress.total} pastes analyzed
                    </div>
                  )}
                  {llmReportProgress && llmReportProgress.total > 0 && (
                    <div className="w-64 h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden mt-3 mx-auto">
                      <div className="h-full bg-[#ff004d] rounded-full transition-all duration-500"
                        style={{ width: `${Math.round(llmReportProgress.current / llmReportProgress.total * 100)}%` }} />
                    </div>
                  )}
                </div>
              )}
              {llmReportError && !llmReportRunning && (
                <div className="py-8 text-center">
                  <div className="text-sm text-[#ff004d] mb-1">Report failed</div>
                  <div className="text-xs text-[#555555]">{llmReportError}</div>
                  <button onClick={handleCloseLlmReport}
                    className="mt-4 text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                    Close
                  </button>
                </div>
              )}
              {llmReportResult && (
                <div className="py-4">
                  <div className="text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: renderMarkdown(llmReportResult) }} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}