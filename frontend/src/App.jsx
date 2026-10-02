import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import StatusTab from './components/StatusTab';
import UsersTab from './components/UsersTab';
import GroupsTab from './components/GroupsTab';
import NasTab from './components/NasTab';
import SessionsTab from './components/SessionsTab';
import DevicesTab from './components/DevicesTab';
import CertsTab from './components/CertsTab';
import PaymentsTab from './components/PaymentsTab';
import TesterTab from './components/TesterTab';
import LogsTab from './components/LogsTab';
import SettingsTab from './components/SettingsTab';
import LoginView from './components/LoginView';
import UserDashboard from './components/UserDashboard';
import PortalView from './components/PortalView';
import CredResultModal from './components/CredResultModal';
import ChangelogModal from './components/ChangelogModal';
import ErrorBoundary from './components/ErrorBoundary';
import { getAuthToken, setAuthToken, removeAuthToken, getUserInfo, setUserInfo, fetchJson } from './utils/api';
import { AlertCircle, CheckCircle2, Info, X, Sparkles, ExternalLink } from 'lucide-react';

export default function App() {
  const [isPortal, setIsPortal] = useState(
    window.location.pathname.includes('/portal') || window.location.hash === '#portal'
  );
  const [currentUser, setCurrentUser] = useState(() => getUserInfo());
  const [authChecking, setAuthChecking] = useState(true);
  const [activeTab, setActiveTab] = useState('status');
  const [credModalData, setCredModalData] = useState(null);
  const [showChangelog, setShowChangelog] = useState(false);
  const [toast, setToast] = useState(null);
  const [health, setHealth] = useState({ status: 'healthy' });
  const [stats, setStats] = useState(null);
  const [signerStatus, setSignerStatus] = useState(null);
  const [publicConfig, setPublicConfig] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type, id: Date.now() });
    setTimeout(() => {
      setToast(current => (current?.message === message ? null : current));
    }, 4500);
  };

  // Background poll: navbar badges only (health + stats). Everything else
  // (signer/status, public-config) is fetched on-demand by the tab that needs
  // it. 60s + hidden-tab guard so idle browsers don't spam the API.
  const loadHealthAndStats = async () => {
    try {
      const [hRes, sRes] = await Promise.allSettled([
        fetchJson('health'),
        fetchJson('stats'),
      ]);
      if (hRes.status === 'fulfilled' && hRes.value) {
        setHealth(hRes.value);
      }
      if (sRes.status === 'fulfilled' && sRes.value) {
        setStats(sRes.value);
      }
    } catch (e) {
      // Ignore background poll errors
    }
  };

  // One-time aux config for tabs that accept it as a prop (Status/Certs fall
  // back to their own on-demand fetch when props are null).
  const loadAuxConfig = async () => {
    try {
      const [sigRes, pRes] = await Promise.allSettled([
        fetchJson('signer/status'),
        fetchJson('public-config')
      ]);
      if (sigRes.status === 'fulfilled' && sigRes.value) {
        setSignerStatus(sigRes.value);
      }
      if (pRes.status === 'fulfilled' && pRes.value) {
        setPublicConfig(pRes.value);
      }
    } catch (e) {
      // Ignore background errors
    }
  };
  const checkAuth = async () => {
    // Admin console: only the admin token counts. User tokens (portal) and
    // garbage values must NOT unlock this console — verified server-side via
    // the admin-only auth/me endpoint (signature + expiry + role + revocation).
    const token = getAuthToken();
    if (!token) {
      setCurrentUser(null);
      setAuthChecking(false);
      return;
    }

    try {
      // Validate session with backend (401 unless a live admin session)
      const me = await fetchJson('auth/me');
      const savedUser = getUserInfo();
      const username = me.username || savedUser?.username || 'Administrator';
      setCurrentUser({ username, role: 'admin', group: savedUser?.group || 'admins' });
      setUserInfo({ username, role: 'admin', group: savedUser?.group || 'admins' });
      loadHealthAndStats();
      loadAuxConfig();
    } catch (err) {
      console.warn('Session verification failed, resetting to login:', err);
      removeAuthToken();
      setCurrentUser(null);
    } finally {
      setAuthChecking(false);
    }
  };

  useEffect(() => {
    if (!isPortal && currentUser) {
      loadHealthAndStats();
      const interval = setInterval(() => {
        if (document.hidden) return;
        loadHealthAndStats();
      }, 60000);
      return () => clearInterval(interval);
    }
  }, [isPortal, currentUser]);

  useEffect(() => {
    const handleLocationChange = () => {
      setIsPortal(window.location.pathname.includes('/portal') || window.location.hash === '#portal');
    };
    window.addEventListener('popstate', handleLocationChange);
    window.addEventListener('hashchange', handleLocationChange);

    if (!isPortal) {
      checkAuth();
    } else {
      setAuthChecking(false);
    }

    return () => {
      window.removeEventListener('popstate', handleLocationChange);
      window.removeEventListener('hashchange', handleLocationChange);
    };
  }, [isPortal]);

  const handleLoginSuccess = (user, token) => {
    setCurrentUser(user);
    setUserInfo(user);
    setAuthChecking(false);
    showToast(`Welcome back, ${user.username}!`, 'success');
  };

  const handleLogout = () => {
    removeAuthToken();
    setCurrentUser(null);
    showToast('Signed out successfully', 'info');
  };

  if (isPortal) {
    return <PortalView />;
  }

  if (authChecking && !currentUser) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-xs font-mono text-slate-400">Verifying session...</span>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return <LoginView onLoginSuccess={handleLoginSuccess} />;
  }

  // Role gate: the admin console (every tab incl. Tester/Payments/Settings) is
  // admin-only (backend enforces the same via authenticate_admin on every
  // management route). Regular users get their own self-service dashboard:
  // subscription status, UPI recharge, own password change, certificates,
  // devices/activity and support — nothing administrative.
  if (currentUser.role && currentUser.role !== 'admin') {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
        <main className="flex-1 max-w-3xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <ErrorBoundary scoped section="UserDashboard" title="My Wi-Fi Account">
            <UserDashboard user={currentUser} onLogout={handleLogout} onNotify={showToast} />
          </ErrorBoundary>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
      {/* Toast Notification */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 animate-fade-in flex items-center gap-2.5 px-4 py-3 rounded-2xl shadow-2xl backdrop-blur-md border text-xs font-medium max-w-sm"
          style={{
            backgroundColor: toast.type === 'error' ? 'rgba(244, 63, 94, 0.15)' :
                             toast.type === 'success' ? 'rgba(16, 185, 129, 0.15)' :
                             toast.type === 'warning' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(99, 102, 241, 0.15)',
            borderColor: toast.type === 'error' ? 'rgba(244, 63, 94, 0.3)' :
                         toast.type === 'success' ? 'rgba(16, 185, 129, 0.3)' :
                         toast.type === 'warning' ? 'rgba(245, 158, 11, 0.3)' : 'rgba(99, 102, 241, 0.3)',
            color: toast.type === 'error' ? '#fda4af' :
                   toast.type === 'success' ? '#6ee7b7' :
                   toast.type === 'warning' ? '#fcd34d' : '#c7d2fe'
          }}
        >
          {toast.type === 'error' ? <AlertCircle className="w-4 h-4 shrink-0" /> :
           toast.type === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> :
           <Info className="w-4 h-4 shrink-0" />}
          <span className="flex-1">{toast.message}</span>
          <button onClick={() => setToast(null)} className="opacity-70 hover:opacity-100">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Top Navbar */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        currentUser={currentUser}
        onLogout={handleLogout}
        health={health}
        stats={stats}
        onOpenChangelog={() => setShowChangelog(true)}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'status' && (
          <ErrorBoundary scoped section="StatusTab" title="System Status Dashboard">
            <StatusTab 
              health={health} 
              stats={stats} 
              signerStatus={signerStatus}
              publicConfig={publicConfig}
              onNotify={showToast} 
              onJumpTab={setActiveTab} 
            />
          </ErrorBoundary>
        )}
        {activeTab === 'users' && (
          <ErrorBoundary scoped section="UsersTab" title="User Management">
            <UsersTab
              onNotify={showToast}
              onShowCredModal={setCredModalData}
            />
          </ErrorBoundary>
        )}
        {activeTab === 'groups' && (
          <ErrorBoundary scoped section="GroupsTab" title="RADIUS Groups & Policies">
            <GroupsTab onNotify={showToast} />
          </ErrorBoundary>
        )}
        {activeTab === 'nas' && (
          <ErrorBoundary scoped section="NasTab" title="NAS Clients & Routers">
            <NasTab onNotify={showToast} />
          </ErrorBoundary>
        )}
        {activeTab === 'sessions' && (
          <ErrorBoundary scoped section="SessionsTab" title="Active Accounting Sessions">
            <SessionsTab onNotify={showToast} />
          </ErrorBoundary>
        )}
        {activeTab === 'devices' && (
          <ErrorBoundary scoped section="DevicesTab" title="Known Client Devices">
            <DevicesTab onNotify={showToast} />
          </ErrorBoundary>
        )}
        {activeTab === 'certs' && (
          <ErrorBoundary scoped section="CertsTab" title="EAP-TLS Certificates">
            <CertsTab 
              signerStatus={signerStatus}
              onNotify={showToast} 
            />
          </ErrorBoundary>
        )}
        {activeTab === 'payments' && (
          <ErrorBoundary scoped section="PaymentsTab" title="Payments & Reconciliation">
            <PaymentsTab 
              onNotify={showToast} 
              onJumpSettings={() => setActiveTab('settings')}
            />
          </ErrorBoundary>
        )}
        {activeTab === 'tester' && (
          <ErrorBoundary scoped section="TesterTab" title="RADIUS Protocol Tester">
            <TesterTab onNotify={showToast} />
          </ErrorBoundary>
        )}
        {activeTab === 'logs' && (
          <ErrorBoundary scoped section="LogsTab" title="Security & Accounting Logs">
            <LogsTab onNotify={showToast} />
          </ErrorBoundary>
        )}
        {activeTab === 'settings' && (
          <ErrorBoundary scoped section="SettingsTab" title="System Settings & Gateways">
            <SettingsTab onNotify={showToast} />
          </ErrorBoundary>
        )}
      </main>

      {/* Enterprise Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950/90 py-4 mt-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-400">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-slate-300">RajLabs FreeRADIUS AAA</span>
            <button
              onClick={() => setShowChangelog(true)}
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/20 font-mono text-[11px] transition"
            >
              <Sparkles className="w-3 h-3 text-indigo-400" />
              <span>v2.5.0 Enterprise</span>
            </button>
            <span className="flex items-center gap-1 text-emerald-400 font-medium text-[11px]">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              AAA Engine Online
            </span>
          </div>

          <div className="flex items-center gap-4 text-[11px]">
            <a href="/radius/portal" className="hover:text-indigo-300 transition">
              Captive Wi-Fi Portal
            </a>
            <span>•</span>
            <button onClick={() => setShowChangelog(true)} className="hover:text-indigo-300 transition">
              Release Notes
            </button>
            <span>•</span>
            <span>© {new Date().getFullYear()} RajLabs Cloud Architecture</span>
          </div>
        </div>
      </footer>

      {/* Credential Result Modal (for newly generated users/vouchers) */}
      <CredResultModal
        data={credModalData}
        onClose={() => setCredModalData(null)}
      />

      {/* Release Changelog Modal */}
      <ChangelogModal
        isOpen={showChangelog}
        onClose={() => setShowChangelog(false)}
      />
    </div>
  );
}
