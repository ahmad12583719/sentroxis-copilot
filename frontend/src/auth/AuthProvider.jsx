import { createContext, useContext, useEffect, useMemo, useState } from 'react'

const AuthContext = createContext(null)

async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || 'Request failed')
  return data
}

export function AuthProvider({ children }) {
  const [state, setState] = useState({ loading: true, authenticated: false, user: null, registrationOpen: false })

  const refresh = async () => {
    try {
      const data = await request('/api/auth/status')
      setState({ loading: false, authenticated: data.authenticated, user: data.user, registrationOpen: data.registration_open })
      return data
    } catch {
      setState((current) => ({ ...current, loading: false, authenticated: false }))
      return null
    }
  }

  useEffect(() => { refresh() }, [])

  const value = useMemo(() => ({
    ...state,
    async login(email, password) {
      const data = await request('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      setState({ loading: false, authenticated: true, user: data.user, registrationOpen: false })
      return data
    },
    async register(name, email, password) {
      const data = await request('/api/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) })
      setState({ loading: false, authenticated: true, user: data.user, registrationOpen: false })
      return data
    },
    async logout() {
      await request('/api/auth/logout', { method: 'POST', body: '{}' })
      setState({ loading: false, authenticated: false, user: null, registrationOpen: false })
    },
    refresh,
  }), [state])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

export { request as authRequest }
