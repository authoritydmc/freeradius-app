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
  Ban,
  Eye,
  Copy,
  Check,
  FileText
} from 'lucide-react';
import { formatDateTime, fetchJson } from '../utils/api';
import CertIssuedModal from './CertIssuedModal';
import { AsyncButton } from './ActionButton';

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

  // Certificate Inspector Modal State
  const [inspectCert, setInspectCert] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [showRawCert, setShowRawCert] = useState(false);
  const [copiedFingerprint, setCopiedFingerprint] = useState(false);

  const handleInspectCert = async (username) => {
    setInspectLoading(true);
    try {
      const data = await fetchJson(`certs/${encodeURIComponent(username)}/inspect`);
      setInspectCert(data);
      setShowRawCert(false);
      setCopiedFingerprint(false);
    } catch (err) {
      onNotify?.(err.message || `Failed to inspect certificate for '${username}'`, 'error');
    } finally {
      setInspectLoading(false);
    }
  };

  const handleCopyFingerprint = (text) => {
    navigator.clipboard?.writeText(text);
    setCopiedFingerprint(true);
    setTimeout(() => setCopiedFingerprint(false), 2000);
  };

  const [internalUsers, setInternalUsers] = useState([]);
  const [showIssuePassword, setShowIssuePassword] = useState(false);
  // Gated handoff when the server generated the bundle password
  const [certIssued, setCertIssued] = useState(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [cData, sData, uData] = await Promise.all([
        fetchJson('certs'),
        fetchJson('certs/signer-status'),
        fetchJson('users').catch(() => [])
      ]);
      setInternalCerts(cData?.certificates || cData || []);
      setInternalOrphans(cData?.orphans || []);
      setInternalSignerStatus(sData);
      setInternalUsers(Array.isArray(uData) ? uData : (uData?.users || []));
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
  const users = internalUsers || [];

  const handleGeneratePassword = () => {
    const chars = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#$%-_=+";
    const pass = Array.from({ length: 16 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
    setIssueForm(prev => ({ ...prev, cert_password: pass }));
    setShowIssuePassword(true);
  };

  const handleOpenIssue = () => {
    setIssueForm({
      username: '',
      cert_password: '',
      valid_days: 365,
      email: ''
    });
    setShowIssuePassword(false);
    setIssueModalOpen(true);
  };

  const handleSubmitIssue = async (e) => {
    e.preventDefault();
    setIssuing(true);
    try {
      if (propOnIssueCert) {
        await propOnIssueCert(issueForm);
      } else {
        const res = await fetchJson('certs/issue', {
          method: 'POST',
          body: JSON.stringify(issueForm)
        });
        // Blank password field => server generated it: hand over via gated popup
        if (!issueForm.cert_password?.trim() && res.p12_password) {
          setCertIssued({ username: res.username || issueForm.username, p12_password: res.p12_password, authority: res.authority });
        } else {
          onNotify?.(`Certificate issued for '${issueForm.username}'!`, 'success');
        }
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
    if (!window.confirm(`Are you sure you want to REVOKE the certificate for user '${username}'? This immediately invalidates their 802.1X EAP-TLS network access.`)) return false;
    try {
      const res = await fetchJson(`certs/${encodeURIComponent(username)}/revoke`, {
        method: 'POST'
      });
      onNotify?.(res.message || `Certificate for '${username}' revoked successfully!`, 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to revoke certificate', 'error');
      throw err;
    }
  };

  const handleCleanupOrphan = async (username) => {
    if (!window.confirm(`Purge orphaned certificate files for '${username}'?`)) return;
    try {
      await fetchJson(`certs/${encodeURIComponent(username)}/revoke`, { method: 'POST' });
      onNotify?.(`Purged orphan certificate files for '${username}'`, 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to purge orphan certificate files', 'error');
    }
  };

  const onCleanupOrphan = propOnCleanupOrphan || handleCleanupOrphan;

  const handleDeleteCert = async (username) => {
    if (!window.confirm(`DELETE the certificate for '${username}'? It will be revoked upstream (signer CRL) and the local bundle removed. This cannot be undone.`)) return false;
    try {
      const res = await fetchJson(`certs/${encodeURIComponent(username)}`, {
        method: 'DELETE'
      });
      onNotify?.(res.message || `Certificate files for '${username}' deleted`, 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to delete certificate', 'error');
      throw err;
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
                signerStatus?.mode === 'central' || signerStatus?.mode === 'remote'
                  ? 'bg-purple-500/10 text-purple-300 border-purple-500/20'
                  : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20'
              }`}>
                {signerStatus?.mode === 'central' || signerStatus?.mode === 'remote' ? 'Central Rajlabs-CA API' : 'Local FreeRADIUS CA'}
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
      <div className="bg-slate-900 border border-slate-800 rounded-3xl shadow-sm">
        <div className="table-scroll overflow-x-auto rounded-3xl" style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <table className="w-full min-w-[720px] text-left text-xs">
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
                  <button
                    onClick={() => handleInspectCert(c.username)}
                    title="Inspect X.509 Certificate Chain & Details"
                    className="px-2.5 py-1.5 bg-purple-950/60 hover:bg-purple-900/80 text-purple-300 border border-purple-800/60 rounded-xl text-xs font-bold inline-flex items-center gap-1.5 transition-colors"
                  >
                    <Eye className="w-3.5 h-3.5 text-purple-400" />
                    <span>Inspect</span>
                  </button>

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

                  <AsyncButton
                    onClick={() => handleRevokeCert(c.username)}
                    title="Revoke Certificate (Invalidates EAP-TLS access)"
                    className="p-1.5 text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 rounded-lg transition-colors border border-amber-500/20"
                    idleContent={<Ban className="w-3.5 h-3.5" />}
                  />

                  <AsyncButton
                    onClick={() => handleDeleteCert(c.username)}
                    title="Delete + revoke upstream (CRL)"
                    className="p-1.5 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors border border-rose-500/20"
                    idleContent={<Trash2 className="w-3.5 h-3.5" />}
                  />
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
      {/* X.509 CERTIFICATE INSPECTION / VIEWER MODAL */}
      {/* ---------------------------------------------------- */}
      {inspectCert && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-purple-500/30 rounded-3xl max-w-2xl w-full p-6 space-y-5 shadow-2xl relative max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="flex items-start justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-purple-500/10 text-purple-400 border border-purple-500/20 flex items-center justify-center">
                  <KeyRound className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <span>Certificate Viewer:</span>
                    <span className="font-mono text-purple-300">{inspectCert.username}</span>
                  </h3>
                  <p className="text-xs text-slate-400">Cryptographic X.509 Identity & Chain Hierarchy</p>
                </div>
              </div>
              <button onClick={() => setInspectCert(null)} className="text-slate-400 hover:text-white p-1 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Authority & Status Badges */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div className="bg-slate-950/80 border border-slate-800 rounded-2xl p-3.5 space-y-1">
                <span className="text-[11px] text-slate-400 block font-medium">Issuing Authority Type:</span>
                <div className="flex items-center gap-2">
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                    inspectCert.authority_type.includes('Central')
                      ? 'bg-purple-500/15 text-purple-300 border-purple-500/30'
                      : 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30'
                  }`}>
                    {inspectCert.authority_type}
                  </span>
                </div>
              </div>

              <div className="bg-slate-950/80 border border-slate-800 rounded-2xl p-3.5 space-y-1">
                <span className="text-[11px] text-slate-400 block font-medium">Bundle Format:</span>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 inline-flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" /> PKCS#12 (.p12) EAP-TLS Ready
                </span>
              </div>
            </div>

            {/* Trust Chain Hierarchy */}
            <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-3">
              <div className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 text-purple-400" />
                <span>PKI Certificate Trust Chain</span>
              </div>

              <div className="space-y-2 text-xs font-mono">
                {/* Level 1: Root / Intermediate Issuer */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-start gap-2.5">
                  <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px] font-bold uppercase shrink-0 mt-0.5">
                    Issuer CA
                  </span>
                  <div className="truncate flex-1">
                    <div className="text-slate-200 font-bold break-all">{inspectCert.issuer || inspectCert.chain_issuer}</div>
                    <div className="text-[11px] text-slate-500 font-sans mt-0.5">Signs and anchors trust for 802.1X RADIUS verification</div>
                  </div>
                </div>

                {/* Level 2: End-Entity Client Cert */}
                <div className="ml-5 border-l-2 border-purple-500/40 pl-3">
                  <div className="bg-purple-950/20 border border-purple-500/30 rounded-xl p-3 flex items-start gap-2.5">
                    <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 text-[10px] font-bold uppercase shrink-0 mt-0.5">
                      Client Cert
                    </span>
                    <div className="truncate flex-1">
                      <div className="text-purple-200 font-bold break-all">{inspectCert.subject}</div>
                      <div className="text-[11px] text-slate-400 font-sans mt-0.5">CN: {inspectCert.username} (Zero-Password EAP-TLS Identity)</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Certificate Details Grid */}
            <div className="space-y-3 bg-slate-950/60 border border-slate-800 rounded-2xl p-4 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <span className="text-slate-500 text-[11px] block font-medium">Serial Number</span>
                  <span className="font-mono text-slate-200 font-semibold">{inspectCert.serial || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-500 text-[11px] block font-medium">Subject Alternative Names (SAN)</span>
                  <span className="font-mono text-slate-200">{inspectCert.san_list && inspectCert.san_list.length > 0 ? inspectCert.san_list.join(', ') : 'None'}</span>
                </div>
                <div>
                  <span className="text-slate-500 text-[11px] block font-medium">Valid Not Before</span>
                  <span className="font-mono text-slate-300">{inspectCert.not_before || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-500 text-[11px] block font-medium">Valid Not After</span>
                  <span className="font-mono text-emerald-400 font-medium">{inspectCert.not_after || '—'}</span>
                </div>
              </div>

              {/* SHA-256 Fingerprint */}
              {inspectCert.fingerprint_sha256 && (
                <div className="pt-2 border-t border-slate-800/80">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-slate-500 text-[11px] font-medium">SHA-256 Fingerprint</span>
                    <button
                      onClick={() => handleCopyFingerprint(inspectCert.fingerprint_sha256)}
                      className="text-[11px] text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
                    >
                      {copiedFingerprint ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copiedFingerprint ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                  <div className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 font-mono text-[11px] text-purple-200 break-all select-all">
                    {inspectCert.fingerprint_sha256}
                  </div>
                </div>
              )}
            </div>

            {/* Raw OpenSSL Text Dump (Collapsible) */}
            {inspectCert.raw_text && (
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setShowRawCert(!showRawCert)}
                  className="text-xs text-slate-400 hover:text-purple-300 flex items-center gap-1.5 transition-colors font-medium"
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>{showRawCert ? 'Hide OpenSSL Text Dump' : 'View Full OpenSSL X.509 Text Dump'}</span>
                </button>

                {showRawCert && (
                  <pre className="bg-slate-950 border border-slate-800 rounded-2xl p-4 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-48 scrollbar-thin">
                    {inspectCert.raw_text}
                  </pre>
                )}
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-800">
              <div className="flex items-center gap-2">
                <a
                  href={`/radius/api/certs/${inspectCert.username}/download`}
                  download
                  className="px-3.5 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-bold inline-flex items-center gap-1.5 shadow-md shadow-purple-600/20 transition-all"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download .p12</span>
                </a>
                <a
                  href={`/radius/api/certs/${inspectCert.username}/mobileconfig`}
                  download
                  className="px-3.5 py-2 bg-cyan-950/70 hover:bg-cyan-900/80 text-cyan-300 border border-cyan-800/60 rounded-xl text-xs font-bold inline-flex items-center gap-1.5 transition-colors"
                >
                  <Apple className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Apple Profile</span>
                </a>
              </div>

              <button
                type="button"
                onClick={() => setInspectCert(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- */}
      {/* ISSUE CERTIFICATE MODAL */}
      {/* ---------------------------------------------------- */}
      {issueModalOpen && (() => {
        const cleanUsername = (issueForm.username || '').trim();
        const matchedUser = users.find(u => u.username?.toLowerCase() === cleanUsername.toLowerCase());
        const isExistingUser = Boolean(matchedUser);
        const existingUserGroup = matchedUser?.group || 'user';
        const isSignerCentral = Boolean(signerStatus?.reachable && (signerStatus?.key_valid || signerStatus?.mode === 'remote' || signerStatus?.mode === 'central'));

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
            <div className="bg-slate-900 border border-purple-500/30 rounded-3xl max-w-lg w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <KeyRound className="w-5 h-5 text-purple-400" />
                  <span>Issue EAP-TLS Client Certificate</span>
                </h3>
                <button onClick={() => setIssueModalOpen(false)} className="text-slate-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Real-time Signing CA Authority Indicator */}
              <div className={`p-3.5 rounded-2xl border flex items-center justify-between gap-3 text-xs ${
                isSignerCentral
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                  : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
              }`}>
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${isSignerCentral ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                  <div className="min-w-0">
                    <div className="font-bold flex items-center gap-1.5 truncate">
                      <span>Signing Authority: {isSignerCentral ? 'Central Rajlabs-CA PKI' : 'Local FreeRADIUS Root CA'}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-slate-950/70 border border-slate-700/50 font-mono">
                        {isSignerCentral ? 'External REST API' : 'Internal Appliance CA'}
                      </span>
                    </div>
                    <div className="text-[11px] opacity-80 truncate font-mono mt-0.5">
                      {isSignerCentral 
                        ? `${signerStatus?.host || 'ca.rajlabs.in'} · Latency: ${signerStatus?.latency_ms ? `${signerStatus.latency_ms}ms` : 'Active'}`
                        : '/etc/freeradius/certs/ca.pem (Local Fallback)'}
                    </div>
                  </div>
                </div>
              </div>

              <form onSubmit={handleSubmitIssue} className="space-y-3.5 text-xs">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-slate-300 font-medium">Username / Common Name (CN)</label>
                    {isExistingUser && (
                      <span className="text-[10px] text-emerald-400 font-medium flex items-center gap-1 bg-emerald-500/10 px-1.5 py-0.5 rounded-md border border-emerald-500/20">
                        <CheckCircle2 className="w-3 h-3" /> Existing User (Group: {existingUserGroup})
                      </span>
                    )}
                    {!isExistingUser && cleanUsername && (
                      <span className="text-[10px] text-indigo-300 font-medium flex items-center gap-1 bg-indigo-500/10 px-1.5 py-0.5 rounded-md border border-indigo-500/20">
                        <Sparkles className="w-3 h-3" /> New User (Will Auto-Register)
                      </span>
                    )}
                  </div>
                  <input
                    type="text"
                    list="radius-users-list"
                    value={issueForm.username}
                    onChange={(e) => setIssueForm({ ...issueForm, username: e.target.value })}
                    required
                    placeholder="e.g. raj or member1 or pick existing user..."
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-purple-500 outline-none font-mono"
                  />
                  <datalist id="radius-users-list">
                    {users.map(u => (
                      <option key={u.username} value={u.username}>{u.group ? `Group: ${u.group}` : 'User'}</option>
                    ))}
                  </datalist>
                  <div className="text-[10px] text-slate-500 mt-1">
                    The certificate Common Name (CN) is strictly bound to this username for 802.1X EAP-TLS authentication.
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-slate-300 font-medium">
                      PKCS#12 Bundle Password
                    </label>
                    <button
                      type="button"
                      onClick={handleGeneratePassword}
                      className="text-[10px] text-purple-400 hover:text-purple-300 flex items-center gap-1 font-mono transition"
                    >
                      <Sparkles className="w-3 h-3" /> Auto-Generate
                    </button>
                  </div>
                  <div className="relative">
                    <input
                      type={showIssuePassword ? "text" : "password"}
                      value={issueForm.cert_password}
                      onChange={(e) => setIssueForm({ ...issueForm, cert_password: e.target.value })}
                      placeholder="Leave blank to auto-generate random secure password"
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 pr-20 text-white focus:border-purple-500 outline-none font-mono"
                    />
                    <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                      {issueForm.cert_password && (
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard?.writeText(issueForm.cert_password);
                            onNotify?.('Password copied to clipboard!', 'info');
                          }}
                          title="Copy Password"
                          className="p-1 text-slate-400 hover:text-white"
                        >
                          <Copy className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setShowIssuePassword(!showIssuePassword)}
                        className="p-1 text-slate-400 hover:text-white"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Validity Period</label>
                  <select
                    value={issueForm.valid_days}
                    onChange={(e) => setIssueForm({ ...issueForm, valid_days: Number(e.target.value) })}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-purple-500 outline-none"
                  >
                    <option value={30}>30 Days (Guest / Short-lived)</option>
                    <option value={90}>90 Days (Quarterly — Recommended)</option>
                    <option value={180}>180 Days (Semi-Annual)</option>
                    <option value={365}>365 Days (1 Year — Enterprise)</option>
                    <option value={730}>730 Days (2 Years)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Subject Alternative Name (SAN) Email (Optional)</label>
                  <input
                    type="email"
                    value={issueForm.email}
                    onChange={(e) => setIssueForm({ ...issueForm, email: e.target.value })}
                    placeholder="e.g. user@rajlabs.in"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-purple-500 outline-none font-mono"
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
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
                    className="px-5 py-2.5 bg-purple-600 hover:bg-purple-500 text-white rounded-xl font-bold shadow-lg shadow-purple-600/25 disabled:opacity-50 flex items-center gap-2 transition"
                  >
                    <Sparkles className="w-4 h-4" />
                    <span>{issuing ? 'Signing with CA...' : 'Sign & Issue Certificate'}</span>
                  </button>
                </div>
              </form>
            </div>
          </div>
        );
      })()}

      {/* Issued-cert handoff (gated on copy/download) */}
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
