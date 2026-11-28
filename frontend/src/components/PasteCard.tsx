import { memo } from 'react'
import { sourceColor, formatSize } from '../lib/utils'

interface Props {
  id: string; filename: string; source: string; content_type: string; size: number
  has_passwords: boolean; has_secrets: boolean; secret_types: string[]; snippet: string
  first_seen: string
  triage_status?: string; triage_note?: string
  onClick: (id: string) => void
}

const SOURCE_NAMES: Record<string, string> = {
  github:   'GitHub',
  pastebin: 'Pastebin',
  dpaste:   'Dpaste',
  pastesio: 'Pastes.io',
}

const TRIAGE_BADGES: Record<string, { label: string; color: string }> = {
  reviewed:       { label: 'Reviewed', color: '#00ff41' },
  false_positive: { label: 'False positive', color: '#ffd700' },
  escalated:      { label: 'Escalated', color: '#ff004d' },
}

export default memo(function PasteCard(props: Props) {
  const { id, filename, source, content_type, size, has_passwords, has_secrets, secret_types, snippet, first_seen, triage_status, triage_note, onClick } = props
  const secretTypes = (secret_types || []).slice(0, 3)
  const badge = TRIAGE_BADGES[triage_status || ''] || null

  // Format first_seen to a short readable date
  const indexedDate = first_seen ? first_seen.slice(0, 10) : ''

  return (
    <div
      onClick={() => onClick(id)}
      className="bg-[#131313] border border-[#222222] rounded-lg p-4 cursor-pointer hover:border-[#333333] hover:bg-[#181818] transition-all duration-200 min-w-0 overflow-hidden"
    >
      <div className="flex items-center justify-between mb-2 gap-2 min-w-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <span style={{ backgroundColor: sourceColor(source) }} className="w-2 h-2 rounded-full shrink-0" />
          <div className="min-w-0">
            <div className="text-sm font-medium text-[#e8e8e8]">{SOURCE_NAMES[source] || source}</div>
            <div className="text-[11px] text-[#666666] mt-0.5 truncate" style={{ fontFamily: 'var(--font-mono)' }}>{filename}</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {indexedDate && <span className="text-[10px] text-[#444444]">Indexed: {indexedDate}</span>}
          {badge && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border whitespace-nowrap"
              style={{ color: badge.color, borderColor: `${badge.color}55`, backgroundColor: `${badge.color}14` }}>
              {badge.label}
            </span>
          )}
          {triage_note && triage_note.length > 0 && (
            <span className="text-[11px] text-[#666666]" title={triage_note}>&#9998;</span>
          )}
          <span className="text-xs text-[#555555]">{formatSize(size)}</span>
        </div>
      </div>

      <div className="text-[13px] text-[#555555] line-clamp-2 break-words leading-relaxed mb-0" style={{ fontFamily: 'var(--font-mono)' }}>
        {snippet}
      </div>

      {secretTypes.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2 min-w-0">
          {secretTypes.map(t => (
            <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-[#ff004d]/5 text-[#ff004d]/70 break-all">{t}</span>
          ))}
        </div>
      )}
    </div>
  )
})