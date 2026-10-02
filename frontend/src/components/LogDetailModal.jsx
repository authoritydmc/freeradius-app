import React from 'react';
import { X, FileText, ShieldCheck, CheckCircle2, XCircle, Clock, Globe, Smartphone } from 'lucide-react';
import { formatDateTime, WIFI_PORTAL_BASE_URL } from '../utils/api';
import { CopyButton } from './ActionButton';

/** Common EAP outer-method numbers (from radpostauth.eap_type). */
const EAP_NAMES = { 1: 'Identity', 4: 'MD5-Challenge', 13: 'EAP-TLS', 21: 'EAP-TTLS', 25: 'PEAP', 26: 'MS-CHAPv2' };
export function eapName(t) {
  if (t === null || t === undefined || t === '') return null;
  const n = String(t).trim();
  return EAP_NAMES[n] ? `${EAP_NAMES[n]} (${n})` : n;
}

/** True when the row only carries the EAP outer identity (real user hidden in the TLS tunnel). */
export function isOuterIdentity(username) {
  const u = String(username || '').trim().toLowerCase();
  return u === '' || u === 'anonymous';
}

/** Turn `k=v k2="v 2"` / `{'k': 'v'}` details into chips; null if not parseable. */
export function parseDetailPairs(detail) {
  if (!detail || typeof detail !== 'string') return null;
  let s = detail.trim();
  // Python-dict repr -> JSON attempt
  if (s.startsWith('{') && s.endsWith('}')) {
    try {
      const obj = JSON.parse(s.replace(/'/g, '"'));
      const entries = Object.entries(obj);
      if (entries.length) return entries.map(([k, v]) => ({ k, v: String(v) }));
    } catch { /* fall through to k=v scan */ }
  }
  const pairs = [];
  const re = /([A-Za-z_][\w-]*)=("[^"]*"|'[^']*'|\S+)/g;
  let m;
  while ((m = re.exec(s)) !== null) {
    pairs.push({ k: m[1], v: m[2].replace(/^["']|["']$/g, '') });
  }
  // Only treat as structured when it covers most of the string
  const covered = pairs.reduce((n, p) => n + p.k.length + p.v.length + 1, 0);
  if (pairs.length >= 2 && covered >= s.length * 0.5) return pairs;
  if (pairs.length === 1 && s.length < 80) return pairs;
  return null;
}

/**
 * LogDetailModal — dossier-style full view for one log row (auth verdict or
 * audit event). Nothing truncated: full reason/detail, parsed chips, copy.
 */
export default function LogDetailModal({ entry, onClose, onNotify }) {
  if (!entry) return null;
  const isAuth = entry.kind === 'auth';
  const accept = isAuth
    ? (entry.event === 'accept' || entry.reply === 'Access-Accept')
    : null;
  const pairs = parseDetailPairs(entry.detail || entry.reason || '');
  const outer = isAuth && isOuterIdentity(entry.username);
  const eap = isAuth ? eapName(entry.eap_type) : null;
  const ctxChips = isAuth
    ? [
        eap ? ['EAP method', eap] : null,
        entry.calling_station ? ['Device MAC', entry.calling_station] : null,
        entry.called_station ? ['AP / SSID', entry.called_station] : null,
      ].filter(Boolean)
    : [];
  const noReason = isAuth && !accept && !(entry.reason || '').trim();
  const portalTestUrl = outer
    ? `${WIFI_PORTAL_BASE_URL}/radius/portal`
    : `${WIFI_PORTAL_BASE_URL}/radius/portal?user=${encodeURIComponent(entry.username || '')}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-700 rounded-3xl max-w-lg w-full p-6 space-y-4 shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            {isAuth ? <Clock className="w-5 h-5 text-sky-400" /> : <ShieldCheck className="w-5 h-5 text-indigo-400" />}
            <span>{isAuth ? 'Auth event detail' : 'Audit event detail'}</span>
            {isAuth && (
              accept ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Accept
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-500/10 text-rose-300 border border-rose-500/30">
                  <XCircle className="w-3.5 h-3.5" /> Reject
                </span>
              )
            )}
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2.5 text-xs">
          {[
            ['When', formatDateTime(entry.timestamp || entry.ts || entry.authdate)],
            isAuth
              ? ['Reply', entry.reply || '—']
              : ['Action', entry.action || '—'],
            isAuth
              ? ['User', entry.username || '—']
              : ['Admin', entry.admin_user || '—'],
            isAuth
              ? ['Source', 'radpostauth']
              : ['Target', entry.target_user || '—'],
          ].map(([k, v]) => (
            <div key={k} className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">{k}</div>
              <div className="text-slate-100 font-mono font-semibold truncate" title={String(v)}>{String(v)}</div>
            </div>
          ))}
        </div>

        <div>
          <div className="text-[11px] uppercase tracking-wider text-slate-500 mb-1.5">
            {isAuth ? 'Reject reason / detail' : 'Full detail'}
          </div>
          {outer && (
            <div className="mb-2 p-2.5 bg-amber-500/10 border border-amber-500/30 rounded-xl text-[11px] text-amber-200 flex items-start gap-2">
              <Smartphone className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
              <span>
                <strong>Outer EAP identity only</strong> — the phone hid the real username inside the encrypted
                tunnel, so this row can't say who failed. Match it by time + device MAC below, then ask that
                user to test their password at the portal.
              </span>
            </div>
          )}
          {ctxChips.length > 0 && (
            <div className="space-y-1.5 mb-2">
              {ctxChips.map(([k, v], i) => (
                <div key={i} className="flex items-start justify-between gap-2 bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs">
                  <span className="font-mono text-indigo-300 font-semibold shrink-0">{k}</span>
                  <span className="font-mono text-slate-200 text-right break-all">{v || '—'}</span>
                </div>
              ))}
            </div>
          )}
          {noReason ? (
            <div className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-xs text-slate-300 space-y-1.5">
              <p className="font-mono">Rejected (this attempt was logged before the server stored reasons — redeploy to record them).</p>
              <p className="text-slate-400">Most likely causes, in order: wrong Wi-Fi password · account expired / no active subscription · device MAC not verified · EAP server not trusted on the phone. Send the user to the portal to test their login and recharge.</p>
            </div>
          ) : pairs ? (
            <div className="space-y-1.5">
              {pairs.map((p, i) => (
                <div key={i} className="flex items-start justify-between gap-2 bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs">
                  <span className="font-mono text-indigo-300 font-semibold shrink-0">{p.k}</span>
                  <span className="font-mono text-slate-200 text-right break-all">{p.v || '—'}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-xs font-mono text-slate-200 whitespace-pre-wrap break-all">
              {entry.detail || entry.reason || entry.rule || '—'}
            </div>
          )}
        </div>

        {isAuth && !accept && (
          <a
            href={portalTestUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-2 w-full py-2.5 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-500/25 transition"
          >
            <Globe className="w-4 h-4" />
            <span>Open captive portal — user tests login & recharges here</span>
          </a>
        )}

        <div className="flex justify-between items-center gap-2 pt-1">
          <CopyButton
            text={JSON.stringify(entry, null, 2)}
            title="Copy full event as JSON"
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold flex items-center gap-1.5"
            iconClassName="w-3.5 h-3.5"
            onCopied={() => onNotify?.('Event copied as JSON', 'success')}
          >
            <span>Copy JSON</span>
          </CopyButton>
          <button onClick={onClose} className="px-5 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-xs font-bold">
            Close
          </button>
        </div>

        <p className="text-[10px] text-slate-600 text-center font-mono flex items-center justify-center gap-1">
          <FileText className="w-3 h-3" /> Secrets are redacted in audit details server-side
        </p>
      </div>
    </div>
  );
}
