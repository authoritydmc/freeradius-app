import React from 'react';
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

export default function StatusTab({ 
  health, 
  stats, 
  publicConfig, 
  signerStatus, 
  auditLogs, 
  statusCheckedAt, 
  onRefreshAll, 
  onJumpTab 
}) {
  const isHealthy = health?.status === 'healthy';

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
              <span className={`w-2.5 h-2.5 rounded-full ${health?.api_ok ? 'bg-emerald-400' : 'bg-rose-400'}`} />
            </div>
            <div className={`text-xl font-black mt-2 ${health?.api_ok ? 'text-emerald-400' : 'text-rose-400'}`}>
              {health?.api_ok ? 'Operational' : 'Unavailable'}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono">FastAPI :8090 /radius/api</div>
          </div>

          {/* Database */}
          <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300">PostgreSQL 16</span>
              <span className={`w-2.5 h-2.5 rounded-full ${health?.db_ok ? 'bg-emerald-400' : 'bg-rose-400'}`} />
            </div>
            <div className={`text-xl font-black mt-2 ${health?.db_ok ? 'text-emerald-400' : 'text-rose-400'}`}>
              {health?.db_ok ? 'Connected' : 'Disconnected'}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono">radcheck · radacct · radreply</div>
          </div>

          {/* FreeRADIUS Daemon */}
          <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300">FreeRADIUS AAA</span>
              <span className={`w-2.5 h-2.5 rounded-full ${health?.radius_ok ? 'bg-emerald-400' : 'bg-rose-400'}`} />
            </div>
            <div className={`text-xl font-black mt-2 ${health?.radius_ok ? 'text-emerald-400' : 'text-rose-400'}`}>
              {health?.radius_ok ? 'Active / Listening' : 'Daemon Offline'}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono">UDP 1812 · 1813 · 3799 CoA</div>
          </div>

          {/* CA Signer Service */}
          <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300">Rajlabs-CA Signer</span>
              <span className={`w-2.5 h-2.5 rounded-full ${signerStatus?.reachable ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            </div>
            <div className={`text-xl font-black mt-2 ${signerStatus?.reachable ? 'text-emerald-400' : 'text-amber-400'}`}>
              {signerStatus?.mode === 'central' ? (signerStatus?.key_valid ? 'Connected (API)' : 'Token Missing') : 'Local CA Ready'}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 font-mono truncate">
              {signerStatus?.mode === 'central' ? 'Central Rajlabs PKI' : 'Local Root CA'}
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
