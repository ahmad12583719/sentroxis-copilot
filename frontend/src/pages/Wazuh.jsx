import { useMemo, useState } from 'react'
import { ArrowDownUp, CheckCircle2, ChevronRight, Filter, RefreshCw, Search, Shield, SlidersHorizontal } from 'lucide-react'
import { demoAlerts } from './demoData'

export default function Wazuh({ onSelectAlert }) {
  const [query, setQuery] = useState('')
  const [severity, setSeverity] = useState('All')
  const filtered = useMemo(() => demoAlerts.filter((alert) => {
    const matchesQuery = `${alert.title} ${alert.agent} ${alert.technique}`.toLowerCase().includes(query.toLowerCase())
    const matchesSeverity = severity === 'All' || alert.severity === severity
    return matchesQuery && matchesSeverity
  }), [query, severity])

  return <main className="page-shell subpage-shell">
    <section className="page-heading compact-heading"><div><p className="eyebrow"><Shield size={13} /> Wazuh integration <span className="slash">/</span> normalized alert stream</p><h1>Wazuh <em>signals.</em></h1><p className="lede">Read-only ingestion surface with server-side authorization and bounded queries.</p></div><div className="heading-actions"><span className="connection-badge"><i /> Indexer connected</span><button className="button secondary"><RefreshCw size={15} /> Sync now</button></div></section>
    <section className="panel signal-toolbar"><div className="search-box"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search alert, agent, or technique" aria-label="Search signals" /></div><div className="filter-group"><Filter size={15} /><label htmlFor="severity">Severity</label><select id="severity" value={severity} onChange={(event) => setSeverity(event.target.value)}><option>All</option><option>Critical</option><option>High</option><option>Medium</option></select><button className="icon-button" aria-label="More filters"><SlidersHorizontal size={16} /></button></div></section>
    <section className="panel table-panel"><div className="table-heading"><div><p className="eyebrow">{filtered.length} matching records</p><h2>Alert inventory</h2></div><span className="table-meta"><CheckCircle2 size={14} /> Last sync 34s ago</span></div><div className="table-scroll"><table><thead><tr><th>Signal <ArrowDownUp size={12} /></th><th>Agent</th><th>Severity</th><th>ATT&amp;CK correlation</th><th>Observed</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>{filtered.map((alert) => <tr key={alert.id} onClick={() => onSelectAlert?.(alert)}><td><div className="table-signal"><span className={`severity-pip ${alert.severityKey}`} /><div><strong>{alert.title}</strong><small>Rule {alert.rule}</small></div></div></td><td><strong>{alert.agent}</strong><small className="table-sub">{alert.ip}</small></td><td><span className={`severity-label ${alert.severityKey}`}>{alert.severity}</span></td><td><span className="technique-chip">{alert.technique}</span><small className="table-sub">{alert.techniqueName}</small></td><td className="muted">{alert.time} UTC</td><td><ChevronRight size={16} className="row-chevron" /></td></tr>)}</tbody></table></div><div className="panel-footer"><span>Showing bounded results · 50 max per request</span><button className="text-button">Export review set <ChevronRight size={14} /></button></div></section>
    <section className="callout-grid"><div className="security-callout"><div className="callout-icon"><Shield size={17} /></div><div><strong>Read-only by default</strong><p>Response actions are never executed from telemetry or AI output. Any containment proposal requires a separate approval workflow.</p></div></div><div className="security-callout"><div className="callout-icon violet"><Filter size={17} /></div><div><strong>Normalization boundary</strong><p>Vendor payloads are transformed into stable Alert models before they enter the case or AI layers.</p></div></div></section>
  </main>
}
