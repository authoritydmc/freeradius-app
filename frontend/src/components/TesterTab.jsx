import React, { useState, useEffect } from 'react';
import {
  Play, Terminal, Shield, CheckCircle2, XCircle, Clock,
  RefreshCw, Cpu, Server, Smartphone, Key, AlertCircle
} from 'lucide-react';
import { fetchJson } from '../utils/api';

export default function TesterTab({ onNotify, initialUsername = '' }) {
  const [form, setForm] = useState({
    username: initialUsername || '',
    password: '',
    nas_ip: '127.0.0.1',
    calling_station_id: ''
  });
  const [users, setUsers] = useState([]);

  // Username autocomplete from the user inventory (best-effort)
  useEffect(() => {
    fetchJson('users').then(u => {
      const list = Array.isArray(u) ? u : (u?.users || []);
      setUsers(list.map(x => x.username).filter(Boolean));
    }).catch(() => {});
  }, []);

  // Deep-link from Users table test button: prefill + focus password
  useEffect(() => {
    if (initialUsername) {
      setForm(prev => ({ ...prev, username: initialUsername }));
      setResult(null);
    }
  }, [initialUsername]);

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const handleTest = async (e) => {
    e.preventDefault();
    try {
      setLoading(true);
      setResult(null);
      const res = await fetchJson('test-auth', {
        method: 'POST',
        body: JSON.stringify(form)
      });
      setResult(res);
      if (res.success) {
        onNotify?.(`Access-Accept received for '${form.username}'!`, 'success');
      } else {
        onNotify?.(`Access-Reject / ${res.status}`, 'warning');
      }
    } catch (err) {
      setResult({
        success: false,
        status: 'Error',
        output: err.message || 'Failed to run RADIUS test.'
      });
      onNotify?.(err.message || 'RADIUS test request failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-violet-500/10 rounded-xl border border-violet-500/20 text-violet-400">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Live RADIUS Protocol & Auth Simulator</h2>
            <p className="text-xs text-slate-400">Execute RFC 2865 Access-Request packets against FreeRADIUS daemon directly</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Input Parameters Form */}
        <div className="lg:col-span-5 bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl">
          <h3 className="text-base font-bold text-white mb-4 flex items-center gap-2">
            <Terminal className="w-4 h-4 text-violet-400" /> Test Parameters
          </h3>

          <form onSubmit={handleTest} className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Username *</label>
              <input
                type="text"
                required
                list="tester-users-list"
                placeholder="e.g. staff_user"
                value={form.username}
                onChange={e => setForm({ ...form, username: e.target.value })}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
              />
              <datalist id="tester-users-list">
                {users.map(u => <option key={u} value={u} />)}
              </datalist>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Password *</label>
              <input
                type="password"
                required
                placeholder="User cleartext password"
                value={form.password}
                onChange={e => setForm({ ...form, password: e.target.value })}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
              />
              <p className="text-[11px] text-slate-500">Server uses its own configured RADIUS secret — no need to enter it.</p>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Calling-Station-Id (Optional MAC)</label>
              <input
                type="text"
                placeholder="e.g. AA:BB:CC:11:22:33 (simulates MAC locking)"
                value={form.calling_station_id}
                onChange={e => setForm({ ...form, calling_station_id: e.target.value })}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
              />
            </div>

            <details className="bg-slate-950/60 border border-slate-800 rounded-xl px-3 py-2">
              <summary className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider cursor-pointer">Advanced: NAS options</summary>
              <div className="space-y-1 pt-2">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">NAS Server IP</label>
                <input
                  type="text"
                  placeholder="127.0.0.1"
                  value={form.nas_ip}
                  onChange={e => setForm({ ...form, nas_ip: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
                />
                <p className="text-[11px] text-slate-500">Default 127.0.0.1 with the server-side secret.</p>
              </div>
            </details>

            <div className="pt-2">
              <button
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-sm font-semibold shadow-lg shadow-violet-500/20 transition disabled:opacity-50"
              >
                {loading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Transmitting RADIUS Packet...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    <span>Run Authentication Test</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Live Packet Output Terminal */}
        <div className="lg:col-span-7 bg-slate-950 border border-slate-800 rounded-2xl flex flex-col overflow-hidden shadow-2xl">
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/80 bg-slate-900/60">
            <div className="flex items-center gap-2">
              <div className="flex gap-1.5">
                <span className="w-3 h-3 rounded-full bg-rose-500/80 inline-block" />
                <span className="w-3 h-3 rounded-full bg-amber-500/80 inline-block" />
                <span className="w-3 h-3 rounded-full bg-emerald-500/80 inline-block" />
              </div>
              <span className="text-xs font-mono text-slate-400 ml-2">radtest / radclient protocol console</span>
            </div>

            {result && (
              <div className="text-right">
                {result.success ? (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {result.status || 'ACCESS-ACCEPT'}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                    <XCircle className="w-3.5 h-3.5" />
                    {result.status || 'ACCESS-REJECT'}
                  </span>
                )}
                {(result.nas_ip || result.secret_source) && (
                  <div className="text-[10px] font-mono text-slate-500 mt-1">
                    via {result.nas_ip || '127.0.0.1'} • {result.secret_source === 'custom' ? 'custom secret' : 'server secret'}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="p-5 font-mono text-xs text-slate-300 overflow-y-auto max-h-[420px] flex-1">
            {result ? (
              <div className="space-y-3">
                {result.command && (
                  <div className="text-slate-500">
                    <span className="text-indigo-400">$ </span>
                    {result.command}
                  </div>
                )}
                <pre className="whitespace-pre-wrap leading-relaxed text-slate-200">
                  {result.output || 'No output returned.'}
                </pre>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-48 text-slate-500 text-center">
                <Terminal className="w-10 h-10 mb-2 opacity-30 text-violet-400" />
                <p>Fill in user credentials and click "Run Authentication Test".</p>
                <p className="text-[11px] text-slate-600 mt-1">Simulates standard UDP 1812 authentication exchanges.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
