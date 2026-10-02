import React, { useState, useEffect, useRef } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { 
  Wifi, Shield, Smartphone, Key, Download, CheckCircle2, 
  AlertCircle, RefreshCw, Apple, Globe, CreditCard, Phone, 
  HelpCircle, ExternalLink, ArrowRight, Copy, Check, Lock, Sparkles, QrCode, Printer,
  X, CheckCircle, Info, Monitor, Cpu, Laptop, ShieldCheck, BadgeCheck
} from 'lucide-react';
import { fetchJson, apiRequest } from '../utils/api';

export default function PortalView() {
  const [config, setConfig] = useState(null);
  const [plans, setPlans] = useState([]);
  const [activeTab, setActiveTab] = useState('plans'); // 'plans', 'qr', 'enroll', 'setup', 'help'
  
  // Auth & Session State
  const [authSession, setAuthSession] = useState(() => {
    try {
      const saved = localStorage.getItem('rajlabs_wifi_auth');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [loggingIn, setLoggingIn] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [creatingGuest, setCreatingGuest] = useState(false);
  const [guestCreatedNotice, setGuestCreatedNotice] = useState(false);

  // Enrollment State
  const [enrollForm, setEnrollForm] = useState({ username: '', password: '', cert_password: '' });
  const [enrolling, setEnrolling] = useState(false);
  const [enrollResult, setEnrollResult] = useState(null);
  const [enrollError, setEnrollError] = useState('');
  
  // UPI Payment State
  const [copiedPass, setCopiedPass] = useState(false);
  const [copiedQrString, setCopiedQrString] = useState(false);
  const [copiedUpi, setCopiedUpi] = useState(false);
  const [selectedPlanForUpi, setSelectedPlanForUpi] = useState(null);
  const [payerUsername, setPayerUsername] = useState('');
  const [utrRef, setUtrRef] = useState('');
  const [verifyingPayment, setVerifyingPayment] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState(null);
  const [osTab, setOsTab] = useState('android'); // 'android', 'ios', 'windows', 'linux'
  const [caInfo, setCaInfo] = useState(null);
  const [downloading, setDownloading] = useState('');

  useEffect(() => {
    fetchJson('public-config').then(setConfig).catch(() => {});
    fetchJson('plans').then(setPlans).catch(() => {});
    // Public CA fingerprint (no auth) — shown so users verify before trusting.
    fetchJson('public/ca-info').catch(() => fetchJson('certs/ca/info').catch(() => null)).then(setCaInfo).catch(() => {});
    // Allow admins/APs to deep-link a rejected user straight into the
    // login test: https://wifi.rajlabs.in/radius/portal?user=guest-9185
    try {
      const u = new URLSearchParams(window.location.search).get('user');
      if (u) {
        setLoginForm(prev => ({ ...prev, username: u }));
        setPayerUsername(u);
        setEnrollForm(prev => ({ ...prev, username: prev.username || u }));
      }
    } catch {}
  }, []);

  // Sync authSession to enrollForm or payerUsername
  useEffect(() => {
    if (authSession?.username) {
      setPayerUsername(authSession.username);
      setEnrollForm(prev => ({ ...prev, username: authSession.username }));
    }
  }, [authSession]);

  const saveAuthSession = (session) => {
    setAuthSession(session);
    try {
      localStorage.setItem('rajlabs_wifi_auth', JSON.stringify(session));
    } catch {}
  };

  const handleLogout = () => {
    setAuthSession(null);
    setPayerUsername('');
    try {
      localStorage.removeItem('rajlabs_wifi_auth');
    } catch {}
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginError('');
    setLoggingIn(true);
    try {
      const res = await fetchJson('portal/login', {
        method: 'POST',
        body: JSON.stringify(loginForm)
      });
      const session = {
        username: res.username,
        group: res.group,
        is_guest: res.is_guest,
        loginAt: Date.now()
      };
      saveAuthSession(session);
      setLoginForm({ username: '', password: '' });
    } catch (err) {
      setLoginError(err.message || 'Invalid username or password. Please try again.');
    } finally {
      setLoggingIn(false);
    }
  };

  const handleCreateGuestPass = async () => {
    setLoginError('');
    setCreatingGuest(true);
    try {
      const res = await fetchJson('portal/create-guest-pass', {
        method: 'POST'
      });
      const session = {
        username: res.username,
        password: res.password,
        group: 'guests',
        is_guest: true,
        validity_days: 1,
        expires_at_epoch_ms: res.expires_at_epoch_ms || (Date.now() + 86400000),
        created_at: Date.now()
      };
      saveAuthSession(session);
      setGuestCreatedNotice(true);
      setTimeout(() => setGuestCreatedNotice(false), 5000);
    } catch (err) {
      setLoginError(err.message || 'Failed to generate guest pass.');
    } finally {
      setCreatingGuest(false);
    }
  };

  const ssid = config?.wifi_ssid || 'RajLabs-Enterprise';
  const wifiString = `WIFI:T:WPA;S:${ssid};;`;
  const upiVpa = config?.payment_config?.upi_vpa || 'wifi@rajlabs';
  const upiMerchant = config?.payment_config?.merchant_name || 'RajLabs Enterprise WiFi';

  // Group-restricted plans (e.g. VIP-only) are hidden from other groups.
  const myGroup = (authSession?.group || '').toLowerCase();
  const visiblePlans = plans.filter(p => {
    const allowed = p.allowed_groups || [];
    if (!allowed.length) return true;
    return myGroup && allowed.some(g => String(g).toLowerCase() === myGroup);
  });
  const hiddenPlanCount = plans.length - visiblePlans.length;

  const handleEnroll = async (e) => {
    e.preventDefault();
    setEnrollError('');
    setEnrollResult(null);
    setEnrolling(true);
    try {
      const res = await fetchJson('portal/enroll-certificate', {
        method: 'POST',
        body: JSON.stringify(enrollForm)
      });
      setEnrollResult(res);
    } catch (err) {
      setEnrollError(err.message || 'Enrollment failed. Please verify your credentials.');
    } finally {
      setEnrolling(false);
    }
  };

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text);
    setCopiedPass(true);
    setTimeout(() => setCopiedPass(false), 2000);
  };

  const handleCopyQr = () => {
    navigator.clipboard.writeText(wifiString);
    setCopiedQrString(true);
    setTimeout(() => setCopiedQrString(false), 2000);
  };

  const handleCopyUpi = (upiId) => {
    navigator.clipboard.writeText(upiId);
    setCopiedUpi(true);
    setTimeout(() => setCopiedUpi(false), 2000);
  };

  // POST-based blob download: keeps the account password in the request
  // body (never in the URL / browser history / proxy logs).
  const downloadBlob = async (kind) => {
    if (!enrollForm.username || !enrollForm.password) return;
    setDownloading(kind);
    try {
      const endpoint = kind === 'p12' ? 'portal/download-cert' : 'portal/download-mobileconfig';
      const res = await apiRequest(endpoint, {
        method: 'POST',
        body: JSON.stringify({ username: enrollForm.username, password: enrollForm.password })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || data.message || `Download failed (HTTP ${res.status})`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = kind === 'p12'
        ? `RajLabs_${enrollForm.username}_Certificate.p12`
        : `RajLabs_${enrollForm.username}_WiFi.mobileconfig`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setEnrollError(err.message || 'Download failed.');
    } finally {
      setDownloading('');
    }
  };

  // Manual-review UTR handoff (NOT an auto-activation): there is no
  // portal claim API — the IMAP reconciliation engine or an admin activates
  // separately. The copy below must never imply otherwise (#35).
  const handleVerifyUtr = (e) => {
    e.preventDefault();
    if (!utrRef.trim()) return;
    setVerifyingPayment(true);
    setPaymentStatus(null);
    setTimeout(() => {
      setVerifyingPayment(false);
      const who = payerUsername || authSession?.username || 'Guest';
      const inv = selectedPlanForUpi ? getUpiNote(selectedPlanForUpi, who) : '';
      setPaymentStatus({
        status: 'manual-review',
        message: `UTR #${utrRef.trim()} noted on this device for '${who}'${inv ? ` (invoice ${inv})` : ''} — this does NOT auto-activate. WhatsApp your payment screenshot with your username to the support desk for manual activation.`
      });
    }, 600);
  };

  // Machine-readable payment note for automated reconciliation.
  // Format WIFI:<username>:<invoice>:<plan_id> — the invoice (date + random)
  // ties the bank alert to one payment intent; the email/IMAP recon engine
  // parses username + invoice + plan out of it. Memoized per plan+user so the
  // QR, the guide text and the UTR claim below all show the SAME invoice.
  // useRef (not state): values are stable across renders, no re-render needed.
  const invoiceCache = useRef({});
  const getInvoice = (planId, user = '') => {
    const key = `${user}|${planId}`;
    if (!invoiceCache.current[key]) {
      const d = new Date();
      const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
      const rand = Math.random().toString(36).slice(2, 6).toUpperCase().replace(/[^A-Z0-9]/g, 'X');
      invoiceCache.current[key] = `${stamp}-${rand}`;
    }
    return invoiceCache.current[key];
  };

  const getUpiNote = (plan, user = '') => {
    const u = String(user || '').trim().replace(/\s+/g, '');
    return `WIFI:${u}:${getInvoice(plan.id, u)}:${plan.id}`;
  };

  const getUpiUrl = (plan, user = '') => {
    const amount = Number(plan.price).toFixed(2);
    const params = new URLSearchParams({
      pa: upiVpa,
      pn: upiMerchant,
      mc: '0000',
      mode: '02',
      purpose: '00',
      am: amount,
      cu: 'INR',
      tn: getUpiNote(plan, user)
    });
    return `upi://pay?${params.toString()}`;
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between relative overflow-hidden">
      {/* Glow Effects */}
      <div className="absolute -top-40 -left-40 w-96 h-96 bg-indigo-600/15 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute top-1/2 -right-40 w-96 h-96 bg-violet-600/15 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-tr from-indigo-600 to-violet-600 rounded-xl text-white shadow-md shadow-indigo-500/20">
              <Wifi className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-extrabold text-white text-base tracking-tight">RajLabs Wi-Fi Onboarding</h1>
              <p className="text-[11px] text-slate-400">Enterprise WPA2/WPA3-Enterprise & EAP-TLS Portal</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {authSession ? (
              <div className="flex items-center gap-2 bg-slate-800/90 border border-slate-700 py-1 px-2.5 rounded-xl text-xs">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="font-mono font-bold text-slate-200">{authSession.username}</span>
                <button
                  onClick={handleLogout}
                  className="text-slate-400 hover:text-rose-400 ml-1.5 transition text-[11px] font-semibold cursor-pointer"
                  title="Sign out"
                >
                  Sign Out
                </button>
              </div>
            ) : null}
            <a
              href="/radius"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-medium border border-slate-700 transition"
            >
              <Shield className="w-3.5 h-3.5 text-indigo-400" />
              <span>Admin Console</span>
            </a>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-4xl mx-auto px-4 py-8 w-full z-10 flex-1 flex flex-col justify-center">
        {/* Navigation Tabs */}
        <div className="flex bg-slate-900/90 p-1.5 rounded-2xl border border-slate-800 max-w-2xl mx-auto mb-8 shadow-xl overflow-x-auto">
          <button
            onClick={() => setActiveTab('plans')}
            className={`flex-1 min-w-[110px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'plans' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <CreditCard className="w-3.5 h-3.5" />
            <span>Pay & Plans</span>
          </button>
          <button
            onClick={() => setActiveTab('qr')}
            className={`flex-1 min-w-[100px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'qr' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <QrCode className="w-3.5 h-3.5" />
            <span>Wi-Fi QR</span>
          </button>
          <button
            onClick={() => setActiveTab('enroll')}
            className={`flex-1 min-w-[110px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'enroll' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Certificates</span>
          </button>
          <button
            onClick={() => setActiveTab('setup')}
            className={`flex-1 min-w-[110px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'setup' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Download className="w-3.5 h-3.5" />
            <span>Root CA</span>
          </button>
          <button
            onClick={() => setActiveTab('help')}
            className={`flex-1 min-w-[90px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'help' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Phone className="w-3.5 h-3.5" />
            <span>Support</span>
          </button>
        </div>

        {/* Tab: Plans & Pricing + Sign-in / Guest Gating */}
        {activeTab === 'plans' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-3xl mx-auto w-full space-y-6 animate-fade-in">
            
            {/* If NOT Signed in, show Auth / Guest Gate first */}
            {!authSession ? (
              <div className="space-y-6">
                <div className="text-center max-w-md mx-auto">
                  <div className="inline-flex p-3 bg-indigo-500/10 text-indigo-400 rounded-2xl mb-2 border border-indigo-500/20">
                    <Lock className="w-6 h-6" />
                  </div>
                  <h2 className="text-xl font-bold text-white">Sign In or Generate Guest Pass</h2>
                  <p className="text-xs text-slate-400 mt-1">
                    To recharge with UPI, please authenticate with your account or claim an instant 1-day guest pass so payment is bound to your user identity.
                  </p>
                </div>

                {loginError && (
                  <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-300 text-xs flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
                    <span>{loginError}</span>
                  </div>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Option 1: Existing Member Sign In */}
                  <form onSubmit={handleLogin} className="bg-slate-950 p-5 rounded-2xl border border-slate-800 flex flex-col justify-between space-y-4">
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-indigo-400 font-bold text-xs uppercase tracking-wider">
                        <Key className="w-4 h-4" />
                        <span>Existing User Sign-In</span>
                      </div>
                      <p className="text-[11px] text-slate-400">
                        Sign in with your assigned username to buy any plan (1 Day, 7 Days, 30 Days).
                      </p>
                      <div className="space-y-2">
                        <input
                          type="text"
                          required
                          placeholder="Username (e.g. john)"
                          value={loginForm.username}
                          onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                          className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                        />
                        <input
                          type="password"
                          required
                          placeholder="Password"
                          value={loginForm.password}
                          onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                          className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                        />
                      </div>
                    </div>

                    <button
                      type="submit"
                      disabled={loggingIn}
                      className="w-full py-2.5 px-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition cursor-pointer disabled:opacity-50"
                    >
                      {loggingIn ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />}
                      <span>{loggingIn ? 'Signing In...' : 'Sign In & View Plans'}</span>
                    </button>
                  </form>

                  {/* Option 2: Instant 1-Day Guest Pass */}
                  <div className="bg-slate-950 p-5 rounded-2xl border border-slate-800 flex flex-col justify-between space-y-4">
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-emerald-400 font-bold text-xs uppercase tracking-wider">
                        <Sparkles className="w-4 h-4" />
                        <span>Instant Guest Pass</span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        Don't have an account? Automatically generate a unique Guest ID & Password (saved to this device) to unlock 1-day pass recharge.
                      </p>
                      <div className="p-3 bg-emerald-500/5 rounded-xl border border-emerald-500/20 text-[11px] text-emerald-300">
                        ✨ Instant setup • Valid for 1 Day Daily Pass • Auto-saved in browser
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={handleCreateGuestPass}
                      disabled={creatingGuest}
                      className="w-full py-2.5 px-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 shadow-md shadow-emerald-600/20 transition cursor-pointer disabled:opacity-50"
                    >
                      {creatingGuest ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                      <span>{creatingGuest ? 'Generating Pass...' : 'Generate 1-Day Guest Pass'}</span>
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              /* Signed In / Guest View: Show Active User Badge and Filtered Plans */
              <div className="space-y-6">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-4 bg-slate-950 rounded-2xl border border-slate-800">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/20">
                      <ShieldCheck className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm">{authSession.username}</span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase ${authSession.is_guest ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'}`}>
                          {authSession.is_guest ? 'Guest Pass (Max 1 Day)' : `Active Member (${authSession.group || 'Users'})`}
                        </span>
                      </div>
                      {authSession.password ? (
                        <p className="text-xs text-slate-400 mt-0.5">
                          Password: <code className="text-amber-300 font-mono font-bold">{authSession.password}</code> (Saved in your browser)
                        </p>
                      ) : (
                        <p className="text-xs text-slate-400 mt-0.5">Signed in session verified.</p>
                      )}
                    </div>
                  </div>

                  <button
                    onClick={handleLogout}
                    className="text-xs text-slate-400 hover:text-slate-200 border border-slate-800 bg-slate-900 px-3 py-1.5 rounded-xl cursor-pointer"
                  >
                    Switch User / Log Out
                  </button>
                </div>

                {guestCreatedNotice && (
                  <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-300 text-xs flex items-center gap-2 animate-fade-in">
                    <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>Guest account created and saved! Select a 1-day pass below to pay with UPI.</span>
                  </div>
                )}

                <div className="text-center max-w-md mx-auto">
                  <h3 className="text-lg font-bold text-white">Available Wi-Fi Subscription Plans</h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {authSession.is_guest
                      ? 'Guest accounts are eligible for 1-Day daily passes only. Sign in with a permanent account to unlock multi-day passes.'
                      : 'Choose your desired recharge tier to generate an instant UPI payment QR code.'}
                  </p>
                  {hiddenPlanCount > 0 && (
                    <p className="text-[11px] text-purple-300/80 mt-1">
                      {hiddenPlanCount} members-only plan{hiddenPlanCount > 1 ? 's' : ''} hidden for your group.
                    </p>
                  )}
                </div>

                {visiblePlans.length === 0 ? (
                  <div className="text-center py-10 border border-dashed border-slate-800 rounded-2xl text-slate-400 text-xs">
                    No plans available for your account. Contact support for details.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {visiblePlans.map((p) => {
                      const currSymbol = p.currency === 'INR' ? '₹' : p.currency === 'USD' ? '$' : p.currency + ' ';
                      const isGuestDisabled = authSession.is_guest && p.validity_days > 1;
                      const isPopular = p.validity_days === 30 || p.name.toLowerCase().includes('monthly');
                      
                      return (
                        <div
                          key={p.id}
                          className={`bg-slate-950/80 border rounded-2xl p-5 flex flex-col justify-between transition group relative ${
                            isGuestDisabled ? 'opacity-45 border-slate-800/50' : isPopular ? 'border-emerald-500/60 shadow-lg shadow-emerald-500/10' : 'border-slate-800 hover:border-indigo-500/50'
                          }`}
                        >
                          {isPopular && !isGuestDisabled && (
                            <span className="absolute -top-2.5 right-4 bg-gradient-to-r from-emerald-600 to-teal-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full shadow">
                              BEST VALUE
                            </span>
                          )}
                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-bold uppercase tracking-wider text-emerald-400 font-mono">
                                {p.validity_days} {p.validity_days === 1 ? 'Day' : 'Days'}
                              </span>
                              <span className="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">
                                {p.max_session_seconds ? `${Math.round(p.max_session_seconds / 3600)}h session` : 'Unlimited'}
                              </span>
                            </div>
                            <div>
                              <h3 className="font-bold text-white text-base">{p.name}</h3>
                              <div className="text-2xl font-extrabold text-white mt-1">
                                {currSymbol}{p.price}
                                <span className="text-xs font-normal text-slate-400 ml-1">/ {p.validity_days}d</span>
                              </div>
                            </div>
                            {p.description && (
                              <p className="text-xs text-slate-400 leading-relaxed border-t border-slate-900 pt-2">
                                {p.description}
                              </p>
                            )}
                          </div>

                          <div className="pt-4 mt-4 border-t border-slate-800/80">
                            {isGuestDisabled ? (
                              <button
                                disabled
                                className="w-full py-2.5 px-3 bg-slate-900 text-slate-500 rounded-xl text-xs font-medium cursor-not-allowed"
                              >
                                Member Account Required (&gt; 1 Day)
                              </button>
                            ) : (
                              <button
                                onClick={() => {
                                  setSelectedPlanForUpi(p);
                                  setPayerUsername(authSession.username);
                                  setPaymentStatus(null);
                                  setUtrRef('');
                                }}
                                className="w-full py-2.5 px-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 shadow-md shadow-emerald-600/20 transition cursor-pointer"
                              >
                                <QrCode className="w-3.5 h-3.5" />
                                <span>Pay with UPI (₹{p.price})</span>
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* UPI Info Bar */}
                <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
                  <div className="flex items-center gap-2.5">
                    <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg">
                      <CreditCard className="w-4 h-4 shrink-0" />
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Direct VPA for all Indian UPI Apps (GPay, PhonePe, Paytm, BHIM):</span>
                      <span className="font-mono font-bold text-emerald-400 text-sm">{upiVpa}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => handleCopyUpi(upiVpa)}
                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold flex items-center gap-1.5 border border-slate-700 transition cursor-pointer shrink-0"
                  >
                    {copiedUpi ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedUpi ? 'Copied VPA' : 'Copy VPA'}</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab: Direct Wi-Fi QR Code */}
        {activeTab === 'qr' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-md mx-auto w-full space-y-5 animate-fade-in">
            <div className="text-center">
              <div className="inline-flex p-3 bg-indigo-500/10 text-indigo-400 rounded-2xl mb-2 border border-indigo-500/20">
                <Wifi className="w-6 h-6" />
              </div>
              <h2 className="text-xl font-bold text-white">Wi-Fi Connection QR</h2>
              <p className="text-xs text-slate-400 mt-1">
                {authSession ? 'Personalized credentials embedded in your connection profile.' : 'Enterprise 802.1X / EAP authentication requires an active account or certificate.'}
              </p>
            </div>

            {/* If user has not enrolled or authenticated yet */}
            {!authSession ? (
              <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-2xl text-left space-y-2.5">
                <div className="flex items-center gap-2 text-amber-300 font-bold text-xs">
                  <Lock className="w-4 h-4 text-amber-400 shrink-0" />
                  <span>Authentication Required</span>
                </div>
                <p className="text-[11px] text-amber-200/90 leading-relaxed">
                  This network is protected with <strong>{config?.wifi_auth_type || 'WPA2/WPA3 Enterprise (802.1X)'}</strong>. A standard Wi-Fi QR code alone without your password or certificate will not grant internet access.
                </p>
                <div className="pt-2 flex flex-col gap-2">
                  <button
                    onClick={() => setActiveTab('plans')}
                    className="w-full py-2 px-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 shadow transition"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Get 1-Day Guest Pass / Sign In</span>
                  </button>
                  <button
                    onClick={() => setActiveTab('enroll')}
                    className="w-full py-2 px-3 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 border border-slate-700 transition"
                  >
                    <Key className="w-3.5 h-3.5" />
                    <span>Generate Device Certificate (EAP-TLS)</span>
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-2xl text-left space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-emerald-300 uppercase tracking-wider">Active User Identity</span>
                  <span className="text-[10px] bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded-full font-bold">{authSession.group}</span>
                </div>
                <div className="font-mono text-xs text-slate-200 space-y-1">
                  <div>Username: <strong className="text-white">{authSession.username}</strong></div>
                  {authSession.password && <div>Password: <strong className="text-amber-300">{authSession.password}</strong></div>}
                </div>
              </div>
            )}

            <div className="text-center">
              <div className="inline-block p-4 bg-white rounded-3xl shadow-xl border-4 border-indigo-500/30">
                <QRCodeSVG
                  value={wifiString}
                  size={190}
                  level="H"
                  includeMargin={false}
                />
              </div>
            </div>

            <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 text-left space-y-2 text-xs font-mono">
              <div className="flex justify-between items-center">
                <span className="text-slate-400 font-sans">SSID:</span>
                <span className="font-bold text-white">{ssid}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400 font-sans">Security:</span>
                <span className="text-indigo-300 font-semibold">{config?.wifi_auth_type || 'WPA2-Enterprise / EAP-TLS'}</span>
              </div>
              {authSession?.username && (
                <div className="flex justify-between items-center border-t border-slate-900 pt-1.5">
                  <span className="text-slate-400 font-sans">Enrolled User:</span>
                  <span className="text-emerald-400 font-bold">{authSession.username}</span>
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3 pt-1">
              <button
                onClick={handleCopyQr}
                className="flex items-center justify-center gap-2 py-2.5 px-3 bg-slate-800 hover:bg-slate-750 text-slate-200 rounded-xl text-xs font-semibold border border-slate-700 transition cursor-pointer"
              >
                {copiedQrString ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                <span>{copiedQrString ? 'Copied' : 'Copy SSID'}</span>
              </button>
              <button
                onClick={() => window.print()}
                className="flex items-center justify-center gap-2 py-2.5 px-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition cursor-pointer"
              >
                <Printer className="w-4 h-4" />
                <span>Print Badge</span>
              </button>
            </div>
          </div>
        )}

        {/* UPI Payment Modal */}
        {selectedPlanForUpi && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto animate-fade-in">
            <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-lg w-full p-6 shadow-2xl relative my-8">
              {/* Close Button */}
              <button
                onClick={() => setSelectedPlanForUpi(null)}
                className="absolute top-4 right-4 p-2 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white rounded-full transition cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>

              <div className="text-center space-y-1 pb-4 border-b border-slate-800">
                <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-400 font-mono">
                  UPI Instant Payment
                </span>
                <h3 className="text-lg font-bold text-white">{selectedPlanForUpi.name}</h3>
                <div className="text-2xl font-extrabold text-emerald-400">
                  ₹{selectedPlanForUpi.price} <span className="text-xs text-slate-400 font-normal">/ {selectedPlanForUpi.validity_days} Days Access</span>
                </div>
              </div>

              {/* Username Input for Note */}
              <div className="py-4 space-y-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                    <span>Recharge Account User</span>
                    <span className="text-emerald-400 font-normal font-mono">Bound to {payerUsername || authSession?.username}</span>
                  </label>
                  <input
                    type="text"
                    disabled
                    value={payerUsername || authSession?.username || ''}
                    className="w-full px-3 py-2 bg-slate-950/80 border border-slate-800 rounded-xl text-xs text-emerald-400 font-bold font-mono opacity-80 cursor-not-allowed"
                  />
                </div>

                {/* QR Code */}
                <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 flex flex-col items-center justify-center space-y-3">
                  <div className="p-3 bg-white rounded-2xl shadow-lg border-2 border-emerald-500/40">
                    <QRCodeSVG
                      value={getUpiUrl(selectedPlanForUpi, payerUsername || authSession?.username)}
                      size={180}
                      level="H"
                      includeMargin={false}
                    />
                  </div>
                  <div className="text-center space-y-0.5">
                    <p className="text-xs font-semibold text-slate-200">Scan using any UPI App</p>
                    <p className="text-[11px] text-slate-400">Google Pay • PhonePe • Paytm • BHIM • Cred</p>
                  </div>
                </div>

                {/* Direct App Button (Mobile only) */}
                <a
                  href={getUpiUrl(selectedPlanForUpi, payerUsername || authSession?.username)}
                  className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/20 transition sm:hidden"
                >
                  <Smartphone className="w-4 h-4" />
                  <span>Open UPI App on Phone (₹{selectedPlanForUpi.price})</span>
                </a>

                {/* Payment Notes & Guide */}
                <div className="p-3 bg-slate-950/70 rounded-xl border border-slate-800 space-y-1.5 text-[11px] text-slate-400">
                  <div className="flex items-center gap-1.5 text-slate-300 font-semibold">
                    <Info className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                    <span>Payment Remark / Note:</span>
                  </div>
                  <ul className="list-disc list-inside space-y-0.5 pl-1 text-[11px] text-slate-400">
                    <li>Payee: <strong className="text-slate-200">{upiMerchant}</strong> (<span className="text-emerald-400 font-mono">{upiVpa}</span>)</li>
                    <li>Remark / Note in UPI (auto-filled, do not change): <strong className="text-emerald-300 font-mono">{getUpiNote(selectedPlanForUpi, payerUsername || authSession?.username)}</strong></li>
                    <li>Keep the 12-digit UTR / Transaction Reference Number handy after payment.</li>
                  </ul>
                </div>

                {/* UTR Manual-Review Handoff */}
                <form onSubmit={handleVerifyUtr} className="space-y-2 pt-1 border-t border-slate-800/80">
                  <label className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider block">
                    Already Paid? Submit UTR for manual review
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="12-digit UPI UTR (e.g. 402918273645)"
                      value={utrRef}
                      onChange={(e) => setUtrRef(e.target.value)}
                      className="flex-1 px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                    />
                    <button
                      type="submit"
                      disabled={verifyingPayment || !utrRef.trim()}
                      className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition cursor-pointer flex items-center gap-1"
                    >
                      {verifyingPayment ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                      <span>Submit</span>
                    </button>
                  </div>
                  <p className="text-[11px] text-slate-500">Submitting notifies nobody automatically — activation is manual (support desk) or via bank-alert reconciliation.</p>
                </form>

                {paymentStatus && (
                  <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-200 text-xs flex items-start gap-2 animate-fade-in">
                    <CheckCircle className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
                    <span>{paymentStatus.message}</span>
                  </div>
                )}
              </div>

              <div className="pt-2 text-center border-t border-slate-800">
                <button
                  onClick={() => setSelectedPlanForUpi(null)}
                  className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
                >
                  Done / Close
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Tab 1: Certificate Enrollment */}
        {activeTab === 'enroll' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-xl mx-auto w-full">
            <div className="text-center mb-6">
              <div className="inline-flex p-3 bg-indigo-500/10 text-indigo-400 rounded-2xl mb-2 border border-indigo-500/20">
                <Shield className="w-6 h-6" />
              </div>
              <h2 className="text-xl font-bold text-white">Enroll Device for EAP-TLS Wi-Fi</h2>
              <p className="text-xs text-slate-400 mt-1">
                Enter your account credentials to generate your encrypted client certificate bundle (.p12) and Apple profile (.mobileconfig).
              </p>
            </div>

            {enrollError && (
              <div className="mb-5 p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
                <span>{enrollError}</span>
              </div>
            )}

            {enrollResult ? (
              <div className="space-y-5 animate-fade-in">
                <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-2xl flex items-start gap-3">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-bold text-emerald-300 text-sm">Certificate Issued Successfully!</h4>
                    <p className="text-xs text-emerald-400/90 mt-0.5">{enrollResult.message}</p>
                  </div>
                </div>

                {/* Password Box */}
                {enrollResult.p12_password && (
                  <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Certificate Bundle Password</span>
                    <div className="flex items-center justify-between">
                      <code className="font-mono text-amber-300 font-bold text-sm tracking-wider">
                        {enrollResult.p12_password}
                      </code>
                      <button
                        onClick={() => handleCopy(enrollResult.p12_password)}
                        className="flex items-center gap-1 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs transition cursor-pointer"
                      >
                        {copiedPass ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedPass ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* Download Actions (POST — password stays out of the URL) */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <button
                    onClick={() => downloadBlob('mobileconfig')}
                    disabled={downloading === 'mobileconfig'}
                    className="flex items-center justify-center gap-2 p-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white rounded-xl text-xs font-semibold shadow transition cursor-pointer disabled:opacity-50"
                  >
                    <Apple className="w-4 h-4 text-slate-200" />
                    <span>{downloading === 'mobileconfig' ? 'Preparing…' : 'Download Apple Profile'}</span>
                  </button>

                  <button
                    onClick={() => downloadBlob('p12')}
                    disabled={downloading === 'p12'}
                    className="flex items-center justify-center gap-2 p-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition cursor-pointer disabled:opacity-50"
                  >
                    <Download className="w-4 h-4" />
                    <span>{downloading === 'p12' ? 'Preparing…' : 'Download .p12 Bundle'}</span>
                  </button>
                </div>
                <p className="text-[11px] text-slate-500 text-center">
                  The .p12 opens with the bundle password above. The Apple profile needs no password — it carries the certificate inside.
                </p>

                <div className="text-center pt-2">
                  <button
                    onClick={() => setEnrollResult(null)}
                    className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
                  >
                    ← Enroll another device
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleEnroll} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Account Username</label>
                  <input
                    type="text"
                    required
                    placeholder="Enter assigned username"
                    value={enrollForm.username}
                    onChange={e => setEnrollForm({ ...enrollForm, username: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Account Password</label>
                  <input
                    type="password"
                    required
                    placeholder="Enter account password"
                    value={enrollForm.password}
                    onChange={e => setEnrollForm({ ...enrollForm, password: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>

                <button
                  type="submit"
                  disabled={enrolling}
                  className="w-full mt-3 py-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-500/25 flex items-center justify-center gap-2 transition disabled:opacity-50 cursor-pointer"
                >
                  {enrolling ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                  <span>{enrolling ? 'Generating EAP-TLS Certificate...' : 'Generate & Download Certificate'}</span>
                </button>
              </form>
            )}
          </div>
        )}

        {/* Tab 2: Root CA & Configuration Profiles */}
        {activeTab === 'setup' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-3xl mx-auto w-full space-y-6 animate-fade-in">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-violet-500/10 text-violet-400 rounded-2xl border border-violet-500/20">
                  <ShieldCheck className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-base">Root CA Certificate & OS Installation</h3>
                  <p className="text-xs text-slate-400">Install and trust the Authority certificate for seamless 802.1X EAP-TLS / PEAP roaming</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className={`px-2.5 py-1 rounded-full text-[11px] font-bold border flex items-center gap-1.5 ${
                  config?.signer_configured
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30'
                }`}>
                  <BadgeCheck className="w-3.5 h-3.5" />
                  <span>{config?.signer_configured ? 'RajLabs-CA PKI Active' : 'FreeRADIUS Local CA Active'}</span>
                </span>
              </div>
            </div>

            {/* What is wifi.rajlabs.in? — mobile-first explainer */}
            <div className="p-5 bg-indigo-500/5 rounded-2xl border border-indigo-500/20 space-y-2">
              <h4 className="font-bold text-indigo-300 text-sm flex items-center gap-2">
                <Globe className="w-4 h-4" /> What is wifi.rajlabs.in?
              </h4>
              <p className="text-xs text-slate-300">
                This is your Wi-Fi home page — open it on your <strong>phone browser</strong> (mobile data or any Wi-Fi) to
                buy a plan, pay via UPI, get your username/password, and set up the <strong>{ssid}</strong> network.
                It is <strong>not</strong> the Wi-Fi network itself: after you register here, you still join <strong>{ssid}</strong> once
                from your phone's Wi-Fi settings below.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                <div className="p-2.5 bg-slate-950 rounded-xl border border-slate-800">
                  <span className="font-bold text-emerald-400">Easiest (most phones): </span>
                  <span className="text-slate-300">join {ssid} with PEAP + your username/password — no certificates needed.</span>
                </div>
                <div className="p-2.5 bg-slate-950 rounded-xl border border-slate-800">
                  <span className="font-bold text-violet-400">Most secure: </span>
                  <span className="text-slate-300">EAP-TLS with the .p12 certificate from the Enroll tab + the Root CA below.</span>
                </div>
              </div>
            </div>

            {/* Root CA Direct Download Card */}
            <div className="p-5 bg-slate-950 rounded-2xl border border-slate-800 flex flex-col gap-4">
              <div className="space-y-1">
                <h4 className="font-bold text-slate-100 text-sm flex items-center gap-2">
                  <span>Download Root Authority Certificate</span>
                </h4>
                <p className="text-xs text-slate-400">
                  Your phone shows “CA certificate required” because it must verify our server before sending your login
                  (this blocks fake hotspots). Install the CA <strong>once</strong>, then it trusts {ssid} forever.
                  Android needs the <strong>.crt</strong> file — iPhone/Windows/Linux can use either.
                </p>
                {caInfo?.sha256_fingerprint && (
                  <p className="text-[11px] text-slate-500">
                    Verify after install — SHA-256 fingerprint: <code className="text-amber-300 font-mono break-all">{caInfo.sha256_fingerprint}</code>
                    {caInfo?.not_after && <span> · valid until {caInfo.not_after}</span>}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <a
                  href="/radius/api/certs/ca?format=crt"
                  download="RajLabs_Root_CA.crt"
                  className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-500/20 transition whitespace-nowrap cursor-pointer shrink-0"
                >
                  <Smartphone className="w-4 h-4" />
                  <span>Android: Download .crt</span>
                </a>
                <a
                  href="/radius/api/certs/ca?format=pem"
                  download="RajLabs_Root_CA.pem"
                  className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white rounded-xl text-xs font-semibold transition whitespace-nowrap cursor-pointer shrink-0"
                >
                  <Download className="w-4 h-4" />
                  <span>Others: Download .pem</span>
                </a>
              </div>
            </div>

            {/* OS Navigation Tabs */}
            <div className="space-y-3">
              <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs overflow-x-auto">
                <button
                  onClick={() => setOsTab('android')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'android' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Smartphone className="w-3.5 h-3.5" />
                  <span>Android</span>
                </button>
                <button
                  onClick={() => setOsTab('ios')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'ios' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Apple className="w-3.5 h-3.5" />
                  <span>iOS / macOS</span>
                </button>
                <button
                  onClick={() => setOsTab('windows')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'windows' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Monitor className="w-3.5 h-3.5" />
                  <span>Windows 10/11</span>
                </button>
                <button
                  onClick={() => setOsTab('linux')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'linux' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Cpu className="w-3.5 h-3.5" />
                  <span>Linux</span>
                </button>
              </div>

              {/* OS Instruction Contents */}
              <div className="p-4 bg-slate-950/70 rounded-2xl border border-slate-800 text-xs text-slate-300 space-y-3">
                {osTab === 'android' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-emerald-400 text-xs flex items-center gap-1.5">
                      <Smartphone className="w-4 h-4" /> Android 11+ — connect to {ssid} from wifi.rajlabs.in:
                    </h5>
                    <p className="text-[11px] text-slate-400">
                      Why the extra step? Your downloaded .p12 holds <strong>your</strong> identity, but Android keeps
                      Wi-Fi server trust separate — so the Root CA must be installed once under “Wi-Fi certificate”.
                      Without it Android refuses to connect or warns about the network.
                    </p>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Tap <strong>Android: Download .crt</strong> above (if Chrome renamed it, rename back to <code className="text-indigo-300">RajLabs_Root_CA.crt</code>).</li>
                      <li>Open <strong>Settings → Security &amp; privacy → More security settings → Install from device storage → Wi-Fi certificate</strong> (on some phones: Settings → Security → Encryption &amp; credentials → Install a certificate → Wi-Fi certificate).</li>
                      <li>Pick the .crt file, name it <strong className="text-white">RajLabs CA</strong>, tap OK. Match the fingerprint shown above if asked.</li>
                      <li>Go to <strong>Settings → Network &amp; internet → Wi-Fi</strong>, tap <strong>{ssid}</strong>:
                        <ul className="list-disc list-inside pl-4 text-slate-400 text-[11px] mt-1 space-y-0.5">
                          <li><strong>No certificate?</strong> EAP method <strong>PEAP</strong>, Phase-2 <strong>MSCHAPv2</strong>, enter your wifi.rajlabs.in username + password.</li>
                          <li><strong>With .p12?</strong> EAP method <strong>TLS</strong>: tap the downloaded .p12 first, enter its bundle password to install, then pick your user certificate here.</li>
                          <li>CA certificate: select <strong>RajLabs CA</strong> (never “Do not validate”).</li>
                          <li>Domain: <code className="text-indigo-300">{config?.eap?.domain_hint || 'rajlabs.in'}</code> — type it exactly as shown (it must match the server certificate).</li>
                          <li>Anonymous identity / Online status: leave default, then Connect.</li>
                        </ul>
                      </li>
                    </ol>
                  </div>
                )}

                {osTab === 'ios' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-indigo-400 text-xs flex items-center gap-1.5">
                      <Apple className="w-4 h-4" /> Apple iOS, iPadOS & macOS One-Click Profile:
                    </h5>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Generate your certificate in the <strong>Certificates Tab</strong> and download the <strong>.mobileconfig</strong> profile.</li>
                      <li>Open <strong>Settings → Profile Downloaded</strong> (or System Settings → Profiles on macOS).</li>
                      <li>Tap <strong>Install</strong> and authenticate with your device passcode.</li>
                      <li>Your Apple device will automatically trust the Root CA and auto-connect to <strong>{ssid}</strong>!</li>
                    </ol>
                  </div>
                )}

                {osTab === 'windows' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-cyan-400 text-xs flex items-center gap-1.5">
                      <Monitor className="w-4 h-4" /> Windows 10 & 11 Setup Guide:
                    </h5>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Download <code className="text-indigo-300">ca.pem</code> (or rename to <code className="text-indigo-300">ca.crt</code>).</li>
                      <li>Double-click the file and click <strong>Install Certificate → Current User → Place all certificates in the following store</strong>.</li>
                      <li>Browse and select <strong>Trusted Root Certification Authorities</strong>, then click Finish.</li>
                      <li>Double-click your user <code className="text-indigo-300">.p12</code> bundle from Tab 1 to import your client key into the Personal certificate store.</li>
                      <li>Click the Wi-Fi icon, choose <strong>{ssid}</strong> and click Connect.</li>
                    </ol>
                  </div>
                )}

                {osTab === 'linux' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-amber-400 text-xs flex items-center gap-1.5">
                      <Cpu className="w-4 h-4" /> Linux / NetworkManager Setup:
                    </h5>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Download <code className="text-indigo-300">ca.pem</code> to <code className="text-indigo-300">~/.config/wifi/ca.pem</code>.</li>
                      <li>Open NetworkManager or edit <code className="text-indigo-300">/etc/NetworkManager/system-connections/{ssid}.nmconnection</code>:</li>
                      <li>Set <code className="text-indigo-300">key-mgmt=wpa-eap</code>, <code className="text-indigo-300">eap=tls</code>, <code className="text-indigo-300">ca-cert=path/to/ca.pem</code>, <code className="text-indigo-300">client-cert=path/to/user.crt</code>, <code className="text-indigo-300">private-key=path/to/user.key</code>.</li>
                    </ol>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Support & UPI */}
        {activeTab === 'help' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-xl mx-auto w-full space-y-6 animate-fade-in">
            <div className="text-center">
              <div className="inline-flex p-3 bg-emerald-500/10 text-emerald-400 rounded-2xl mb-2 border border-emerald-500/20">
                <Phone className="w-6 h-6" />
              </div>
              <h3 className="font-bold text-white text-base">Network Support & Recharge</h3>
              <p className="text-xs text-slate-400 mt-1">Get immediate assistance or renew Wi-Fi subscription</p>
            </div>

            <div className="p-4 bg-slate-950 rounded-2xl border border-slate-800 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Support Desk:</span>
                <span className="font-semibold text-slate-200">{config?.admin_contact?.name || 'RajLabs Network Operations'}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">WhatsApp / Phone:</span>
                <a
                  href={`tel:${config?.admin_contact?.phone || '+91'}`}
                  className="font-mono text-cyan-400 hover:underline font-bold"
                >
                  {config?.admin_contact?.phone || 'Contact Admin'}
                </a>
              </div>
              <div className="flex items-center justify-between text-xs border-t border-slate-800 pt-3">
                <span className="text-slate-400">UPI Payment VPA:</span>
                <span className="font-mono text-emerald-400 font-bold">{upiVpa}</span>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 py-4 text-center text-xs text-slate-500 bg-slate-950/80">
        <p>© {new Date().getFullYear()} RajLabs FreeRADIUS Enterprise AAA • WPA2/WPA3 EAP-TLS</p>
      </footer>
    </div>
  );
}

