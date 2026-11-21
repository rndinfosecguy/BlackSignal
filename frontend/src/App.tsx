import { useState, useCallback, useEffect } from 'react'
import { sourceColor } from './lib/utils'
import SearchBar from './components/SearchBar'
import FilterChips from './components/FilterChips'
import PasteCard from './components/PasteCard'
import PasteDetail from './components/PasteDetail'
import StatsDashboard from './components/StatsDashboard'
import Pagination from './components/Pagination'
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
  const [activeSource, setActiveSource] = useState('')
  const [activeType, setActiveType] = useState('')
  const [activeSecretTypes, setActiveSecretTypes] = useState<string[]>([])
  const [hasSecrets, setHasSecrets] = useState(false)
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [groupBy, setGroupBy] = useState('')
  const [detailId, setDetailId] = useState<string | null>(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // Computed filter state flags (used before the dashboard section)
  const noFilters = !query && !activeSource && !activeType && activeSecretTypes.length === 0 && !hasSecrets && !dateFrom && !dateTo
  const sourceDisabled = noFilters && groupBy !== 'source'
  const typeDisabled = noFilters && groupBy !== 'content_type'
  const [currentTab, setCurrentTab] = useState('dashboard')
  const [confirmReindex, setConfirmReindex] = useState<string | null>(null)
  const [reindexToast, setReindexToast] = useState<string | null>(null)
  const [showLoadingOverlay, setShowLoadingOverlay] = useState(false)

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
    const nextSource = overrides.source !== undefined ? overrides.source : activeSource
    const nextType = overrides.type !== undefined ? overrides.type : activeType
    const nextSecretTypes = overrides.secretTypes !== undefined ? overrides.secretTypes : activeSecretTypes
    const nextHasSecrets = overrides.hasSecrets !== undefined ? overrides.hasSecrets : hasSecrets
    const nextGroupBy = overrides.groupBy !== undefined ? overrides.groupBy : groupBy
    const nextDateFrom = overrides.dateFrom !== undefined ? overrides.dateFrom : dateFrom
    const nextDateTo = overrides.dateTo !== undefined ? overrides.dateTo : dateTo

    // When no filters are active, force grouping to None
    const noActiveFilters = !nextQuery && !nextSource && !nextType && nextSecretTypes.length === 0 && !nextHasSecrets && !nextDateFrom && !nextDateTo
    const finalGroupBy = noActiveFilters ? '' : nextGroupBy

    const filterChanged =
      overrides.q !== undefined ||
      overrides.source !== undefined ||
      overrides.type !== undefined ||
      overrides.secretTypes !== undefined ||
      overrides.hasSecrets !== undefined ||
      overrides.groupBy !== undefined ||
      overrides.dateFrom !== undefined ||
      overrides.dateTo !== undefined

    applyFilters({
      q: nextQuery,
      source: nextSource,
      type: nextType,
      secretTypes: nextSecretTypes,
      hasSecrets: nextHasSecrets,
      groupBy: finalGroupBy,
      dateFrom: nextDateFrom,
      dateTo: nextDateTo,
      page: filterChanged ? 1 : (overrides.page ?? page),
    })
    if (finalGroupBy !== groupBy) setGroupBy(finalGroupBy)

    // Re-fetch filtered counts when source or type filter changes
    if (overrides.source !== undefined || overrides.type !== undefined) {
      if (nextSource || nextType) {
        fetchSources(nextType)
        fetchTypes(nextSource)
        fetchSecretTypes(nextSource, nextType)
      } else {
        // Cleared — restore global counts
        fetchTypes()
        fetchSources()
        fetchSecretTypes()
      }
    }
  }, [applyFilters, fetchSources, fetchTypes, fetchSecretTypes, query, activeSource, activeType, activeSecretTypes, hasSecrets, groupBy, dateFrom, dateTo, page])

  const handleSearch = useCallback((q: string) => {
    setQuery(q)
    applyAll({ q })
  }, [applyAll])

  const handleSourceChange = useCallback((s: string) => {
    setActiveSource(s)
    applyAll({ source: s })
  }, [applyAll])

  const handleTypeChange = useCallback((t: string) => {
    setActiveType(t)
    applyAll({ type: t })
  }, [applyAll])

  const handleSecretTypeToggle = useCallback((st: string) => {
    const next = activeSecretTypes.includes(st)
      ? activeSecretTypes.filter(x => x !== st)
      : [...activeSecretTypes, st]
    setActiveSecretTypes(next)
    applyAll({ secretTypes: next })
  }, [applyAll, activeSecretTypes])

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
            <button onClick={() => { fetchStats({ q: query, source: activeSource, type: activeType, secretTypes: activeSecretTypes.length > 0 ? activeSecretTypes : undefined, hasSecrets, dateFrom, dateTo }); setCurrentTab('pastes') }}
              className={`text-sm px-4 py-2 ${currentTab === 'pastes' ? 'text-[#00e5ff] border-b-2 border-[#00e5ff]' : 'text-[#555555] hover:text-[#777777]'} transition-all cursor-pointer`}>
              Pastes
            </button>
            <button onClick={() => setCurrentTab('reindex')}
              className={`text-sm px-4 py-2 ${currentTab === 'reindex' ? 'text-[#00e5ff] border-b-2 border-[#00e5ff]' : 'text-[#555555] hover:text-[#777777]'} transition-all cursor-pointer`}>
              Reindex
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
                activeSource={activeSource}
                activeType={activeType}
                activeSecretTypes={activeSecretTypes}
                hasSecrets={hasSecrets}
                categoryFilter={categoryFilter}
                onSourceChange={handleSourceChange}
                onTypeChange={handleTypeChange}
                onSecretTypeToggle={handleSecretTypeToggle}
                onSecretTypeClear={handleSecretTypeClear}
                onHasSecretsToggle={handleHasSecretsToggle}
                onCategoryFilterChange={setCategoryFilter}
              />
            </div>

            <div className="flex flex-wrap gap-2 items-center mb-2">
              <span className="text-xs text-[#444444] mr-1">Date</span>
              <input type="date" value={dateFrom}
                onChange={e => { setDateFrom(e.target.value); applyAll({ dateFrom: e.target.value }) }}
                className="text-xs px-3 py-1.5 rounded-md border border-[#222222] bg-transparent text-[#888888] outline-none [color-scheme:dark] w-36" />
              <span className="text-xs text-[#444444]">to</span>
              <input type="date" value={dateTo}
                onChange={e => { setDateTo(e.target.value); applyAll({ dateTo: e.target.value }) }}
                className="text-xs px-3 py-1.5 rounded-md border border-[#222222] bg-transparent text-[#888888] outline-none [color-scheme:dark] w-36" />
              {(dateFrom || dateTo) && (
                <button onClick={() => { setDateFrom(''); setDateTo(''); applyAll({ dateFrom: '', dateTo: '' }) }}
                  className="text-xs px-3 py-1.5 rounded-md border border-[#ff004d] text-[#ff004d] hover:bg-[#ff004d]/5 transition-all cursor-pointer">
                  Clear
                </button>
              )}
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
                  <button onClick={() => { if (!noFilters || groupBy === 'source') { setGroupBy('source'); applyAll({ groupBy: 'source' }) } }}
                    className={`text-xs px-3 py-1.5 rounded-md border transition-all ${sourceDisabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer'} ${groupBy === 'source' ? 'border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/5' : 'border-[#222222] text-[#555555]'}`}>
                    Source
                  </button>
                  <button onClick={() => { if (!noFilters || groupBy === 'content_type') { setGroupBy('content_type'); applyAll({ groupBy: 'content_type' }) } }}
                    className={`text-xs px-3 py-1.5 rounded-md border transition-all ${typeDisabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer'} ${groupBy === 'content_type' ? 'border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/5' : 'border-[#222222] text-[#555555]'}`}>
                    Type
                  </button>
                </div>
                <div className="flex flex-wrap gap-2 items-center">
                  <span className="text-xs text-[#444444] mr-1">Export</span>
                  <a href={`/api/pastes/export?format=csv${query ? `&q=${encodeURIComponent(query)}` : ''}${activeSource ? `&source=${encodeURIComponent(activeSource)}` : ''}${activeType ? `&content_type=${encodeURIComponent(activeType)}` : ''}${hasSecrets ? '&has_secrets=true' : ''}${activeSecretTypes.map(st => `&secret_type=${encodeURIComponent(st)}`).join('')}${dateFrom ? `&date_from=${encodeURIComponent(dateFrom)}` : ''}${dateTo ? `&date_to=${encodeURIComponent(dateTo)}` : ''}`}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:border-[#444444] hover:text-[#888888] transition-all cursor-pointer no-underline">
                    CSV
                  </a>
                  <a href={`/api/pastes/export?format=json${query ? `&q=${encodeURIComponent(query)}` : ''}${activeSource ? `&source=${encodeURIComponent(activeSource)}` : ''}${activeType ? `&content_type=${encodeURIComponent(activeType)}` : ''}${hasSecrets ? '&has_secrets=true' : ''}${activeSecretTypes.map(st => `&secret_type=${encodeURIComponent(st)}`).join('')}${dateFrom ? `&date_from=${encodeURIComponent(dateFrom)}` : ''}${dateTo ? `&date_to=${encodeURIComponent(dateTo)}` : ''}`}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:border-[#444444] hover:text-[#888888] transition-all cursor-pointer no-underline">
                    JSON
                  </a>
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
                          if (groupBy === 'source') { setActiveSource(g.key); applyAll({ source: g.key }) }
                          else { setActiveType(g.key); applyAll({ type: g.key }) }
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

          {confirmReindex && (
            <div onClick={() => setConfirmReindex(null)}
              className="fixed inset-0 z-40 flex items-center justify-center bg-[#0d0d0d]/70 backdrop-blur-sm p-4">
              <div onClick={e => e.stopPropagation()}
                className="bg-[#131313] border border-[#222222] rounded-xl w-full max-w-sm p-6 text-center">
                {(() => {
                  const mode = confirmReindex
                  const accent = mode === 'purge' ? '#ff004d' : mode === 'comprehensive' ? '#ffd700' : '#00e5ff'
                  const title = mode === 'purge' ? 'Purge all data?' : mode === 'comprehensive' ? 'Comprehensive reindex?' : 'Standard reindex?'
                  const desc = mode === 'purge'
                    ? 'All indexed data will be permanently deleted. A fresh reindex will start from scratch.'
                    : mode === 'comprehensive'
                      ? 'All large files will be re-scanned without size limits. This may take a long time.'
                      : 'Only new paste files will be indexed. Already indexed files are skipped.'
                  return (
                    <>
                    <div className="text-sm font-medium mb-3" style={{ color: accent }}>{title}</div>
                    <div className="text-xs text-[#555555] mb-5">{desc}</div>
                    <div className="flex items-center gap-3 justify-center">
                      <button onClick={() => { setConfirmReindex(null); triggerReindex(mode) }}
                        className="text-sm px-5 py-2 rounded-md transition-all cursor-pointer"
                        style={{ border: `1px solid ${accent}`, color: accent, backgroundColor: 'transparent' }}>
                        Yes, start reindex
                      </button>
                      <button onClick={() => setConfirmReindex(null)}
                        className="text-xs px-4 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                        Cancel
                      </button>
                    </div>
                    </>
                  )
                })()}
              </div>
            </div>
          )}
          {currentTab === 'reindex' && (
            <div className="space-y-5">
              <div className="bg-[#131313] border border-[#222222] rounded-lg p-5 cursor-pointer hover:bg-[#00e5ff]/5 transition-all"
                onClick={() => setConfirmReindex('standard')}>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-[#00e5ff]">Standard reindex</div>
                    <div className="text-xs text-[#555555] mt-1">200K limit per file - quick, respects size limits</div>
                  </div>
                  <span className="text-[#00e5ff] text-lg">▶</span>
                </div>
              </div>

              <details className="bg-[#131313] border border-[#222222] rounded-lg p-5 open:border-[#ffd700]">
                <summary className="text-sm font-medium text-[#ffd700] cursor-pointer">Comprehensive reindex</summary>
                <div className="mt-3 text-xs text-[#777777] leading-relaxed">
                  Disables the file size limit and scans the full content of every paste.
                  The additional detections depend on your data — pastes with many large files
                  will benefit more. It can take significantly longer; for large datasets it
                  could take hours.
                </div>
                <button onClick={() => setConfirmReindex('comprehensive')}
                  className="w-full mt-3 text-sm px-4 py-2 rounded-md border border-[#ffd700] text-[#ffd700] hover:bg-[#ffd700]/5 transition-all cursor-pointer">
                  Start comprehensive reindex
                </button>
              </details>

              <details className="bg-[#131313] border border-[#222222] rounded-lg p-5">
                <summary className="text-sm font-medium text-[#ff004d] cursor-pointer">Purge & reindex</summary>
                <div className="mt-3 text-xs text-[#ff004d]/80 leading-relaxed">
                  Permanently deletes all indexed data from the database and starts a
                  fresh reindex from scratch. This cannot be undone. Only use this if
                  you want to completely rebuild the index.
                </div>
                <button onClick={() => setConfirmReindex('purge')}
                  className="w-full mt-3 text-sm px-4 py-2 rounded-md border border-[#ff004d] text-[#ff004d] hover:bg-[#ff004d]/5 transition-all cursor-pointer">
                  Execute purge
                </button>
              </details>
            </div>
          )}
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
    </div>
  )
}