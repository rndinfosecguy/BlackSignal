import { useMemo, useState, useEffect, useRef } from 'react'
import { sourceColor } from '../lib/utils'

interface SourceCount { source: string; count: number }
interface TypeCount { content_type: string; count: number }
interface SecretTypeCount { type: string; count: number }

interface Props {
  sources: SourceCount[]; types: TypeCount[]; secretTypes: SecretTypeCount[]
  activeSources: string[]; activeTypes: string[]; activeSecretTypes: string[]
  hasSecrets: boolean
  dateFrom: string; dateTo: string
  onSourcesChange: (s: string[]) => void
  onTypesChange: (t: string[]) => void
  onSecretTypeToggle: (st: string) => void
  onSecretTypesBatch: (st: string[]) => void
  onFiltersBatch: (filters: { sources?: string[]; types?: string[]; secretTypes?: string[]; hasSecrets?: boolean; dateFrom?: string; dateTo?: string }) => void
  onSecretTypeClear: () => void
  onHasSecretsToggle: () => void
  onDateFromChange: (d: string) => void
  onDateToChange: (d: string) => void
}

const ACTIVE = 'border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/5'
const INACTIVE = 'border-[#222222] text-[#666666] hover:border-[#444444] hover:text-[#888888]'

const PERSONAL_TYPES = ['personal_email','ssn','btc_address','eth_address','passport','name_dob']

const Chip = ({ label, count, active, onClick, dotColor, className, activeStyle }: {
  label: string; count?: number; active: boolean; onClick: () => void
  dotColor?: string; className?: string; activeStyle?: string
}) => (
  <button onClick={onClick}
    className={`text-xs px-3 py-1.5 rounded-md border transition-all duration-200 cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${className || ''} ${active ? (activeStyle || ACTIVE) : INACTIVE}`}>
    {dotColor && <span style={{ backgroundColor: dotColor }} className="w-1.5 h-1.5 rounded-full shrink-0" />}
    {label}
    {count !== undefined && <span className="text-[#444444] ml-0.5">{count.toLocaleString()}</span>}
  </button>
)

const Pill = ({ label, dotColor, onRemove, onClick }: {
  label: string; dotColor: string; onRemove: () => void; onClick: () => void
}) => (
  <div className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-[#222222] bg-[#1a1a1a]">
    {dotColor && <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: dotColor }} />}
    <span onClick={onClick} className="text-[#888888] cursor-pointer hover:text-[#00e5ff]">{label}</span>
    <button onClick={e => { e.stopPropagation(); onRemove() }} className="text-[#555555] hover:text-[#ff004d] ml-1 leading-none">&times;</button>
  </div>
)

