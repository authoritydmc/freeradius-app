import React, { useState } from 'react';
import { 
  ShieldCheck, 
  Activity, 
  Users, 
  KeyRound, 
  Layers, 
  Network, 
  Radio, 
  Smartphone, 
  CheckCircle2, 
  FileText, 
  Sliders, 
  LogOut, 
  Menu, 
  X, 
  Wifi, 
  Download, 
  UserCheck 
} from 'lucide-react';

export default function Navbar({ 
  activeTab, 
  setActiveTab, 
  currentUser, 
  onLogout, 
  health, 
  stats, 
  onOpenPortal 
}) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const navItems = [
    { id: 'status', label: 'Status', icon: Activity },
    { id: 'users', label: 'Users', icon: Users, badge: stats?.total_users },
    { id: 'certs', label: 'EAP-TLS Certs', icon: KeyRound, badge: stats?.client_certificates },
    { id: 'groups', label: 'Policies', icon: Layers },
    { id: 'nas', label: 'NAS Clients', icon: Network },
    { id: 'sessions', label: 'Sessions', icon: Radio, badge: stats?.active_sessions, highlight: stats?.active_sessions > 0 },
    { id: 'devices', label: 'Devices', icon: Smartphone, badge: stats?.known_devices },
    { id: 'tester', label: 'RADIUS Tester', icon: CheckCircle2 },
    { id: 'logs', label: 'Auth Logs', icon: FileText },
    { id: 'settings', label: 'Settings', icon: Sliders, highlightColor: 'text-indigo-400' },
  ];

  return (
    <header className="bg-slate-900/90 backdrop-blur-xl border-b border-slate-800 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          
          {/* Brand Logo & Title */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-indigo-600 via-purple-600 to-cyan-400 flex items-center justify-center text-white shadow-lg shadow-indigo-600/25 shrink-0">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div className="truncate">
              <div className="flex items-center gap-2">
                <span className="text-base font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent truncate">
                  RajLabs FreeRADIUS
                </span>
                <span className="hidden xs:inline-block text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 whitespace-nowrap">
                  Enterprise AAA
                </span>
              </div>
            </div>
          </div>

          {/* Desktop Right Actions & Badges */}
          <div className="flex items-center gap-2 sm:gap-3">
            {/* Live Health Indicator */}
            <div className={`hidden sm:flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold border ${
              health?.status === 'healthy' 
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
            }`}>
              <span className={`w-2 h-2 rounded-full animate-ping ${health?.status === 'healthy' ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span>{health?.status === 'healthy' ? 'RADIUS Online' : 'System Degraded'}</span>
            </div>

            {/* Root CA Public Download */}
            <a 
              href="/radius/api/certs/ca" 
              download 
              title="Download Root CA Certificate"
              className="hidden md:flex text-xs font-semibold items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-950/60 hover:bg-indigo-900/80 text-indigo-300 transition-colors border border-indigo-800/60"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Root CA</span>
            </a>

            {/* Captive Portal Jump */}
            <button
              onClick={onOpenPortal}
              title="Open Wi-Fi Self-Service & Device Setup Portal"
              className="hidden md:flex text-xs font-semibold items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700"
            >
              <Wifi className="w-3.5 h-3.5 text-indigo-400" />
              <span>Portal</span>
            </button>

            {/* Quick Settings Shortcut */}
            <button
              onClick={() => { setActiveTab('settings'); setMobileMenuOpen(false); }}
              title="System Configuration & Cert-Signer API"
              className={`flex text-xs items-center gap-1.5 px-3 py-1.5 rounded-xl transition-all border shadow-sm ${
                activeTab === 'settings'
                  ? 'bg-indigo-600 text-white border-indigo-500 shadow-indigo-600/30'
                  : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700'
              }`}
            >
              <Sliders className="w-3.5 h-3.5 text-indigo-400" />
              <span className="hidden sm:inline font-semibold">Settings</span>
            </button>

            {/* User Profile & Logout */}
            <div className="flex items-center gap-1.5 sm:gap-2 pl-2 border-l border-slate-800">
              <span className="text-xs font-semibold px-2.5 py-1 rounded-xl bg-purple-500/20 text-purple-300 border border-purple-500/30 flex items-center gap-1.5">
                <UserCheck className="w-3.5 h-3.5 text-purple-400" />
                <span className="max-w-[80px] sm:max-w-none truncate">{currentUser}</span>
              </span>
              <button
                onClick={onLogout}
                title="Sign Out"
                className="p-2 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-xl transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>

            {/* Mobile Hamburger Toggle Button */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label="Toggle Navigation Menu"
              className="md:hidden p-2 rounded-xl bg-slate-800 border border-slate-700 text-slate-300 hover:text-white focus:outline-none"
            >
              {mobileMenuOpen ? <X className="w-5 h-5 text-indigo-400" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Drawer Dropdown Menu */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-slate-800 bg-slate-900/98 backdrop-blur-2xl px-4 py-4 space-y-2 shadow-2xl max-h-[85vh] overflow-y-auto">
          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider px-2 pt-1 pb-2 flex items-center justify-between">
            <span>Navigation Menu</span>
            <span className="text-emerald-400 text-[10px] font-normal flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" /> RADIUS Active
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveTab(item.id);
                    setMobileMenuOpen(false);
                  }}
                  className={`p-3 rounded-2xl border text-left flex items-center justify-between transition-all ${
                    isActive
                      ? 'bg-indigo-600/30 border-indigo-500 text-white font-bold shadow-lg shadow-indigo-600/20'
                      : 'bg-slate-950 border-slate-800/80 text-slate-300 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center gap-2.5 truncate">
                    <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-indigo-400' : 'text-slate-400'}`} />
                    <span className="text-xs truncate">{item.label}</span>
                  </div>
                  {item.badge !== undefined && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="pt-3 border-t border-slate-800 flex items-center justify-between text-xs">
            <a
              href="/radius/api/certs/ca"
              download
              className="flex items-center gap-2 text-indigo-400 hover:text-indigo-300 font-semibold p-2"
            >
              <Download className="w-4 h-4" /> Download Root CA
            </a>
            <button
              onClick={() => { onOpenPortal(); setMobileMenuOpen(false); }}
              className="flex items-center gap-2 text-slate-300 hover:text-white p-2 font-semibold"
            >
              <Wifi className="w-4 h-4 text-indigo-400" /> User Portal →
            </button>
          </div>
        </div>
      )}

      {/* Desktop & Smooth Touch Tab Navigation Bar */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 border-t border-slate-800/60 overflow-hidden">
        <nav className="flex space-x-2 sm:space-x-4 overflow-x-auto py-1.5 scrollbar-none" style={{ WebkitOverflowScrolling: 'touch' }}>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`py-2 px-3 border-b-2 font-semibold text-xs sm:text-sm flex items-center gap-2 transition-all whitespace-nowrap rounded-t-xl touch-manipulation ${
                  isActive
                    ? 'border-indigo-500 text-indigo-400 bg-indigo-500/10'
                    : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span>{item.label}</span>
                {item.badge !== undefined && (
                  <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full ${
                    isActive ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-400'
                  }`}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
