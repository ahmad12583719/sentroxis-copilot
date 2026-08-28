import { useEffect, useState } from 'react'
import { Archive, CheckCircle2, Copy, Download, FileKey2, Info, Loader2, Monitor, Package, Plus, RefreshCw, ShieldCheck, Terminal, Waypoints } from 'lucide-react'
import { authRequest } from '../auth/AuthProvider'

function CommandLine({ command, onCopy }) {
  return <div className="wazuh-command-row"><code>{command}</code><button className="icon-button" type="button" onClick={() => onCopy(command)} title="Copy command" aria-label="Copy command"><Copy size={14} /></button></div>
}

const targets = [
  { id: 'linux-amd64', label: 'Linux amd64', description: 'Executable client with shell commands for interactive or service deployment.' },
  { id: 'windows-amd64', label: 'Windows amd64', description: 'Executable client plus an official MSI, repacked with the generated client configuration when supported.' },
]

export default function Agents() {
  const [status, setStatus] = useState(null)
  const [bundles, setBundles] = useState({})
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [wazuhAgents, setWazuhAgents] = useState([])
  const [wazuhEnrollment, setWazuhEnrollment] = useState(null)
  const [wazuhBusy, setWazuhBusy] = useState(false)
  const [wazuhForm, setWazuhForm] = useState({ name: '', ip: '', group: '', platform: 'linux', manager_address: window.location.hostname || '127.0.0.1' })

  const refresh = async () => {
    try {
      const [nextStatus, savedBundles] = await Promise.all([
        authRequest('/api/velociraptor/status'),
        authRequest('/api/velociraptor/endpoints/bundles'),
      ])
      setStatus(nextStatus)
      setBundles(Object.fromEntries((savedBundles.bundles || []).map((bundle) => [bundle.platform, bundle])))
    } catch (reason) {
      setError(reason.message || 'Unable to read Velociraptor package status.')
    }
  }
  const loadWazuhAgents = () => authRequest('/api/wazuh/overview').then((data) => setWazuhAgents(data.agents || [])).catch((reason) => setError(reason.message || 'Unable to read Wazuh agent status.'))
  useEffect(() => { refresh(); loadWazuhAgents() }, [])

  const updateWazuhField = (field, value) => setWazuhForm((current) => ({ ...current, [field]: value }))
  const enrollWazuh = async (event) => {
    event.preventDefault(); setWazuhBusy(true); setWazuhEnrollment(null); setMessage(''); setError('')
    try {
      const result = await authRequest('/api/wazuh/agents/enroll', { method: 'POST', body: JSON.stringify({ ...wazuhForm, ip: wazuhForm.ip || null, group: wazuhForm.group || null, manager_address: wazuhForm.manager_address || null, confirm_create: true }) })
      setWazuhEnrollment(result); setMessage(`Wazuh agent ${result.name} (${result.id}) was created. Complete the four endpoint steps below.`)
    } catch (reason) { setError(reason.message || 'Wazuh agent enrollment failed.') } finally { setWazuhBusy(false) }
  }
  const copyCommand = (command) => navigator.clipboard?.writeText(command).then(() => setMessage('Command copied to clipboard.'))

  const generateBundle = async (platform) => {
    setBusy(platform); setMessage(''); setError('')
    try {
      const result = await authRequest('/api/velociraptor/endpoints/bundle', { method: 'POST', body: JSON.stringify({ platform, confirm_download: true }) })
      setBundles((current) => ({ ...current, [platform]: result }))
      setMessage(`${result.filename} is ready to download.`)
    } catch (reason) {
      setError(reason.message || 'Bundle generation failed. Generate the server, client, and API configs first.')
    } finally { setBusy('') }
  }

  const ready = Boolean(status?.configured && status?.api_config_ready)
  return <main className="page-shell subpage-shell endpoint-page">
    <section className="page-heading compact-heading">
      <div><p className="eyebrow"><Waypoints size={13} /> Endpoint operations <span className="slash">/</span> Wazuh &amp; Velociraptor</p><h1>Prepare your <em>endpoints.</em></h1><p className="lede">Configure Wazuh agents from the Manager API, or generate controlled Velociraptor client packages for this workspace.</p></div>
      <span className={`connection-badge ${ready ? '' : 'muted'}`}><i /> {ready ? 'Package-ready' : 'Setup required'}</span>
    </section>

    <section className="panel wazuh-endpoint-panel">
      <div className="panel-heading"><div><p className="eyebrow"><Monitor size={13} /> Wazuh endpoint operations</p><h2>Configure a Wazuh agent</h2><p className="endpoint-lede">Create the agent in Wazuh, then complete the endpoint-side installation, key import, manager configuration, and restart.</p></div><span className="connection-badge"><i /> Manager API</span></div>
      <form className="wazuh-agent-form" onSubmit={enrollWazuh}>
        <label>Agent name<input required value={wazuhForm.name} onChange={(event) => updateWazuhField('name', event.target.value)} placeholder="kali-workstation" pattern="[A-Za-z0-9._-]+" /></label>
        <label>Endpoint IP <small>optional</small><input value={wazuhForm.ip} onChange={(event) => updateWazuhField('ip', event.target.value)} placeholder="10.5.89.68" /></label>
        <label>Agent group <small>optional</small><input value={wazuhForm.group} onChange={(event) => updateWazuhField('group', event.target.value)} placeholder="workstations" pattern="[A-Za-z0-9._-]+" /></label>
        <label>Endpoint platform<select value={wazuhForm.platform} onChange={(event) => updateWazuhField('platform', event.target.value)}><option value="linux">Linux / Unix</option><option value="windows">Windows</option></select></label>
        <label>Manager address<input required value={wazuhForm.manager_address} onChange={(event) => updateWazuhField('manager_address', event.target.value)} placeholder="10.5.89.68" /></label>
        <button className="button primary" type="submit" disabled={wazuhBusy || !wazuhForm.name}>{wazuhBusy ? <Loader2 className="spin" size={15} /> : <Plus size={15} />} {wazuhBusy ? 'Creating agent…' : 'Create agent in Wazuh'}</button>
      </form>
      <div className="wazuh-enrollment-steps"><div className="wazuh-step"><span>01</span><div><strong>Create and obtain key</strong><p>Sentroxis uses the protected Manager API to register the endpoint and retrieve its one-time client key.</p></div></div><div className="wazuh-step"><span>02</span><div><strong>Install the agent</strong><p>Install the official Wazuh agent package or MSI on the target endpoint.</p>{wazuhEnrollment && <CommandLine command={wazuhEnrollment.install_command} onCopy={copyCommand} />}</div></div><div className="wazuh-step"><span>03</span><div><strong>Import key and configure Manager</strong><p>Run both commands on the endpoint. The key is shown only in this authenticated session.</p>{wazuhEnrollment && <><CommandLine command={wazuhEnrollment.enroll_command} onCopy={copyCommand} /><CommandLine command={wazuhEnrollment.configure_command} onCopy={copyCommand} /></>}</div></div><div className="wazuh-step"><span>04</span><div><strong>Restart and verify</strong><p>Restart the agent service, then refresh live telemetry to confirm it is reporting.</p>{wazuhEnrollment && <CommandLine command={wazuhEnrollment.restart_command} onCopy={copyCommand} />}</div></div></div>
      {wazuhEnrollment && <div className="wazuh-agent-key"><div><strong>Created agent {wazuhEnrollment.name}</strong><small>ID {wazuhEnrollment.id} · manager {wazuhEnrollment.manager_address}</small></div><button className="button secondary" type="button" onClick={() => copyCommand(wazuhEnrollment.key)}><Copy size={14} /> Copy client key</button></div>}
      <div className="wazuh-agent-list"><div className="panel-heading"><div><p className="eyebrow">Live inventory</p><h3>Agents reporting into Wazuh</h3></div><button className="button secondary" type="button" onClick={loadWazuhAgents}><RefreshCw size={14} /> Refresh</button></div>{wazuhAgents.length ? <div className="wazuh-agent-table">{wazuhAgents.map((agent) => <div className="wazuh-agent-row" key={agent.id || agent.name}><span className="status-check ready"><CheckCircle2 size={14} /></span><strong>{agent.name || agent.id}</strong><span>{agent.ip || 'IP unavailable'}</span><span>{agent.status || 'unknown'}</span><small>{agent.version || 'version unavailable'}</small></div>)}</div> : <p className="empty-state compact-empty">No Wazuh agents are reporting yet. Complete the four endpoint steps above, then refresh.</p>}</div>
    </section>

    <section className="panel endpoint-status-panel">
      <div className="panel-heading"><div><p className="eyebrow">Readiness</p><h2>Velociraptor package prerequisites</h2></div><ShieldCheck size={18} /></div>
      <div className="endpoint-status-body">
        <div className="endpoint-status-item"><span className={status?.configured ? 'status-check ready' : 'status-check'}><CheckCircle2 size={15} /></span><div><strong>Server configuration</strong><small>{status?.configured ? status.config_path : 'Generate server.config.yaml from the Velociraptor setup workflow.'}</small></div></div>
        <div className="endpoint-status-item"><span className={status?.api_config_ready ? 'status-check ready' : 'status-check'}><FileKey2 size={15} /></span><div><strong>Client and API configurations</strong><small>{status?.api_config_ready ? 'Generated and available to authorized analysts.' : 'Generate client.config.yaml and api.config.yaml before packaging.'}</small></div></div>
        <div className="endpoint-status-note"><Info size={15} /><span>The ZIP contains private API key material. Keep it restricted, transfer it through an approved channel, and do not commit it to source control.</span></div>
      </div>
    </section>

    <section className="endpoint-targets" aria-label="Endpoint package targets">
      {targets.map((target) => { const bundle = bundles[target.id]; return <section className="panel endpoint-target-card" key={target.id}>
        <div className="panel-heading"><div><p className="eyebrow">Client target</p><h2>{target.label}</h2></div><Package size={18} /></div>
        <div className="endpoint-card-body"><p>{target.description}</p><div className="endpoint-contents"><span><Archive size={14} /> Official binary</span><span><FileKey2 size={14} /> client.config.yaml</span><span><FileKey2 size={14} /> api.config.yaml</span><span><Terminal size={14} /> README.md</span>{target.id === 'windows-amd64' && <span><Package size={14} /> MSI when available</span>}</div>
          {bundle ? <div className="endpoint-download-row"><div><strong>{bundle.filename}</strong><small>{bundle.includes_msi ? `Windows MSI: ${bundle.msi_mode}` : 'ZIP bundle generated'}</small></div><a className="button primary" href={bundle.download_url}><Download size={15} /> Download ZIP</a></div> : <button className="button primary" onClick={() => generateBundle(target.id)} disabled={!ready || Boolean(busy)}>{busy === target.id ? <Loader2 className="spin" size={15} /> : <Archive size={15} />} {busy === target.id ? 'Building bundle…' : 'Generate ZIP package'}</button>}
        </div>
      </section> })}
    </section>
    {message && <p className="endpoint-feedback success"><CheckCircle2 size={14} /> {message}</p>}
    {error && <p className="endpoint-feedback error"><Info size={14} /> {error}</p>}
  </main>
}
