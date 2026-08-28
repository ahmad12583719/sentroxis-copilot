import { useEffect, useState } from 'react'
import { Archive, CheckCircle2, Download, FileKey2, Info, Loader2, Package, ShieldCheck, Terminal, Waypoints } from 'lucide-react'
import { authRequest } from '../auth/AuthProvider'

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
  useEffect(() => { refresh() }, [])

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
      <div><p className="eyebrow"><Waypoints size={13} /> Endpoint operations <span className="slash">/</span> Velociraptor</p><h1>Prepare your <em>endpoints.</em></h1><p className="lede">Generate controlled Velociraptor client packages for this workspace.</p></div>
      <span className={`connection-badge ${ready ? '' : 'muted'}`}><i /> {ready ? 'Package-ready' : 'Setup required'}</span>
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
