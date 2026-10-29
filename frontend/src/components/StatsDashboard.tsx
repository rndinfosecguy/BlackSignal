interface Stats {
  total: number; with_secrets: number; with_passwords: number; sources: number
  total_all?: number; with_secrets_all?: number; with_passwords_all?: number; sources_all?: number
}
interface Props { stats: Stats | null }

export default function StatsDashboard({ stats }: Props) {
  if (!stats) return null

  const fmt = (v: number) => v.toLocaleString()

  const cards = [
    {
      label: 'Pastes',
      value: fmt(stats.total),
      total: stats.total_all !== undefined ? fmt(stats.total_all) : null,
      accent: 'text-[#00ff41]',
    },
    {
      label: 'Secrets',
      value: fmt(stats.with_secrets),
      total: stats.with_secrets_all !== undefined ? fmt(stats.with_secrets_all) : null,
      accent: 'text-[#ff004d]',
    },
    {
      label: 'Passwords',
      value: fmt(stats.with_passwords),
      total: stats.with_passwords_all !== undefined ? fmt(stats.with_passwords_all) : null,
      accent: 'text-[#ff004d]',
    },
    {
      label: 'Sources',
      value: fmt(stats.sources),
      total: stats.sources_all !== undefined ? fmt(stats.sources_all) : null,
      accent: 'text-[#00e5ff]',
    },
  ]

  const isFiltered = stats.total !== stats.total_all

  return (
    <div className="flex-1">
      <div className="grid grid-cols-4 gap-4">
      {cards.map(card => (
        <div key={card.label} className="text-center border-b border-[#222222] pb-2">
          <div className={`text-xl font-semibold ${card.accent}`}>
            {card.value}
            {isFiltered && card.total !== null && (
              <span className="text-[#555555] text-sm font-normal"> / {card.total}</span>
            )}
          </div>
          <div className="text-[11px] text-[#666666] mt-1">{card.label}</div>
        </div>
      ))}
    </div>
    </div>
  )
}