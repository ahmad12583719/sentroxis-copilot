import { useEffect, useMemo, useState } from 'react'
import { animate } from 'animejs'
import { ArrowUpRight, Bot, ChevronRight, CircleAlert, Clock3, Crosshair, Database, LockKeyhole, Radar, ShieldAlert, Sparkles, TimerReset, Zap } from 'lucide-react'
import AnimatedCard from '../components/AnimatedCard'
import { demoAlerts } from './demoData'

const tactics = ['Reconnaissance', 'Resource Development', 'Initial Access', 'Execution', 'Persistence', 'Privilege Escalation', 'Defense Evasion', 'Credential Access', 'Discovery', 'Lateral Movement', 'Collection', 'Command & Control', 'Exfiltration', 'Impact']
const techniques = ['T1059.001', 'T1053.005', 'T1003', 'T1562.001', 'T1087', 'T1021.001', 'T1105', 'T1041']

function MitreMatrix({ selectedAlert }) {
  const active = useMemo(() => new Set(demoAlerts.map((item) => item.technique)), [])

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const animation = animate('.mitre-cell.is-active', {
      backgroundColor: ['#192d3a', '#2df7b5', '#143530'],
      boxShadow: ['0 0 0 rgba(45,247,181,0)', '0 0 18px rgba(45,247,181,.65)', '0 0 8px rgba(45,247,181,.2)'],
      duration: 850,
      delay: (_, i) => i * 90,
      ease: 'inOut(2)',
    })
    return () => animation?.pause?.()
  }, [selectedAlert])

  return (
    <div className="matrix-wrap">
      <div className="matrix-header"><span>ATT&amp;CK enterprise coverage</span><span className="matrix-legend"><i className="legend-active" /> correlated <i className="legend-idle" /> observed</span></div>
      <div className="mitre-matrix" role="grid" aria-label="MITRE ATT&CK correlation matrix">
        <div className="matrix-tactic-labels">{tactics.map((tactic) => <span key={tactic}>{tactic}</span>)}</div>
        <div className="matrix-grid">
          {tactics.map((tactic) => (
            <div className="matrix-column" key={tactic}>
              {techniques.map((technique, index) => {
                const isActive = active.has(technique) && ((index + tactic.length) % 4 === 0 || technique === selectedAlert?.technique)
                return <span key={`${tactic}-${technique}`} className={`mitre-cell ${isActive ? 'is-active' : ''}`} title={`${tactic} / ${technique}`} role="gridcell">{isActive ? '•' : ''}</span>
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Metric({ icon: Icon, label, value, delta, tone, detail, index }) {
  return <AnimatedCard index={index} className={`metric-${tone}`}>
    <div className="metric-top"><span className="metric-icon"><Icon size={18} /></span><span className="metric-delta"><ArrowUpRight size={13} /> {delta}</span></div>
    <div className="metric-value">{value}</div>
    <div className="metric-label">{label}</div>
    <div className="metric-detail">{detail}</div>
  </AnimatedCard>
}

export default function Dashboard({ onNavigate, onSelectAlert }) {
  const [selectedAlert, setSelectedAlert] = useState(demoAlerts[0])
  const select = (alert) => { setSelectedAlert(alert); onSelectAlert?.(alert) }
  return <main className="page-shell">
    <section className="page-heading">
      <div><p className="eyebrow"><span className="pulse-dot" /> Live command view <span className="slash">/</span> Tuesday, 24 August 2026</p><h1>Good morning, <em>analyst.</em></h1><p className="lede">Your detection surface is stable. <strong>4 signals</strong> need a decision.</p></div>
      <div className="heading-actions"><button className="button secondary" onClick={() => onNavigate('ai')}><Bot size={16} /> Ask co-pilot</button><button className="button primary" onClick={() => onNavigate('wazuh')}><Radar size={16} /> Review signals <ChevronRight size={15} /></button></div>
    </section>
    <section className="metrics-grid" aria-label="Operational metrics">
      <Metric icon={ShieldAlert} label="Open incidents" value="12" delta="18%" detail="2 critical · 5 high" tone="red" index={0} />
      <Metric icon={Zap} label="Mean time to detect" value="04:18" delta="31%" detail="vs. 06:12 last week" tone="teal" index={1} />
      <Metric icon={TimerReset} label="Mean time to respond" value="18:42" delta="12%" detail="within 30 min target" tone="amber" index={2} />
      <Metric icon={Crosshair} label="ATT&CK coverage" value="78.4%" delta="4.6%" detail="31 techniques observed" tone="violet" index={3} />
    </section>
    <section className="dashboard-grid">
      <div className="panel alert-panel">
        <div className="panel-heading"><div><p className="eyebrow">Detection queue</p><h2>Latest signals</h2></div><button className="text-button" onClick={() => onNavigate('wazuh')}>View all <ArrowUpRight size={14} /></button></div>
        <div className="alert-list">
          {demoAlerts.map((alert) => <button key={alert.id} className={`alert-row ${selectedAlert?.id === alert.id ? 'selected' : ''}`} onClick={() => select(alert)}>
            <span className={`severity-pip ${alert.severityKey}`} aria-label={`${alert.severity} severity`} />
            <span className="alert-main"><strong>{alert.title}</strong><small>{alert.agent} <span>·</span> {alert.ip}</small></span>
            <span className="alert-tech"><b>{alert.technique}</b><small>{alert.tactic}</small></span>
            <span className="alert-time">{alert.time}</span><ChevronRight size={15} className="row-chevron" />
          </button>)}
        </div>
        <div className="panel-footer"><span><CircleAlert size={14} /> Data refreshes every 30 seconds</span><span className="freshness"><i /> Fresh</span></div>
      </div>
      <div className="panel ai-brief-panel">
        <div className="panel-heading"><div><p className="eyebrow">Evidence-grounded</p><h2>Co-pilot brief</h2></div><span className="ai-orb"><Sparkles size={16} /></span></div>
        <div className="ai-brief"><div className="avatar ai-avatar">SX</div><div><p className="ai-label">Sentroxis AI <span>advisory</span></p><p>Signals cluster around <strong>{selectedAlert?.techniqueName}</strong> on <strong>{selectedAlert?.agent}</strong>. The current pattern is consistent with {selectedAlert?.tactic.toLowerCase()} activity.</p><p className="ai-note">Next best step: validate the process tree, then collect read-only endpoint context before any containment decision.</p></div></div>
        <div className="confidence"><div><span>Correlation confidence</span><strong>82%</strong></div><div className="confidence-bar"><i style={{ width: '82%' }} /></div></div>
        <button className="button full-width" onClick={() => onNavigate('ai')}>Open investigation brief <ArrowUpRight size={14} /></button>
      </div>
    </section>
    <section className="panel matrix-panel"><div className="panel-heading"><div><p className="eyebrow">Threat coverage</p><h2>MITRE ATT&amp;CK matrix</h2></div><div className="matrix-stat"><span className="stat-number">31</span><span>techniques<br />observed</span></div></div><MitreMatrix selectedAlert={selectedAlert} /></section>
    <section className="bottom-strip"><div className="mini-status"><Database size={16} /><div><strong>Data plane</strong><span>Wazuh indexer · connected</span></div><i className="status-ok" /></div><div className="mini-status"><LockKeyhole size={16} /><div><strong>Evidence vault</strong><span>Chain of custody · intact</span></div><i className="status-ok" /></div><div className="mini-status"><Clock3 size={16} /><div><strong>Last sync</strong><span>24 Aug 2026 · 08:21 UTC</span></div><i className="status-ok" /></div></section>
  </main>
}
