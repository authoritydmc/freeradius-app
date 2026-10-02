import React, { useState, useEffect } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { 
  Settings, Save, Key, Shield, Phone, CreditCard, RefreshCw, 
  CheckCircle2, AlertCircle, ExternalLink, Globe, Wifi, QrCode,
  Printer, Copy, Check, Plus, Trash2, Edit3, Tag, Clock, DollarSign,
  Sparkles
} from 'lucide-react';
import { fetchJson } from '../utils/api';

export default function SettingsTab({ onNotify }) {
  const [loading, setLoading] = useState(true);
  const [savingAll, setSavingAll] = useState(false);
  const [savingSection, setSavingSection] = useState(null); // 'wifi' | 'signer' | 'payment' | 'contact'
  const [testingSigner, setTestingSigner] = useState(false);
  const [signerStatus, setSignerStatus] = useState(null);
  const [copiedQrString, setCopiedQrString] = useState(false);

  // Plans state
  const [plans, setPlans] = useState([]);
  const [loadingPlans, setLoadingPlans] = useState(false);
  const [showPlanModal, setShowPlanModal] = useState(false);
  const [editingPlan, setEditingPlan] = useState(null);
  const [planForm, setPlanForm] = useState({
    name: '',
    price: 52,
    currency: 'INR',
    validity_days: 30,
    max_session_seconds: 2592000,
    description: ''
  });

  const [form, setForm] = useState({
    admin_contact_name: '',
    admin_contact_phone: '',
    upi_vpa: '',
    upi_merchant_name: '',
    default_voucher_code: '',
    currency: 'INR',
    cert_signer_api_url: '',
    cert_signer_api_key: '',
    wifi_ssid: 'RajLabs-Enterprise',
    wifi_auth_type: 'WPA2-Enterprise / EAP-TLS'
  });

  const loadSettings = async () => {
    try {
      setLoading(true);
      const data = await fetchJson('settings');
      if (data && data.settings) {
        setForm({
          admin_contact_name: data.settings.admin_contact_name || '',
          admin_contact_phone: data.settings.admin_contact_phone || '',
          upi_vpa: data.settings.upi_vpa || '',
          upi_merchant_name: data.settings.upi_merchant_name || '',
          default_voucher_code: data.settings.default_voucher_code || '',
          currency: data.settings.currency || 'INR',
          cert_signer_api_url: data.settings.cert_signer_api_url || '',
          cert_signer_api_key: data.settings.cert_signer_api_key || '',
          wifi_ssid: data.settings.wifi_ssid || 'RajLabs-Enterprise',
          wifi_auth_type: data.settings.wifi_auth_type || 'WPA2-Enterprise / EAP-TLS'
        });
      }
      checkSignerStatus(false);
      loadPlans();
    } catch (err) {
      onNotify?.(err.message || 'Failed to load system settings', 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadPlans = async () => {
    try {
      setLoadingPlans(true);
      const data = await fetchJson('plans');
      setPlans(data || []);
    } catch (err) {
      console.error('Failed to load plans:', err);
    } finally {
      setLoadingPlans(false);
    }
  };

  const checkSignerStatus = async (forceRefresh = true) => {
    try {
      setTestingSigner(true);
      const status = await fetchJson(`certs/signer-status?refresh=${forceRefresh}`);
      setSignerStatus(status);
      if (forceRefresh) {
        if (status.status === 'ok' || (status.reachable && status.key_valid)) {
          onNotify?.('Cert-Signer CA online & API Token verified!', 'success');
        } else {
          onNotify?.(`Cert-Signer probe: ${status.status || status.mode} (${status.detail || 'Check URL/token'})`, 'warning');
        }
      }
    } catch (err) {
      setSignerStatus({ status: 'error', error: err.message, reachable: false });
      if (forceRefresh) {
        onNotify?.(err.message || 'Failed to reach Cert-Signer API', 'error');
      }
    } finally {
      setTestingSigner(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const saveSettingsPayload = async (sectionKey = null, successMessage = 'System settings saved successfully!') => {
    if (sectionKey) {
      setSavingSection(sectionKey);
    } else {
      setSavingAll(true);
    }

    try {
      await fetchJson('settings', {
        method: 'POST',
        body: JSON.stringify(form)
      });
      onNotify?.(successMessage, 'success');
      if (sectionKey === 'signer' || !sectionKey) {
        checkSignerStatus(true);
      }
    } catch (err) {
      onNotify?.(err.message || 'Failed to save settings', 'error');
    } finally {
      setSavingSection(null);
      setSavingAll(false);
    }
  };

  const handleSaveAll = (e) => {
    if (e) e.preventDefault();
    saveSettingsPayload(null, 'All system configuration saved successfully!');
  };

  const handleSavePlan = async (e) => {
    e.preventDefault();
    try {
      await fetchJson('plans', {
        method: 'POST',
        body: JSON.stringify({
          ...planForm,
          id: editingPlan ? editingPlan.id : undefined
        })
      });
      onNotify?.(`Plan '${planForm.name}' saved successfully!`, 'success');
      setShowPlanModal(false);
      setEditingPlan(null);
      setPlanForm({
        name: '',
        price: 52,
        currency: form.currency || 'INR',
        validity_days: 30,
        max_session_seconds: 2592000,
        description: ''
      });
      loadPlans();
    } catch (err) {
      onNotify?.(err.message || 'Failed to save plan', 'error');
    }
  };

  const handleDeletePlan = async (plan) => {
    if (!window.confirm(`Are you sure you want to delete plan '${plan.name}'?`)) return;
    try {
      await fetchJson(`plans/${plan.id}`, { method: 'DELETE' });
      onNotify?.(`Plan '${plan.name}' deleted`, 'success');
      loadPlans();
    } catch (err) {
      onNotify?.(err.message || 'Failed to delete plan', 'error');
    }
  };

  const openEditPlan = (plan) => {
    setEditingPlan(plan);
    setPlanForm({
      name: plan.name,
      price: plan.price,
      currency: plan.currency || 'INR',
      validity_days: plan.validity_days,
      max_session_seconds: plan.max_session_seconds || 86400,
      description: plan.description || ''
    });
    setShowPlanModal(true);
  };

  const qrWifiString = `WIFI:T:WPA;S:${form.wifi_ssid || 'RajLabs-Enterprise'};;`;

  const handleCopyQr = () => {
    navigator.clipboard.writeText(qrWifiString);
    setCopiedQrString(true);
    onNotify?.('Copied Wi-Fi connection string to clipboard', 'info');
    setTimeout(() => setCopiedQrString(false), 2000);
  };

  return (
    <div className="space-y-6">
      
      {/* Header Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-amber-500/10 rounded-xl border border-amber-500/20 text-amber-400">
            <Settings className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">System Settings & Plans Pricing</h2>
            <p className="text-xs text-slate-400">Configure Wi-Fi plans, recharge rates, SSID, central PKI Signer, and UPI payments</p>
          </div>
        </div>

        <button
          type="button"
          onClick={handleSaveAll}
          disabled={savingAll || Boolean(savingSection)}
          className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white rounded-xl text-sm font-semibold shadow-md shadow-amber-500/20 transition disabled:opacity-50 cursor-pointer"
        >
          {savingAll ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          <span>Save All Settings</span>
        </button>
      </div>

      {/* 1. Wi-Fi Plans & Pricing Section */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/20">
              <CreditCard className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Wi-Fi Subscription Plans & Recharge Pricing</h3>
              <p className="text-xs text-slate-400">Manage paid packages, validity days, and voucher recharge rates</p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => {
              setEditingPlan(null);
              setPlanForm({
                name: '',
                price: 52,
                currency: form.currency || 'INR',
                validity_days: 30,
                max_session_seconds: 2592000,
                description: ''
              });
              setShowPlanModal(true);
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-500/20 transition"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add New Plan</span>
          </button>
        </div>

        {loadingPlans ? (
          <div className="p-8 text-center text-xs text-slate-400">Loading plans...</div>
        ) : plans.length === 0 ? (
          <div className="p-8 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl">
            No plans configured. Click "Add New Plan" to create your first Wi-Fi recharge package.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            {plans.map(plan => (
              <div 
                key={plan.id}
                className="bg-slate-950 p-4 rounded-2xl border border-slate-800 hover:border-slate-700 transition flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <h4 className="font-bold text-white text-sm">{plan.name}</h4>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => openEditPlan(plan)}
                        className="p-1 text-slate-400 hover:text-indigo-400 rounded transition"
                        title="Edit Plan"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDeletePlan(plan)}
                        className="p-1 text-slate-400 hover:text-rose-400 rounded transition"
                        title="Delete Plan"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  <div className="text-2xl font-black text-emerald-400 font-mono mb-2">
                    {plan.currency === 'INR' ? '₹' : plan.currency} {plan.price}
                  </div>

                  <p className="text-xs text-slate-400 mb-3">{plan.description || 'Broadband Wi-Fi access pass'}</p>

                  <div className="space-y-1.5 text-[11px] font-mono border-t border-slate-800/80 pt-2.5 text-slate-300">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Validity:</span>
                      <span className="font-bold text-indigo-300">{plan.validity_days} Days</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Max Session:</span>
                      <span>{Math.round(plan.max_session_seconds / 3600)} Hours</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 2. Broadcast Wi-Fi SSID & QR Settings Card */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
              <Wifi className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Broadcast Wi-Fi & Direct Connect QR</h3>
              <p className="text-xs text-slate-400">Set the default network name (SSID) encoded into connection QR codes</p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => saveSettingsPayload('wifi', 'Wi-Fi broadcast settings saved successfully!')}
            disabled={savingSection === 'wifi'}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-600/20 transition disabled:opacity-50 cursor-pointer"
          >
            {savingSection === 'wifi' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            <span>Save Wi-Fi Settings</span>
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
          <div className="lg:col-span-7 space-y-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Wi-Fi Network Name (SSID) *</label>
              <input
                type="text"
                required
                placeholder="e.g. RajLabs-Enterprise or RajLabs-Guest"
                value={form.wifi_ssid}
                onChange={e => setForm({ ...form, wifi_ssid: e.target.value })}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono font-bold"
              />
              <p className="text-[11px] text-slate-500">Matches the broadcast SSID configured on your MikroTik, UniFi, or Cisco APs.</p>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Security / Authentication Type</label>
              <select
                value={form.wifi_auth_type}
                onChange={e => setForm({ ...form, wifi_auth_type: e.target.value })}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="WPA2-Enterprise / EAP-TLS">WPA2/WPA3-Enterprise (802.1X EAP-TLS / PEAP)</option>
                <option value="WPA2-Personal (PSK)">WPA2-Personal (Pre-Shared Key)</option>
                <option value="Open / Captive Web Auth">Open Network + Captive Portal Splash</option>
              </select>
            </div>
          </div>

          {/* Live QR Badge Preview */}
          <div className="lg:col-span-5 bg-slate-950 p-4 rounded-2xl border border-slate-800 flex flex-col items-center text-center space-y-3">
            <div className="p-3 bg-white rounded-xl shadow-lg border border-indigo-500/20">
              <QRCodeSVG
                value={qrWifiString}
                size={140}
                level="H"
                includeMargin={false}
              />
            </div>
            <div>
              <span className="font-mono text-xs font-bold text-indigo-300 block">{form.wifi_ssid || 'RajLabs-Enterprise'}</span>
              <span className="text-[10px] text-slate-400">Direct Connect Wi-Fi QR Preview</span>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleCopyQr}
                className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs flex items-center gap-1 border border-slate-700"
              >
                {copiedQrString ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>Copy String</span>
              </button>
              <button
                type="button"
                onClick={() => window.print()}
                className="px-2.5 py-1 bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 rounded-lg text-xs flex items-center gap-1 border border-indigo-500/30"
              >
                <Printer className="w-3.5 h-3.5" />
                <span>Print Badge</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 3. PKI & Central Cert-Signer API Card */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
              <Shield className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Central RajLabs-CA Cert-Signer API</h3>
              <p className="text-xs text-slate-400">Automated X.509 client certificate signing for EAP-TLS authentication</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => checkSignerStatus(true)}
              disabled={testingSigner}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-750 border border-slate-750 text-slate-200 rounded-xl text-xs font-medium transition disabled:opacity-50 cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${testingSigner ? 'animate-spin text-indigo-400' : ''}`} />
              <span>Test Signer</span>
            </button>
            <button
              type="button"
              onClick={() => saveSettingsPayload('signer', 'Cert-Signer API configuration saved successfully!')}
              disabled={savingSection === 'signer'}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-600/20 transition disabled:opacity-50 cursor-pointer"
            >
              {savingSection === 'signer' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              <span>Save Signer Settings</span>
            </button>
          </div>
        </div>

        {/* Signer status banner */}
        {signerStatus && (
          <div className="space-y-2">
            <div className={`p-3.5 rounded-xl border flex items-center justify-between gap-3 text-xs ${signerStatus.status === 'ok' || signerStatus.reachable ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-amber-500/10 border-amber-500/30 text-amber-300'}`}>
              <div className="flex items-center gap-2">
                {signerStatus.status === 'ok' || signerStatus.reachable ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                )}
                <div>
                  <span className="font-semibold">Signer Status: </span>
                  <span>{signerStatus.status === 'ok' || (signerStatus.reachable && signerStatus.key_valid) ? 'Online & Authenticated' : (signerStatus.detail || signerStatus.error || 'Token Missing or Unreachable')}</span>
                  {signerStatus.host && (
                    <span className="ml-2 font-mono text-[11px] opacity-80">({signerStatus.host})</span>
                  )}
                </div>
              </div>
              <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-slate-900/60 border border-slate-700/50">
                Mode: {signerStatus.mode || 'REST API'}
              </span>
            </div>

            {/* Live Probe Response Console */}
            <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 font-mono text-[11px] space-y-1 text-slate-300">
              <div className="text-slate-500 flex items-center justify-between pb-1 border-b border-slate-900">
                <span>Signer Diagnostic Probe Response:</span>
                <span>{signerStatus.checked_at ? new Date(signerStatus.checked_at).toLocaleTimeString() : 'live'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Target Host / URL:</span>
                <span className="text-indigo-300 font-bold">{form.cert_signer_api_url || 'https://backend.rajlabs.in/cert-signer'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">HTTP Status Code:</span>
                <span className={signerStatus.status_code === 200 ? 'text-emerald-400' : 'text-amber-400'}>
                  {signerStatus.status_code || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Round-Trip Latency:</span>
                <span className="text-slate-200">{signerStatus.latency_ms ? `${signerStatus.latency_ms} ms` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">API Key Configured:</span>
                <span className={form.cert_signer_api_key ? 'text-emerald-400' : 'text-amber-400'}>
                  {form.cert_signer_api_key ? 'Yes (Bearer / X-API-KEY)' : 'None'}
                </span>
              </div>
              <div className="pt-1 text-slate-400 text-[10px] border-t border-slate-900 leading-relaxed">
                {signerStatus.detail || 'Central Rajlabs PKI Signer is active for 802.1X client certificates.'}
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Cert-Signer API Base URL</label>
            <input
              type="text"
              placeholder="https://ca.rajlabs.in or https://backend.rajlabs.in/cert-signer"
              value={form.cert_signer_api_url}
              onChange={e => setForm({ ...form, cert_signer_api_url: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">Auto-routes to central CA microservice.</p>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Cert-Signer API Key / Token</label>
            <input
              type="password"
              placeholder="Bearer API Key / Secret Token"
              value={form.cert_signer_api_key}
              onChange={e => setForm({ ...form, cert_signer_api_key: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">Provided to /api/v1/sign for CSR authorization.</p>
          </div>
        </div>
      </div>

      {/* 4. UPI Payments & Self-Service Vouchers */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/20">
              <CreditCard className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">UPI Payments & Guest Vouchers</h3>
              <p className="text-xs text-slate-400">Configure instant QR payments on the Captive Self-Service Portal</p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => saveSettingsPayload('payment', 'Payment gateway configuration saved successfully!')}
            disabled={savingSection === 'payment'}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-600/20 transition disabled:opacity-50 cursor-pointer"
          >
            {savingSection === 'payment' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            <span>Save Payment Settings</span>
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">UPI VPA (Virtual Payment Address)</label>
            <input
              type="text"
              placeholder="e.g. rajlabs@oksbi"
              value={form.upi_vpa}
              onChange={e => setForm({ ...form, upi_vpa: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Merchant Display Name</label>
            <input
              type="text"
              placeholder="e.g. RajLabs Enterprise Wi-Fi"
              value={form.upi_merchant_name}
              onChange={e => setForm({ ...form, upi_merchant_name: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Default Voucher Code</label>
            <input
              type="text"
              placeholder="e.g. WELCOME100"
              value={form.default_voucher_code}
              onChange={e => setForm({ ...form, default_voucher_code: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
            />
          </div>
        </div>
      </div>

      {/* 5. Support & Admin Contacts */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-blue-500/10 text-blue-400 rounded-xl border border-blue-500/20">
              <Phone className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Captive Portal Support Contact</h3>
              <p className="text-xs text-slate-400">Displayed to users when Wi-Fi connection fails or assistance is needed</p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => saveSettingsPayload('contact', 'Contact details saved successfully!')}
            disabled={savingSection === 'contact'}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-blue-600/20 transition disabled:opacity-50 cursor-pointer"
          >
            {savingSection === 'contact' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            <span>Save Contact Details</span>
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Admin Contact Name</label>
            <input
              type="text"
              placeholder="e.g. Network NOC Team"
              value={form.admin_contact_name}
              onChange={e => setForm({ ...form, admin_contact_name: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Support Phone / WhatsApp Number</label>
            <input
              type="text"
              placeholder="e.g. +91 9876543210"
              value={form.admin_contact_phone}
              onChange={e => setForm({ ...form, admin_contact_phone: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>
        </div>
      </div>

      {/* Add / Edit Plan Modal */}
      {showPlanModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="bg-slate-900 border border-slate-750 rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/50">
              <div className="flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-emerald-400" />
                <h3 className="font-bold text-white text-base">
                  {editingPlan ? 'Edit Wi-Fi Plan' : 'Create New Wi-Fi Plan'}
                </h3>
              </div>
              <button
                onClick={() => setShowPlanModal(false)}
                className="text-slate-400 hover:text-white text-lg"
              >
                &times;
              </button>
            </div>

            <form onSubmit={handleSavePlan} className="p-6 space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Plan Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. 1 Month Unlimited Pass"
                  value={planForm.name}
                  onChange={e => setPlanForm({ ...planForm, name: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-medium"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Price ({form.currency || 'INR'}) *</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={planForm.price}
                    onChange={e => setPlanForm({ ...planForm, price: parseFloat(e.target.value) || 0 })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono font-bold"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Validity (Days) *</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={planForm.validity_days}
                    onChange={e => setPlanForm({ ...planForm, validity_days: parseInt(e.target.value) || 1 })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Description</label>
                <input
                  type="text"
                  placeholder="Plan features, speed, device limit"
                  value={planForm.description}
                  onChange={e => setPlanForm({ ...planForm, description: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowPlanModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-500/20"
                >
                  {editingPlan ? 'Update Plan' : 'Create Plan'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
