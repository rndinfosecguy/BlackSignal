import { useState, useCallback } from 'react'
import SearchBar from './components/SearchBar'
import FilterChips from './components/FilterChips'
import PasteCard from './components/PasteCard'
import PasteDetail from './components/PasteDetail'
import StatsDashboard from './components/StatsDashboard'
import Pagination from './components/Pagination'
import { usePastes } from './hooks/usePastes'
import type { FilterState } from './hooks/usePastes'

type Overrides = Partial<FilterState>

function sourceColor(source: string): string {
  let hash = 0
  for (let i = 0; i < source.length; i++)
    hash = source.charCodeAt(i) + ((hash << 5) - hash)
  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 80%, 55%)`
}

export default function App() {
  const {
    pastes, total, page, totalPages, loading, error,
    sources, types, secretTypes, stats, indexStatus, version,
    applyFilters, fetchStats, triggerReindex,
  } = usePastes()

  const [query, setQuery] = useState('')
  const [activeSource, setActiveSource] = useState('')
  const [activeType, setActiveType] = useState('')
  const [activeSecretTypes, setActiveSecretTypes] = useState<string[]>([])
  const [hasSecrets, setHasSecrets] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [currentTab, setCurrentTab] = useState('dashboard')
  const [confirmReindex, setConfirmReindex] = useState<string | null>(null)

  const applyAll = useCallback((overrides: Overrides) => {
    const filterChanged =
      overrides.q !== undefined ||
      overrides.source !== undefined ||
      overrides.type !== undefined ||
      overrides.secretTypes !== undefined ||
      overrides.hasSecrets !== undefined

    applyFilters({
      q: overrides.q !== undefined ? overrides.q : query,
      source: overrides.source !== undefined ? overrides.source : activeSource,
      type: overrides.type !== undefined ? overrides.type : activeType,
      secretTypes: overrides.secretTypes !== undefined ? overrides.secretTypes : activeSecretTypes,
      hasSecrets: overrides.hasSecrets !== undefined ? overrides.hasSecrets : hasSecrets,
      page: filterChanged ? 1 : (overrides.page ?? page),
    })
  }, [applyFilters, query, activeSource, activeType, activeSecretTypes, hasSecrets, page])

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
            <button onClick={() => { fetchStats({ q: query, source: activeSource, type: activeType, secretTypes: activeSecretTypes.length > 0 ? activeSecretTypes : undefined, hasSecrets }); setCurrentTab('pastes') }}
              className={`text-sm px-4 py-2 ${currentTab === 'pastes' ? 'text-[#00e5ff] border-b-2 border-[#00e5ff]' : 'text-[#555555] hover:text-[#777777]'} transition-all cursor-pointer`}>
              Pastes
            </button>
            <button onClick={() => setCurrentTab('reindex')}
              className={`text-sm px-4 py-2 ${currentTab === 'reindex' ? 'text-[#00e5ff] border-b-2 border-[#00e5ff]' : 'text-[#555555] hover:text-[#777777]'} transition-all cursor-pointer`}>
              Reindex
            </button>
          </div>

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
                onSourceChange={handleSourceChange}
                onTypeChange={handleTypeChange}
                onSecretTypeToggle={handleSecretTypeToggle}
                onSecretTypeClear={handleSecretTypeClear}
                onHasSecretsToggle={handleHasSecretsToggle}
              />
            </div>

            <div className="space-y-3">
              {loading && pastes.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-[#555555]">Loading pastes...</div>
              ) : error ? (
                <div className="flex items-center justify-center h-32"><span className="text-[#ff004d]">Error: {error}</span></div>
              ) : pastes.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-[#555555]">No results found</div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {pastes.map(p => <PasteCard key={p.id} {...p} onClick={setDetailId} />)}
                </div>
              )}
            </div>

            <Pagination page={page} totalPages={totalPages} total={total} onChange={handlePageChange} />
            </>
          )}

          {currentTab === 'dashboard' && stats && (
            <div className="space-y-5">
              <div className="grid grid-cols-3 gap-5">
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-5 text-center">
                  <div className="text-xs text-[#888888] mb-2">Individual detections</div>
                  <div className="text-3xl font-semibold text-[#ff004d]">{totalDetections.toLocaleString()}</div>
                  <div className="text-[11px] text-[#555555] mt-1">
                    in {stats.with_secrets.toLocaleString()} pastes
                    {stats.with_secrets > 0 ? `(avg ${(totalDetections / stats.with_secrets).toFixed(1)} per paste)` : ''}
                  </div>
                </div>
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-5">
                  <div className="text-xs text-[#888888] mb-2">Most common secret</div>
                  <div className="text-sm font-semibold text-[#ffd700] mt-1">{topSecretType?.type || '—'}</div>
                  <div className="text-[11px] text-[#555555] mt-1">
                    {topSecretType ? topSecretType.count.toLocaleString() + ' occurrences' : 'No secrets detected'}
                  </div>
                </div>
                <div className="bg-[#131313] border border-[#222222] rounded-lg p-5 text-center">
                  <div className="text-xs text-[#888888] mb-2">Password density</div>
                  <div className="text-3xl font-semibold text-[#ff004d]">
                    {stats.with_secrets > 0 ? Math.round(stats.with_passwords / stats.with_secrets * 100) : 0}%
                  </div>
                  <div className="text-[11px] text-[#555555] mt-1">
                    of pastes with secrets have email:password combos
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

              <div className="bg-[#131313] border border-[#222222] rounded-lg p-4">
                <div className="text-xs text-[#888888] font-medium mb-3 uppercase tracking-wider">Detected Secret Types</div>
                {(() => {
                  const withCounts = secretTypes.filter(st => st.count > 0)
                  return withCounts.length > 0 ? withCounts.slice(0, 15).map(st => {
                    const hue = Math.abs(st.type.split('').reduce((h: number, c: string) => c.charCodeAt(0) + ((h << 5) - h), 0)) % 360
                    const pct = totalDetections > 0 ? st.count / totalDetections * 100 : 0
                    return (
                      <div key={st.type} className="flex items-center gap-2 mb-1.5">
                        <span style={{ backgroundColor: `hsl(${hue}, 80%, 55%)` }} className="w-2 h-2 rounded-full shrink-0" />
                        <span className="text-xs text-[#777777]">{st.type}</span>
                        <div className="flex-1 h-1.5 rounded-full bg-[#222222] overflow-hidden">
                          <div className="h-full bg-[#ff004d] rounded-full" style={{ width: `${pct}%`, maxWidth: '100%' }} />
                        </div>
                        <span className="text-xs text-[#555555]">{st.count.toLocaleString()}</span>
                      </div>
                    )
                  }) : <div className="text-xs text-[#555555]">No secrets detected yet</div>
                })()}
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
                    <div className="text-xs text-[#555555] mt-1">200K limit per file — quick, respects size limits</div>
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