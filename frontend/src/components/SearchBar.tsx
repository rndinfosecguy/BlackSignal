import { useState, useCallback, useRef, useEffect } from 'react'

interface Props {
  /** Active search term from the parent (persists across tab switches). */
  value: string
  onSearch: (q: string) => void
  loading: boolean
}

export default function SearchBar({ value, onSearch, loading }: Props) {
  const [text, setText] = useState(value)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (inputRef.current) inputRef.current.focus()
  }, [])

  // The component is unmounted when switching tabs; initialise from the parent
  // term and re-sync when it changes externally. Skip while the user is typing
  // so a debounced echo never overwrites newer input.
  useEffect(() => {
    if (document.activeElement !== inputRef.current && text !== value) {
      setText(value)
    }
  }, [value, text])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setText(v)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onSearch(v), 300)
  }, [onSearch])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      clearTimeout(timerRef.current)
      onSearch(text)
    }
  }, [onSearch, text])

  return (
    <div className="relative">
      <div className="flex items-center border border-[#222222] bg-[#131313] rounded-lg px-4 py-2.5 focus-within:border-[#ff004d] focus-within:shadow-[0_0_12px_rgba(255,0,77,0.1)] transition-all duration-200">
        <input
          ref={inputRef}
          type="search"
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Search pastes..."
          className="flex-1 bg-transparent border-none outline-none text-[#e8e8e8] text-sm placeholder:text-[#444444]"
        />
        {loading && (
          <span className="text-[#555555] text-xs ml-2">searching...</span>
        )}
        <button
          onClick={() => { clearTimeout(timerRef.current); onSearch(text) }}
          className="text-xs px-3 py-1 rounded-md border border-[#222222] text-[#666666] hover:text-[#ff004d] hover:border-[#ff004d] transition-all ml-2"
        >
          Search
        </button>
      </div>
    </div>
  )
}