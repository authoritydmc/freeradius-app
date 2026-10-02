import React, { useState, useEffect } from 'react';
import {
  Play, Terminal, Shield, CheckCircle2, XCircle, Clock,
  RefreshCw, Cpu, Server, Smartphone, Key, AlertCircle,
  HelpCircle, Eye, EyeOff, Layers, Activity, Lock, Globe,
  ArrowRight, FileText
} from 'lucide-react';
import { fetchJson } from '../utils/api';

export default function TesterTab({ onNotify, initialUsername = '' }) {
  const [form, setForm] = useState({
    username: initialUsername || '',
    password: '',
    nas_ip: '127.0.0.1',
    calling_station_id: ''
  });
  const [showPassword, setShowPassword] = useState(false);
  const [users, setUsers] = useState([]);
  const [diagnostics, setDiagnostics] = useState(null);
  const [diagLoading, setDiagLoading] = useState(false);

  // Load user autocomplete and live server diagnostics
  const loadDiagnostics = () => {
    setDiagLoading(true);
    fetchJson('test-auth/diagnostics')
      .then(data => setDiagnostics(data))
      .catch(() => {})
      .finally(() => setDiagLoading(false));
  };

  useEffect(() => {
    fetchJson('users').then(u => {
      const list = Array.isArray(u) ? u : (u?.users || []);
      setUsers(list.map(x => x.username).filter(Boolean));
    }).catch(() => {});

    loadDiagnostics();
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
    if (e) e.preventDefault();
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
        onNotify?.(`Access-Reject: ${res.diagnosis || res.status}`, 'warning');
      }
      loadDiagnostics();
    } catch (err) {
      setResult({
        success: false,
        status: 'Error',
        diagnosis: err.message || 'Failed to communicate with FreeRADIUS API.',
        output: err.message || 'Failed to run RADIUS test.'
      });
      onNotify?.(err.message || 'RADIUS test request failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const applyPreset = (presetType) => {
    if (users.length > 0) {
      const targetUser = users[0];
      if (presetType === 'valid') {
        setForm({ ...form, username: targetUser });
      } else if (presetType === 'badpass') {
        setForm({ ...form, username: targetUser, password: 'WrongPassword123!' });
      } else if (presetType === 'maclock') {
        setForm({ ...form, username: targetUser, calling_station_id: 'AA:BB:CC:DD:EE:FF' });
      }
    }
  };

  return (
    <div className="space-y-6">
      {/* Header with Server Diagnostics */}
      <div className="bg-slate-900/70 p-5 rounded-2xl border border-slate-800 shadow-lg">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-violet-500/10 rounded-xl border border-violet-500/20 text-violet-400">
              <Cpu className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-white">Live RADIUS Protocol & Auth Simulator</h2>
                <span className="px-2 py-0.5 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full flex items-center gap-1">
                  <Activity className="w-3 h-3" /> UDP 1812 Active
                </span>
              </div>
              <p className="text-xs text-slate-400">Execute RFC 2865 Access-Request packets against the live FreeRADIUS daemon with real-time log correlation</p>
            </div>
          </div>

          {/* Server Certificate & Domain Badge */}
          {diagnostics?.server_cert?.exists && (
            <div className="flex items-center gap-3 bg-slate-950/80 px-4 py-2.5 rounded-xl border border-slate-800 text-xs">
              <Globe className="w-4 h-4 text-sky-400" />
              <div>
                <div className="flex items-center gap-1.5 font-semibold text-slate-200">
                  <span>EAP Domain:</span>
                  <span className="text-sky-300 font-mono">{diagnostics.server_cert.domain}</span>
                  {diagnostics.server_cert.is_public_ca ? (
                    <span className="px-1.5 py-0.2 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded text-[9px] font-bold">
                      Public CA (Trusted)
                    </span>
                  ) : (
                    <span className="px-1.5 py-0.2 bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded text-[9px] font-bold">
                      Local CA
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-slate-500">
                  Issuer: {diagnostics.server_cert.issuer.split(',')[0] || 'Let\'s Encrypt'}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Input Parameters Form */}
        <div className="lg:col-span-5 bg-slate-900/70 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Terminal className="w-4 h-4 text-violet-400" /> Test Parameters
              </h3>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => applyPreset('badpass')}
                  className="px-2 py-0.5 text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 transition"
                  title="Test wrong password reject"
                >
                  Bad Pass
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset('maclock')}
                  className="px-2 py-0.5 text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 transition"
                  title="Test with dummy MAC"
                >
                  MAC Test
                </button>
              </div>
            </div>

            <form onSubmit={handleTest} className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                  <span>Username *</span>
                  <span className="text-[10px] text-slate-500 normal-case">Supplicant identity</span>
                </label>
                <input
                  type="text"
                  required
                  list="tester-users-list"
                  placeholder="e.g. raj"
                  value={form.username}
                  onChange={e => setForm({ ...form, username: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
                />
                <datalist id="tester-users-list">
                  {users.map(u => <option key={u} value={u} />)}
                </datalist>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                  <span>Password *</span>
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-slate-400 hover:text-slate-200 text-xs flex items-center gap-1 normal-case"
                  >
                    {showPassword ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                    {showPassword ? 'Hide' : 'Show'}
                  </button>
                </label>
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  placeholder="User cleartext password"
                  value={form.password}
                  onChange={e => setForm({ ...form, password: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                  <span>Calling-Station-Id (Optional MAC)</span>
                  <span className="text-[10px] text-slate-500 normal-case">For MAC Lock test</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. 00:11:22:33:44:55"
                  value={form.calling_station_id}
                  onChange={e => setForm({ ...form, calling_station_id: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
                />
              </div>

              <details className="bg-slate-950/60 border border-slate-800 rounded-xl px-3 py-2">
                <summary className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider cursor-pointer">Advanced: NAS IP</summary>
                <div className="space-y-1 pt-2">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">NAS Server IP</label>
                  <input
                    type="text"
                    placeholder="127.0.0.1"
                    value={form.nas_ip}
                    onChange={e => setForm({ ...form, nas_ip: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
                  />
                  <p className="text-[11px] text-slate-500">Uses internal server secret from the NAS configuration table.</p>
                </div>
              </details>

              <div className="pt-3">
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 py-3 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-sm font-semibold shadow-lg shadow-violet-500/20 transition disabled:opacity-50 cursor-pointer"
                >
                  {loading ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Transmitting RADIUS Packet...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 fill-current" />
                      <span>Run Live Authentication Test</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>

          <div className="mt-6 p-3.5 bg-slate-950/60 border border-slate-800/80 rounded-xl text-[11px] text-slate-400 space-y-1.5">
            <div className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-violet-400" />
              What this tests:
            </div>
            <p>1. RFC 2865 Access-Request transmitted over UDP 1812 to FreeRADIUS daemon.</p>
            <p>2. SQL authentication matching in PostgreSQL <code className="text-violet-300">radcheck</code>.</p>
            <p>3. Reply attributes resolution from <code className="text-violet-300">radgroupreply</code> and policies.</p>
          </div>
        </div>

        {/* Right Column: Diagnostics, Reply Attributes & Protocol Console */}
        <div className="lg:col-span-7 space-y-4">
          {/* Result Card & Diagnosis */}
          {result && (
            <div className={`p-5 rounded-2xl border ${result.success ? 'bg-emerald-950/20 border-emerald-500/30' : 'bg-rose-950/20 border-rose-500/30'} shadow-xl space-y-4`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  {result.success ? (
                    <div className="p-2 bg-emerald-500/20 rounded-xl text-emerald-400">
                      <CheckCircle2 className="w-6 h-6" />
                    </div>
                  ) : (
                    <div className="p-2 bg-rose-500/20 rounded-xl text-rose-400">
                      <XCircle className="w-6 h-6" />
                    </div>
                  )}
                  <div>
                    <h4 className="text-base font-bold text-white">
                      {result.success ? 'ACCESS-ACCEPT (Authenticated)' : 'ACCESS-REJECT (Authentication Failed)'}
                    </h4>
                    <p className="text-xs text-slate-400">
                      Verified for user <span className="text-slate-200 font-mono font-semibold">{form.username}</span> via {result.nas_ip || '127.0.0.1'}
                    </p>
                  </div>
                </div>

                <span className={`px-3 py-1 rounded-full text-xs font-extrabold uppercase tracking-wider ${result.success ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'}`}>
                  {result.status}
                </span>
              </div>

              {/* Actionable Diagnosis */}
              {result.diagnosis && (
                <div className={`p-3.5 rounded-xl border text-xs leading-relaxed ${result.success ? 'bg-emerald-950/40 border-emerald-500/20 text-emerald-200' : 'bg-rose-950/40 border-rose-500/20 text-rose-200'}`}>
                  <div className="font-semibold mb-0.5 flex items-center gap-1.5">
                    <AlertCircle className="w-3.5 h-3.5" />
                    Server Diagnosis:
                  </div>
                  <div>{result.diagnosis}</div>
                </div>
              )}

              {/* Granted RADIUS Reply Attributes (VLAN, Timeouts, Speeds) */}
              {result.reply_attributes && result.reply_attributes.length > 0 && (
                <div className="space-y-2 pt-2 border-t border-slate-800">
                  <div className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-indigo-400" />
                    Granted Session Attributes ({result.reply_attributes.length}):
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {result.reply_attributes.map((attr, idx) => (
                      <div key={idx} className="bg-slate-900/90 border border-slate-800 rounded-lg p-2 flex items-center justify-between text-xs">
                        <span className="font-mono text-indigo-300 font-medium">{attr.attribute}</span>
                        <span className="font-mono text-slate-200 bg-slate-950 px-2 py-0.5 rounded border border-slate-800 text-[11px]">
                          {attr.value}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Correlated radpostauth Server Log */}
              {result.postauth_record && (
                <div className="bg-slate-950/80 p-3 rounded-xl border border-slate-800 text-[11px] font-mono space-y-1 text-slate-400">
                  <div className="text-slate-300 font-semibold flex items-center justify-between">
                    <span className="flex items-center gap-1">
                      <FileText className="w-3 h-3 text-violet-400" />
                      Database radpostauth log entry:
                    </span>
                    <span className="text-slate-500 text-[10px]">{result.postauth_record.authdate}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] text-slate-400 pt-1">
                    <div>Reply: <span className={result.postauth_record.reply === 'Access-Accept' ? 'text-emerald-400' : 'text-rose-400'}>{result.postauth_record.reply}</span></div>
                    <div>Reason: <span className="text-slate-300">{result.postauth_record.reason || 'None (Normal)'}</span></div>
                    <div>Calling-Station: <span className="text-slate-300">{result.postauth_record.calling_station || 'N/A'}</span></div>
                    <div>EAP Type: <span className="text-slate-300">{result.postauth_record.eap_type || 'PAP/Plain'}</span></div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Live Packet Output Terminal */}
          <div className="bg-slate-950 border border-slate-800 rounded-2xl flex flex-col overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/80 bg-slate-900/60">
              <div className="flex items-center gap-2">
                <div className="flex gap-1.5">
                  <span className="w-3 h-3 rounded-full bg-rose-500/80 inline-block" />
                  <span className="w-3 h-3 rounded-full bg-amber-500/80 inline-block" />
                  <span className="w-3 h-3 rounded-full bg-emerald-500/80 inline-block" />
                </div>
                <span className="text-xs font-mono text-slate-400 ml-2">radtest / radclient raw protocol console</span>
              </div>
            </div>

            <div className="p-5 font-mono text-xs text-slate-300 overflow-y-auto max-h-[320px]">
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
                  <p>Fill in user credentials and click "Run Live Authentication Test".</p>
                  <p className="text-[11px] text-slate-600 mt-1">Simulates standard UDP 1812 authentication exchanges.</p>
                </div>
              )}
            </div>
          </div>

          {/* Recent Server Auth Log Feed */}
          {diagnostics?.recent_logs && diagnostics.recent_logs.length > 0 && (
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4 shadow-lg space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
                <span className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-violet-400" />
                  Recent Server Authentication Attempts (Live Feed)
                </span>
                <button
                  type="button"
                  onClick={loadDiagnostics}
                  className="text-slate-400 hover:text-slate-200 flex items-center gap-1 text-[11px]"
                >
                  <RefreshCw className={`w-3 h-3 ${diagLoading ? 'animate-spin' : ''}`} /> Refresh
                </button>
              </div>

              <div className="divide-y divide-slate-800/80 overflow-x-auto text-[11px] font-mono">
                {diagnostics.recent_logs.map((log) => (
                  <div key={log.id} className="py-2 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${log.reply === 'Access-Accept' ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                      <span className="text-slate-200 font-semibold">{log.username}</span>
                      <span className="text-slate-500 text-[10px]">({log.reply})</span>
                      {log.reason && <span className="text-amber-300/80 text-[10px]">[{log.reason}]</span>}
                    </div>
                    <span className="text-slate-500 text-[10px] whitespace-nowrap">
                      {log.authdate ? new Date(log.authdate).toLocaleTimeString() : ''}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
