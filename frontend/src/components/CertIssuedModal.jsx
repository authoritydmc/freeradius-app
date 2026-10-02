import React, { useState } from 'react';
import {
  KeyRound, Copy, Check, Download, Apple, X, ShieldCheck, AlertTriangle
} from 'lucide-react';
import { apiRequest } from '../utils/api';

/**
 * CertIssuedModal — shown right after a certificate is issued with a
 * server-generated .p12 password (the only moment it exists in plaintext).
 *
 * The password is unrecoverable afterwards, so closing requires proof of
 * handoff: either the password was copied OR a bundle was downloaded.
 */
export default function CertIssuedModal({ data, onClose, onNotify }) {
  const [copied, setCopied] = useState(false);
  const [downloaded, setDownloaded] = useState([]); // 'p12' | 'mobileconfig'
  const [downloading, setDownloading] = useState('');

  if (!data) return null;
  const username = data.username || '';
  const password = data.p12_password || '';
  const secured = copied || downloaded.length > 0;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(password);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = password;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    setCopied(true);
    onNotify?.('Certificate password copied — store it somewhere safe', 'success');
  };

  const handleDownload = async (kind) => {
    setDownloading(kind);
    try {
      const path = kind === 'p12'
        ? `certs/${encodeURIComponent(username)}/download`
        : `certs/${encodeURIComponent(username)}/mobileconfig`;
      const res = await apiRequest(path);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.message || `Download failed (HTTP ${res.status})`);
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
      setDownloaded(prev => (prev.includes(kind) ? prev : [...prev, kind]));
      onNotify?.(kind === 'p12' ? 'Bundle downloaded — it needs the password above to import.' : 'Apple profile downloaded.', 'success');
    } catch (err) {
      onNotify?.(err.message || 'Download failed', 'error');
    } finally {
      setDownloading('');
    }
  };

  const attemptClose = () => {
    if (!secured) {
      onNotify?.('Copy the password or download a bundle first — it cannot be recovered later.', 'warning');
      return;
    }
    onClose?.();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-emerald-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <span className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
              <KeyRound className="w-4 h-4 text-emerald-400" />
            </span>
            <span>Certificate issued: <code className="font-mono text-emerald-300">{username}</code></span>
          </h3>
          <button onClick={attemptClose} title={secured ? 'Close' : 'Save the password first'} className={`${secured ? 'text-slate-400 hover:text-white' : 'text-slate-600 cursor-not-allowed'}`}>
            <X className="w-5 h-5" />
          </button>
        </div>

        {data.authority && (
          <p className="text-[11px] text-slate-400 flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
            Signed by {data.authority}
          </p>
        )}

        <div className="bg-amber-500/10 border border-amber-500/25 rounded-2xl p-4">
          <div className="text-[11px] font-bold text-amber-200 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Bundle password — shown once</span>
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-center text-lg font-black text-amber-300 font-mono bg-slate-950 border border-amber-500/20 rounded-xl px-3 py-2.5 select-all">
              {password || '—'}
            </code>
            <button
              onClick={handleCopy}
              title="Copy password"
              className={`p-2.5 rounded-xl border transition shrink-0 ${copied ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300' : 'bg-slate-800 border-slate-700 text-slate-300 hover:text-white'}`}
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
          <div className="mt-2.5 flex items-center gap-2 text-[11px]">
            <span className={`flex items-center gap-1 ${copied ? 'text-emerald-300 font-bold' : 'text-slate-500'}`}>
              {copied ? <Check className="w-3.5 h-3.5" /> : <span className="w-3.5 h-3.5 rounded-full border border-slate-600 inline-block" />}
              Copied
            </span>
            <span className={`flex items-center gap-1 ${downloaded.includes('p12') || downloaded.includes('mobileconfig') ? 'text-emerald-300 font-bold' : 'text-slate-500'}`}>
              {(downloaded.includes('p12') || downloaded.includes('mobileconfig')) ? <Check className="w-3.5 h-3.5" /> : <span className="w-3.5 h-3.5 rounded-full border border-slate-600 inline-block" />}
              Downloaded
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => handleDownload('p12')} disabled={!!downloading}
            className="px-3 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5" />
            <span>{downloading === 'p12' ? 'Preparing…' : '.p12 bundle'}</span>
          </button>
          <button
            onClick={() => handleDownload('mobileconfig')} disabled={!!downloading}
            className="px-3 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            <Apple className="w-3.5 h-3.5" />
            <span>{downloading === 'mobileconfig' ? 'Preparing…' : 'Apple profile'}</span>
          </button>
        </div>

        <button
          onClick={attemptClose}
          className={`w-full py-2.5 rounded-xl text-xs font-bold transition ${secured ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20' : 'bg-slate-800 text-slate-500 cursor-not-allowed'}`}
        >
          {secured ? 'Done — password secured' : 'Copy the password or download a bundle to continue'}
        </button>
      </div>
    </div>
  );
}
