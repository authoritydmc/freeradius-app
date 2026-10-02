import React, { useState, useEffect } from 'react';
import { 
  Wifi, Shield, Smartphone, Key, Download, CheckCircle2, 
  AlertCircle, RefreshCw, Apple, Globe, CreditCard, Phone, 
  HelpCircle, ExternalLink, ArrowRight, Copy, Check, Lock, Sparkles
} from 'lucide-react';
import { fetchJson, apiRequest } from '../utils/api';

export default function PortalView() {
  const [config, setConfig] = useState(null);
  const [activeTab, setActiveTab] = useState('enroll'); // 'enroll', 'setup', 'voucher', 'help'
  const [enrollForm, setEnrollForm] = useState({ username: '', password: '', cert_password: '' });
  const [enrolling, setEnrolling] = useState(false);
  const [enrollResult, setEnrollResult] = useState(null);
  const [enrollError, setEnrollError] = useState('');
  const [copiedPass, setCopiedPass] = useState(false);

  useEffect(() => {
    fetchJson('public-config').then(setConfig).catch(() => {});
  }, []);

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

          <a
            href="/radius"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-medium border border-slate-700 transition"
          >
            <Shield className="w-3.5 h-3.5 text-indigo-400" />
            <span>Admin Console</span>
          </a>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-4xl mx-auto px-4 py-8 w-full z-10 flex-1 flex flex-col justify-center">
        {/* Navigation Tabs */}
        <div className="flex bg-slate-900/90 p-1.5 rounded-2xl border border-slate-800 max-w-xl mx-auto mb-8 shadow-xl">
          <button
            onClick={() => setActiveTab('enroll')}
            className={`flex-1 py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'enroll' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>1-Click Cert Enroll</span>
          </button>
          <button
            onClick={() => setActiveTab('setup')}
            className={`flex-1 py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'setup' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Download className="w-3.5 h-3.5" />
            <span>Root CA & Profiles</span>
          </button>
          <button
            onClick={() => setActiveTab('help')}
            className={`flex-1 py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'help' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Phone className="w-3.5 h-3.5" />
            <span>Support & Pay</span>
          </button>
        </div>

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
                        className="flex items-center gap-1 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs transition"
                      >
                        {copiedPass ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedPass ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* Download Actions */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <a
                    href={`/radius/api/portal/download-mobileconfig?username=${encodeURIComponent(enrollForm.username)}&password=${encodeURIComponent(enrollForm.password)}`}
                    className="flex items-center justify-center gap-2 p-3 bg-slate-800 hover:bg-slate-750 border border-slate-700 text-white rounded-xl text-xs font-semibold shadow transition"
                  >
                    <Apple className="w-4 h-4 text-slate-200" />
                    <span>Download Apple Profile</span>
                  </a>

                  <a
                    href={`/radius/api/portal/download-cert?username=${encodeURIComponent(enrollForm.username)}&password=${encodeURIComponent(enrollForm.password)}`}
                    className="flex items-center justify-center gap-2 p-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition"
                  >
                    <Download className="w-4 h-4" />
                    <span>Download .p12 Bundle</span>
                  </a>
                </div>

                <div className="text-center pt-2">
                  <button
                    onClick={() => setEnrollResult(null)}
                    className="text-xs text-slate-400 hover:text-slate-200"
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
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-2xl mx-auto w-full space-y-6">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-4">
              <div className="p-2.5 bg-violet-500/10 text-violet-400 rounded-xl border border-violet-500/20">
                <Download className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-white text-base">Root CA Certificate & Network Parameters</h3>
                <p className="text-xs text-slate-400">Install RajLabs CA on your smartphone, tablet, or laptop</p>
              </div>
            </div>

            <div className="p-4 bg-slate-950 rounded-2xl border border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div>
                <h4 className="font-bold text-slate-200 text-sm">RajLabs FreeRADIUS Root CA</h4>
                <p className="text-xs text-slate-400 mt-0.5">Required for trusted EAP-TLS / PEAP / TTLS validation.</p>
              </div>
              <a
                href="/radius/api/certs/ca"
                download="RajLabs_FreeRADIUS_Root_CA.pem"
                className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-violet-500/20 transition whitespace-nowrap"
              >
                <Download className="w-4 h-4" />
                <span>Download ca.pem</span>
              </a>
            </div>

            <div className="space-y-3 text-xs text-slate-300">
              <h4 className="font-bold text-slate-200 uppercase tracking-wider text-[11px]">Setup Instructions by Platform:</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="p-3.5 bg-slate-950/60 rounded-xl border border-slate-800/80">
                  <span className="font-bold text-indigo-300 flex items-center gap-1.5 mb-1">
                    <Apple className="w-3.5 h-3.5" /> iOS / iPadOS / macOS
                  </span>
                  <p className="text-slate-400">Download the <code>.mobileconfig</code> profile from Tab 1. Go to Settings → Profile Downloaded → Install.</p>
                </div>
                <div className="p-3.5 bg-slate-950/60 rounded-xl border border-slate-800/80">
                  <span className="font-bold text-emerald-300 flex items-center gap-1.5 mb-1">
                    <Smartphone className="w-3.5 h-3.5" /> Android 11+
                  </span>
                  <p className="text-slate-400">Download Root CA, go to Settings → Security → Install Certificate → Wi-Fi Certificate, select <code>ca.pem</code>.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Support & UPI */}
        {activeTab === 'help' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-xl mx-auto w-full space-y-6">
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
              {config?.payment_config?.upi_vpa && (
                <div className="flex items-center justify-between text-xs border-t border-slate-800 pt-3">
                  <span className="text-slate-400">UPI Payment VPA:</span>
                  <span className="font-mono text-emerald-400 font-bold">{config.payment_config.upi_vpa}</span>
                </div>
              )}
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
