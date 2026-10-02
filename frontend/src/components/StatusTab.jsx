import React, { useState, useEffect } from 'react';
import { 
  Server, 
  Database, 
  Radio, 
  ShieldCheck, 
  RotateCw, 
  Plug, 
  Users, 
  Activity, 
  KeyRound, 
  Network, 
  Clock 
} from 'lucide-react';
import { fetchJson } from '../utils/api';

export default function StatusTab({ 
  health: propHealth, 
  stats: propStats, 
  publicConfig: propPublicConfig, 
  signerStatus: propSignerStatus, 
  auditLogs: propAuditLogs, 
  statusCheckedAt: propStatusCheckedAt, 
  onRefreshAll: propOnRefreshAll, 
  onJumpTab,
  onNotify
}) {
  const [internalHealth, setInternalHealth] = useState(null);
  const [internalStats, setInternalStats] = useState(null);
  const [internalPublicConfig, setInternalPublicConfig] = useState(null);
  const [internalSignerStatus, setInternalSignerStatus] = useState(null);
  const [internalAuditLogs, setInternalAuditLogs] = useState([]);
  const [internalCheckedAt, setInternalCheckedAt] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async () => {
    setRefreshing(true);
    try {
      const [h, st, pc, ss, logs] = await Promise.allSettled([
        fetchJson('health'),
        fetchJson('stats'),
        fetchJson('public-config'),
        fetchJson('signer/status'),
        fetchJson('audit-logs?limit=5')
      ]);

      if (h.status === 'fulfilled') setInternalHealth(h.value);
      if (st.status === 'fulfilled') setInternalStats(st.value);
      if (pc.status === 'fulfilled') setInternalPublicConfig(pc.value);
      if (ss.status === 'fulfilled') setInternalSignerStatus(ss.value);
      if (logs.status === 'fulfilled') setInternalAuditLogs(logs.value || []);
      setInternalCheckedAt(new Date().toLocaleTimeString());
    } catch (err) {
      onNotify?.(err.message || 'Failed to refresh status data', 'error');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 15000);
    return () => clearInterval(interval);
  }, []);

  const health = propHealth || internalHealth;
  const stats = propStats || internalStats;
  const publicConfig = propPublicConfig || internalPublicConfig;
  const signerStatus = propSignerStatus || internalSignerStatus;
  const auditLogs = propAuditLogs || internalAuditLogs;
  const statusCheckedAt = propStatusCheckedAt || internalCheckedAt;
  const onRefreshAll = propOnRefreshAll || loadData;

  const isApiOk = health ? (health.api_ok !== undefined ? Boolean(health.api_ok) : true) : false;
  const isDbOk = health ? (health.db_ok !== undefined ? Boolean(health.db_ok) : Boolean(health.database?.connected)) : false;
  const isRadiusOk = health ? (health.radius_ok !== undefined ? Boolean(health.radius_ok) : Boolean(health.freeradius_process?.running)) : false;
  const isHealthy = isApiOk && isDbOk;

  const isSignerOnline = signerStatus && (signerStatus.reachable && (signerStatus.key_valid || signerStatus.mode === 'remote' || signerStatus.mode === 'central'));

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      
      {/* Top Controls & Status Pill */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/60 p-4 rounded-3xl border border-slate-800">
        <div className="flex items-center gap-3">
          <span className={`px-3.5 py-1.5 rounded-full text-xs font-bold border flex items-center gap-2 ${
            isHealthy 
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
              : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
          }`}>
            <span className={`w-2.5 h-2.5 rounded-full ${isHealthy ? 'bg-emerald-400 animate-ping' : 'bg-amber-400'}`} />
            <span>{isHealthy ? 'All Systems Operational' : 'System Degraded / Investigating'}</span>
          </span>
          <span className="text-xs text-slate-500 font-mono">
            {statusCheckedAt ? `checked ${statusCheckedAt}` : 'monitoring live'}
          </span>
        </div>

        <button
          onClick={onRefreshAll}
          className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-bold flex items-center gap-2 transition-all"
        >
          <RotateCw className="w-3.5 h-3.5" />
          <span>Refresh All</span>
        </button>
      </div>

      {/* Core Services Health Grid */}
      <div>
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Server className="w-4 h-4 text-indigo-400" /> Core Enterprise Services
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          
          {/* API */}
          <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300">FastAPI Engine</span>
              <span className={`w-2.5 h-2.5 rounded-full ${isApiOk ? 'bg-emerald-400' : 'bg-rose-400'}`} />
            </div>
            <div className={`text-xl font-black mt-2 ${isApiOk ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isApiOk ? 'Operational' : 'Unavailable'}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono">FastAPI :8090 /radius/api</div>
          </div>

          {/* Database */}
          <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300">PostgreSQL 16</span>
              <span className={`w-2.5 h-2.5 rounded-full ${isDbOk ? 'bg-emerald-400' : 'bg-rose-400'}`} />
            </div>
            <div className={`text-xl font-black mt-2 ${isDbOk ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isDbOk ? 'Connected' : 'Disconnected'}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono">radcheck · radacct · radreply</div>
          </div>

          {/* FreeRADIUS Daemon */}
          <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300">FreeRADIUS AAA</span>
              <span className={`w-2.5 h-2.5 rounded-full ${isRadiusOk ? 'bg-emerald-400' : 'bg-rose-400'}`} />
            </div>
            <div className={`text-xl font-black mt-2 ${isRadiusOk ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isRadiusOk ? 'Active / Listening' : 'Daemon Offline'}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono">UDP 1812 · 1813 · 3799 CoA</div>
          </div>

          {/* CA Signer Service */}
          <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300">Rajlabs-CA Signer</span>
              <span className={`w-2.5 h-2.5 rounded-full ${
                !signerStatus 
                  ? 'bg-slate-500 animate-pulse' 
                  : isSignerOnline 
                    ? 'bg-emerald-400' 
                    : signerStatus.reachable 
                      ? 'bg-amber-400' 
                      : 'bg-rose-400'
              }`} />
            </div>
            <div className={`text-xl font-black mt-2 ${
              !signerStatus 
                ? 'text-slate-400' 
                : isSignerOnline 
                  ? 'text-emerald-400' 
                  : signerStatus.reachable 
                    ? 'text-amber-400' 
                    : 'text-rose-400'
            }`}>
              {!signerStatus ? (
                'Checking...'
              ) : isSignerOnline ? (
                'Connected (API)'
              ) : signerStatus.configured && !signerStatus.key_valid && signerStatus.reachable ? (
                'Token Missing'
              ) : signerStatus.mode === 'local' ? (
                'Local CA Ready'
              ) : (
                'Local CA Fallback'
              )}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono truncate">
              {!signerStatus ? (
                'Probing PKI endpoint...'
              ) : isSignerOnline ? (
                `Central Rajlabs PKI (${signerStatus.latency_ms ? `${signerStatus.latency_ms}ms` : 'Active'})`
              ) : (
                'Local FreeRADIUS Root CA'
              )}
            </div>
          </div>

        </div>
      </div>

      {/* RADIUS Gateway Endpoints Information Box */}
      <div>
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Plug className="w-4 h-4 text-indigo-400" /> Router & NAS Gateway Connection Parameters
        </h3>
        <div className="bg-gradient-to-r from-slate-900 via-indigo-950/30 to-slate-900 border border-slate-800 p-5 rounded-3xl grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs font-mono">
          <div className="bg-slate-950/80 p-3.5 rounded-2xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px] mb-1">RADIUS Host / Server:</div>
            <div className="text-indigo-300 font-bold text-sm truncate">
              {publicConfig?.radius_host || window.location.hostname}
            </div>
          </div>
          <div className="bg-slate-950/80 p-3.5 rounded-2xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px] mb-1">Authentication Port (UDP):</div>
            <div className="text-indigo-300 font-bold text-sm">1812 / udp</div>
          </div>
          <div className="bg-slate-950/80 p-3.5 rounded-2xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px] mb-1">Accounting Port (UDP):</div>
            <div className="text-indigo-300 font-bold text-sm">1813 / udp</div>
          </div>
          <div className="bg-slate-950/80 p-3.5 rounded-2xl border border-slate-800/80">
            <div className="text-slate-400 text-[11px] mb-1">RFC 5176 CoA / Disconnect (UDP):</div>
            <div className="text-indigo-300 font-bold text-sm">3799 / udp</div>
          </div>
        </div>
      </div>

      {/* Real-Time Metrics Snapshot */}
      <div>
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Activity className="w-4 h-4 text-indigo-400" /> Network Metrics Snapshot
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <button 
            onClick={() => onJumpTab('users')} 
            className="bg-slate-900 hover:bg-slate-800/80 border border-slate-800 p-4 rounded-2xl flex items-center gap-3.5 transition-all text-left group"
          >
            <div className="w-10 h-10 rounded-2xl bg-indigo-500/10 text-indigo-400 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <div className="text-2xl font-black text-white">{stats?.total_users || 0}</div>
              <div className="text-xs text-slate-400">Total Users</div>
            </div>
          </button>

          <button 
            onClick={() => onJumpTab('sessions')} 
            className="bg-slate-900 hover:bg-slate-800/80 border border-slate-800 p-4 rounded-2xl flex items-center gap-3.5 transition-all text-left group"
          >
            <div className="w-10 h-10 rounded-2xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Radio className="w-5 h-5" />
            </div>
            <div>
              <div className="text-2xl font-black text-emerald-400">{stats?.active_sessions || 0}</div>
              <div className="text-xs text-slate-400">Live Sessions</div>
            </div>
          </button>

          <button 
            onClick={() => onJumpTab('certs')} 
            className="bg-slate-900 hover:bg-slate-800/80 border border-slate-800 p-4 rounded-2xl flex items-center gap-3.5 transition-all text-left group"
          >
            <div className="w-10 h-10 rounded-2xl bg-purple-500/10 text-purple-400 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <KeyRound className="w-5 h-5" />
            </div>
            <div>
              <div className="text-2xl font-black text-purple-400">{stats?.client_certificates || 0}</div>
              <div className="text-xs text-slate-400">Certificates</div>
            </div>
          </button>

          <button 
            onClick={() => onJumpTab('nas')} 
            className="bg-slate-900 hover:bg-slate-800/80 border border-slate-800 p-4 rounded-2xl flex items-center gap-3.5 transition-all text-left group"
          >
            <div className="w-10 h-10 rounded-2xl bg-cyan-500/10 text-cyan-400 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Network className="w-5 h-5" />
            </div>
            <div>
              <div className="text-2xl font-black text-white">{stats?.nas_clients || 0}</div>
              <div className="text-xs text-slate-400">NAS Gateways</div>
            </div>
          </button>
        </div>
      </div>

      {/* Latest Admin Activity Audit Stream */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-2">
            <Clock className="w-4 h-4 text-indigo-400" /> Recent Security Audit Trail
          </h3>
          <button 
            onClick={() => onJumpTab('logs')}
            className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold"
          >
            View Full Log →
          </button>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-sm">
          <table className="w-full text-left text-xs">
            <tbody className="divide-y divide-slate-800/80 font-mono">
              {(auditLogs || []).slice(0, 5).map((a, i) => (
                <tr key={a.id || i} className="hover:bg-slate-800/40 transition-colors">
                  <td className="px-5 py-3 text-slate-500 whitespace-nowrap">{a.ts}</td>
                  <td className="px-5 py-3 font-semibold text-white">{a.admin_user}</td>
                  <td className="px-5 py-3">
                    <span className="px-2.5 py-0.5 rounded-lg text-[10px] font-mono border bg-slate-800 text-slate-300 border-slate-700">
                      {a.action}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-300">{a.target_user || '—'}</td>
                  <td className="px-5 py-3 text-slate-500 truncate max-w-xs">{a.detail || '—'}</td>
                </tr>
              ))}
              {(!auditLogs || auditLogs.length === 0) && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-500 italic font-sans">
                    No admin actions recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
