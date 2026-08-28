import { useEffect, useState } from 'react'
import { AlertTriangle, ExternalLink, KeyRound, LogIn, Maximize2, RefreshCw, Server } from 'lucide-react'
import { authRequest } from '../auth/AuthProvider'

export default function Velociraptor() {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  const [consoleAuthenticated, setConsoleAuthenticated] = useState(false)
  const [consolePassword, setConsolePassword] = useState('')
  const [authBusy, setAuthBusy] = useState(false)

  const refreshStatus = async () => {
    try {
      const data = await authRequest('/api/velociraptor/status')
      setStatus(data)
      setError('')
    } catch (requestError) {
      setError(requestError.message || 'Could not load Velociraptor server status')
    }
  }

  const refreshConsoleAuth = async () => {
    try { const data = await authRequest('/api/velociraptor/console/session'); setConsoleAuthenticated(Boolean(data.authenticated)) } catch { setConsoleAuthenticated(false) }
  }

  const signInToConsole = async (event) => {
    event.preventDefault(); setAuthBusy(true); setError('')
    try {
      await authRequest('/api/velociraptor/console/session', { method: 'POST', body: JSON.stringify({ password_confirmation: consolePassword }) })
      setConsolePassword(''); setConsoleAuthenticated(true)
    } catch (requestError) { setError(requestError.message || 'Velociraptor console authentication failed') }
    finally { setAuthBusy(false) }
  }

  useEffect(() => {
    // The console reads live local-runtime status after the page opens.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshStatus(); refreshConsoleAuth()
    const timer = window.setInterval(() => { refreshStatus(); refreshConsoleAuth() }, 5000)
    return () => window.clearInterval(timer)
  }, [])

  const consoleUrl = status?.gui_proxy_url || '/velociraptor-console/app/index.html'
  const consoleReady = Boolean(status?.running && status?.gui_proxy_url && consoleAuthenticated)

  return <main className="velociraptor-console-page">
    <header className="velociraptor-console-bar">
      <div className="velociraptor-console-identity"><Server size={17} /><strong>Velociraptor Console</strong><span className={`server-status-pill ${status?.running ? 'online' : 'offline'}`}><i /> {status?.running ? `Running · GUI 127.0.0.1:${status.gui_port}` : 'Server offline'}</span></div>
      <div className="velociraptor-console-actions"><span>Frontend 8010</span><button className="text-button" onClick={refreshStatus}><RefreshCw size={14} /> Refresh</button>{consoleReady && <a className="text-button" href={consoleUrl} target="_blank" rel="noreferrer">Open full window <ExternalLink size={14} /></a>}</div>
    </header>
    <section className="velociraptor-console-stage">
      {consoleReady ? <iframe title="Velociraptor server GUI" className="velociraptor-fullscreen-frame" src={consoleUrl} /> : <div className="velociraptor-console-empty">{status?.running && status?.gui_proxy_url && !consoleAuthenticated ? <form className="console-login-card" onSubmit={signInToConsole}><KeyRound size={34} /><h1>Sign in to Velociraptor</h1><p>Confirm the signed-in Sentroxis account password once. It is used only in backend memory to authenticate this console session.</p><label htmlFor="velociraptor-console-password">Sentroxis password</label><input id="velociraptor-console-password" type="password" value={consolePassword} onChange={(event) => setConsolePassword(event.target.value)} minLength="12" required autoComplete="current-password" /><button className="button primary" disabled={authBusy}>{authBusy ? 'Signing in…' : <><LogIn size={15} /> Sign in to console</>}</button></form> : <><Maximize2 size={34} /><h1>Velociraptor server GUI</h1><p>{status?.configured ? 'The configuration is ready, but the local server is not running. Start the project with ./startup.sh; the GUI will then load here automatically.' : 'Generate the local Velociraptor server configuration from Project Setup first.'}</p>{status?.log_path && <code>{status.log_path}</code>}</>}{error && <p className="velociraptor-status-error" role="alert"><AlertTriangle size={14} /> {error}</p>}</div>}
    </section>
  </main>
}
