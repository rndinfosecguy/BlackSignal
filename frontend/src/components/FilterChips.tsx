import { useMemo } from 'react'

interface SourceCount { source: string; count: number }
interface TypeCount { content_type: string; count: number }
interface SecretTypeCount { type: string; count: number }

interface Props {
  sources: SourceCount[]; types: TypeCount[]; secretTypes: SecretTypeCount[]
  activeSource: string; activeType: string; activeSecretTypes: string[]
  hasSecrets: boolean
  onSourceChange: (s: string) => void
  onTypeChange: (t: string) => void
  onSecretTypeToggle: (st: string) => void
  onSecretTypeClear: () => void
  onHasSecretsToggle: () => void
}

const SOURCE_STYLES: Record<string, string> = {
  github: 'bg-[#00e5ff]', pastebin: 'bg-[#ffd700]', dpaste: 'bg-[#ff79c6]', pastesio: 'bg-[#888888]',
}

const ACTIVE = 'border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/5'
const INACTIVE = 'border-[#222222] text-[#666666] hover:border-[#444444] hover:text-[#888888]'

const Chip = ({ label, count, active, onClick, dotColor, className, activeStyle }: {
  label: string; count?: number; active: boolean; onClick: () => void
  dotColor?: string; className?: string; activeStyle?: string
}) => (
  <button onClick={onClick}
    className={`text-xs px-3 py-1.5 rounded-md border transition-all duration-200 cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${className || ''} ${active ? (activeStyle || ACTIVE) : INACTIVE}`}>
    {dotColor && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />}
    {label}
    {count !== undefined && <span className="text-[#444444] ml-0.5">{count.toLocaleString()}</span>}
  </button>
)

export default function FilterChips({ sources, types, secretTypes, activeSource, activeType, activeSecretTypes, hasSecrets, onSourceChange, onTypeChange, onSecretTypeToggle, onSecretTypeClear, onHasSecretsToggle }: Props) {
  const topTypes = useMemo(() => types.slice(0, 12), [types])

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-[#444444] mr-1">Source</span>
        <Chip label="All" active={!activeSource} onClick={() => onSourceChange('')} />
        {sources.filter(s => s.count > 0).map(s => (
          <Chip key={s.source} label={s.source} count={s.count} active={activeSource === s.source}
            dotColor={SOURCE_STYLES[s.source]} onClick={() => onSourceChange(activeSource === s.source ? '' : s.source)} />
        ))}
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-[#444444] mr-1">Type</span>
        <Chip label="All" active={!activeType} onClick={() => onTypeChange('')} />
        {topTypes.filter(t => t.count > 0).map(t => (
          <Chip key={t.content_type} label={t.content_type} count={t.count}
            active={activeType === t.content_type} onClick={() => onTypeChange(activeType === t.content_type ? '' : t.content_type)} />
        ))}
      </div>

      {secretTypes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 items-center overflow-x-auto pb-1">
          <span className="text-xs text-[#444444] mr-1">Sensitive</span>
          <Chip label="Secrets only" active={hasSecrets}
            activeStyle="border-[#ff004d] text-[#ff004d] bg-[#ff004d]/5"
            onClick={onHasSecretsToggle} />
          <Chip label="All types" active={activeSecretTypes.length === 0 && !hasSecrets} onClick={onSecretTypeClear} />
          {secretTypes.map(st => (
            <Chip key={st.type} label={st.type} count={st.count}
              active={activeSecretTypes.includes(st.type)}
              onClick={() => onSecretTypeToggle(st.type)} />
          ))}
        </div>
      )}
    </div>
  )
}