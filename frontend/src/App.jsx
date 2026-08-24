import { useEffect, useState } from 'react'
import { Activity, ChevronLeft, ChevronRight, Cpu, FileText, Home, LogOut, Radio, Server, Settings2, Sparkles, Waypoints } from 'lucide-react'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Wazuh from './pages/Wazuh'
import Velociraptor from './pages/Velociraptor'
import AIChat from './pages/AIChat'
import Setup from './pages/Setup'
import Login from './pages/Login'
import { AuthProvider, authRequest, useAuth } from './auth/AuthProvider'
import './App.css'

const sideItems = [
  { key: 'setup', label: 'Server setup', icon: Server },
  { key: 'dashboard', label: 'Overview', icon: Home },
  { key: 'wazuh', label: 'Wazuh signals', icon: Activity },
  { key: 'velociraptor', label: 'Velociraptor', icon: Waypoints },
  { key: 'ai', label: 'AI co-pilot', icon: Sparkles, badge: 'ADVISORY' },
]

function Sidebar({ activeView, onNavigate, collapsed, onToggle, user, onLogout }) {
  return <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}><div className="sidebar-top"><span className="sidebar-kicker">Command center</span><button className="collapse-button" onClick={onToggle} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>{collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button></div><div className="workspace-switcher"><span className="workspace-logo">S</span><span><strong>Sentroxis workspace</strong><small>Authenticated / primary</small></span><ChevronRight size={14} /></div><div className="side-nav-label">Operate</div><nav className="side-nav" aria-label="Workspace navigation">{sideItems.map(({ key, label, icon: Icon, badge }) => <button key={key} className={`side-link ${activeView === key ? 'active' : ''}`} onClick={() => onNavigate(key)}><Icon size={17} /><span>{label}</span>{badge && <b className="nav-badge">{badge}</b>}</button>)}</nav><div className="side-nav-label lower">Manage</div><nav className="side-nav"><button className="side-link"><FileText size={17} /><span>Casebook</span></button><button className="side-link"><Radio size={17} /><span>Integrations</span></button><button className="side-link"><Settings2 size={17} /><span>Settings</span></button></nav><div className="sidebar-spacer" /><div className="analyst-card"><span className="analyst-avatar large">{user?.name?.slice(0, 2).toUpperCase() || 'AN'}</span><span><strong>{user?.name || 'Authenticated analyst'}</strong><small>{user?.role || 'member'}</small></span><span className="online-dot" /></div><button className="sidebar-logout" onClick={onLogout}><LogOut size={14} /> Sign out</button><div className="sidebar-footer"><Cpu size={14} /><span>Sentroxis v0.1.0</span></div></aside>
}

function AuthenticatedApp() {
  const { user, logout } = useAuth()
  const [activeView, setActiveView] = useState('setup')
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [setupState, setSetupState] = useState(null)
  const navigate = (view) => { setActiveView(view); setMobileOpen(false) }

  useEffect(() => {
    let cancelled = false
    authRequest('/api/setup').then((data) => { if (!cancelled) setSetupState(data) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const refreshSetup = () => authRequest('/api/setup').then(setSetupState).catch(() => {})
  const hasExistingServer = Boolean(setupState?.servers?.some((server) => server.endpoint))
  const page = activeView === 'setup' ? <Setup mode={hasExistingServer ? 'connected' : 'installation'} setupState={setupState} onSetupChanged={refreshSetup} /> : activeView === 'wazuh' ? <Wazuh onSelectAlert={(alert) => { setSelectedAlert(alert); navigate('ai') }} /> : activeView === 'velociraptor' ? <Velociraptor /> : activeView === 'ai' ? <AIChat selectedAlert={selectedAlert} /> : <Dashboard onNavigate={navigate} onSelectAlert={setSelectedAlert} />
  return <div className={`app-frame ${mobileOpen ? 'mobile-nav-open' : ''}`}><Sidebar activeView={activeView} onNavigate={navigate} collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} user={user} onLogout={logout} /><div className="main-area"><Navbar activeView={activeView} onNavigate={navigate} onMenu={() => setMobileOpen((value) => !value)} user={user} onLogout={logout} />{page}<footer className="page-footer"><span>Sentroxis Copilot</span><span>Authenticated workspace</span><span>All telemetry is untrusted data</span></footer></div>{mobileOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}</div>
}

function AuthGate() {
  const { loading, authenticated } = useAuth()
  if (loading) return <main className="auth-loading"><div className="auth-spinner" /><p>Checking secure session…</p></main>
  return authenticated ? <AuthenticatedApp /> : <Login />
}

export default function App() {
  return <AuthProvider><AuthGate /></AuthProvider>
}
