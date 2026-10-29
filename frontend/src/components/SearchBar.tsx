import { useState, useCallback, useRef, useEffect } from 'react'

interface Props { onSearch: (q: string) => void; loading: boolean }

export default function SearchBar({ onSearch, loading }: Props) {
  const [value, setValue] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (inputRef.current) inputRef.current.focus()
  }, [])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setValue(v)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onSearch(v), 300)
  }, [onSearch])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      clearTimeout(timerRef.current)
      onSearch(value)
    }
  }, [onSearch, value])

  return (
    <div className="relative">
      <div className="flex items-center border border-[#222222] bg-[#131313] rounded-lg px-4 py-2.5 focus-within:border-[#00e5ff] focus-within:shadow-[0_0_12px_rgba(0,229,255,0.1)] transition-all duration-200">
        <input
          ref={inputRef}
          type="search"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Search pastes..."
          className="flex-1 bg-transparent border-none outline-none text-[#e8e8e8] text-sm placeholder:text-[#444444]"
        />
        {loading && (
          <span className="text-[#555555] text-xs ml-2">searching...</span>
        )}
        <button
          onClick={() => onSearch(value)}
          className="text-xs px-3 py-1 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all ml-2"
        >
          Search
        </button>
      </div>
    </div>
  )
}