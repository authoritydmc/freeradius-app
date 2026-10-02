import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import StatusTab from './components/StatusTab';
import UsersTab from './components/UsersTab';
import GroupsTab from './components/GroupsTab';
import NasTab from './components/NasTab';
import SessionsTab from './components/SessionsTab';
import DevicesTab from './components/DevicesTab';
import CertsTab from './components/CertsTab';
import TesterTab from './components/TesterTab';
import LogsTab from './components/LogsTab';
import SettingsTab from './components/SettingsTab';
import LoginView from './components/LoginView';
import PortalView from './components/PortalView';
import CredResultModal from './components/CredResultModal';
import { getAuthToken, setAuthToken, removeAuthToken, fetchJson } from './utils/api';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';

export default function App() {
  const [isPortal, setIsPortal] = useState(
    window.location.pathname.includes('/portal') || window.location.hash === '#portal'
  );
  const [currentUser, setCurrentUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [activeTab, setActiveTab] = useState('status');
  const [credModalData, setCredModalData] = useState(null);
  const [toast, setToast] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type, id: Date.now() });
    setTimeout(() => {
      setToast(current => (current?.message === message ? null : current));
    }, 4500);
  };

  const checkAuth = async () => {
    const token = getAuthToken();
    if (!token) {
      setCurrentUser(null);
      setAuthChecking(false);
      return;
    }

    try {
      // Validate session with backend
      const data = await fetchJson('status');
      // If status succeeds, token is valid admin
      setCurrentUser({ username: 'Admin', role: 'admin' });
    } catch (err) {
      if (err.status === 401) {
        removeAuthToken();
        setCurrentUser(null);
      }
    } finally {
      setAuthChecking(false);
    }
  };

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

  if (authChecking) {
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
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'status' && <StatusTab onNotify={showToast} />}
        {activeTab === 'users' && (
          <UsersTab
            onNotify={showToast}
            onShowCredModal={setCredModalData}
          />
        )}
        {activeTab === 'groups' && <GroupsTab onNotify={showToast} />}
        {activeTab === 'nas' && <NasTab onNotify={showToast} />}
        {activeTab === 'sessions' && <SessionsTab onNotify={showToast} />}
        {activeTab === 'devices' && <DevicesTab onNotify={showToast} />}
        {activeTab === 'certs' && <CertsTab onNotify={showToast} />}
        {activeTab === 'tester' && <TesterTab onNotify={showToast} />}
        {activeTab === 'logs' && <LogsTab onNotify={showToast} />}
        {activeTab === 'settings' && <SettingsTab onNotify={showToast} />}
      </main>

      {/* Credential Result Modal (for newly generated users/vouchers) */}
      <CredResultModal
        data={credModalData}
        onClose={() => setCredModalData(null)}
      />
    </div>
  );
}
