import { useEffect, useState } from 'react'
import { Activity, CheckCircle2, ClipboardCheck, ExternalLink, FileKey2, FolderSearch, Loader2, Lock, Play, RefreshCw, Server, ShieldCheck, Square, TerminalSquare } from 'lucide-react'
import { authRequest } from '../auth/AuthProvider'

const endpoints = [
  { name: 'ws-fin-07', os: 'Windows 11 · Finance', lastSeen: '32 sec ago', health: 'Healthy', trust: 'Verified' },
  { name: 'srv-app-02', os: 'Ubuntu 24.04 · App tier', lastSeen: '48 sec ago', health: 'Healthy', trust: 'Verified' },
  { name: 'dc-east-01', os: 'Windows Server · Identity', lastSeen: '1 min ago', health: 'Healthy', trust: 'Verified' },
  { name: 'ws-ops-12', os: 'Windows 11 · Operations', lastSeen: '2 min ago', health: 'Review', trust: 'Verified' },
]

export default function Velociraptor() {
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const refreshStatus = async () => {
    try {
      const data = await authRequest('/api/velociraptor/status')
      setStatus(data)
      setError('')
    } catch (requestError) {
      setError(requestError.message || 'Could not load Velociraptor server status')
    }
  }

  useEffect(() => {
    // This external runtime status must be fetched once when the dashboard opens.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshStatus()
    const timer = window.setInterval(refreshStatus, 5000)
    return () => window.clearInterval(timer)
  }, [])

  const runServer = async () => {
    if (!status?.platform || !window.confirm('Start the locally configured Velociraptor server now?')) return
    setBusy('start')
    setError('')
    try {
      await authRequest('/api/velociraptor/run', { method: 'POST', body: JSON.stringify({ platform: status.platform, confirm_run: true }) })
      await refreshStatus()
    } catch (requestError) {
      setError(requestError.message || 'Velociraptor server could not be started')
    } finally {
      setBusy('')
    }
  }

  const stopServer = async () => {
    if (!window.confirm('Stop the locally managed Velociraptor server?')) return
    setBusy('stop')
    setError('')
    try {
      await authRequest('/api/velociraptor/stop', { method: 'POST', body: JSON.stringify({}) })
      await refreshStatus()
    } catch (requestError) {
      setError(requestError.message || 'Velociraptor server could not be stopped')
    } finally {
      setBusy('')
    }
  }

  const guiAvailable = Boolean(status?.running && status?.gui_url)
  return <main className="page-shell subpage-shell">
    <section className="page-heading compact-heading"><div><p className="eyebrow"><FolderSearch size={13} /> Endpoint forensics <span className="slash">/</span> approved collections</p><h1>Velociraptor <em>evidence.</em></h1><p className="lede">Collect bounded, read-only context with provenance attached to every artifact.</p></div><div className="heading-actions"><span className={`connection-badge ${status?.running ? '' : 'muted'}`}><i /> {status?.running ? 'Server running' : 'Server offline'}</span><button className="button secondary" onClick={refreshStatus} disabled={busy !== ''}><RefreshCw size={14} /> Refresh status</button></div></section>

    <section className="velociraptor-server-grid">
      <article className="panel velociraptor-server-control">
        <div className="panel-heading"><div><p className="eyebrow"><Activity size={13} /> Local runtime</p><h2>Server control</h2></div><span className={`server-status-pill ${status?.running ? 'online' : 'offline'}`}><i /> {status?.running ? 'Running' : 'Stopped'}</span></div>
        <p>{status?.message || 'Loading the local Velociraptor runtime status…'}</p>
        <dl className="velociraptor-status-list"><div><dt>Frontend port</dt><dd>{status?.frontend_port || 8010} <small>fixed</small></dd></div><div><dt>GUI port</dt><dd>{status?.gui_port || 'Configure first'}</dd></div><div><dt>Process</dt><dd>{status?.running ? `PID ${status.pid}` : 'Not running'}</dd></div><div><dt>Configuration</dt><dd>{status?.configured ? 'Ready' : 'Required'}</dd></div></dl>
        {status?.command_preview && <div className="velociraptor-command"><TerminalSquare size={15} /><code>{status.command_preview}</code></div>}
        {status?.config_path && <p className="runtime-path"><strong>Config:</strong> {status.config_path}</p>}
        {status?.log_path && <p className="runtime-path"><strong>Log:</strong> {status.log_path}</p>}
        <div className="velociraptor-control-actions">
          <button className="button primary" onClick={runServer} disabled={!status?.configured || !status?.platform || busy !== '' || status?.running}>{busy === 'start' ? <Loader2 size={14} className="spin" /> : <Play size={14} />} Start local server</button>
          <button className="button stop-button" onClick={stopServer} disabled={!status?.running || busy !== ''}>{busy === 'stop' ? <Loader2 size={14} className="spin" /> : <Square size={13} />} Stop server</button>
        </div>
        {error && <p className="velociraptor-status-error" role="alert">{error}</p>}
      </article>

      <article className="panel velociraptor-gui-panel">
        <div className="panel-heading"><div><p className="eyebrow"><Server size={13} /> Embedded server GUI</p><h2>Velociraptor console</h2></div>{status?.gui_url && <a className="text-button" href={status.gui_url} target="_blank" rel="noreferrer">Open separately <ExternalLink size={14} /></a>}</div>
        {guiAvailable ? <div className="velociraptor-frame-wrap"><iframe title="Velociraptor server GUI" className="velociraptor-server-frame" src={status.gui_url} /></div> : <div className="velociraptor-gui-empty"><Server size={30} /><strong>GUI is not available yet</strong><p>{status?.configured ? 'Start the local server to load its GUI in this panel.' : 'Generate server.config.yaml from Project Setup first.'}</p>{status?.gui_url && <a className="text-button" href={status.gui_url} target="_blank" rel="noreferrer">Open configured GUI <ExternalLink size={14} /></a>}</div>}
      </article>
    </section>

    <section className="forensics-overview"><div className="panel forensics-hero"><div className="forensics-icon"><FolderSearch size={24} /></div><div><p className="eyebrow">Collection posture</p><h2>Evidence chain intact</h2><p>4 endpoints are reporting. No collection is currently running. Every result is hashed and linked to an alert or case.</p></div><div className="hero-check"><CheckCircle2 size={18} /><span>Verified<br /><b>100%</b></span></div></div><div className="panel quick-fact"><Lock size={16} /><span><strong>Read-only mode</strong><small>VQL is not executed from free text.</small></span></div></section>
    <section className="panel table-panel"><div className="table-heading"><div><p className="eyebrow">Endpoint inventory</p><h2>Collection targets</h2></div><span className="table-meta"><Server size={14} /> {endpoints.length} enrolled</span></div><div className="endpoint-list">{endpoints.map((endpoint) => <div className="endpoint-row" key={endpoint.name}><span className="endpoint-icon"><Server size={17} /></span><div className="endpoint-name"><strong>{endpoint.name}</strong><small>{endpoint.os}</small></div><div><small className="field-label">Last seen</small><span>{endpoint.lastSeen}</span></div><div><small className="field-label">Health</small><span className={endpoint.health === 'Healthy' ? 'health-good' : 'health-review'}><i />{endpoint.health}</span></div><div><small className="field-label">Identity</small><span className="verified"><ShieldCheck size={14} /> {endpoint.trust}</span></div><button className="icon-button" aria-label={`Review ${endpoint.name}`}><ClipboardCheck size={16} /></button></div>)}</div><div className="panel-footer"><span>Collection limits: 30s runtime · 10 MB result cap · 1 endpoint scope</span><button className="text-button">View evidence vault <FileKey2 size={14} /></button></div></section>
    <section className="collection-steps"><div className="step complete"><span>01</span><div><strong>Signal selected</strong><small>Wazuh alert or investigation case</small></div></div><div className="step-line" /><div className="step active"><span>02</span><div><strong>Read-only collection</strong><small>Approved artifact with bounded scope</small></div></div><div className="step-line" /><div className="step"><span>03</span><div><strong>Analyst decision</strong><small>Evidence reviewed before response</small></div></div></section>
  </main>
}
