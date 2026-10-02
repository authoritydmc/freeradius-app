import React, { useState, useEffect } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import {
  Settings, Save, Key, Shield, Phone, CreditCard, RefreshCw,
  CheckCircle2, AlertCircle, ExternalLink, Globe, Wifi, QrCode,
  Printer, Copy, Check,
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

  const [testingImap, setTestingImap] = useState(false);
  const [testingGateway, setTestingGateway] = useState(null);

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
    wifi_auth_type: 'WPA2-Enterprise / EAP-TLS',
    payment_active_gateway: 'UPI_QR',
    razorpay_key_id: '',
    razorpay_key_secret: '',
    razorpay_key_secret_set: false,
    razorpay_webhook_secret: '',
    razorpay_webhook_secret_set: false,
    cashfree_app_id: '',
    cashfree_secret_key: '',
    cashfree_secret_key_set: false,
    cashfree_env: 'TEST',
    payu_merchant_key: '',
    payu_merchant_salt: '',
    payu_merchant_salt_set: false,
    email_imap_host: 'imap.gmail.com',
    email_imap_port: 993,
    email_imap_user: '',
    email_imap_password: '',
    email_imap_password_set: false,
    email_imap_folder: 'INBOX',
    cert_signer_api_key_set: false
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
          wifi_ssid: data.settings.wifi_ssid || 'RajLabs-Enterprise',
          wifi_auth_type: data.settings.wifi_auth_type || 'WPA2-Enterprise / EAP-TLS',
          payment_active_gateway: data.settings.payment_active_gateway || 'UPI_QR',
          razorpay_key_id: data.settings.razorpay_key_id || '',
          razorpay_key_secret: '',
          razorpay_key_secret_set: !!data.settings.razorpay_key_secret_set,
          razorpay_webhook_secret: '',
          razorpay_webhook_secret_set: !!data.settings.razorpay_webhook_secret_set,
          cashfree_app_id: data.settings.cashfree_app_id || '',
          cashfree_secret_key: '',
          cashfree_secret_key_set: !!data.settings.cashfree_secret_key_set,
          cashfree_env: data.settings.cashfree_env || 'TEST',
          payu_merchant_key: data.settings.payu_merchant_key || '',
          payu_merchant_salt: '',
          payu_merchant_salt_set: !!data.settings.payu_merchant_salt_set,
          email_imap_host: data.settings.email_imap_host || 'imap.gmail.com',
          email_imap_port: parseInt(data.settings.email_imap_port || 993),
          email_imap_user: data.settings.email_imap_user || '',
          email_imap_password: '',
          email_imap_password_set: !!data.settings.email_imap_password_set,
          email_imap_folder: data.settings.email_imap_folder || 'INBOX',
          cert_signer_api_key: '',
          cert_signer_api_key_set: !!data.settings.cert_signer_api_key_set
        });
      }
      checkSignerStatus(false);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load system settings', 'error');
    } finally {
      setLoading(false);
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

  const qrWifiString = `WIFI:T:WPA;S:${form.wifi_ssid || 'RajLabs-Enterprise'};;`;

  const handleCopyQr = () => {
    navigator.clipboard.writeText(qrWifiString);
    setCopiedQrString(true);
    onNotify?.('Copied Wi-Fi connection string to clipboard', 'info');
    setTimeout(() => setCopiedQrString(false), 2000);
  };

  const handleTestGateway = async (gatewayName) => {
    try {
      setTestingGateway(gatewayName);
      let payload = { gateway: gatewayName };
      if (gatewayName === 'razorpay') {
        payload.key_id = form.razorpay_key_id;
        payload.key_secret = form.razorpay_key_secret;
      } else if (gatewayName === 'cashfree') {
        payload.app_id = form.cashfree_app_id;
        payload.secret_key = form.cashfree_secret_key;
        payload.env = form.cashfree_env;
      }

      const res = await fetchJson('payments/gateway/test', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      if (res && res.ok) {
        onNotify?.(res.message || `${gatewayName} API verified successfully!`, 'success');
      } else {
        onNotify?.(res?.error || `Failed to verify ${gatewayName} credentials`, 'error');
      }
    } catch (err) {
      onNotify?.(err.message || `Failed to test ${gatewayName}`, 'error');
    } finally {
      setTestingGateway(null);
    }
  };

  const handleTestImap = async () => {
    try {
      setTestingImap(true);
      const res = await fetchJson('payments/email/test', {
        method: 'POST',
        body: JSON.stringify({
          gateway: 'imap',
          imap_host: form.email_imap_host,
          imap_port: form.email_imap_port,
          imap_user: form.email_imap_user,
          imap_password: form.email_imap_password
        })
      });

      if (res && res.ok) {
        onNotify?.(res.message || 'Gmail / Bank IMAP connection successful!', 'success');
      } else {
        onNotify?.(res?.error || 'Failed to connect to IMAP server. Check host, username, and App Password.', 'error');
      }
    } catch (err) {
      onNotify?.(err.message || 'Failed to test IMAP connection', 'error');
    } finally {
      setTestingImap(false);
    }
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
            <h2 className="text-lg font-bold text-white">System Settings</h2>
            <p className="text-xs text-slate-400">Configure SSID, central PKI Signer, UPI payments and gateways (plans live under Payments)</p>
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

      {/* 1. Broadcast Wi-Fi SSID & QR Settings Card */}
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
                <span className={form.cert_signer_api_key || form.cert_signer_api_key_set ? 'text-emerald-400' : 'text-amber-400'}>
                  {(form.cert_signer_api_key || form.cert_signer_api_key_set) ? 'Yes (Bearer / X-API-KEY)' : 'None'}
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
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Cert-Signer API Key / Token {form.cert_signer_api_key_set && <span className="text-emerald-400 font-bold normal-case">· saved ✓</span>}</label>
              <input
                type="password"
                placeholder="Blank = keep saved value"
                value={form.cert_signer_api_key}
              onChange={e => setForm({ ...form, cert_signer_api_key: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">Provided to /api/v1/sign for CSR authorization.</p>
          </div>
        </div>
      </div>

      {/* 4. Payment Gateways & UPI Section */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/20">
              <CreditCard className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Payment Gateways & Direct UPI</h3>
              <p className="text-xs text-slate-400">Configure Indian Payment Gateways (Razorpay, Cashfree, PayU) and Dynamic UPI QR</p>
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

        {/* Gateway Selector Pill */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Active Captive Portal Gateway</label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { id: 'UPI_QR', label: 'Dynamic UPI QR', desc: 'Direct VPA QR Intent' },
              { id: 'RAZORPAY', label: 'Razorpay', desc: 'UPI, Cards, Netbanking' },
              { id: 'CASHFREE', label: 'Cashfree PG', desc: 'Instant UPI Intent & Cards' },
              { id: 'PAYU', label: 'PayU India', desc: 'Cards, NetBanking, UPI' }
            ].map(gw => (
              <button
                key={gw.id}
                type="button"
                onClick={() => setForm({ ...form, payment_active_gateway: gw.id })}
                className={`p-3 rounded-xl border text-left transition ${
                  form.payment_active_gateway === gw.id
                    ? 'bg-emerald-500/10 border-emerald-500 text-emerald-300 ring-1 ring-emerald-500/30'
                    : 'bg-slate-950/60 border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <div className="font-bold text-xs text-white">{gw.label}</div>
                <div className="text-[10px] text-slate-400 mt-0.5">{gw.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 4a. Direct UPI Settings */}
        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 space-y-3">
          <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
            <QrCode className="w-4 h-4 text-emerald-400" />
            <span>Direct UPI QR & Voucher Settings</span>
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">UPI VPA (Virtual Payment Address)</label>
              <input
                type="text"
                placeholder="e.g. rajlabs@oksbi"
                value={form.upi_vpa}
                onChange={e => setForm({ ...form, upi_vpa: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Merchant Display Name</label>
              <input
                type="text"
                placeholder="e.g. RajLabs Enterprise Wi-Fi"
                value={form.upi_merchant_name}
                onChange={e => setForm({ ...form, upi_merchant_name: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Default Voucher Promo Code</label>
              <input
                type="text"
                placeholder="e.g. WELCOME100"
                value={form.default_voucher_code}
                onChange={e => setForm({ ...form, default_voucher_code: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
          </div>
        </div>

        {/* 4b. Razorpay Settings */}
        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-blue-400" />
              <span>Razorpay Payment Gateway</span>
            </h4>
            <button
              type="button"
              onClick={() => handleTestGateway('razorpay')}
              disabled={testingGateway === 'razorpay' || !form.razorpay_key_id || !(form.razorpay_key_secret || form.razorpay_key_secret_set)}
              className="px-2.5 py-1 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 rounded-lg text-xs font-semibold transition disabled:opacity-40 flex items-center gap-1"
            >
              <RefreshCw className={`w-3 h-3 ${testingGateway === 'razorpay' ? 'animate-spin' : ''}`} />
              <span>Test Razorpay API Keys</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Razorpay Key ID</label>
              <input
                type="text"
                placeholder="rzp_test_... or rzp_live_..."
                value={form.razorpay_key_id}
                onChange={e => setForm({ ...form, razorpay_key_id: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Razorpay Key Secret {form.razorpay_key_secret_set && <span className="text-emerald-400 font-bold">· saved ✓</span>}</label>
              <input
                type="password"
                placeholder="Blank = keep saved value"
                value={form.razorpay_key_secret}
                onChange={e => setForm({ ...form, razorpay_key_secret: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Webhook Secret {form.razorpay_webhook_secret_set && <span className="text-emerald-400 font-bold">· saved ✓</span>}</label>
              <input
                type="password"
                placeholder="Blank = keep saved value"
                value={form.razorpay_webhook_secret}
                onChange={e => setForm({ ...form, razorpay_webhook_secret: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
              />
            </div>
          </div>
          <div className="text-[11px] text-slate-500 font-mono">
            Webhook URL: <code className="text-slate-300">https://radius.rajlabs.in/radius/api/webhooks/razorpay</code> (Subscribe to event: <code className="text-slate-300">payment.captured</code>)
          </div>
        </div>

        {/* 4c. Cashfree PG Settings */}
        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              <CreditCard className="w-4 h-4 text-purple-400" />
              <span>Cashfree Payment Gateway</span>
            </h4>
            <button
              type="button"
              onClick={() => handleTestGateway('cashfree')}
              disabled={testingGateway === 'cashfree' || !form.cashfree_app_id || !(form.cashfree_secret_key || form.cashfree_secret_key_set)}
              className="px-2.5 py-1 bg-purple-600/20 hover:bg-purple-600/30 text-purple-300 border border-purple-500/30 rounded-lg text-xs font-semibold transition disabled:opacity-40 flex items-center gap-1"
            >
              <RefreshCw className={`w-3 h-3 ${testingGateway === 'cashfree' ? 'animate-spin' : ''}`} />
              <span>Test Cashfree Keys</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Cashfree App ID</label>
              <input
                type="text"
                placeholder="CF...AppId"
                value={form.cashfree_app_id}
                onChange={e => setForm({ ...form, cashfree_app_id: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-purple-500 font-mono"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Cashfree Secret Key {form.cashfree_secret_key_set && <span className="text-emerald-400 font-bold">· saved ✓</span>}</label>
              <input
                type="password"
                placeholder="Blank = keep saved value"
                value={form.cashfree_secret_key}
                onChange={e => setForm({ ...form, cashfree_secret_key: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-purple-500 font-mono"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">Environment</label>
              <select
                value={form.cashfree_env}
                onChange={e => setForm({ ...form, cashfree_env: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-purple-500 font-mono"
              >
                <option value="TEST">TEST (Sandbox)</option>
                <option value="PROD">PROD (Production)</option>
              </select>
            </div>
          </div>
        </div>

        {/* 4d. PayU Settings */}
        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 space-y-3">
          <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
            <CreditCard className="w-4 h-4 text-emerald-400" />
            <span>PayU India Gateway</span>
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">PayU Merchant Key</label>
              <input
                type="text"
                placeholder="Merchant Key"
                value={form.payu_merchant_key}
                onChange={e => setForm({ ...form, payu_merchant_key: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-400">PayU Merchant Salt {form.payu_merchant_salt_set && <span className="text-emerald-400 font-bold">· saved ✓</span>}</label>
              <input
                type="password"
                placeholder="Blank = keep saved value"
                value={form.payu_merchant_salt}
                onChange={e => setForm({ ...form, payu_merchant_salt: e.target.value })}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
          </div>
        </div>
      </div>

      {/* 5. Google Gmail / Bank Email IMAP Auto-Reconciliation */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-amber-500/10 text-amber-400 rounded-xl border border-amber-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Google Gmail & Bank Alert IMAP Reconciliation</h3>
              <p className="text-xs text-slate-400">Read incoming HDFC/SBI/ICICI/UPI credit emails & auto-activate subscriptions from payment remarks</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleTestImap}
              disabled={testingImap || !form.email_imap_user || !(form.email_imap_password || form.email_imap_password_set)}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700 rounded-xl text-xs font-semibold transition disabled:opacity-40 flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${testingImap ? 'animate-spin text-amber-400' : ''}`} />
              <span>Test IMAP Login</span>
            </button>
            <button
              type="button"
              onClick={() => saveSettingsPayload('payment', 'Gmail / IMAP settings saved successfully!')}
              disabled={savingSection === 'payment'}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-amber-600/20 transition disabled:opacity-50 cursor-pointer"
            >
              {savingSection === 'payment' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              <span>Save IMAP Settings</span>
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">IMAP Server Host</label>
            <input
              type="text"
              placeholder="imap.gmail.com"
              value={form.email_imap_host}
              onChange={e => setForm({ ...form, email_imap_host: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">IMAP Port (SSL)</label>
            <input
              type="number"
              placeholder="993"
              value={form.email_imap_port}
              onChange={e => setForm({ ...form, email_imap_port: parseInt(e.target.value) || 993 })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Email Address / User</label>
            <input
              type="email"
              placeholder="youraccount@gmail.com"
              value={form.email_imap_user}
              onChange={e => setForm({ ...form, email_imap_user: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
            />
          </div>

          <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Google App Password {form.email_imap_password_set && <span className="text-emerald-400 font-bold normal-case">· saved ✓</span>}</label>
              <input
                type="password"
                placeholder="Blank = keep saved value"
                value={form.email_imap_password}
              onChange={e => setForm({ ...form, email_imap_password: e.target.value })}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
            />
          </div>
        </div>

        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-300 space-y-1">
          <div className="font-bold flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4" />
            <span>How Note-Based UPI Auto-Reconciliation Works</span>
          </div>
          <p className="text-[11px] text-slate-300 leading-relaxed">
            When users transfer money via PhonePe, GPay, Paytm, or BHIM to your UPI VPA, they include their username or package in the UPI remark note (e.g. <code className="text-amber-200 bg-slate-900 px-1 py-0.5 rounded font-mono">wifi:username:plan_id</code> or simply <code className="text-amber-200 bg-slate-900 px-1 py-0.5 rounded font-mono">wifi:username</code>). The engine matches the bank credit email UTR, validates the amount against the active plan pricing, and grants instant 802.1X enterprise network access.
          </p>
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

    </div>
  );
}
