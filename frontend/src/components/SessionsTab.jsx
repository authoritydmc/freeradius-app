import React, { useState, useEffect } from 'react';
import { 
  Activity, RefreshCw, Search, PowerOff, Shield, Wifi, 
  ArrowDown, ArrowUp, Clock, Smartphone, Globe, AlertCircle, CheckCircle2
} from 'lucide-react';
import { fetchJson, formatBytes, formatDuration, formatDateTime } from '../utils/api';
import { AsyncButton } from './ActionButton';

export default function SessionsTab({ onNotify }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeOnly, setActiveOnly] = useState(true);
  const [search, setSearch] = useState('');
  const [disconnectingId, setDisconnectingId] = useState(null);
  const [gaps, setGaps] = useState([]);

  const loadSessions = async () => {
    try {
      setLoading(true);
      const data = await fetchJson(`accounting?limit=100&active_only=${activeOnly}`);
      setSessions(data || []);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load sessions', 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadGaps = async () => {
    try {
      const res = await fetchJson('accounting/gaps?days=7');
      setGaps(res?.gaps || []);
    } catch {
      setGaps([]);
    }
  };

  useEffect(() => {
    loadSessions();
    loadGaps();
  }, [activeOnly]);

  const handleDisconnect = async (session) => {
    if (!window.confirm(`Force terminate session for '${session.username}' via RFC 5176 CoA Disconnect?`)) return false;
    try {
      setDisconnectingId(session.radacctid);
      const res = await fetchJson('sessions/disconnect', {
        method: 'POST',
        body: JSON.stringify({
          username: session.username,
          nas_ip: session.nasipaddress,
          acct_session_id: session.acctsessionid,
          framed_ip: session.framedipaddress
        })
      });
      if (res.success) {
        onNotify?.(`Session for ${session.username} disconnected!`, 'success');
      } else {
        onNotify?.(res.status || 'CoA packet sent', 'warning');
      }
      loadSessions();
    } catch (err) {
      onNotify?.(err.message || 'Failed to disconnect session', 'error');
      throw err;
    } finally {
      setDisconnectingId(null);
    }
  };

  const filtered = sessions.filter(s =>
    (s.username || '').toLowerCase().includes(search.toLowerCase()) ||
    (s.callingstationid || '').toLowerCase().includes(search.toLowerCase()) ||
    (s.framedipaddress || '').toLowerCase().includes(search.toLowerCase()) ||
    (s.nasipaddress || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-emerald-500/10 rounded-xl border border-emerald-500/20 text-emerald-400">
            <Activity className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Live Accounting & Wi-Fi Sessions</h2>
            <p className="text-xs text-slate-400">Real-time RADIUS sessions, data usage, and RFC 5176 CoA termination</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 w-full sm:w-auto">
          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs font-medium">
            <button
              onClick={() => setActiveOnly(true)}
              className={`px-3 py-1 rounded-lg transition ${activeOnly ? 'bg-emerald-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
            >
              Active Only
            </button>
            <button
              onClick={() => setActiveOnly(false)}
              className={`px-3 py-1 rounded-lg transition ${!activeOnly ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
            >
              All History
            </button>
          </div>

          <div className="relative flex-1 sm:w-60">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search user, IP, MAC..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700/70 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
            />
          </div>

          <button
            onClick={loadSessions}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700 transition"
            title="Refresh Sessions"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-emerald-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Sessions Table */}
      {gaps.length > 0 && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-2xl space-y-2">
          <div className="flex items-center gap-2 text-amber-300 font-bold text-sm">
            <AlertCircle className="w-4 h-4" />
            <span>{gaps.length} user{gaps.length === 1 ? '' : 's'} authenticated but never sent accounting</span>
          </div>
          <p className="text-xs text-amber-200/80">
            {gaps.slice(0, 5).map(g => g.username).join(', ')}{gaps.length > 5 ? ` +${gaps.length - 5} more` : ''} got
            Access-Accept (UDP 1812) in the last 7 days, yet have zero session rows — the AP is not sending
            Accounting (UDP 1813). On the controller/AP check: accounting server IP set, accounting port 1813,
            same shared secret as auth, UDP 1813 allowed through firewalls, and interim updates enabled.
          </p>
        </div>
      )}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="table-scroll overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm text-slate-300">
            <thead className="bg-slate-950/80 text-[11px] uppercase tracking-wider text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-3.5 px-4 font-semibold">User / Client</th>
                <th className="py-3.5 px-4 font-semibold">IP & Station (MAC)</th>
                <th className="py-3.5 px-4 font-semibold">NAS Gateway</th>
                <th className="py-3.5 px-4 font-semibold">Duration / Started</th>
                <th className="py-3.5 px-4 font-semibold">Data Usage (Rx / Tx)</th>
                <th className="py-3.5 px-4 font-semibold">Status</th>
                <th className="py-3.5 px-4 text-right font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loading && sessions.length === 0 ? (
                <tr>
                  <td colSpan="7" className="py-12 text-center text-slate-400">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-emerald-400" />
                    <span>Loading session data...</span>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan="7" className="py-12 text-center text-slate-400">
                    <Activity className="w-10 h-10 mx-auto mb-2 text-slate-600 opacity-50" />
                    <p className="font-medium text-slate-300">No {activeOnly ? 'Active' : ''} Sessions Found</p>
                    <p className="text-xs text-slate-500 mt-1">RADIUS accounting packets (Start/Interim/Stop) will automatically appear here.</p>
                  </td>
                </tr>
              ) : (
                filtered.map(s => {
                  const isActive = !s.acctstoptime;
                  const inBytes = parseInt(s.acctinputoctets) || 0;
                  const outBytes = parseInt(s.acctoutputoctets) || 0;
                  const totalDuration = s.acctsessiontime || 0;

                  return (
                    <tr key={s.radacctid} className="hover:bg-slate-800/40 transition">
                      <td className="py-3.5 px-4">
                        <div className="font-bold text-slate-100 flex items-center gap-1.5 font-mono">
                          {s.username}
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono">ID: {s.acctsessionid || `#${s.radacctid}`}</div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-1.5 font-mono text-cyan-400 text-xs">
                          <Globe className="w-3.5 h-3.5 text-cyan-500" />
                          {s.framedipaddress || 'Dynamic DHCP'}
                        </div>
                        <div className="flex items-center gap-1.5 font-mono text-slate-400 text-[11px] mt-0.5">
                          <Smartphone className="w-3.5 h-3.5 text-slate-500" />
                          {s.callingstationid || '—'}
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="font-mono text-xs text-slate-300">{s.nasipaddress}</div>
                        <div className="text-[11px] text-slate-500">{s.calledstationid || 'Port / SSID'}</div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-1 text-slate-200 text-xs font-mono font-medium">
                          <Clock className="w-3.5 h-3.5 text-amber-400" />
                          {formatDuration(totalDuration)}
                        </div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          {formatDateTime(s.acctstarttime)}
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-1.5 text-xs font-mono">
                          <span className="flex items-center text-emerald-400" title="Download / Rx">
                            <ArrowDown className="w-3 h-3 mr-0.5" /> {formatBytes(inBytes)}
                          </span>
                          <span className="text-slate-600">|</span>
                          <span className="flex items-center text-blue-400" title="Upload / Tx">
                            <ArrowUp className="w-3 h-3 mr-0.5" /> {formatBytes(outBytes)}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400 mt-0.5 font-mono">
                          Total: {formatBytes(inBytes + outBytes)}
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        {isActive ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                            Connected
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-400">
                            {s.acctterminatecause || 'Terminated'}
                          </span>
                        )}
                      </td>

                      <td className="py-3.5 px-4 text-right">
                        {isActive ? (
                          <AsyncButton
                            onClick={() => handleDisconnect(s)}
                            title="Send RFC 5176 Disconnect-Request"
                            className="inline-flex items-center gap-1 px-2.5 py-1 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 rounded-lg text-xs font-medium transition disabled:opacity-50"
                            idleContent={<><PowerOff className="w-3.5 h-3.5" /><span>Disconnect</span></>}
                            okText="Kicked"
                          />
                        ) : (
                          <span className="text-xs text-slate-500">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
