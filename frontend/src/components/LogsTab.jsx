import React, { useState, useEffect } from 'react';
import { 
  FileText, Shield, CheckCircle2, XCircle, RefreshCw, 
  Search, Filter, Clock, User, AlertCircle, Terminal, Layers
} from 'lucide-react';
import { fetchJson, formatDateTime } from '../utils/api';

export default function LogsTab({ onNotify }) {
  const [activeSubTab, setActiveSubTab] = useState('auth'); // 'auth' or 'audit'
  const [authLogs, setAuthLogs] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterResult, setFilterResult] = useState('all'); // 'all', 'accept', 'reject'

  const loadLogs = async () => {
    try {
      setLoading(true);
      if (activeSubTab === 'auth') {
        let q = `auth-logs?limit=100`;
        if (filterResult !== 'all') q += `&result=${filterResult}`;
        const data = await fetchJson(q);
        setAuthLogs(data || []);
      } else {
        const data = await fetchJson('audit?limit=100');
        setAuditLogs(data || []);
      }
    } catch (err) {
      onNotify?.(err.message || 'Failed to load log events', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [activeSubTab, filterResult]);

  const filteredAuth = authLogs.filter(l =>
    (l.username || '').toLowerCase().includes(search.toLowerCase()) ||
    (l.reply || '').toLowerCase().includes(search.toLowerCase()) ||
    (l.reason || '').toLowerCase().includes(search.toLowerCase())
  );

  const filteredAudit = auditLogs.filter(l =>
    (l.admin_user || '').toLowerCase().includes(search.toLowerCase()) ||
    (l.action || '').toLowerCase().includes(search.toLowerCase()) ||
    (l.target_user || '').toLowerCase().includes(search.toLowerCase()) ||
    (l.detail || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-sky-500/10 rounded-xl border border-sky-500/20 text-sky-400">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">System Logs & Security Audit Trail</h2>
            <p className="text-xs text-slate-400">RADIUS post-auth events and administrative change history</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 w-full sm:w-auto">
          {/* Sub-tab switcher */}
          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs font-medium">
            <button
              onClick={() => setActiveSubTab('auth')}
              className={`px-3 py-1.5 rounded-lg transition ${activeSubTab === 'auth' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
            >
              RADIUS Auth Events
            </button>
            <button
              onClick={() => setActiveSubTab('audit')}
              className={`px-3 py-1.5 rounded-lg transition ${activeSubTab === 'audit' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
            >
              Admin Audit Log
            </button>
          </div>

          {activeSubTab === 'auth' && (
            <select
              value={filterResult}
              onChange={e => setFilterResult(e.target.value)}
              className="bg-slate-950 border border-slate-700/70 text-xs rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-sky-500"
            >
              <option value="all">All Verdicts</option>
              <option value="accept">Accepts Only</option>
              <option value="reject">Rejections Only</option>
            </select>
          )}

          <div className="relative flex-1 sm:w-48">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search logs..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700/70 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
            />
          </div>

          <button
            onClick={loadLogs}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700 transition"
            title="Refresh Logs"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-sky-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Auth Logs Table */}
      {activeSubTab === 'auth' ? (
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950/80 text-[11px] uppercase tracking-wider text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="py-3.5 px-4 font-semibold">User</th>
                  <th className="py-3.5 px-4 font-semibold">Verdict</th>
                  <th className="py-3.5 px-4 font-semibold">Reason / Detail</th>
                  <th className="py-3.5 px-4 font-semibold">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {loading && authLogs.length === 0 ? (
                  <tr>
                    <td colSpan="4" className="py-12 text-center text-slate-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-sky-400" />
                      <span>Loading authentication logs...</span>
                    </td>
                  </tr>
                ) : filteredAuth.length === 0 ? (
                  <tr>
                    <td colSpan="4" className="py-12 text-center text-slate-400">
                      <FileText className="w-10 h-10 mx-auto mb-2 text-slate-600 opacity-50" />
                      <p className="font-medium text-slate-300">No RADIUS Authentication Events</p>
                      <p className="text-xs text-slate-500 mt-1">RADIUS Access-Request attempts will be recorded here via radpostauth.</p>
                    </td>
                  </tr>
                ) : (
                  filteredAuth.map((log, idx) => {
                    const isAccept = log.event === 'accept' || log.reply === 'Access-Accept';
                    return (
                      <tr key={log.id || idx} className="hover:bg-slate-800/40 transition">
                        <td className="py-3 px-4 font-mono font-bold text-slate-200">
                          {log.username}
                        </td>
                        <td className="py-3 px-4">
                          {isAccept ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Access-Accept
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
                              <XCircle className="w-3.5 h-3.5" /> Access-Reject
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-xs text-slate-300">
                          {log.reason || log.rule || '—'}
                        </td>
                        <td className="py-3 px-4 text-xs font-mono text-slate-400">
                          {formatDateTime(log.timestamp || log.authdate)}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Audit Logs Table */
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950/80 text-[11px] uppercase tracking-wider text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="py-3.5 px-4 font-semibold">Admin</th>
                  <th className="py-3.5 px-4 font-semibold">Action</th>
                  <th className="py-3.5 px-4 font-semibold">Target Entity</th>
                  <th className="py-3.5 px-4 font-semibold">Details</th>
                  <th className="py-3.5 px-4 font-semibold">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {loading && auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan="5" className="py-12 text-center text-slate-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-400" />
                      <span>Loading admin audit trail...</span>
                    </td>
                  </tr>
                ) : filteredAudit.length === 0 ? (
                  <tr>
                    <td colSpan="5" className="py-12 text-center text-slate-400">
                      <Shield className="w-10 h-10 mx-auto mb-2 text-slate-600 opacity-50" />
                      <p className="font-medium text-slate-300">No Administrative Audit Events Found</p>
                    </td>
                  </tr>
                ) : (
                  filteredAudit.map(a => (
                    <tr key={a.id} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-4 font-bold text-slate-200 text-xs font-mono">
                        {a.admin_user}
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-xs font-mono font-medium">
                          {a.action}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-xs font-mono text-cyan-300 font-semibold">
                        {a.target_user || '—'}
                      </td>
                      <td className="py-3 px-4 text-xs text-slate-400 max-w-md truncate" title={a.detail}>
                        {a.detail || '—'}
                      </td>
                      <td className="py-3 px-4 text-xs font-mono text-slate-400">
                        {formatDateTime(a.ts)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
