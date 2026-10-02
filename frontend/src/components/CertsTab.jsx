import React, { useState, useEffect } from 'react';
import { 
  KeyRound, 
  Plus, 
  Download, 
  ShieldCheck, 
  CheckCircle2, 
  Trash2, 
  Apple, 
  FileCode, 
  X, 
  Radio, 
  Sparkles, 
  RotateCw,
  AlertCircle,
  ShieldAlert,
  Ban
} from 'lucide-react';
import { formatDateTime, fetchJson } from '../utils/api';

export default function CertsTab({
  certs: propCerts,
  orphans: propOrphans,
  signerStatus: propSignerStatus,
  onIssueCert: propOnIssueCert,
  onCleanupOrphan: propOnCleanupOrphan,
  onRefreshSignerStatus: propOnRefreshSignerStatus,
  onRefreshCerts: propOnRefreshCerts,
  onNotify
}) {
  const [internalCerts, setInternalCerts] = useState([]);
  const [internalOrphans, setInternalOrphans] = useState([]);
  const [internalSignerStatus, setInternalSignerStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [issueModalOpen, setIssueModalOpen] = useState(false);
  const [issueForm, setIssueForm] = useState({
    username: '',
    cert_password: '',
    valid_days: 365,
    email: ''
  });
  const [issuing, setIssuing] = useState(false);

  const loadData = async () => {
    try {
      setLoading(true);
      const [cData, sData] = await Promise.all([
        fetchJson('certs'),
        fetchJson('certs/signer-status')
      ]);
      setInternalCerts(cData?.certificates || cData || []);
      setInternalOrphans(cData?.orphans || []);
      setInternalSignerStatus(sData);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load certificate inventory', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!propCerts) {
      loadData();
    }
  }, [propCerts]);

  const certs = propCerts || internalCerts;
  const orphans = propOrphans || internalOrphans;
  const signerStatus = propSignerStatus || internalSignerStatus;

  const handleOpenIssue = () => {
    setIssueForm({
      username: '',
      cert_password: '',
      valid_days: 365,
      email: ''
    });
    setIssueModalOpen(true);
  };

  const handleSubmitIssue = async (e) => {
    e.preventDefault();
    setIssuing(true);
    try {
      if (propOnIssueCert) {
        await propOnIssueCert(issueForm);
      } else {
        await fetchJson('certs/issue', {
          method: 'POST',
          body: JSON.stringify(issueForm)
        });
        onNotify?.(`Certificate issued for '${issueForm.username}'!`, 'success');
        loadData();
      }
      setIssueModalOpen(false);
    } catch (err) {
      onNotify?.(err.message || 'Failed to issue certificate', 'error');
    } finally {
      setIssuing(false);
    }
  };

  const handleRefreshSigner = async () => {
    if (propOnRefreshSignerStatus) {
      propOnRefreshSignerStatus();
      return;
    }
    try {
      const s = await fetchJson('certs/signer-status?refresh=true');
      setInternalSignerStatus(s);
      onNotify?.('Signer connection probed', 'info');
    } catch (err) {
      onNotify?.(err.message || 'Probe failed', 'error');
    }
  };

  const handleRevokeCert = async (username) => {
    if (!window.confirm(`Are you sure you want to REVOKE the certificate for user '${username}'? This immediately invalidates their 802.1X EAP-TLS network access.`)) return;
    try {
      const res = await fetchJson(`certs/${encodeURIComponent(username)}/revoke`, {
        method: 'POST'
      });
      onNotify?.(res.message || `Certificate for '${username}' revoked successfully!`, 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to revoke certificate', 'error');
    }
  };

  const handleDeleteCert = async (username) => {
    if (!window.confirm(`Are you sure you want to permanently DELETE the certificate bundle files for '${username}'?`)) return;
    try {
      const res = await fetchJson(`certs/${encodeURIComponent(username)}`, {
        method: 'DELETE'
      });
      onNotify?.(res.message || `Certificate files for '${username}' deleted`, 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to delete certificate', 'error');
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      
      {/* Top Banner & CA Signer Status */}
      <div className="bg-slate-900/60 p-5 rounded-3xl border border-slate-800 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <KeyRound className="w-5 h-5 text-purple-400" />
            <span>EAP-TLS X.509 Client Certificates</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Issue cryptographically verified PKCS#12 bundles (.p12) and Apple WiFi profiles for zero-password 802.1X.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <a
            href="/radius/api/certs/ca"
            download
            className="px-4 py-2 bg-indigo-950/70 hover:bg-indigo-900/80 text-indigo-300 border border-indigo-800/60 rounded-xl text-xs font-bold flex items-center gap-2 transition-all shadow-sm"
          >
            <Download className="w-4 h-4" />
            <span>Download Root CA (.pem)</span>
          </a>

          <button
            onClick={handleOpenIssue}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-bold flex items-center gap-2 shadow-lg shadow-purple-600/25 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Issue Certificate</span>
          </button>
        </div>
      </div>

      {/* Central CA vs Local Signer Status Bar */}
      <div className="bg-slate-900 border border-slate-800 p-4 rounded-2xl flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-purple-500/10 text-purple-400 flex items-center justify-center shrink-0">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="font-bold text-white flex items-center gap-2">
              <span>Signer Authority:</span>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono border ${
                signerStatus?.mode === 'central'
                  ? 'bg-purple-500/10 text-purple-300 border-purple-500/20'
                  : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20'
              }`}>
                {signerStatus?.mode === 'central' ? 'Central Rajlabs-CA API' : 'Local FreeRADIUS CA'}
              </span>
            </div>
            <div className="text-slate-400 text-[11px] mt-0.5">
              {signerStatus?.detail || 'Ready for EAP-TLS client authentication.'}
            </div>
          </div>
        </div>

        <button
          onClick={handleRefreshSigner}
          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs flex items-center gap-1.5 transition-colors"
        >
          <RotateCw className="w-3.5 h-3.5" />
          <span>Probe Signer</span>
        </button>
      </div>

      {/* Certificates Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-sm">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-950/60 text-slate-400 uppercase border-b border-slate-800 text-[10px] tracking-wider">
            <tr>
              <th className="px-6 py-4">Client Identity (CN)</th>
              <th className="px-6 py-4">Status & Files</th>
              <th className="px-6 py-4">Issued Date</th>
              <th className="px-6 py-4 text-right">Downloads</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/80">
            {certs.map((c) => (
              <tr key={c.username} className="hover:bg-slate-800/40 transition-colors">
                <td className="px-6 py-4 font-semibold text-white">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20 flex items-center justify-center font-mono font-bold text-xs">
                      {c.username.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div className="font-bold text-slate-100">{c.username}</div>
                      <div className="text-[10px] text-slate-500 font-mono">{c.p12_file}</div>
                    </div>
                  </div>
                </td>

                <td className="px-6 py-4">
                  <span className="px-2.5 py-1 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold text-[10px] flex items-center gap-1.5 w-max">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Valid EAP-TLS Bundle
                  </span>
                </td>

                <td className="px-6 py-4 text-slate-400 font-mono text-[11px]">
                  {c.created_at ? new Date(c.created_at * 1000).toLocaleString() : '—'}
                </td>

                <td className="px-6 py-4 text-right space-x-1.5 whitespace-nowrap">
                  <a
                    href={`/radius/api/certs/${c.username}/download`}
                    download
                    title="Download PKCS#12 bundle (.p12)"
                    className="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-bold inline-flex items-center gap-1.5 transition-colors"
                  >
                    <Download className="w-3.5 h-3.5 text-indigo-400" />
                    <span>.p12</span>
                  </a>
                  
                  <a
                    href={`/radius/api/certs/${c.username}/mobileconfig`}
                    download
                    title="Download Apple iOS/macOS profile"
                    className="px-2.5 py-1.5 bg-cyan-950/60 hover:bg-cyan-900/80 text-cyan-300 border border-cyan-800/60 rounded-xl text-xs font-bold inline-flex items-center gap-1.5 transition-colors"
                  >
                    <Apple className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Profile</span>
                  </a>

                  <button
                    onClick={() => handleRevokeCert(c.username)}
                    title="Revoke Certificate (Invalidates EAP-TLS access)"
                    className="p-1.5 text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 rounded-lg transition-colors border border-amber-500/20"
                  >
                    <Ban className="w-3.5 h-3.5" />
                  </button>

                  <button
                    onClick={() => handleDeleteCert(c.username)}
                    title="Delete Certificate Bundle Files"
                    className="p-1.5 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors border border-rose-500/20"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}

            {certs.length === 0 && (
              <tr>
                <td colSpan={4} className="px-6 py-10 text-center text-slate-500 italic">
                  No EAP-TLS client certificates issued yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Orphaned Certificates Section (if any found) */}
      {orphans && orphans.length > 0 && (
        <div className="bg-rose-950/20 border border-rose-500/30 rounded-3xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold text-rose-300 uppercase tracking-wider flex items-center gap-2">
              <Trash2 className="w-4 h-4 text-rose-400" /> Orphaned Certificate Files Detected ({orphans.length})
            </h3>
            <span className="text-[11px] text-slate-400">These files belong to users that were deleted from the database.</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
            {orphans.map((uname) => (
              <div key={uname} className="bg-slate-950/80 border border-slate-800 rounded-2xl p-3 flex items-center justify-between text-xs">
                <span className="font-mono text-white">{uname}</span>
                <button
                  onClick={() => onCleanupOrphan(uname)}
                  className="px-2.5 py-1 bg-rose-600/20 hover:bg-rose-600/40 text-rose-300 border border-rose-500/30 rounded-lg text-[11px] font-semibold transition-colors"
                >
                  Purge Files
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- */}
      {/* ISSUE CERTIFICATE MODAL */}
      {/* ---------------------------------------------------- */}
      {issueModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-purple-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <KeyRound className="w-5 h-5 text-purple-400" />
                <span>Issue EAP-TLS Client Certificate</span>
              </h3>
              <button onClick={() => setIssueModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmitIssue} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Username / Common Name (CN)</label>
                <input
                  type="text"
                  value={issueForm.username}
                  onChange={(e) => setIssueForm({ ...issueForm, username: e.target.value })}
                  required
                  placeholder="e.g. member1 or raj"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-purple-500 outline-none font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">
                  PKCS#12 Export Password <span className="text-slate-500 font-normal">(leave blank for auto-generated)</span>
                </label>
                <input
                  type="password"
                  value={issueForm.cert_password}
                  onChange={(e) => setIssueForm({ ...issueForm, cert_password: e.target.value })}
                  placeholder="••••••••••••"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-purple-500 outline-none font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Validity Period</label>
                <select
                  value={issueForm.valid_days}
                  onChange={(e) => setIssueForm({ ...issueForm, valid_days: Number(e.target.value) })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-purple-500 outline-none"
                >
                  <option value={30}>30 Days (Short-lived)</option>
                  <option value={90}>90 Days (Quarterly)</option>
                  <option value={365}>365 Days (1 Year — Default)</option>
                  <option value={730}>730 Days (2 Years)</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">SAN Email Address (Optional)</label>
                <input
                  type="email"
                  value={issueForm.email}
                  onChange={(e) => setIssueForm({ ...issueForm, email: e.target.value })}
                  placeholder="e.g. user@rajlabs.in"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-purple-500 outline-none font-mono"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIssueModalOpen(false)}
                  className="px-4 py-2 text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={issuing}
                  className="px-5 py-2.5 bg-purple-600 hover:bg-purple-500 text-white rounded-xl font-bold shadow-lg shadow-purple-600/25 disabled:opacity-50 flex items-center gap-2"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>{issuing ? 'Signing with CA...' : 'Sign & Issue Certificate'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
