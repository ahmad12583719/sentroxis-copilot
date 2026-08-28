import { useState } from 'react'
import { Activity, ChevronLeft, ChevronRight, Cpu, LogOut, Sparkles, Users, Waypoints } from 'lucide-react'
import Navbar from './components/Navbar'
import Wazuh from './pages/Wazuh'
import Velociraptor from './pages/Velociraptor'
import Agents from './pages/Agents'
import AIChat from './pages/AIChat'
import Login from './pages/Login'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import './App.css'

const tabItems = [
  { key: 'wazuh', label: 'Wazuh', icon: Activity },
  { key: 'velociraptor', label: 'Velociraptor', icon: Waypoints },
  { key: 'agents', label: 'Endpoints', icon: Users },
  { key: 'ai', label: 'AI co-pilot', icon: Sparkles },
]

function Sidebar({ activeView, onNavigate, collapsed, onToggle, user, onLogout }) {
  return <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}><div className="sidebar-top"><span className="sidebar-kicker">Command center</span><button className="collapse-button" onClick={onToggle} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>{collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button></div><div className="workspace-switcher"><span className="workspace-logo">S</span><span><strong>Sentroxis workspace</strong><small>Authenticated / primary</small></span><ChevronRight size={14} /></div><div className="side-nav-label">Workspace</div><nav className="side-nav" aria-label="Workspace navigation">{tabItems.map(({ key, label, icon: Icon }) => <button key={key} className={`side-link ${activeView === key ? 'active' : ''}`} onClick={() => onNavigate(key)}><Icon size={17} /><span>{label}</span></button>)}</nav><div className="sidebar-spacer" /><div className="analyst-card"><span className="analyst-avatar large">{user?.name?.slice(0, 2).toUpperCase() || 'AN'}</span><span><strong>{user?.name || 'Authenticated analyst'}</strong><small>{user?.role || 'member'}</small></span><span className="online-dot" /></div><button className="sidebar-logout" onClick={onLogout}><LogOut size={14} /> Sign out</button><div className="sidebar-footer"><Cpu size={14} /><span>Sentroxis v0.1.0</span></div></aside>
}

function AuthenticatedApp() {
  const { user, logout } = useAuth()
  const [activeView, setActiveView] = useState('wazuh')
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [selectedAlert, setSelectedAlert] = useState(null)
  const navigate = (view) => { setActiveView(view); setMobileOpen(false) }
  const page = activeView === 'wazuh' ? <Wazuh onSelectAlert={(alert) => { setSelectedAlert(alert); navigate('ai') }} /> : activeView === 'velociraptor' ? <Velociraptor /> : activeView === 'agents' ? <Agents /> : <AIChat selectedAlert={selectedAlert} />
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
