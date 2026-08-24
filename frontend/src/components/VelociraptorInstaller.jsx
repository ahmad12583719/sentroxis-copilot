import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronRight, Download, FileCode2, Loader2, Play, RefreshCw, ShieldCheck, Square, TerminalSquare } from 'lucide-react'

const fallbackCatalog = {
  release: '0.77.2',
  host_platform: 'linux-amd64',
  source_url: 'https://docs.velociraptor.app/downloads/',
  signature_key: '0572F28B4EF19A043F4CBBE0B22A7FB19CB6CFA1',
  assets: [{ platform: 'linux-amd64', version: '0.77.2', filename: 'velociraptor-v0.77.2-linux-amd64', sha256: '6c4c23c466d892788ff56ddcd3a31f844e4c0d797ade454c5e2625eb9e427077', is_host_platform: true }],
}

function StepBadge({ state, children }) {
  return <span className={`installer-state ${state}`}><i />{children}</span>
}

export default function VelociraptorInstaller() {
  const [catalog, setCatalog] = useState(fallbackCatalog)
  const [platform, setPlatform] = useState('linux-amd64')
  const [installation, setInstallation] = useState(null)
  const [wizard, setWizard] = useState(null)
  const [wizardInput, setWizardInput] = useState('')
  const [server, setServer] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/velociraptor/catalog').then((response) => response.ok ? response.json() : Promise.reject(new Error('Catalog unavailable'))).then((data) => {
      setCatalog(data)
      setPlatform(data.host_platform || data.assets[0]?.platform || 'linux-amd64')
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!wizard?.session_id || !wizard.running) return undefined
    const timer = window.setInterval(() => {
      fetch(`/api/velociraptor/wizard/${wizard.session_id}`).then((response) => response.json()).then((data) => setWizard((current) => ({ ...current, ...data }))).catch(() => {})
    }, 700)
    return () => window.clearInterval(timer)
  }, [wizard?.session_id, wizard?.running])

  const asset = useMemo(() => catalog.assets.find((item) => item.platform === platform) || catalog.assets[0], [catalog.assets, platform])
  const call = async (label, url, body) => {
    setBusy(label)
    setError('')
    try {
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Action failed')
      return data
    } catch (actionError) {
      setError(actionError.message)
      return null
    } finally { setBusy('') }
  }
  const prepare = async () => { const data = await call('download', '/api/velociraptor/prepare', { platform, confirm_download: true }); if (data) setInstallation(data.installation) }
  const startWizard = async () => { const data = await call('wizard', '/api/velociraptor/wizard/start', { platform, confirm_start: true }); if (data) setWizard(data) }
  const sendInput = async (event) => { event.preventDefault(); if (!wizardInput || !wizard) return; const data = await call('input', '/api/velociraptor/wizard/input', { session_id: wizard.session_id, input: `${wizardInput}\n` }); if (data) { setWizard((current) => ({ ...current, ...data })); setWizardInput('') } }
  const runServer = async () => { const data = await call('run', '/api/velociraptor/run', { platform, confirm_run: true }); if (data) setServer(data) }
  const stopServer = async () => { const data = await call('stop', '/api/velociraptor/stop', {}); if (data) setServer(data) }

  return <section className="panel installer-panel"><div className="installer-heading"><div><p className="eyebrow"><TerminalSquare size={13} /> Velociraptor runtime</p><h2>Download, configure, then run</h2><p>Every transition is explicit. The browser never accepts arbitrary URLs or shell commands.</p></div><span className="release-badge">release v{catalog.release}</span></div><div className="installer-flow"><div className={`installer-card ${installation ? 'done' : ''}`}><div className="installer-card-top"><span className="installer-index">01</span>{installation ? <StepBadge state="done">Verified</StepBadge> : <StepBadge state="pending">Waiting</StepBadge>}</div><Download size={18} className="installer-card-icon" /><h3>Install official binary</h3><p>Download the allowlisted GitHub release asset for the selected OS and verify its SHA-256 before use.</p><label htmlFor="vr-platform">Target platform</label><select id="vr-platform" value={platform} onChange={(event) => setPlatform(event.target.value)}>{catalog.assets.map((item) => <option key={item.platform} value={item.platform}>{item.platform}{item.is_host_platform ? ' · host' : ''}</option>)}</select><button className="button secondary installer-action" onClick={prepare} disabled={busy !== ''}>{busy === 'download' ? <Loader2 size={14} className="spin" /> : <Download size={14} />}{installation ? 'Verify again' : 'Download & verify'}</button>{asset && <small className="hash-line">SHA-256 {asset.sha256.slice(0, 16)}…</small>}</div><div className="installer-connector"><ChevronRight size={16} /></div><div className={`installer-card ${wizard ? 'done' : ''}`}><div className="installer-card-top"><span className="installer-index">02</span>{wizard ? <StepBadge state="done">Running</StepBadge> : <StepBadge state="pending">Locked</StepBadge>}</div><FileCode2 size={18} className="installer-card-icon violet" /><h3>Generate server config</h3><p>Run the official interactive command with a streamed terminal. The generated YAML stays on the local server.</p>{installation && <code className="command-chip">{installation.command_preview}</code>}<button className="button secondary installer-action" onClick={startWizard} disabled={!installation || busy !== ''}>{busy === 'wizard' ? <Loader2 size={14} className="spin" /> : <Play size={14} />}Start config wizard</button>{wizard && <div className="terminal-box" aria-live="polite"><pre>{wizard.output || 'Waiting for Velociraptor…'}</pre><form onSubmit={sendInput} className="terminal-input"><input value={wizardInput} onChange={(event) => setWizardInput(event.target.value)} placeholder="Type the next answer…" aria-label="Velociraptor wizard input" /><button aria-label="Send wizard input"><ChevronRight size={15} /></button></form></div>}</div><div className="installer-connector"><ChevronRight size={16} /></div><div className={`installer-card ${server?.running ? 'done' : ''}`}><div className="installer-card-top"><span className="installer-index">03</span>{server?.running ? <StepBadge state="done">Running</StepBadge> : <StepBadge state="pending">Approval</StepBadge>}</div><ShieldCheck size={18} className="installer-card-icon green" /><h3>Start server</h3><p>Only a generated config and verified executable can reach this final, approval-gated action.</p>{installation && <code className="command-chip">{installation.server_command_preview}</code>}<button className="button primary installer-action" onClick={runServer} disabled={!installation || !wizard?.config_ready || busy !== ''}>{busy === 'run' ? <Loader2 size={14} className="spin" /> : <Play size={14} />}Run Velociraptor server</button>{server?.running && <button className="button stop-button" onClick={stopServer} disabled={busy !== ''}>{busy === 'stop' ? <Loader2 size={14} className="spin" /> : <Square size={13} />} Stop server · PID {server.pid}</button>}</div></div>{error && <div className="installer-error" role="alert"><RefreshCw size={14} /> {error}</div>}<div className="installer-footer"><span><Check size={13} /> SHA-256 verified release asset</span><span><ShieldCheck size={13} /> GPG key: {catalog.signature_key.slice(0, 16)}…</span><span>Config required before server start</span></div></section>
}
