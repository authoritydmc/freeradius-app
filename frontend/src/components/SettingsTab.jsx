import React, { useState, useEffect } from 'react';
import { 
  Settings, Save, Key, Shield, Phone, CreditCard, RefreshCw, 
  CheckCircle2, AlertCircle, ExternalLink, Globe, Wifi, QrCode
} from 'lucide-react';
import { fetchJson } from '../utils/api';

export default function SettingsTab({ onNotify }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingSigner, setTestingSigner] = useState(false);
  const [signerStatus, setSignerStatus] = useState(null);

  const [form, setForm] = useState({
    admin_contact_name: '',
    admin_contact_phone: '',
    upi_vpa: '',
    upi_merchant_name: '',
    default_voucher_code: '',
    currency: 'INR',
    cert_signer_api_url: '',
    cert_signer_api_key: ''
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
          cert_signer_api_key: data.settings.cert_signer_api_key || ''
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
        if (status.status === 'ok') {
          onNotify?.('Cert-Signer CA online & API Token verified!', 'success');
        } else {
          onNotify?.(`Cert-Signer probe: ${status.status} (${status.error || 'Check URL/token'})`, 'warning');
        }
      }
    } catch (err) {
      setSignerStatus({ status: 'error', error: err.message });
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

  const handleSave = async (e) => {
    e.preventDefault();
    try {
      setSaving(true);
      await fetchJson('settings', {
        method: 'POST',
        body: JSON.stringify(form)
      });
      onNotify?.('System settings saved successfully!', 'success');
      checkSignerStatus(true);
    } catch (err) {
      onNotify?.(err.message || 'Failed to save system settings', 'error');
    } finally {
      setSaving(false);
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
            <h2 className="text-lg font-bold text-white">System Settings & Gateway Integrations</h2>
            <p className="text-xs text-slate-400">Configure central PKI Cert-Signer API, UPI payments, and support contacts</p>
          </div>
        </div>

        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white rounded-xl text-sm font-semibold shadow-md shadow-amber-500/20 transition disabled:opacity-50"
        >
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          <span>Save Changes</span>
        </button>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* PKI & Cert-Signer Integration Card */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
                <Shield className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-white text-base">Central RajLabs-CA Cert-Signer API</h3>
                <p className="text-xs text-slate-400">Automated X.509 client certificate signing for EAP-TLS and Admin login</p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => checkSignerStatus(true)}
              disabled={testingSigner}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-750 border border-slate-700 text-slate-200 rounded-xl text-xs font-medium transition disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${testingSigner ? 'animate-spin text-indigo-400' : ''}`} />
              <span>Test Signer Connection</span>
            </button>
          </div>

          {/* Signer status banner */}
          {signerStatus && (
            <div className={`p-3.5 rounded-xl border flex items-center justify-between gap-3 text-xs ${signerStatus.status === 'ok' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-amber-500/10 border-amber-500/30 text-amber-300'}`}>
              <div className="flex items-center gap-2">
                {signerStatus.status === 'ok' ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                )}
                <div>
                  <span className="font-semibold">Signer Status: </span>
                  <span>{signerStatus.status === 'ok' ? 'Online & Authenticated' : (signerStatus.error || 'Token Missing or Unreachable')}</span>
                  {signerStatus.ca_subject && (
                    <span className="ml-2 font-mono text-[11px] opacity-80">({signerStatus.ca_subject})</span>
                  )}
                </div>
              </div>
              <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-slate-900/60 border border-slate-700/50">
                Mode: {signerStatus.mode || 'REST API'}
              </span>
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
              <p className="text-[11px] text-slate-500">Supports direct subdomain or subpath proxying.</p>
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
              <p className="text-[11px] text-slate-500">Provided to /api/v1/sign for privileged CSR authorization.</p>
            </div>
          </div>
        </div>

        {/* UPI Payments & Self-Service Vouchers */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex items-center gap-2.5 border-b border-slate-800 pb-3">
            <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/20">
              <CreditCard className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">UPI Payments & Guest Vouchers</h3>
              <p className="text-xs text-slate-400">Configure instant QR payments on the Captive Self-Service Portal</p>
            </div>
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

        {/* Support & Admin Contacts */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex items-center gap-2.5 border-b border-slate-800 pb-3">
            <div className="p-2 bg-blue-500/10 text-blue-400 rounded-xl border border-blue-500/20">
              <Phone className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Captive Portal Support Contact</h3>
              <p className="text-xs text-slate-400">Displayed to users when Wi-Fi connection fails or help is needed</p>
            </div>
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
      </form>
    </div>
  );
}
