import React from 'react';
import { Sparkles, CheckCircle2, Shield, X, Tag, Calendar, Layers, Terminal, RefreshCw } from 'lucide-react';

const RELEASES = [
  {
    version: 'v2.5.0',
    date: 'October 2, 2026',
    tag: 'Latest Enterprise Release',
    highlights: [
      'Modern React 18 + Tailwind CSS + Lucide Icons Single-Page-Application redesign',
      'Dual Login: Username/Password + X.509 Cryptographic Certificate Authentication',
      'Direct Connect Wi-Fi QR Code with standard schema scannable by phone cameras',
      'Zero-Hardcoding: Strictly dynamic administrative role resolution via DB & groups',
      'Central PKI Cert-Signer API integration with real-time health probe & key testing',
      '1-Click Guest Pass generator with customizable expiry duration dropdown (1h to 30d)',
      'Self-Service Captive Portal with EAP-TLS profile generation & Root CA download'
    ]
  },
  {
    version: 'v2.4.0',
    date: 'September 2026',
    tag: 'Security & PKI Hardening',
    highlights: [
      'RFC 5176 CoA Disconnect integration for live session termination',
      'Device MAC locking and IEEE OUI hardware vendor identification',
      'Sliding-window token bucket IP rate limiting on authentication and CSR endpoints',
      'PostgreSQL connection pooling with automated health self-healing'
    ]
  },
  {
    version: 'v2.0.0',
    date: 'August 2026',
    tag: 'Enterprise Core',
    highlights: [
      'WPA2/WPA3 Enterprise 802.1X FreeRADIUS AAA core with multi-NAS support',
      'PostgreSQL backend schemas for radcheck, radreply, radusergroup, and radacct',
      'Automated background accounting and session data usage accounting'
    ]
  }
];

export default function ChangelogModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="bg-slate-900 border border-slate-750 rounded-3xl w-full max-w-xl max-h-[85vh] overflow-hidden shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/60">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Release Notes & Changelog</h3>
              <p className="text-xs text-slate-400">RajLabs FreeRADIUS Enterprise AAA Platform</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-lg transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content list */}
        <div className="p-6 overflow-y-auto space-y-6 text-slate-300 text-xs">
          {RELEASES.map(rel => (
            <div key={rel.version} className="bg-slate-950/70 border border-slate-800 rounded-2xl p-5 space-y-3">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-sm text-white px-2.5 py-0.5 rounded-lg bg-indigo-500/20 border border-indigo-500/30 text-indigo-300">
                    {rel.version}
                  </span>
                  <span className="text-slate-400 text-[11px] flex items-center gap-1">
                    <Calendar className="w-3.5 h-3.5 text-slate-500" /> {rel.date}
                  </span>
                </div>
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                  {rel.tag}
                </span>
              </div>

              <ul className="space-y-1.5 pt-1">
                {rel.highlights.map((h, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-slate-300">
                    <CheckCircle2 className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                    <span>{h}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-800 bg-slate-950/60 flex justify-between items-center text-xs text-slate-400">
          <span>Current Version: <strong className="text-white font-mono">v2.5.0</strong></span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl font-medium transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
