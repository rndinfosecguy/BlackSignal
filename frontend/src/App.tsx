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

export default function App() {
  const {
    pastes, total, page, totalPages, loading, error,
    sources, types, secretTypes, stats, applyFilters,
  } = usePastes()

  const [query, setQuery] = useState('')
  const [activeSource, setActiveSource] = useState('')
  const [activeType, setActiveType] = useState('')
  const [activeSecretTypes, setActiveSecretTypes] = useState<string[]>([])
  const [hasSecrets, setHasSecrets] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)

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

  return (
    <div className="min-h-screen bg-[#0d0d0d]">
      <div className="max-w-5xl mx-auto px-6 py-6">
        <header className="mb-6">
          <div className="flex items-center gap-6">
            <img src="/bs_logo.png" alt="BlackSignal" className="h-16 shrink-0" />
            <StatsDashboard stats={stats} />
          </div>
        </header>

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

        <footer className="mt-10 pt-5 border-t border-[#1a1a1a] flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 text-[12px] text-[#444444]">
            <span>BlackSignal &middot; Paste Intelligence System</span>
            <span className="text-[#555555]">|</span>
            <span className="text-[#555555]">FOR RESEARCH ONLY</span>
          </div>
          <div className="text-[12px] text-[#444444]">
            {stats ? `${stats.total.toLocaleString()} pastes indexed` : ''}
          </div>
        </footer>
      </div>

      {detailId && <PasteDetail id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}