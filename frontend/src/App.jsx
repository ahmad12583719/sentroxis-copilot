import { useState } from 'react'
import { Activity, ChevronLeft, ChevronRight, Cpu, FileText, Home, Radio, Server, Settings2, Sparkles, Waypoints } from 'lucide-react'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Wazuh from './pages/Wazuh'
import Velociraptor from './pages/Velociraptor'
import AIChat from './pages/AIChat'
import Setup from './pages/Setup'
import './App.css'

const sideItems = [
  { key: 'setup', label: 'Project setup', icon: Server, badge: 'STEP 1' },
  { key: 'dashboard', label: 'Overview', icon: Home },
  { key: 'wazuh', label: 'Wazuh signals', icon: Activity, count: 4 },
  { key: 'velociraptor', label: 'Velociraptor', icon: Waypoints },
  { key: 'ai', label: 'AI co-pilot', icon: Sparkles, badge: 'NEW' },
]

function Sidebar({ activeView, onNavigate, collapsed, onToggle }) {
  return <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}><div className="sidebar-top"><span className="sidebar-kicker">Command center</span><button className="collapse-button" onClick={onToggle} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>{collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button></div><div className="workspace-switcher"><span className="workspace-logo">S</span><span><strong>Northstar SOC</strong><small>Workspace / primary</small></span><ChevronRight size={14} /></div><div className="side-nav-label">Monitor</div><nav className="side-nav" aria-label="Workspace navigation">{sideItems.map(({ key, label, icon: Icon, count, badge }) => <button key={key} className={`side-link ${activeView === key ? 'active' : ''}`} onClick={() => onNavigate(key)}><Icon size={17} /><span>{label}</span>{count && <b className="nav-count">{count}</b>}{badge && <b className="nav-badge">{badge}</b>}</button>)}</nav><div className="side-nav-label lower">Manage</div><nav className="side-nav"><button className="side-link"><FileText size={17} /><span>Casebook</span></button><button className="side-link"><Radio size={17} /><span>Integrations</span></button><button className="side-link"><Settings2 size={17} /><span>Settings</span></button></nav><div className="sidebar-spacer" /><div className="analyst-card"><span className="analyst-avatar large">AM</span><span><strong>Alex Morgan</strong><small>Senior analyst</small></span><span className="online-dot" /></div><div className="sidebar-footer"><Cpu size={14} /><span>Sentroxis v0.1.0</span></div></aside>
}

export default function App() {
  const [activeView, setActiveView] = useState('setup')
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [selectedAlert, setSelectedAlert] = useState(null)
  const navigate = (view) => { setActiveView(view); setMobileOpen(false) }
  const page = activeView === 'setup' ? <Setup /> : activeView === 'wazuh' ? <Wazuh onSelectAlert={(alert) => { setSelectedAlert(alert); navigate('ai') }} /> : activeView === 'velociraptor' ? <Velociraptor /> : activeView === 'ai' ? <AIChat selectedAlert={selectedAlert} /> : <Dashboard onNavigate={navigate} onSelectAlert={setSelectedAlert} />
  return <div className={`app-frame ${mobileOpen ? 'mobile-nav-open' : ''}`}><Sidebar activeView={activeView} onNavigate={navigate} collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} /><div className="main-area"><Navbar activeView={activeView} onNavigate={navigate} onMenu={() => setMobileOpen((value) => !value)} />{page}<footer className="page-footer"><span>Sentroxis Copilot</span><span>Read-only demo environment</span><span>All telemetry is untrusted data</span></footer></div>{mobileOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}</div>
}
