/** Authentication helpers: session check, login/logout, 401 interception. */

const API_BASE = '/api'

export interface SessionInfo {
  authenticated: boolean
  username?: string | null
}

export async function checkSession(): Promise<SessionInfo> {
  try {
    const res = await fetch(`${API_BASE}/auth/session`)
    if (!res.ok) return { authenticated: false }
    return await res.json() as SessionInfo
  } catch {
    return { authenticated: false }
  }
}

export async function login(
  username: string,
  password: string,
): Promise<{ ok: boolean; username?: string; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) return { ok: false, error: data.detail || 'Login failed' }
    return { ok: true, username: data.username }
  } catch {
    return { ok: false, error: 'Network error — please try again' }
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, { method: 'POST' })
  } catch {
    /* ignore */
  }
}

let installed = false

/**
 * Any 401 from a non-auth API call means the session expired or was rotated;
 * notify the app so it can show the login screen. Installed once at startup.
 */
export function installAuthInterceptor(): void {
  if (installed) return
  installed = true
  const original = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const res = await original(input, init)
    if (res.status === 401) {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url
      if (!url.includes('/api/auth/')) {
        window.dispatchEvent(new Event('bs-auth-expired'))
      }
    }
    return res
  }
}