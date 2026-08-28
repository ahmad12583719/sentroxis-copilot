import { Bell, LogOut, Menu, Search } from 'lucide-react'

const navItems = [
  { label: 'Wazuh', key: 'wazuh' },
  { label: 'Velociraptor', key: 'velociraptor' },
  { label: 'Endpoints', key: 'agents' },
  { label: 'AI co-pilot', key: 'ai' },
]

export default function Navbar({ activeView, onNavigate, onMenu, user, onLogout }) {
  const initials = user?.name?.slice(0, 2).toUpperCase() || 'AN'
  return <header className="topbar"><button className="mobile-menu icon-button" onClick={onMenu} aria-label="Open navigation menu"><Menu size={19} /></button><button className="brand" onClick={() => onNavigate('wazuh')} aria-label="Go to Wazuh workspace"><span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 40 40" role="img"><path d="M20 3 34 9v10c0 9.4-5.6 15.5-14 18C11.6 34.5 6 28.4 6 19V9l14-6Z" fill="none" stroke="currentColor" strokeWidth="2.2" /><path d="m13 20 4.1 4.1L27.5 14" fill="none" stroke="currentColor" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round" /></svg></span><span className="brand-copy"><strong>sentroxis</strong><small>security operations</small></span></button><nav className="topnav" aria-label="Primary navigation">{navItems.map((item) => <button key={item.key} className={activeView === item.key ? 'nav-link active' : 'nav-link'} onClick={() => onNavigate(item.key)}>{item.label}</button>)}</nav><div className="top-actions"><span className="environment-pill"><i /> <span>Authenticated</span></span><button className="icon-button" aria-label="Search alerts"><Search size={17} /></button><button className="icon-button notification" aria-label="View notifications"><Bell size={17} /></button><span className="analyst-avatar" aria-label={`Signed in as ${user?.name || 'analyst'}`}>{initials}</span><button className="icon-button" onClick={onLogout} aria-label="Sign out"><LogOut size={16} /></button></div></header>
}