export default function FilterChips({ sources, types, secretTypes, activeSources, activeTypes, activeSecretTypes, hasSecrets, dateFrom, dateTo, onSourcesChange, onTypesChange, onSecretTypeToggle, onSecretTypesBatch, onSecretTypeClear, onHasSecretsToggle, onDateFromChange, onDateToChange, onFiltersBatch }: Props) {
  const topTypes = useMemo(() => types.slice(0, 12), [types])

  const [showOverlay, setShowOverlay] = useState(false)
  const [overlayView, setOverlayView] = useState<string | null>(null)

  // Pending state — mutable closure object held alive by useRef
  const pending = useRef({
    sources: [...activeSources],
    types: [...activeTypes],
    secretTypes: [...activeSecretTypes],
    hasSecrets: hasSecrets,
    dateFrom: dateFrom,
    dateTo: dateTo,
  })
  // Force re-render when pending changes by toggling this counter
  const [pendingVer, setPendingVer] = useState(0)

  function openOverlay() {
    const p = pending.current
    p.sources = [...activeSources]
    p.types = [...activeTypes]
    p.secretTypes = [...activeSecretTypes]
    p.hasSecrets = hasSecrets
    p.dateFrom = dateFrom
    p.dateTo = dateTo
    setPendingVer(pendingVer + 1)
    setShowOverlay(true)
    setOverlayView(null)
  }

  function closeOverlay() {
    const p = pending.current
    onFiltersBatch({
      sources: [...p.sources],
      types: [...p.types],
      secretTypes: [...p.secretTypes],
      hasSecrets: p.hasSecrets,
      dateFrom: p.dateFrom,
      dateTo: p.dateTo,
    })
    setShowOverlay(false)
    setOverlayView(null)
  }

  // Escape closes overlay
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && showOverlay) { closeOverlay() } }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [showOverlay])

  // pills from real active state
  const pills: { key: string; label: string; dotColor: string; onRemove: () => void; filterId: string }[] = []
  activeSources.forEach(s => {
    pills.push({ key: `src:${s}`, label: s, dotColor: sourceColor(s), onRemove: () => onSourcesChange(activeSources.filter(x => x !== s)), filterId: 'source' })
  })
  activeTypes.forEach(t => {
    pills.push({ key: `type:${t}`, label: t, dotColor: '#00e5ff', onRemove: () => onTypesChange(activeTypes.filter(x => x !== t)), filterId: 'type' })
  })
  if (hasSecrets) {
    pills.push({ key: 'secrets', label: 'Has secrets', dotColor: '#ff004d', onRemove: () => onHasSecretsToggle(), filterId: 'secrets' })
  }
  activeSecretTypes.forEach(st => {
    const dc = PERSONAL_TYPES.includes(st) ? '#ffd700' : '#00e5ff'
    pills.push({ key: `st:${st}`, label: st, dotColor: dc, onRemove: () => onSecretTypeToggle(st), filterId: 'secrets' })
  })
  if (dateFrom || dateTo) {
    const dl = dateFrom && dateTo ? `${dateFrom} to ${dateTo}` : dateFrom || dateTo || ''
    pills.push({ key: 'date', label: dl, dotColor: '#00e5ff', onRemove: () => { onDateFromChange(''); onDateToChange('') }, filterId: 'date' })
  }

  // Dummy use of pendingVer to silence unused-variable warning — it drives re-render
  void pendingVer

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        {pills.map(p => (
          <Pill key={p.key} label={p.label} dotColor={p.dotColor} onRemove={p.onRemove} onClick={() => {}} />
        ))}
        <button onClick={openOverlay}
          className={`text-xs px-2.5 py-1 rounded-md border transition-all cursor-pointer ${showOverlay ? ACTIVE : INACTIVE}`}>
          + Add filter
        </button>
      </div>

      {showOverlay && (
        <div onClick={() => closeOverlay()}
          className="fixed inset-0 z-30 flex items-center justify-center bg-[#0d0d0d]/40"
          style={{ backdropFilter: 'blur(2px)', WebkitBackdropFilter: 'blur(2px)' }}>
          <div onClick={e => e.stopPropagation()}
            className="bg-[#131313] border border-[#222222] rounded-xl w-full max-w-md max-h-[80vh] overflow-y-auto p-5 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                {overlayView ? (
                  <button onClick={() => setOverlayView(null)}
                    className="text-xs px-2 py-1 rounded-md border border-[#222222] text-[#555555] hover:border-[#444444] transition-all cursor-pointer">&#8592; Filters</button>
                ) : null}
                <span className="text-sm text-[#888888] font-medium">{overlayView ? overlayView.charAt(0).toUpperCase() + overlayView.slice(1) : 'Add filter'}</span>
              </div>
              <button onClick={() => closeOverlay()}
                className="text-[#666666] hover:text-[#ff004d] text-lg transition-all leading-none">&times;</button>
            </div>

            {!overlayView && (
              <div className="grid grid-cols-2 gap-3">
                {[
                  { id: 'source', label: 'Source', active: pending.current.sources.length, color: '#00e5ff' },
                  { id: 'type', label: 'Type', active: pending.current.types.length, color: '#00e5ff' },
                  { id: 'secrets', label: 'Secrets', active: (pending.current.hasSecrets || pending.current.secretTypes.length) ? 1 : 0, color: '#ff004d' },
                  { id: 'date', label: 'Date range', active: (pending.current.dateFrom || pending.current.dateTo) ? 1 : 0, color: '#00e5ff' },
                ].map(cat => (
                  <button key={cat.id} onClick={() => setOverlayView(cat.id)}
                    className={`text-left px-4 py-3 rounded-lg border transition-all cursor-pointer ${cat.active > 0 ? 'border-[#00e5ff] bg-[#00e5ff]/5' : 'border-[#222222] hover:border-[#444444]'}`}>
                    <div className="text-sm font-medium" style={{ color: cat.active > 0 ? cat.color : '#888888' }}>{cat.label}</div>
                    <div className="text-[10px] text-[#555555] mt-0.5">
                      {cat.id === 'source' ? (cat.active > 0 ? `${cat.active} selected` : 'Any source') : 
                       cat.id === 'type' ? (cat.active > 0 ? `${cat.active} selected` : 'Any type') :
                       cat.id === 'secrets' ? (cat.active > 0 ? 'Active' : 'Inactive') :
                       cat.id === 'date' ? ((pending.current.dateFrom || pending.current.dateTo) ? `${pending.current.dateFrom || '...'} to ${pending.current.dateTo || '...'}` : 'Not set') : ''}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {overlayView === 'source' && (
              <div className="flex flex-wrap gap-2 items-center">
                {sources.filter(s => s.count > 0).map(s => {
                  const active = pending.current.sources.includes(s.source)
                  return (
                    <Chip key={s.source} label={s.source} count={s.count}
                      dotColor={sourceColor(s.source)} active={active}
                      onClick={() => {
                        pending.current.sources = active ? pending.current.sources.filter(x => x !== s.source) : [...pending.current.sources, s.source]
                        setPendingVer(pendingVer + 1)
                      }} />
                  )
                })}
              </div>
            )}

            {overlayView === 'type' && (
              <div className="flex flex-wrap gap-2 items-center">
                {topTypes.filter(t => t.count > 0).map(t => {
                  const active = pending.current.types.includes(t.content_type)
                  return (
                    <Chip key={t.content_type} label={t.content_type} count={t.count} active={active}
                      onClick={() => {
                        pending.current.types = active ? pending.current.types.filter(x => x !== t.content_type) : [...pending.current.types, t.content_type]
                        setPendingVer(pendingVer + 1)
                      }} />
                  )
                })}
              </div>
            )}

            {overlayView === 'secrets' && (
              <div>
                <div className="flex flex-wrap gap-2 items-center mb-2">
                  <Chip label="Has secrets" active={pending.current.hasSecrets}
                    activeStyle="border-[#ff004d] text-[#ff004d] bg-[#ff004d]/5"
                    onClick={() => { pending.current.hasSecrets = !pending.current.hasSecrets; setPendingVer(pendingVer + 1) }} />
                  <Chip label="All types" active={pending.current.secretTypes.length === 0} onClick={() => { pending.current.secretTypes = []; setPendingVer(pendingVer + 1) }} />
                </div>
                {secretTypes.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 items-center overflow-x-auto pb-1">
                    {secretTypes.map(st => {
                      const active = pending.current.secretTypes.includes(st.type)
                      return (
                        <Chip key={st.type} label={st.type} count={st.count}
                          dotColor={PERSONAL_TYPES.includes(st.type) ? '#ffd700' : '#00e5ff'}
                          active={active}
                          onClick={() => {
                            pending.current.secretTypes = active ? pending.current.secretTypes.filter(x => x !== st.type) : [...pending.current.secretTypes, st.type]
                            setPendingVer(pendingVer + 1)
                          }} />
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {overlayView === 'date' && (
              <div className="flex flex-wrap gap-2 items-center">
                <input type="date" value={pending.current.dateFrom}
                  onChange={e => { pending.current.dateFrom = e.target.value; setPendingVer(pendingVer + 1) }}
                  className="text-xs px-3 py-1.5 rounded-md border border-[#222222] bg-transparent text-[#888888] outline-none w-36" style={{ colorScheme: 'dark' }} />
                <span className="text-xs text-[#444444]">to</span>
                <input type="date" value={pending.current.dateTo}
                  onChange={e => { pending.current.dateTo = e.target.value; setPendingVer(pendingVer + 1) }}
                  className="text-xs px-3 py-1.5 rounded-md border border-[#222222] bg-transparent text-[#888888] outline-none w-36" style={{ colorScheme: 'dark' }} />
                {(pending.current.dateFrom || pending.current.dateTo) && (
                  <button onClick={() => { pending.current.dateFrom = ''; pending.current.dateTo = ''; setPendingVer(pendingVer + 1) }}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#ff004d] text-[#ff004d] hover:bg-[#ff004d]/5 transition-all cursor-pointer">
                    Clear
                  </button>
                )}
              </div>
            )}

            {overlayView && (
              <div className="mt-3 flex justify-end" />
            )}
          </div>
        </div>
      )}
    </div>
  )
}