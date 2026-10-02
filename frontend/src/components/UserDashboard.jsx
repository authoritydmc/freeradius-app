import React, { useState, useEffect } from 'react';
import {
  Wifi, CreditCard, Key, ShieldCheck, Download, Apple, Smartphone,
  Activity, RefreshCw, LogOut, Phone, MessageCircle, Eye, EyeOff
} from 'lucide-react';
import { fetchJson, apiRequest, formatDateTime, formatBytes } from '../utils/api';
import CertIssuedModal from './CertIssuedModal';

function Card({ icon: Icon, title, action, children }) {
  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 shadow-xl">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Icon className="w-4 h-4 text-indigo-400" />
          <span>{title}</span>
        </h3>
        {action}
      </div>
      {children}
    </div>
  );
}

export default function UserDashboard({ user, onLogout, onNotify }) {
  const username = user?.username || '';
  const [overview, setOverview] = useState(null);
  const [plans, setPlans] = useState([]);
  const [support, setSupport] = useState(null);
  const [loading, setLoading] = useState(true);

  // Password change
  const [pwForm, setPwForm] = useState({ current_password: '', new_password: '' });
  const [showPw, setShowPw] = useState(false);
  const [pwSaving, setPwSaving] = useState(false);

  // Certificate enroll
  const [enrollPw, setEnrollPw] = useState('');
  const [enrolling, setEnrolling] = useState(false);
  const [enrollResult, setEnrollResult] = useState(null);
  const [certIssued, setCertIssued] = useState(null);
  const [downloading, setDownloading] = useState('');

  const loadAll = async () => {
    try {
      setLoading(true);
      const [ov, pl, cfg] = await Promise.allSettled([
        fetchJson('me/overview'),
        fetchJson('plans').catch(() => []),
        fetchJson('public-config').catch(() => null)
      ]);
      if (ov.status === 'fulfilled') setOverview(ov.value);
      if (pl.status === 'fulfilled') setPlans(Array.isArray(pl.value) ? pl.value : []);
      if (cfg.status === 'fulfilled') setSupport(cfg.value);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load your account', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setPwSaving(true);
    try {
      const res = await fetchJson('me/password', {
        method: 'POST',
        body: JSON.stringify(pwForm)
      });
      onNotify?.(res.message || 'Password updated!', 'success');
      setPwForm({ current_password: '', new_password: '' });
    } catch (err) {
      onNotify?.(err.message || 'Failed to update password', 'error');
    } finally {
      setPwSaving(false);
    }
  };

  const handleEnroll = async (e) => {
    e.preventDefault();
    if (!enrollPw) {
      onNotify?.('Enter your Wi-Fi password to generate a certificate', 'warning');
      return;
    }
    setEnrolling(true);
    setEnrollResult(null);
    try {
      const res = await fetchJson('portal/enroll-certificate', {
        method: 'POST',
        body: JSON.stringify({ username, password: enrollPw })
      });
      setEnrollResult(res);
      // Gated handoff: the bundle password only exists in this response
      setCertIssued({ username, p12_password: res.p12_password, authority: res.authority });
      onNotify?.('Certificate generated! Save the password shown.', 'success');
      loadAll();
    } catch (err) {
      onNotify?.(err.message || 'Certificate enrollment failed', 'error');
    } finally {
      setEnrolling(false);
    }
  };

  const handleDownload = async (kind) => {
    // kind: 'p12' | 'mobileconfig' — owner endpoints accept your user token
    setDownloading(kind);
    try {
      const path = kind === 'p12'
        ? `certs/${encodeURIComponent(username)}/download`
        : `certs/${encodeURIComponent(username)}/mobileconfig`;
      const res = await apiRequest(path);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || data.message || `Download failed (HTTP ${res.status})`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = kind === 'p12' ? `${username}_rajlabs_wifi.p12` : `RajLabs_${username}_WiFi.mobileconfig`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      onNotify?.(kind === 'p12' ? 'Certificate downloaded — import it into your device.' : 'Apple profile downloaded — open it on your iPhone/Mac.', 'success');
    } catch (err) {
      onNotify?.(err.message || 'Download failed', 'error');
    } finally {
      setDownloading('');
    }
  };

  const sub = overview?.active_subscription;
  const usage = overview?.usage || {};
  const totalBytes = (usage.up_bytes || 0) + (usage.down_bytes || 0);
  // Hide group-restricted plans (e.g. VIP-only) from other groups
  const myGroup = (overview?.group || user?.group || '').toLowerCase();
  const visiblePlans = plans.filter(p => {
    const allowed = p.allowed_groups || [];
    if (!allowed.length) return true;
    return myGroup && allowed.some(g => String(g).toLowerCase() === myGroup);
  });

  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/60 p-4 rounded-3xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center font-mono font-bold text-lg text-indigo-300">
            {(username || '?').charAt(0).toUpperCase()}
          </div>
          <div>
            <h2 className="text-base font-bold text-white font-mono">{username}</h2>
            <div className="flex flex-wrap items-center gap-1.5 mt-1">
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                {overview?.group || user?.group || 'member'}
              </span>
              {(overview?.live_sessions?.length || 0) > 0 ? (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                  ● {overview.live_sessions.length} ONLINE
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-slate-800 text-slate-400 border border-slate-700">offline</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadAll} title="Refresh" className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
          <button onClick={onLogout} className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold flex items-center gap-1.5 border border-slate-700">
            <LogOut className="w-3.5 h-3.5" />
            <span>Sign out</span>
          </button>
        </div>
      </div>

      {/* Subscription status */}
      {sub ? (
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl p-4 flex items-center gap-3">
          <Wifi className="w-6 h-6 text-emerald-400 shrink-0" />
          <div className="text-xs">
            <div className="font-bold text-emerald-300 text-sm">{sub.plan_name} — ACTIVE</div>
            <div className="text-emerald-200/70 font-mono mt-0.5">Valid till {formatDateTime(sub.expires_at_epoch_ms || sub.expires_at)}</div>
          </div>
        </div>
      ) : (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4 text-xs text-amber-200">
          <span className="font-bold">No active subscription.</span> Recharge below to restore Wi-Fi access.
        </div>
      )}

      {/* Usage */}
      <Card icon={Activity} title="My usage">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center">
          {[
            { label: 'Sessions', value: String(usage.total_sessions ?? 0) },
            { label: 'Download', value: formatBytes(usage.down_bytes || 0) },
            { label: 'Upload', value: formatBytes(usage.up_bytes || 0) },
            { label: 'Connected', value: `${usage.total_hours ?? 0} hrs` }
          ].map(s => (
            <div key={s.label} className="bg-slate-950 border border-slate-800 rounded-xl py-2.5 px-2">
              <div className="text-sm font-bold text-white font-mono">{s.value}</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-slate-500 font-mono mt-2">Total transfer {formatBytes(totalBytes)} • times in your local timezone</p>
      </Card>

      {/* Recharge / UPI */}
      <Card
        icon={CreditCard}
        title="Recharge with UPI"
        action={<a href="/radius/portal" className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-bold">Open payment portal</a>}
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          {visiblePlans.map(p => (
            <div key={p.id} className="bg-slate-950 border border-slate-800 rounded-xl p-3">
              <div className="text-xs font-bold text-white">{p.name}</div>
              <div className="text-sm font-black text-emerald-400 font-mono mt-1">₹{Number(p.price).toFixed(2)}</div>
              <div className="text-[10px] text-slate-500 font-mono">{p.validity_days} day(s) validity</div>
            </div>
          ))}
          {!visiblePlans.length && <p className="text-[11px] text-slate-500 italic">No plans available for your group right now.</p>}
        </div>
        <p className="text-[11px] text-slate-400 mt-3">
          Pay with Google Pay / PhonePe / Paytm in the portal — keep the auto-filled remark
          (<code className="text-indigo-300 font-mono">WIFI:{username}:planId</code>) untouched so activation is automatic after verification.
        </p>
      </Card>

      {/* Password */}
      <Card icon={Key} title="Change my Wi-Fi password">
        <form onSubmit={handlePasswordChange} className="space-y-3 text-xs max-w-md">
          <div>
            <label className="block text-slate-300 mb-1 font-medium">Current password</label>
            <input
              type="password" required value={pwForm.current_password}
              onChange={e => setPwForm({ ...pwForm, current_password: e.target.value })}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono"
            />
          </div>
          <div>
            <label className="block text-slate-300 mb-1 font-medium">New password <span className="text-slate-500 font-normal">(min 12 chars: Aa 0 $)</span></label>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'} required value={pwForm.new_password}
                onChange={e => setPwForm({ ...pwForm, new_password: e.target.value })}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono pr-10"
              />
              <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-2.5 top-2.5 text-slate-500 hover:text-white">
                {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <button type="submit" disabled={pwSaving} className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold disabled:opacity-50">
            {pwSaving ? 'Updating…' : 'Update password'}
          </button>
        </form>
      </Card>

      {/* Certificates */}
      <Card icon={ShieldCheck} title="Certificates & easy login">
        <div className="text-xs text-slate-300 space-y-3">
          <div className="flex items-center gap-2">
            <span className={`px-2.5 py-1 rounded-xl text-[10px] font-bold border ${overview?.has_certificate ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' : 'bg-slate-800 text-slate-400 border-slate-700'}`}>
              {overview?.has_certificate ? 'Certificate issued' : 'No certificate yet'}
            </span>
          </div>
          {overview?.has_certificate ? (
            <div className="flex flex-wrap gap-2">
              <button onClick={() => handleDownload('p12')} disabled={!!downloading} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold flex items-center gap-1.5 disabled:opacity-50">
                <Download className="w-3.5 h-3.5" />
                <span>{downloading === 'p12' ? 'Preparing…' : 'Download .p12'}</span>
              </button>
              <button onClick={() => handleDownload('mobileconfig')} disabled={!!downloading} className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl font-bold flex items-center gap-1.5 disabled:opacity-50">
                <Apple className="w-3.5 h-3.5" />
                <span>{downloading === 'mobileconfig' ? 'Preparing…' : 'Apple profile'}</span>
              </button>
            </div>
          ) : (
            <form onSubmit={handleEnroll} className="space-y-2.5 max-w-md">
              <p className="text-[11px] text-slate-400">Generate an EAP-TLS certificate for password-less Wi-Fi login. Confirm with your Wi-Fi password:</p>
              <input
                type="password" required placeholder="Your Wi-Fi password" value={enrollPw}
                onChange={e => setEnrollPw(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono"
              />
              <button type="submit" disabled={enrolling} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold disabled:opacity-50">
                {enrolling ? 'Generating…' : 'Generate my certificate'}
              </button>
            </form>
          )}
          {enrollResult && !certIssued && (
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 text-[11px] text-emerald-200">
              Certificate ready — use the download buttons above. Your bundle password was shown once at generation time.
            </div>
          )}
          <p className="text-[11px] text-slate-500">
            You can also sign in with your certificate from the login screen (X.509 Certificate tab) instead of a password.
          </p>
        </div>
      </Card>

      {/* Devices + recent activity */}
      <Card icon={Smartphone} title="My devices & recent activity">
        {!overview ? (
          <p className="text-[11px] text-slate-500 italic">Loading…</p>
        ) : (
          <div className="space-y-2">
            {(overview.seen_devices || []).slice(0, 5).map((d, i) => (
              <div key={`${d.mac}-${i}`} className="flex items-center justify-between gap-2 text-[11px] bg-slate-950 border border-slate-800 rounded-xl px-3 py-2">
                <span className="font-mono text-slate-200">{d.mac}</span>
                <span className="text-slate-500">{d.sessions || 0} session(s){d.last_seen ? ` • ${formatDateTime(d.last_seen)}` : ''}</span>
              </div>
            ))}
            {!(overview.seen_devices || []).length && (
              <p className="text-[11px] text-slate-500 italic">No devices seen yet.</p>
            )}
            {(overview.auth_history || []).slice(0, 5).map((h, i) => (
              <div key={i} className="text-[11px] bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 flex items-center justify-between gap-2">
                <span className={`font-bold ${h.reply === 'Access-Accept' ? 'text-emerald-300' : 'text-rose-300'}`}>{h.reply}</span>
                <span className="font-mono text-slate-500">{h.at ? formatDateTime(h.at) : ''}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Support */}
      <Card icon={Phone} title="Need help?">
        <div className="text-xs text-slate-300 space-y-2">
          <p>Contact {support?.admin_contact?.name || 'your network administrator'} for recharge or login help.</p>
          {support?.admin_contact?.phone && (
            <div className="flex flex-wrap gap-2">
              <a
                href={`https://wa.me/${String(support.admin_contact.phone).replace(/\D/g, '')}?text=${encodeURIComponent(`Hi, I need help with my Wi-Fi account (${username})`)}`}
                target="_blank" rel="noreferrer"
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-bold flex items-center gap-1.5"
              >
                <MessageCircle className="w-3.5 h-3.5" />
                <span>WhatsApp support</span>
              </a>
              <a href={`tel:${support.admin_contact.phone}`} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl font-semibold border border-slate-700">
                {support.admin_contact.phone}
              </a>
            </div>
          )}
        </div>
      </Card>

      {loading && !overview && (
        <p className="text-center text-[11px] text-slate-500 font-mono flex items-center justify-center gap-2">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Loading your account…
        </p>
      )}

      {certIssued && (
        <CertIssuedModal
          data={certIssued}
          onClose={() => setCertIssued(null)}
          onNotify={onNotify}
        />
      )}
    </div>
  );
}
