import { useState } from 'react'
import { ArrowRight, Eye, EyeOff, KeyRound, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'

export default function Login() {
  const { registrationOpen, login, register } = useAuth()
  const [mode, setMode] = useState(registrationOpen ? 'register' : 'login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (mode === 'register') await register(name, email, password)
      else await login(email, password)
    } catch (submitError) {
      setError(submitError.message)
    } finally {
      setBusy(false)
    }
  }

  const switchMode = (nextMode) => {
    setMode(nextMode)
    setError('')
  }

  return <main className="auth-page"><div className="auth-grid" aria-hidden="true"><span /><span /><span /><span /><span /><span /></div><section className="auth-brand"><div className="auth-brand-mark"><ShieldCheck size={24} /></div><p className="eyebrow"><Sparkles size={13} /> Security operations workspace</p><h1>Keep every decision<br /><em>inside the boundary.</em></h1><p>Sentroxis Copilot gives authenticated analysts one controlled place to connect detection, evidence, and response workflows.</p><div className="auth-promise"><LockKeyhole size={16} /><span><strong>Protected by default</strong><small>Session cookies are HTTP-only and telemetry stays out of the login flow.</small></span></div></section><section className="auth-card" aria-labelledby="auth-title"><div className="auth-card-top"><span className="auth-logo">S</span><span className="auth-status"><i /> Secure access</span></div><div className="auth-heading"><p className="eyebrow">{mode === 'register' ? 'Initialize workspace' : 'Analyst sign in'}</p><h2 id="auth-title">{mode === 'register' ? 'Create the first account.' : 'Welcome back.'}</h2><p>{mode === 'register' ? 'The first account becomes the workspace administrator.' : 'Sign in to continue to your command center.'}</p></div><form onSubmit={submit} className="auth-form">{mode === 'register' && <label htmlFor="auth-name">Full name<input id="auth-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Security analyst" autoComplete="name" required /></label>}<label htmlFor="auth-email">Work email<input id="auth-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="analyst@company.com" autoComplete="email" required /></label><label htmlFor="auth-password">Password<div className="password-field"><input id="auth-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="12+ characters" autoComplete={mode === 'register' ? 'new-password' : 'current-password'} minLength={mode === 'register' ? 12 : 1} required /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></label>{mode === 'register' && <p className="auth-hint"><KeyRound size={13} /> Use at least 12 characters. Your password is never shown in the UI or stored in plaintext.</p>}{error && <p className="auth-error" role="alert">{error}</p>}<button className="button primary auth-submit" disabled={busy}>{busy ? 'Securing session…' : mode === 'register' ? 'Create secure account' : 'Sign in'} <ArrowRight size={15} /></button></form><div className="auth-divider"><span>Sentroxis access</span></div><p className="auth-switch">{mode === 'register' ? 'Already have an account?' : registrationOpen ? 'First time here?' : 'Need the administrator to create your account?'} {registrationOpen && <button type="button" onClick={() => switchMode(mode === 'register' ? 'login' : 'register')}>{mode === 'register' ? 'Sign in' : 'Create the first account'}</button>}</p><p className="auth-footnote"><LockKeyhole size={12} /> Access is restricted to authenticated workspace members.</p></section></main>
}
