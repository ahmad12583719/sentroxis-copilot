import { useEffect, useState } from 'react'
import { Archive, CheckCircle2, Copy, Download, FileKey2, Info, Loader2, Monitor, Package, RefreshCw, ShieldCheck, Terminal, Waypoints } from 'lucide-react'
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
  const [wazuhDeployment, setWazuhDeployment] = useState(null)
  const [wazuhBusy, setWazuhBusy] = useState(false)
  const [wazuhPackage, setWazuhPackage] = useState('deb-amd64')
  const [wazuhManagerAddress, setWazuhManagerAddress] = useState('10.5.89.68')

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
  useEffect(() => {
    refresh(); loadWazuhAgents()
    const refreshTimer = window.setInterval(loadWazuhAgents, 15000)
    return () => window.clearInterval(refreshTimer)
  }, [])

  const generateWazuhCommands = async (event) => {
    event.preventDefault(); setWazuhBusy(true); setWazuhDeployment(null); setMessage(''); setError('')
    try {
      const result = await authRequest('/api/wazuh/agents/deploy', { method: 'POST', body: JSON.stringify({ package: wazuhPackage, manager_address: wazuhManagerAddress.trim(), confirm_generate: true }) })
      setWazuhDeployment(result); setMessage('Wazuh deployment commands are ready for the selected endpoint package.')
    } catch (reason) { setError(reason.message || 'Wazuh deployment command generation failed.') } finally { setWazuhBusy(false) }
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
      <div className="panel-heading"><div><p className="eyebrow"><Monitor size={13} /> Wazuh endpoint operations</p><h2>Deploy a new agent</h2><p className="endpoint-lede">Follow the same package, Manager address, install, and start flow as the native Wazuh Dashboard.</p></div><span className="connection-badge"><i /> Manager API</span></div>
      <form className="wazuh-wizard-form" onSubmit={generateWazuhCommands}>
        <div className="wazuh-wizard-section"><div className="wazuh-wizard-title"><span>01</span><div><strong>Select the package to download and install</strong><small>Choose the operating system and architecture of the endpoint.</small></div></div><div className="wazuh-package-grid">{[['rpm-amd64','RPM amd64'],['rpm-aarch64','RPM aarch64'],['deb-amd64','DEB amd64'],['deb-aarch64','DEB aarch64'],['msi','MSI 32/64 bits'],['macos-intel','Intel'],['macos-apple-silicon','Apple silicon']].map(([value, label]) => <label className={`wazuh-package-option ${wazuhPackage === value ? 'selected' : ''}`} key={value}><input type="radio" name="wazuh-package" value={value} checked={wazuhPackage === value} onChange={() => { setWazuhPackage(value); setWazuhDeployment(null) }} /><span>{label}</span></label>)}</div><small className="wazuh-doc-note">For additional systems and architectures, consult the <a href="https://documentation.wazuh.com/current/installation-guide/wazuh-agent/index.html" target="_blank" rel="noreferrer">official Wazuh documentation</a>.</small></div>
        <div className="wazuh-wizard-section"><div className="wazuh-wizard-title"><span>02</span><div><strong>Server address</strong><small>This is the address the agent uses to communicate with the Wazuh Manager.</small></div></div><label className="wazuh-address-field"><span>Assign a server address</span><input required value={wazuhManagerAddress} onChange={(event) => { setWazuhManagerAddress(event.target.value); setWazuhDeployment(null) }} placeholder="10.5.89.68 or wazuh.example.com" /></label></div>
        <div className="wazuh-wizard-section"><div className="wazuh-wizard-title"><span>03</span><div><strong>Run the following command to download and install the agent</strong><small>{wazuhDeployment ? 'Run this command on the selected endpoint with administrator/root privileges.' : 'Select a package and enter the Manager address first.'}</small></div></div>{wazuhDeployment ? <CommandLine command={wazuhDeployment.install_command} onCopy={copyCommand} /> : <p className="wazuh-disabled-note">Please select the operating system and server address.</p>}</div>
        <div className="wazuh-wizard-section"><div className="wazuh-wizard-title"><span>04</span><div><strong>Start the agent</strong><small>{wazuhDeployment ? 'Run this after installation completes.' : 'The start command will appear after package and address selection.'}</small></div></div>{wazuhDeployment ? <CommandLine command={wazuhDeployment.start_command} onCopy={copyCommand} /> : <p className="wazuh-disabled-note">Please select the operating system and server address.</p>}</div>
        <button className="button primary wazuh-generate-button" type="submit" disabled={wazuhBusy || !wazuhManagerAddress.trim()}>{wazuhBusy ? <Loader2 className="spin" size={15} /> : <Terminal size={15} />} {wazuhBusy ? 'Preparing commands…' : 'Generate deployment commands'}</button>
      </form>
      <div className="wazuh-agent-list"><div className="panel-heading"><div><p className="eyebrow">Live inventory</p><h3>Agents reporting into Wazuh</h3></div><button className="button secondary" type="button" onClick={loadWazuhAgents}><RefreshCw size={14} /> Refresh</button></div>{wazuhAgents.length ? <div className="wazuh-agent-table">{wazuhAgents.map((agent) => <div className="wazuh-agent-row" key={agent.id || agent.name}><span className="status-check ready"><CheckCircle2 size={14} /></span><strong>{agent.name || agent.id}</strong><span>{agent.ip || 'IP unavailable'}</span><span>{agent.status || 'unknown'}</span><small>{agent.version || 'version unavailable'}</small></div>)}</div> : <p className="empty-state compact-empty">No Wazuh agents are reporting yet. Install and start an endpoint agent, then refresh.</p>}</div>
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
