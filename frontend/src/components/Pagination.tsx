interface Props { page: number; totalPages: number; total: number; onChange: (p: number) => void }

export default function Pagination({ page, totalPages, total, onChange }: Props) {
  if (totalPages <= 1) return null

  const pages: (number | string)[] = []
  const range = 2
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= page - range && i <= page + range)) {
      pages.push(i)
    } else if (pages[pages.length - 1] !== '...') {
      pages.push('...')
    }
  }

  return (
    <div className="flex items-center justify-between mt-4">
      <div className="text-xs text-[#666666]">{total.toLocaleString()} results &middot; Page {page} of {totalPages}</div>
      <div className="flex items-center gap-1.5">
        <button onClick={() => onChange(page - 1)} disabled={page <= 1}
          className="text-sm px-2 py-1 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all disabled:opacity-30 disabled:cursor-not-allowed">
          &larr;
        </button>
        {pages.map((p, i) =>
          typeof p === 'number' ? (
            <button key={i} onClick={() => onChange(p)}
              className={`text-sm px-2.5 py-1 rounded-md transition-all cursor-pointer ${
                p === page ? 'text-[#00e5ff] border border-[#00e5ff] bg-[#00e5ff]/5' : 'text-[#666666] hover:text-[#888888]'
              }`}>
              {p}
            </button>
          ) : <span key={i} className="text-[#444444] text-xs">&hellip;</span>
        )}
        <button onClick={() => onChange(page + 1)} disabled={page >= totalPages}
          className="text-sm px-2 py-1 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all disabled:opacity-30 disabled:cursor-not-allowed">
          &rarr;
        </button>
      </div>
    </div>
  )
}