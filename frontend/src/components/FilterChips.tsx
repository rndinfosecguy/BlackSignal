import { useMemo } from 'react'
import { sourceColor } from '../lib/utils'

interface SourceCount { source: string; count: number }
interface TypeCount { content_type: string; count: number }
interface SecretTypeCount { type: string; count: number }

interface Props {
  sources: SourceCount[]; types: TypeCount[]; secretTypes: SecretTypeCount[]
  activeSource: string; activeType: string; activeSecretTypes: string[]
  hasSecrets: boolean
  categoryFilter: string  // 'all', 'technical', 'personal'
  onSourceChange: (s: string) => void
  onTypeChange: (t: string) => void
  onSecretTypeToggle: (st: string) => void
  onSecretTypeClear: () => void
  onHasSecretsToggle: () => void
  onCategoryFilterChange: (c: string) => void
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

export default function FilterChips({ sources, types, secretTypes, activeSource, activeType, activeSecretTypes, hasSecrets, categoryFilter, onSourceChange, onTypeChange, onSecretTypeToggle, onSecretTypeClear, onHasSecretsToggle, onCategoryFilterChange }: Props) {
  const topTypes = useMemo(() => types.slice(0, 12), [types])

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-[#444444] mr-1">Source</span>
        <Chip label="All" active={!activeSource} onClick={() => onSourceChange('')} />
        {sources.filter(s => s.count > 0).map(s => (
          <Chip key={s.source} label={s.source} count={s.count} active={activeSource === s.source}
            dotColor={sourceColor(s.source)} onClick={() => onSourceChange(activeSource === s.source ? '' : s.source)} />
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

      <hr className="border-[#222222] my-1" />

      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-[#444444] mr-1">Secrets</span>
        <Chip label="Only" active={hasSecrets}
          activeStyle="border-[#ff004d] text-[#ff004d] bg-[#ff004d]/5"
          onClick={onHasSecretsToggle} />
        <Chip label="All types" active={activeSecretTypes.length === 0} onClick={onSecretTypeClear} />
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-[#444444] mr-1">Category</span>
        <Chip label="All" active={categoryFilter === 'all'} onClick={() => onCategoryFilterChange('all')} />
        <Chip label="Technical" active={categoryFilter === 'technical'} onClick={() => onCategoryFilterChange('technical')} />
        <Chip label="Personal" active={categoryFilter === 'personal'} onClick={() => onCategoryFilterChange('personal')} />
      </div>

      {secretTypes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 items-center overflow-x-auto pb-1">
          {(() => {
            let filtered = secretTypes
            if (categoryFilter === 'technical') filtered = secretTypes.filter(st => !PERSONAL_TYPES.includes(st.type))
            if (categoryFilter === 'personal') filtered = secretTypes.filter(st => PERSONAL_TYPES.includes(st.type))
            return filtered.length > 0 ? filtered.map(st => (
              <Chip key={st.type} label={st.type} count={st.count}
                dotColor={PERSONAL_TYPES.includes(st.type) ? '#ffd700' : '#00e5ff'}
                active={activeSecretTypes.includes(st.type)}
                onClick={() => onSecretTypeToggle(st.type)} />
            )) : <span className="text-xs text-[#555555]">No types in this category</span>
          })()}
        </div>
      )}
    </div>
  )
}