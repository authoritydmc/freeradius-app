import React, { useState, useEffect } from 'react';
import { 
  CreditCard, DollarSign, CheckCircle2, Clock, AlertCircle, RefreshCw, 
  Search, Plus, Mail, Shield, Check, ExternalLink, QrCode, Tag,
  Zap, FileText, ArrowUpRight, Sparkles, Filter, Lock, Eye, Copy
} from 'lucide-react';
import { fetchJson, formatDateTime } from '../utils/api';
import PlansManager from './PlansManager';

export default function PaymentsTab({ onNotify, onJumpSettings }) {
  const [payments, setPayments] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [gatewayFilter, setGatewayFilter] = useState('');
  
  // Plans & Users for quick topup
  const [plans, setPlans] = useState([]);
  const [users, setUsers] = useState([]);

  // Manual Activation Modal
  const [showManualModal, setShowManualModal] = useState(false);
  const [activating, setActivating] = useState(false);
  const [manualForm, setManualForm] = useState({
    username: '',
    plan_id: '',
    validity_days: 30,
    amount: 51.35,
    utr: '',
    note: '',
    gateway: 'MANUAL_ADMIN'
  });

  // Email Scanning State
  const [scanningEmail, setScanningEmail] = useState(false);
  const [scanResult, setScanResult] = useState(null);

  const loadData = async () => {
    try {
      setRefreshing(true);
      const queryParams = new URLSearchParams();
      if (searchQuery) queryParams.set('query', searchQuery);
      if (statusFilter) queryParams.set('status_filter', statusFilter);
      if (gatewayFilter) queryParams.set('gateway_filter', gatewayFilter);

      const [pRes, plRes, uRes] = await Promise.all([
        fetchJson(`payments?${queryParams.toString()}`),
        fetchJson('plans').catch(() => []),
        fetchJson('users').catch(() => [])
      ]);

      setPayments(pRes?.payments || []);
      setMetrics(pRes?.metrics || null);
      setPlans(Array.isArray(plRes) ? plRes : []);
      setUsers(Array.isArray(uRes) ? uRes : (uRes?.users || []));
    } catch (err) {
      onNotify?.(err.message || 'Failed to load payments ledger', 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [statusFilter, gatewayFilter]);

  // Refresh pricing dropdowns after plan CRUD in PlansManager below
  const reloadPlans = async () => {
    try {
      const plRes = await fetchJson('plans').catch(() => []);
      setPlans(Array.isArray(plRes) ? plRes : []);
    } catch {
      // keep existing pricing on failure
    }
  };

  const handleSearch = (e) => {
    e.preventDefault();
    loadData();
  };

  const handleManualActivate = async (e) => {
    e.preventDefault();
    if (!manualForm.username) {
      onNotify?.('Please provide a username', 'warning');
      return;
    }
    setActivating(true);
    try {
      const res = await fetchJson('payments/manual-activate', {
        method: 'POST',
        body: JSON.stringify({
          username: manualForm.username.trim(),
          plan_id: manualForm.plan_id ? parseInt(manualForm.plan_id) : null,
          validity_days: manualForm.validity_days ? parseInt(manualForm.validity_days) : 30,
          amount: parseFloat(manualForm.amount || 0),
          utr: manualForm.utr?.trim() || null,
          note: manualForm.note?.trim() || null,
          gateway: manualForm.gateway || 'MANUAL_ADMIN'
        })
      });
      onNotify?.(res.message || `Plan successfully activated for '${manualForm.username}'!`, 'success');
      if (res.group_warning) {
        onNotify?.(res.group_warning, 'warning');
      }
      setShowManualModal(false);
      setManualForm({
        username: '',
        plan_id: '',
        validity_days: 30,
        amount: 51.35,
        utr: '',
        note: '',
        gateway: 'MANUAL_ADMIN'
      });
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Manual activation failed', 'error');
    } finally {
      setActivating(false);
    }
  };

  const handleScanEmails = async () => {
    setScanningEmail(true);
    setScanResult(null);
    try {
      const res = await fetchJson('payments/email/scan', {
        method: 'POST',
        body: JSON.stringify({
          folder: 'INBOX',
          limit: 30,
          auto_activate: true
        })
      });
      setScanResult(res);
      const autoCount = res?.auto_processed?.length || 0;
      if (autoCount > 0) {
        onNotify?.(`Bank alert scan complete! Auto-activated ${autoCount} UPI payment(s)!`, 'success');
      } else {
        onNotify?.(`Mailbox scanned: ${res?.scan_summary?.scanned_count || 0} emails inspected.`, 'info');
      }
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to scan mailbox. Check IMAP settings.', 'error');
    } finally {
      setScanningEmail(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      
      {/* Top Header & Fast Actions */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-5 rounded-3xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-emerald-500/10 text-emerald-400 rounded-2xl border border-emerald-500/20">
            <CreditCard className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <span>Payments & Automated Reconciliation</span>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                UPI / PG / IMAP
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Live transaction ledger, note-based UPI capture, and Indian Payment Gateway integration
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={handleScanEmails}
            disabled={scanningEmail}
            className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-semibold flex items-center gap-2 shadow-sm transition disabled:opacity-50"
          >
            <Mail className={`w-3.5 h-3.5 text-blue-400 ${scanningEmail ? 'animate-bounce' : ''}`} />
            <span>{scanningEmail ? 'Scanning IMAP...' : 'Scan Bank Emails'}</span>
          </button>

          <button
            onClick={() => setShowManualModal(true)}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-bold flex items-center gap-2 shadow-md shadow-emerald-600/20 transition"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>1-Click Top-Up / UTR</span>
          </button>

          <button
            onClick={loadData}
            disabled={refreshing}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs transition"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* KPI Metrics Snapshot */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>Total Collected Revenue</span>
            <DollarSign className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-black text-white mt-2 font-mono">
            ₹{metrics?.total_revenue?.toLocaleString('en-IN', { minimumFractionDigits: 2 }) || '0.00'}
          </div>
          <div className="text-[11px] text-emerald-400 mt-1 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />
            <span>{metrics?.successful_count || 0} Successful Transactions</span>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>Pending / Unclaimed UPI</span>
            <Clock className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-black text-amber-400 mt-2 font-mono">
            {metrics?.pending_count || 0}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            Awaiting UTR or Note Confirmation
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>Automated Recon Channels</span>
            <Zap className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-sm font-bold text-slate-200 mt-2 flex flex-wrap gap-1.5">
            <span className="px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-[10px]">UPI QR</span>
            <span className="px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-300 border border-blue-500/20 text-[10px]">Gmail IMAP</span>
            <span className="px-2 py-0.5 rounded-md bg-purple-500/10 text-purple-300 border border-purple-500/20 text-[10px]">Razorpay</span>
            <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 text-[10px]">Cashfree</span>
          </div>
          <div className="text-[11px] text-slate-500 mt-2 font-mono">
            Configurable in Settings
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>Reconciliation Engine</span>
            <Sparkles className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-sm font-bold text-emerald-400 mt-2 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Active & Syncing</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            Format: <code className="text-indigo-300">wifi:&lt;username&gt;</code>
          </div>
        </div>
      </div>

      {/* Wi-Fi Subscription Plans (what customers buy) */}
      <PlansManager onNotify={onNotify} onPlansChanged={reloadPlans} />

      {/* Filter and Search Bar */}
      <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-2xl flex flex-wrap items-center justify-between gap-3">
        <form onSubmit={handleSearch} className="flex items-center gap-2 flex-1 min-w-[240px]">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search by Username, UTR, Payment ID, or Bank Note..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-4 py-2 text-xs text-white focus:border-emerald-500 outline-none font-mono"
            />
          </div>
          <button
            type="submit"
            className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold"
          >
            Search
          </button>
        </form>

        <div className="flex items-center gap-2 text-xs">
          <select
            value={gatewayFilter}
            onChange={(e) => setGatewayFilter(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-300 focus:border-emerald-500 outline-none"
          >
            <option value="">All Gateways</option>
            <option value="UPI_QR">UPI QR / Intent</option>
            <option value="EMAIL_IMAP">Gmail / IMAP Auto</option>
            <option value="RAZORPAY">Razorpay</option>
            <option value="CASHFREE">Cashfree</option>
            <option value="MANUAL_ADMIN">Manual Admin</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-300 focus:border-emerald-500 outline-none"
          >
            <option value="">All Statuses</option>
            <option value="SUCCESS">Successful</option>
            <option value="PENDING">Pending</option>
            <option value="FAILED">Failed</option>
          </select>
        </div>
      </div>

      {/* Transactions Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
            <FileText className="w-4 h-4 text-emerald-400" />
            <span>Transaction Ledger & Verified Entitlements ({payments.length})</span>
          </h3>
        </div>

        {loading ? (
          <div className="p-12 text-center text-slate-500 text-xs font-mono">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-emerald-500" />
            Loading transactions...
          </div>
        ) : payments.length === 0 ? (
          <div className="p-12 text-center text-slate-500 text-xs font-mono">
            No payment records found matching criteria.
          </div>
        ) : (
          <div className="table-scroll overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-xs font-sans">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Ref / UTR / Order ID</th>
                  <th className="py-3 px-4">User</th>
                  <th className="py-3 px-4">Plan</th>
                  <th className="py-3 px-4">Amount</th>
                  <th className="py-3 px-4">Gateway</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Date / Time</th>
                  <th className="py-3 px-4 text-right">Subscription Expiry</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {payments.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-3 px-4 font-mono text-slate-200">
                      <div className="font-bold flex items-center gap-1.5">
                        <span>{p.gateway_payment_id || `TXN-${p.id}`}</span>
                      </div>
                      {p.gateway_order_id && (
                        <div className="text-[10px] text-slate-500 truncate max-w-[200px]">
                          {p.gateway_order_id}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-4 font-semibold text-white">
                      <span className="px-2 py-0.5 bg-slate-800 rounded-md font-mono text-indigo-300">
                        {p.username}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-300">
                      {p.plan_name || 'Standard Plan'}
                    </td>
                    <td className="py-3 px-4 font-bold text-emerald-400 font-mono">
                      ₹{parseFloat(p.amount || 0).toFixed(2)}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold border ${
                        p.gateway === 'RAZORPAY' ? 'bg-purple-500/10 text-purple-300 border-purple-500/20' :
                        p.gateway === 'CASHFREE' ? 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20' :
                        p.gateway === 'EMAIL_IMAP' ? 'bg-blue-500/10 text-blue-300 border-blue-500/20' :
                        p.gateway === 'UPI_QR' ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' :
                        'bg-slate-800 text-slate-300 border-slate-700'
                      }`}>
                        {p.gateway}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold inline-flex items-center gap-1 ${
                        p.status === 'SUCCESS' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                        p.status === 'PENDING' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                        'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${p.status === 'SUCCESS' ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                        {p.status}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-400 font-mono text-[11px]">
                      {p.created_at ? formatDateTime(p.created_at) : '—'}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-[11px] text-slate-300">
                      {p.subscription_expires_at ? (
                        <span className="text-emerald-400 font-semibold">
                          {formatDateTime(p.subscription_expires_at)}
                        </span>
                      ) : (
                        <span className="text-slate-500">Active</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---------------------------------------------------- */}
      {/* 1-CLICK MANUAL TOP-UP / UTR MODAL */}
      {/* ---------------------------------------------------- */}
      {showManualModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-emerald-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-emerald-400" />
                <span>1-Click Note / UTR Plan Activation</span>
              </h3>
              <button onClick={() => setShowManualModal(false)} className="text-slate-400 hover:text-white">
                ✕
              </button>
            </div>

            <form onSubmit={handleManualActivate} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Username / Target Subscriber</label>
                <input
                  type="text"
                  list="quick-users-list"
                  value={manualForm.username}
                  onChange={(e) => setManualForm({ ...manualForm, username: e.target.value })}
                  required
                  placeholder="e.g. raj or select existing user..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-emerald-500 outline-none font-mono"
                />
                <datalist id="quick-users-list">
                  {users.map(u => (
                    <option key={u.username} value={u.username} />
                  ))}
                </datalist>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Select Plan Package</label>
                  <select
                    value={manualForm.plan_id}
                    onChange={(e) => {
                      const pid = e.target.value;
                      const selectedPlan = plans.find(p => String(p.id) === pid);
                      setManualForm({
                        ...manualForm,
                        plan_id: pid,
                        validity_days: selectedPlan ? selectedPlan.validity_days : manualForm.validity_days,
                        amount: selectedPlan ? selectedPlan.price : manualForm.amount
                      });
                    }}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-emerald-500 outline-none"
                  >
                    <option value="">Custom Plan / Manual Pass</option>
                    {plans.map(pl => (
                      <option key={pl.id} value={pl.id}>
                        {pl.name} (₹{pl.price} · {pl.validity_days}d{(pl.allowed_groups?.length || 0) > 0 ? ` · ${pl.allowed_groups.join(',')} only` : ''})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Recharge Amount (₹ INR)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={manualForm.amount}
                    onChange={(e) => setManualForm({ ...manualForm, amount: parseFloat(e.target.value) || 0 })}
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-emerald-500 outline-none font-mono font-bold text-emerald-400"
                  />
                </div>
              </div>

              {/* Validity Days Picker & Quick Pills */}
              <div className="space-y-1.5 bg-slate-950/60 p-3 rounded-2xl border border-slate-800/80">
                <div className="flex items-center justify-between">
                  <label className="text-slate-300 font-medium">Validity Duration (Days)</label>
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      min="1"
                      value={manualForm.validity_days}
                      onChange={(e) => setManualForm({ ...manualForm, validity_days: parseInt(e.target.value) || 1 })}
                      className="w-16 px-2 py-1 bg-slate-900 border border-slate-750 rounded-lg text-white font-mono font-bold text-right text-xs focus:border-emerald-500 outline-none"
                    />
                    <span className="text-slate-400 text-[11px]">days</span>
                  </div>
                </div>

                <div className="flex flex-wrap gap-1.5 pt-1">
                  {[
                    { label: '1 Day (₹10)', days: 1, price: 10.0 },
                    { label: '7 Days (₹30)', days: 7, price: 30.0 },
                    { label: '30 Days (₹51.35)', days: 30, price: 51.35 },
                    { label: '90 Days', days: 90, price: 150.0 },
                    { label: '1 Year (365d)', days: 365, price: 600.0 }
                  ].map(pill => (
                    <button
                      key={pill.days}
                      type="button"
                      onClick={() => {
                        // Keep plan_id in sync: link to matching plan when available,
                        // otherwise fall back to Custom Plan (empty plan_id) so the
                        // ledger doesn't show a mismatched plan name.
                        const match = plans.find(p => Number(p.validity_days) === pill.days && Number(p.price) === Number(pill.price));
                        const exactDay = plans.find(p => Number(p.validity_days) === pill.days);
                        setManualForm({
                          ...manualForm,
                          plan_id: match ? String(match.id) : (exactDay && pill.days <= 30 ? String(exactDay.id) : ''),
                          validity_days: pill.days,
                          amount: pill.price
                        });
                      }}
                      className={`px-2.5 py-1 rounded-lg text-[10px] font-semibold border transition ${
                        manualForm.validity_days === pill.days
                          ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 font-bold'
                          : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      {pill.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Bank UTR / Transaction Reference (Optional)</label>
                <input
                  type="text"
                  value={manualForm.utr}
                  onChange={(e) => setManualForm({ ...manualForm, utr: e.target.value })}
                  placeholder="e.g. 427192810291 (12-digit UPI Ref)"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-emerald-500 outline-none font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Note / Remarks (Optional)</label>
                <input
                  type="text"
                  value={manualForm.note}
                  onChange={(e) => setManualForm({ ...manualForm, note: e.target.value })}
                  placeholder="e.g. Paid via Google Pay / Cash at front desk"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-emerald-500 outline-none"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowManualModal(false)}
                  className="px-4 py-2 text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={activating}
                  className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-bold shadow-lg shadow-emerald-600/25 disabled:opacity-50 flex items-center gap-2"
                >
                  <CheckCircle2 className="w-4 h-4" />
                  <span>{activating ? 'Activating...' : 'Activate Subscription'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
