import { memo } from 'react'

interface Props {
  id: string; filename: string; source: string; content_type: string; size: number
  has_passwords: boolean; has_secrets: boolean; secret_types: string[]; snippet: string
  onClick: (id: string) => void
}

const SOURCE_DOTS: Record<string, string> = {
  github:   'bg-[#00e5ff]',
  pastebin: 'bg-[#ffd700]',
  dpaste:   'bg-[#ff79c6]',
  pastesio: 'bg-[#888888]',
}

const SOURCE_NAMES: Record<string, string> = {
  github:   'GitHub',
  pastebin: 'Pastebin',
  dpaste:   'Dpaste',
  pastesio: 'Pastes.io',
}

function formatSize(bytes: number): string {
  if (bytes <= 0) return 'empty'
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

export default memo(function PasteCard(props: Props) {
  const { id, filename, source, content_type, size, has_passwords, has_secrets, secret_types, snippet, onClick } = props
  const secretTypes = (secret_types || []).slice(0, 3)

  return (
    <div
      onClick={() => onClick(id)}
      className="bg-[#131313] border border-[#222222] rounded-lg p-4 cursor-pointer hover:border-[#333333] hover:bg-[#181818] transition-all duration-200"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2.5">
          <span className={`w-2 h-2 rounded-full shrink-0 ${SOURCE_DOTS[source] || 'bg-[#888888]'}`} />
          <div>
            <div className="text-sm font-medium text-[#e8e8e8]">{SOURCE_NAMES[source] || source}</div>
            <div className="text-[11px] text-[#666666] mt-0.5" style={{ fontFamily: 'var(--font-mono)' }}>{filename}</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-xs text-[#555555]">{formatSize(size)}</span>
        </div>
      </div>

      <div className="text-[13px] text-[#555555] line-clamp-2 leading-relaxed mb-0" style={{ fontFamily: 'var(--font-mono)' }}>
        {snippet}
      </div>

      {secretTypes.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {secretTypes.map(t => (
            <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-[#ff004d]/5 text-[#ff004d]/70">{t}</span>
          ))}
        </div>
      )}
    </div>
  )
})