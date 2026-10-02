import React, { useState, useEffect } from 'react';
import { MessageCircle, Copy, Check, X, Send, Phone, Save } from 'lucide-react';
import { fetchJson } from '../utils/api';

export function toWaNumber(phone) {
  return String(phone || '').replace(/\D/g, '');
}

export function buildOnboardingMessage({ username, ssid, portalUrl, supportName, supportPhone, hasCertificate }) {
  const lines = [
    `🎉 *Welcome to ${ssid} Wi-Fi!*`,
    ``,
    `Your account is ready. Save this message:`,
    ``,
    `📶 *Network:* ${ssid}`,
    `🔐 *Security:* WPA2-Enterprise`,
    `👤 *Username:* ${username}`,
    `🔑 *Password:* shared with you separately — keep it private`,
    ``,
    `*How to connect (phone):*`,
    `1. Open Wi-Fi settings → tap ${ssid}`,
    `2. EAP method: PEAP • Phase-2: MSCHAPV2`,
    `3. Enter the username & password above`,
    `4. Accept the certificate prompt if asked`,
    ...(hasCertificate ? [
      `*Password-less option:* an EAP-TLS certificate is installed for you — choose EAP-TLS instead of a password where offered.`,
      ``,
    ] : []),
    `💳 *Recharge:* open ${portalUrl} → pick a plan → pay via UPI (note: wifi:${username})`,
    ``,
    `📞 *Need help?* ${supportName || 'Support'}${supportPhone ? ` — ${supportPhone}` : ''}`,
    ``,
    `— RajLabs Network Team`,
  ];
  return lines.join('\n');
}

/**
 * OnboardModal — 1-click WhatsApp/SMS onboarding invite with detailed,
 * styled login instructions. Phone can be added/fixed inline (saved to the
 * user record). Never includes the password (unknown post-creation).
 */
export default function OnboardModal({ user, onClose, onSavePhone, onNotify }) {
  const [phone, setPhone] = useState(user?.phone || '');
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [config, setConfig] = useState(null);

  useEffect(() => {
    setPhone(user?.phone || '');
    fetchJson('public-config').then(setConfig).catch(() => {});
  }, [user?.username]);

  if (!user) return null;

  const ssid = config?.wifi_ssid || 'RajLabs-Enterprise';
  const portalUrl = typeof window !== 'undefined' ? `${window.location.origin}/radius/portal` : '/radius/portal';
  const message = buildOnboardingMessage({
    username: user.username,
    ssid,
    portalUrl,
    supportName: config?.admin_contact?.name,
    supportPhone: config?.admin_contact?.phone,
    hasCertificate: user.has_certificate
  });
  const digits = toWaNumber(phone);
  const waHref = digits ? `https://wa.me/${digits}?text=${encodeURIComponent(message)}` : null;
  const smsHref = phone ? `sms:${encodeURIComponent(phone)}?body=${encodeURIComponent(message)}` : null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = message;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    onNotify?.('Onboarding message copied', 'success');
  };

  const handleSavePhone = async () => {
    if (!phone.trim()) {
      onNotify?.('Enter a phone number first', 'warning');
      return;
    }
    setSaving(true);
    try {
      await onSavePhone(phone.trim());
      onNotify?.(`Phone number saved for '${user.username}'`, 'success');
    } catch (err) {
      onNotify?.(err.message || 'Failed to save phone number', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-emerald-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Send className="w-5 h-5 text-emerald-400" />
            <span>Onboard <code className="font-mono text-emerald-300">{user.username}</code></span>
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div>
          <label className="block text-xs text-slate-300 mb-1 font-medium">Recipient phone (WhatsApp / SMS)</label>
          <div className="flex gap-1.5">
            <div className="relative flex-1">
              <Phone className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="tel" value={phone} onChange={e => setPhone(e.target.value)}
                placeholder="+919876543210"
                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-white focus:border-emerald-500 outline-none font-mono text-xs"
              />
            </div>
            <button onClick={handleSavePhone} disabled={saving} title="Save to user record"
              className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold border border-slate-700 disabled:opacity-50 flex items-center gap-1">
              <Save className="w-3.5 h-3.5" />
              <span>{saving ? '…' : 'Save'}</span>
            </button>
          </div>
        </div>

        <div>
          <div className="text-xs text-slate-400 mb-1.5 font-medium">Message preview (styled for WhatsApp)</div>
          <div className="bg-[#0b141a] border border-slate-800 rounded-2xl p-3.5 max-h-64 overflow-y-auto">
            <div className="bg-[#005c4b] text-white text-xs rounded-xl rounded-tl-sm px-3 py-2 whitespace-pre-wrap leading-relaxed">
              {message.replace(/\*(.+?)\*/g, '$1')}
            </div>
            <p className="text-[10px] text-slate-500 mt-1.5">*bold*, 🎉 and line breaks render natively in WhatsApp.</p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 text-xs font-semibold">
          {waHref ? (
            <a href={waHref} target="_blank" rel="noopener noreferrer"
              className="px-3 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl flex items-center justify-center gap-1.5">
              <MessageCircle className="w-4 h-4" />
              <span>WhatsApp</span>
            </a>
          ) : (
            <button disabled title="Save a phone number first"
              className="px-3 py-2.5 bg-slate-800 text-slate-500 rounded-xl flex items-center justify-center gap-1.5 cursor-not-allowed">
              <MessageCircle className="w-4 h-4" />
              <span>WhatsApp</span>
            </button>
          )}
          {smsHref ? (
            <a href={smsHref}
              className="px-3 py-2.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl flex items-center justify-center gap-1.5">
              <Send className="w-3.5 h-3.5" />
              <span>SMS</span>
            </a>
          ) : (
            <button disabled title="Save a phone number first"
              className="px-3 py-2.5 bg-slate-800 text-slate-500 rounded-xl flex items-center justify-center gap-1.5 cursor-not-allowed">
              <Send className="w-3.5 h-3.5" />
              <span>SMS</span>
            </button>
          )}
          <button onClick={handleCopy}
            className="px-3 py-2.5 bg-slate-800 hover:bg-slate-700 text-white rounded-xl flex items-center justify-center gap-1.5">
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>
        </div>

        <p className="text-[11px] text-slate-500 text-center">
          Password is never included — share it via the credential card handed at signup.
        </p>
      </div>
    </div>
  );
}
