import { useEffect, useMemo, useState } from 'react'
import { Check, Download, FileCode2, Loader2, Play, RefreshCw, ShieldCheck, Square, TerminalSquare } from 'lucide-react'
import { authRequest, useAuth } from '../auth/AuthProvider'

const fallbackCatalog = {
  release: '0.77.2',
  host_platform: 'linux-amd64',
  source_url: 'https://docs.velociraptor.app/downloads/',
  signature_key: '0572F28B4EF19A043F4CBBE0B22A7FB19CB6CFA1',
  assets: [{ platform: 'linux-amd64', version: '0.77.2', filename: 'velociraptor-v0.77.2-linux-amd64', sha256: '6c4c23c466d892788ff56ddcd3a31f844e4c0d797ade454c5e2625eb9e427077', is_host_platform: true }],
}

function hostnameFromEndpoint(endpoint) {
  try { return endpoint ? new URL(endpoint).hostname : '' } catch { return '' }
}

function StepBadge({ state, children }) {
  return <span className={`installer-state ${state}`}><i />{children}</span>
}

export default function VelociraptorInstaller({ endpoint = '' }) {
  const { user } = useAuth()
  const [catalog, setCatalog] = useState(fallbackCatalog)
  const [platform, setPlatform] = useState('linux-amd64')
  const [installation, setInstallation] = useState(null)
  const [server, setServer] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const endpointHostname = hostnameFromEndpoint(endpoint)
  const [settings, setSettings] = useState({
    server_os: 'linux',
    datastore_path: '',
    log_path: '',
    certificate_years: '1',
    use_registry_writeback: false,
    frontend_hostname: endpointHostname,
    use_websocket: false,
    gui_port: '8889',
    password_confirmation: '',
  })

  useEffect(() => {
    authRequest('/api/velociraptor/catalog').then((data) => {
      if (!Array.isArray(data.assets) || !data.assets.length) throw new Error('Catalog unavailable')
      setCatalog(data)
      setPlatform(data.host_platform || data.assets[0]?.platform || 'linux-amd64')
    }).catch(() => {})
  }, [])

  const asset = useMemo(() => catalog.assets.find((item) => item.platform === platform) || catalog.assets[0], [catalog.assets, platform])
  const updateSetting = (name, value) => setSettings((current) => ({ ...current, [name]: value }))
  const call = async (label, url, body) => {
    setBusy(label)
    setError('')
    setNotice('')
    try { return await authRequest(url, { method: 'POST', body: JSON.stringify(body) }) } catch (actionError) { setError(actionError.message || 'Action failed'); return null } finally { setBusy('') }
  }
  const prepare = async () => {
    const data = await call('download', '/api/velociraptor/prepare', { platform, confirm_download: true })
    if (data) { setInstallation(data.installation); setNotice('Verified binary is ready. Complete the bounded configuration form below.') }
  }
  const generateConfig = async (event) => {
    event.preventDefault()
    const data = await call('generate', '/api/velociraptor/config/generate', {
      platform,
      confirm_generate: true,
      server_os: settings.server_os,
      datastore_path: settings.datastore_path,
      log_path: settings.log_path || null,
      certificate_years: Number(settings.certificate_years),
      use_registry_writeback: settings.use_registry_writeback,
      frontend_hostname: settings.frontend_hostname || endpointHostname,
      use_websocket: settings.use_websocket,
      gui_port: Number(settings.gui_port),
      password_confirmation: settings.password_confirmation,
    })
    setSettings((current) => ({ ...current, password_confirmation: '' }))
    if (data) { setServer(data); setNotice(`Server and client configuration created. Initial Velociraptor administrator: ${data.admin_username}`) }
  }
  const runServer = async () => {
    const data = await call('run', '/api/velociraptor/run', { platform, confirm_run: true })
    if (data) setServer((current) => ({ ...current, ...data }))
  }
  const stopServer = async () => {
    const data = await call('stop', '/api/velociraptor/stop', {})
    if (data) setServer((current) => ({ ...current, ...data }))
  }

  return <section className="panel installer-panel"><div className="installer-heading"><div><p className="eyebrow"><TerminalSquare size={13} /> Velociraptor runtime</p><h2>Install, configure, then run</h2><p>Self-signed TLS is the only permitted deployment mode in this workflow. The client frontend is fixed to port <strong>8010</strong>; all listed operational choices remain under the operator’s control.</p></div><span className="release-badge">release v{catalog.release}</span></div><div className="installer-flow"><div className={`installer-card ${installation ? 'done' : ''}`}><div className="installer-card-top"><span className="installer-index">01</span>{installation ? <StepBadge state="done">Verified</StepBadge> : <StepBadge state="pending">Waiting</StepBadge>}</div><Download size={18} className="installer-card-icon" /><h3>Install official binary</h3><p>Download an allowlisted release for the selected platform and verify its SHA-256 before use.</p><label htmlFor="vr-platform">Target platform</label><select id="vr-platform" value={platform} onChange={(event) => setPlatform(event.target.value)} disabled={busy !== ''}>{catalog.assets.map((item) => <option key={item.platform} value={item.platform}>{item.platform}{item.is_host_platform ? ' · host' : ''}</option>)}</select><button className="button secondary installer-action" onClick={prepare} disabled={busy !== ''}>{busy === 'download' ? <Loader2 size={14} className="spin" /> : <Download size={14} />}{installation ? 'Verify again' : 'Download & verify'}</button>{asset && <small className="hash-line">SHA-256 {asset.sha256.slice(0, 16)}…</small>}</div><div className="installer-card"><div className="installer-card-top"><span className="installer-index">02</span>{server?.client_config_path ? <StepBadge state="done">Generated</StepBadge> : <StepBadge state="pending">Required</StepBadge>}</div><FileCode2 size={18} className="installer-card-icon violet" /><h3>Generate server &amp; client config</h3><p>Only the deployment type, frontend port, DNS mode, and initial administrator identity are automated. The remaining values below are selected by the operator.</p><form onSubmit={generateConfig} className="terminal-input installer-config-form"><label htmlFor="vr-server-os">Server operating system</label><select id="vr-server-os" value={settings.server_os} onChange={(event) => updateSetting('server_os', event.target.value)} disabled={!installation || busy !== ''}><option value="linux">Linux</option><option value="windows">Windows</option><option value="darwin">macOS</option></select><label htmlFor="vr-datastore">Datastore directory</label><input id="vr-datastore" value={settings.datastore_path} onChange={(event) => updateSetting('datastore_path', event.target.value)} placeholder={settings.server_os === 'windows' ? 'C:\\Velociraptor' : '/opt/velociraptor'} required disabled={!installation || busy !== ''} /><label htmlFor="vr-logs">Logs directory <small>optional</small></label><input id="vr-logs" value={settings.log_path} onChange={(event) => updateSetting('log_path', event.target.value)} placeholder="Defaults to <datastore>/logs" disabled={!installation || busy !== ''} /><label htmlFor="vr-cert-years">Internal certificate lifetime</label><select id="vr-cert-years" value={settings.certificate_years} onChange={(event) => updateSetting('certificate_years', event.target.value)} disabled={!installation || busy !== ''}><option value="1">1 year</option><option value="2">2 years</option><option value="10">10 years</option></select><label htmlFor="vr-hostname">Public frontend DNS name or server IP</label><input id="vr-hostname" value={settings.frontend_hostname || endpointHostname} onChange={(event) => updateSetting('frontend_hostname', event.target.value)} placeholder="192.168.1.10 or velo.example.com" required disabled={!installation || busy !== ''} /><label htmlFor="vr-gui-port">GUI port</label><input id="vr-gui-port" type="number" min="1" max="65535" value={settings.gui_port} onChange={(event) => updateSetting('gui_port', event.target.value)} required disabled={!installation || busy !== ''} /><label className="installer-checkbox"><input type="checkbox" checked={settings.use_websocket} onChange={(event) => updateSetting('use_websocket', event.target.checked)} disabled={!installation || busy !== ''} /> Use experimental WebSocket communications</label><label className="installer-checkbox"><input type="checkbox" checked={settings.use_registry_writeback} onChange={(event) => updateSetting('use_registry_writeback', event.target.checked)} disabled={!installation || busy !== ''} /> Use the Windows registry for client writeback</label><label htmlFor="vr-frontend-port">Frontend port <small>fixed by Sentroxis</small></label><input id="vr-frontend-port" value="8010" readOnly aria-readonly="true" /><label htmlFor="vr-admin">Initial Velociraptor administrator</label><input id="vr-admin" value={user?.email || ''} readOnly aria-readonly="true" /><label htmlFor="vr-password">Confirm current Sentroxis password</label><input id="vr-password" type="password" autoComplete="current-password" value={settings.password_confirmation} onChange={(event) => updateSetting('password_confirmation', event.target.value)} placeholder="Used once; never stored" required disabled={!installation || busy !== ''} /><button className="button secondary installer-action" type="submit" disabled={!installation || busy !== ''}>{busy === 'generate' ? <Loader2 size={14} className="spin" /> : <FileCode2 size={14} />}Generate `server.config.yaml` &amp; `client.config.yaml`</button></form></div><div className={`installer-card ${server?.running ? 'done' : ''}`}><div className="installer-card-top"><span className="installer-index">03</span>{server?.running ? <StepBadge state="done">Running</StepBadge> : <StepBadge state="pending">Approval</StepBadge>}</div><ShieldCheck size={18} className="installer-card-icon green" /><h3>Start server</h3><p>Configuration generation is complete before this final, explicit action can start the local server process.</p>{server?.config_path && <code className="command-chip">velociraptor --config server.config.yaml frontend</code>}<button className="button primary installer-action" onClick={runServer} disabled={!server?.client_config_path || busy !== ''}>{busy === 'run' ? <Loader2 size={14} className="spin" /> : <Play size={14} />}Run Velociraptor server</button>{server?.running && <button className="button stop-button" onClick={stopServer} disabled={busy !== ''}>{busy === 'stop' ? <Loader2 size={14} className="spin" /> : <Square size={13} />} Stop server · PID {server.pid}</button>}</div></div>{notice && <div className="installer-footer"><span><Check size={13} /> {notice}</span></div>}{error && <div className="installer-error" role="alert"><RefreshCw size={14} /> {error}</div>}<div className="installer-footer"><span><Check size={13} /> Self-signed TLS and manual DNS only</span><span><ShieldCheck size={13} /> Frontend client port: 8010</span><span>GUI port remains operator-selected</span></div></section>
}
