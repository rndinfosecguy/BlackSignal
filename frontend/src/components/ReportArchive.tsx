import { useEffect, useState } from 'react'
import { renderMarkdown } from '../lib/utils'
import { lockScroll } from '../lib/scrollLock'

interface ReportMeta {
  id: string
  type: 'single' | 'batch'
  created_at: string
  title: string
  paste_count?: number
  risk_level?: string
  risk_score?: number
}

interface ReportDetail {
  meta: ReportMeta
  markdown: string
}

const RISK_STYLES: Record<string, string> = {
  critical: 'bg-[#ff004d]/15 text-[#ff004d] border border-[#ff004d]/40',
  high: 'bg-[#ff8c1a]/15 text-[#ff8c1a] border border-[#ff8c1a]/40',
  medium: 'bg-[#ffd700]/15 text-[#ffd700] border border-[#ffd700]/40',
  low: 'bg-[#00ff41]/10 text-[#00ff41] border border-[#00ff41]/40',
}
const NO_RATING_STYLE = 'bg-[#1a1a1a] text-[#666666] border border-[#222222]'

function riskLabel(meta: ReportMeta): { text: string; style: string } {
  const level = (meta.risk_level || '').toLowerCase()
  if (!level || !(level in RISK_STYLES)) {
    return { text: 'No rating', style: NO_RATING_STYLE }
  }
  const label = level.charAt(0).toUpperCase() + level.slice(1)
  const score = typeof meta.risk_score === 'number' ? ` · ${meta.risk_score}` : ''
  return { text: `${label}${score}`, style: RISK_STYLES[level] }
}

export default function ReportArchive() {
  const [reports, setReports] = useState<ReportMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [viewing, setViewing] = useState<ReportDetail | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    fetch('/api/reports')
      .then(r => r.json())
      .then(d => { setReports(d.reports || []); setError(null) })
      .catch(() => setError('Failed to load reports'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  // Lock background scrolling while the report viewer is open.
  useEffect(() => {
    if (!viewing) return
    return lockScroll()
  }, [viewing])

  const handleView = async (id: string) => {
    try {
      const res = await fetch(`/api/reports/${encodeURIComponent(id)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setViewing(await res.json())
    } catch {
      setError('Failed to open report')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await fetch(`/api/reports/${encodeURIComponent(id)}`, { method: 'DELETE' })
    } catch {
      /* ignore — refresh below reflects reality */
    }
    setConfirmDelete(null)
    load()
  }

  const fmtDate = (iso: string): string => {
    const d = new Date(iso)
    return isNaN(d.getTime()) ? iso : d.toLocaleString()
  }

  const downloadHref = (id: string) => `/api/reports/${encodeURIComponent(id)}/download`

  return (
    <div className="space-y-4">
      {reports.length > 0 && (
        <div className="text-xs text-[#888888]">
          {reports.length.toLocaleString()} archived report{reports.length === 1 ? '' : 's'}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-32 text-[#555555]">Loading...</div>
      ) : error ? (
        <div className="flex items-center justify-center h-32 text-[#ff004d] text-sm">{error}</div>
      ) : reports.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-[#555555] text-sm">
          No reports yet
        </div>
      ) : (
        <div className="space-y-2">
          {reports.map(r => {
            const risk = riskLabel(r)
            return (
            <div key={r.id}
              className="bg-[#131313] border border-[#222222] rounded-lg p-4 flex items-center gap-4">
              <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider whitespace-nowrap ${
                r.type === 'batch'
                  ? 'bg-[#ff004d]/10 text-[#ff004d]'
                  : 'bg-[#1a1a1a] text-[#888888]'
              }`}>
                {r.type === 'batch' ? 'Batch' : 'Single'}
              </span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider whitespace-nowrap ${risk.style}`}
                title={r.risk_level
                  ? `Risk: ${r.risk_level} (score ${r.risk_score ?? '?'}/100) · scale 0-24 Low, 25-49 Medium, 50-74 High, 75-100 Critical`
                  : 'No risk rating available for this report'}>
                {risk.text}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-[#e8e8e8] truncate" style={{ fontFamily: 'var(--font-mono)' }}
                  title={r.title}>
                  {r.title}
                </div>
                <div className="text-[11px] text-[#555555] mt-0.5">
                  {fmtDate(r.created_at)}
                  {r.type === 'batch' && typeof r.paste_count === 'number' && (
                    <> &middot; {r.paste_count.toLocaleString()} paste{r.paste_count === 1 ? '' : 's'}</>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => handleView(r.id)}
                  className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#ff004d] hover:border-[#ff004d] transition-all cursor-pointer">
                  View
                </button>
                <a href={downloadHref(r.id)} download
                  className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#ff004d] hover:border-[#ff004d] transition-all cursor-pointer no-underline">
                  Download
                </a>
                {confirmDelete === r.id ? (
                  <>
                    <button onClick={() => handleDelete(r.id)}
                      className="text-xs px-2.5 py-1.5 rounded-md bg-[#ff004d]/20 border border-[#ff004d] text-[#ff004d] hover:bg-[#ff004d]/30 transition-all cursor-pointer">
                      Yes
                    </button>
                    <button onClick={() => setConfirmDelete(null)}
                      className="text-xs px-2.5 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                      No
                    </button>
                  </>
                ) : (
                  <button onClick={() => setConfirmDelete(r.id)}
                    className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#ff004d] hover:border-[#ff004d] transition-all cursor-pointer">
                    Delete
                  </button>
                )}
              </div>
            </div>
            )
          })}
        </div>
      )}

      {viewing && (
        <div onClick={() => setViewing(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#0d0d0d]/70 backdrop-blur-sm overflow-y-hidden p-4">
          <div onClick={e => e.stopPropagation()}
            className="bg-[#0d0d0d] border border-[#222222] rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-[#222222]">
              <div className="min-w-0">
                <div className="text-sm text-[#e8e8e8] font-medium truncate"
                  style={{ fontFamily: 'var(--font-mono)' }}>
                  {viewing.meta.title}
                </div>
                <div className="text-[11px] text-[#555555] mt-0.5">
                  {viewing.meta.type === 'batch' ? 'Batch report' : 'Single-paste analysis'} &middot;{' '}
                  {fmtDate(viewing.meta.created_at)}
                </div>
              </div>
              <div className="flex items-center gap-2.5">
                <a href={downloadHref(viewing.meta.id)} download
                  className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#ff004d] hover:border-[#ff004d] transition-all cursor-pointer no-underline">
                  Download
                </a>
                <button onClick={() => setViewing(null)}
                  className="text-[#666666] hover:text-[#ff004d] text-lg transition-all leading-none cursor-pointer">&times;</button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-4">
              <div className="text-sm leading-relaxed"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(viewing.markdown) }} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}