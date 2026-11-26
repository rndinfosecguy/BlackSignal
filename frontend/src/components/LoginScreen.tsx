import { useState } from 'react'
import { login } from '../lib/auth'

interface Props {
  onLogin: (username: string) => void
}

export default function LoginScreen({ onLogin }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy || !username.trim() || !password) return
    setBusy(true)
    setError(null)
    const res = await login(username.trim(), password)
    if (res.ok) {
      onLogin(res.username || username.trim())
    } else {
      setError(res.error || 'Login failed')
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0d0d0d] flex flex-col items-center justify-center px-6">
      <img src="/bs_logo.png" alt="BlackSignal" className="h-24 mb-10" />

      <form onSubmit={submit}
        className="w-full max-w-sm bg-[#131313] border border-[#222222] rounded-xl p-6 space-y-4">
        <div>
          <div className="text-sm text-[#e8e8e8] font-medium">Sign in</div>
          <div className="text-xs text-[#555555] mt-0.5">BlackSignal &middot; Paste Intelligence System</div>
        </div>

        <div>
          <label htmlFor="username" className="text-xs text-[#555555] block mb-1">Username</label>
          <input
            id="username"
            autoFocus
            autoComplete="username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            className="w-full bg-[#0d0d0d] border border-[#222222] rounded-md px-3 py-2 text-sm text-[#e8e8e8] outline-none focus:border-[#ff004d] transition-colors"
          />
        </div>

        <div>
          <label htmlFor="password" className="text-xs text-[#555555] block mb-1">Password</label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-[#0d0d0d] border border-[#222222] rounded-md px-3 py-2 pr-14 text-sm text-[#e8e8e8] outline-none focus:border-[#ff004d] transition-colors"
            />
            <button type="button" onClick={() => setShowPassword(!showPassword)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-[#555555] hover:text-[#ff004d] transition-colors cursor-pointer">
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        {error && <div className="text-xs text-[#ff004d]">{error}</div>}

        <button type="submit" disabled={busy || !username.trim() || !password}
          className="w-full text-sm px-4 py-2 rounded-md border border-[#ff004d]/40 text-[#ff004d] hover:bg-[#ff004d]/10 hover:border-[#ff004d] transition-all disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer">
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}