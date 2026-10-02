import React, { useEffect, useState } from 'react';
import { X, RefreshCw, CreditCard, Wifi, Smartphone, Activity, History, HardDrive } from 'lucide-react';
import { fetchJson, formatBytes, formatDateTime } from '../utils/api';

function Section({ icon: Icon, title, count, children }) {
  return (
    <div className="bg-slate-950/60 border border-slate-800 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-2">
          <Icon className="w-4 h-4 text-indigo-400" />
          <span>{title}</span>
        </h4>
        {count != null && (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
            {count}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

export default function UserDetailModal({ username, onClose, onNotify }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState(null); // subscription id being revoked

  const load = async () => {
    if (!username) return;
    try {
      setLoading(true);
      const res = await fetchJson(`users/${encodeURIComponent(username)}/overview`);
      setData(res);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load user details', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [username]);

  const handleRevoke = async (sub) => {
    if (!window.confirm(`Revoke '${sub.plan_name}' for '${username}'? Access stops at once and live sessions are kicked.`)) return;
    setRevoking(sub.id);
    try {
      const res = await fetchJson(`subscriptions/${sub.id}/revoke`, {
        method: 'POST',
        body: JSON.stringify({ disconnect: true })
      });
      onNotify?.(res.message || 'Subscription revoked', 'success');
      await load();
    } catch (err) {
      onNotify?.(err.message || 'Failed to revoke subscription', 'error');
    } finally {
      setRevoking(null);
    }
  };

  if (!username) return null;

  const sub = data?.active_subscription;
  const usage = data?.usage || {};
  const totalBytes = (usage.up_bytes || 0) + (usage.down_bytes || 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-indigo-500/30 rounded-3xl max-w-2xl w-full shadow-2xl relative overflow-hidden max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4 shrink-0">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <span className="w-8 h-8 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center font-mono">
                {(username || '?').charAt(0).toUpperCase()}
              </span>
              <span className="font-mono">{username}</span>
            </h3>
            <p className="text-[11px] text-slate-400 mt-1 ml-10 flex flex-wrap items-center gap-1.5">
              {data ? (
                <>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${String(data.status).toUpperCase() === 'DISABLED' ? 'bg-rose-500/10 text-rose-300 border-rose-500/20' : 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'}`}>
                    {String(data.status || 'ACTIVE').toUpperCase()}
                  </span>
                  {(data.live_sessions?.length || 0) > 0 ? (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                      ● {data.live_sessions.length} ONLINE
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-slate-800 text-slate-400 border border-slate-700">
                      offline
                    </span>
                  )}
                  {data.has_certificate && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                      EAP-TLS cert
                    </span>
                  )}
                </>
              ) : (
                <span>Subscriber dossier</span>
              )}
            </p>
            <p className="text-[11px] text-slate-500 mt-0.5 ml-10">
              {data?.group ? `Group: ${data.group}` : ''}
              {sub ? ` • ${sub.plan_name} valid till ${formatDateTime(sub.expires_at)}` : (data ? ' • No active subscription' : '')}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={load} title="Refresh" className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button onClick={onClose} className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto p-4 sm:p-5 space-y-4 grow">
          {loading && !data ? (
            <div className="py-12 text-center text-slate-400 text-xs">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-400" />
              Loading subscriber dossier...
            </div>
          ) : !data ? (
            <div className="py-12 text-center text-slate-500 text-xs italic">No details available.</div>
          ) : (
            <>
              {/* Subscription banner */}
              {sub ? (
                <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl p-3.5 flex items-center gap-3">
                  <Wifi className="w-5 h-5 text-emerald-400 shrink-0" />
                  <div className="text-xs">
                    <div className="font-bold text-emerald-300">{sub.plan_name} — ACTIVE</div>
                    <div className="text-emerald-200/70 font-mono mt-0.5">
                      Expires {formatDateTime(sub.expires_at_epoch_ms || sub.expires_at)}
                      {sub.payment_amount != null && ` • ₹${Number(sub.payment_amount).toFixed(2)} via ${sub.payment_gateway || '—'}`}
                    </div>
                  </div>
                </div>
              ) : data?.recharge_required === false ? (
                <div className="bg-slate-800/60 border border-slate-700 rounded-2xl p-3.5 text-xs text-slate-300">
                  Exempt from recharge{data?.recharge_policy ? ` (${data.recharge_policy})` : ''} — no subscription needed for Wi-Fi access.
                </div>
              ) : (
                <div className="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-3.5 text-xs text-amber-200">
                  No valid subscription — RADIUS will reject with “recharge required” (see Auth History below).
                </div>
              )}

              {/* Stats */}
              <Section icon={Activity} title="Usage stats">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center">
                  {[
                    { label: 'Sessions', value: String(usage.total_sessions ?? 0) },
                    { label: 'Download', value: formatBytes(usage.down_bytes || 0) },
                    { label: 'Upload', value: formatBytes(usage.up_bytes || 0) },
                    { label: 'Total', value: formatBytes(totalBytes) },
                  ].map(s => (
                    <div key={s.label} className="bg-slate-900 border border-slate-800 rounded-xl py-2.5 px-2">
                      <div className="text-sm font-bold text-white font-mono">{s.value}</div>
                      <div className="text-[10px] text-slate-500 uppercase tracking-wide mt-0.5">{s.label}</div>
                    </div>
                  ))}
                </div>
                <div className="text-[11px] text-slate-500 mt-2 font-mono">
                  {usage.total_hours ?? 0} hrs connected • {data.live_sessions?.length || 0} live session(s)
                </div>
              </Section>

              {/* Subscriptions */}
              <Section icon={CreditCard} title="Subscriptions" count={data.subscriptions?.length || 0}>
                {!data.subscriptions?.length ? (
                  <p className="text-[11px] text-slate-500 italic">No subscription records.</p>
                ) : (
                  <div className="table-scroll overflow-x-auto border border-slate-800 rounded-xl">
                    <table className="w-full text-left text-[11px]">
                      <thead className="bg-slate-900 text-slate-400 uppercase text-[10px]">
                        <tr>
                          <th className="px-3 py-2 whitespace-nowrap">Plan</th>
                          <th className="px-3 py-2 whitespace-nowrap">Status</th>
                          <th className="px-3 py-2 whitespace-nowrap">Expires</th>
                          <th className="px-3 py-2 whitespace-nowrap text-right">Paid</th>
                          <th className="px-3 py-2 whitespace-nowrap text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {data.subscriptions.map(s => (
                          <tr key={s.id}>
                            <td className="px-3 py-2 text-slate-200 font-medium whitespace-nowrap">{s.plan_name}</td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${s.status === 'ACTIVE' ? 'bg-emerald-500/10 text-emerald-300' : s.status === 'CANCELLED' ? 'bg-rose-500/10 text-rose-300' : 'bg-slate-800 text-slate-400'}`}>
                                {s.status}
                              </span>
                            </td>
                            <td className="px-3 py-2 font-mono text-slate-400 whitespace-nowrap">{formatDateTime(s.expires_at_epoch_ms || s.expires_at)}</td>
                            <td className="px-3 py-2 text-right font-mono text-emerald-300 whitespace-nowrap">
                              {s.payment_amount != null ? `₹${Number(s.payment_amount).toFixed(2)}` : '—'}
                            </td>
                            <td className="px-3 py-2 text-right whitespace-nowrap">
                              {s.status === 'ACTIVE' ? (
                                <button
                                  onClick={() => handleRevoke(s)}
                                  disabled={revoking === s.id}
                                  title="Revoke this subscription now"
                                  className="px-2 py-1 rounded-lg text-[10px] font-bold bg-rose-500/10 text-rose-300 border border-rose-500/20 hover:bg-rose-500/20 disabled:opacity-50"
                                >
                                  {revoking === s.id ? 'Revoking…' : 'Revoke'}
                                </button>
                              ) : (
                                <span className="text-slate-600 text-[10px]">—</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Section>

              {/* Payments */}
              <Section icon={History} title="Payments" count={data.payments?.length || 0}>
                {!data.payments?.length ? (
                  <p className="text-[11px] text-slate-500 italic">No payment records (guest 0-Rs sales appear here too).</p>
                ) : (
                  <div className="space-y-1.5">
                    {data.payments.map(p => (
                      <div key={p.id} className="flex items-center justify-between gap-2 text-[11px] bg-slate-900 border border-slate-800 rounded-xl px-3 py-2">
                        <div className="truncate">
                          <span className="text-slate-200 font-semibold">{p.plan_name}</span>
                          <span className="text-slate-500 font-mono ml-2 truncate">{p.reference}</span>
                        </div>
                        <div className="text-right shrink-0 font-mono">
                          <span className="text-emerald-300 font-bold">₹{Number(p.amount).toFixed(2)}</span>
                          <span className="text-slate-500 ml-2">{p.gateway} • {p.status}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              {/* Devices */}
              <Section
                icon={Smartphone}
                title="Devices"
                count={`${data.verified_devices?.devices?.length || 0} verified / ${data.seen_devices?.length || 0} seen`}
              >
                {data.verified_devices?.require_verified && (
                  <p className="text-[11px] text-amber-300 mb-2">MAC lockdown enforced — only verified devices can connect.</p>
                )}
                {!data.verified_devices?.devices?.length && !data.seen_devices?.length ? (
                  <p className="text-[11px] text-slate-500 italic">No devices seen yet.</p>
                ) : (
                  <div className="space-y-1.5">
                    {[...(data.verified_devices?.devices || []).map(d => ({ ...d, verified: true })),
                      ...(data.seen_devices || []).filter(s => !(data.verified_devices?.devices || []).some(v => v.mac === s.mac))
                    ].slice(0, 20).map((d, i) => (
                      <div key={`${d.mac}-${i}`} className="flex items-center justify-between gap-2 text-[11px] bg-slate-900 border border-slate-800 rounded-xl px-3 py-2">
                        <span className="font-mono text-slate-200">{d.mac}</span>
                        <span className="text-slate-500 truncate">{d.label || `${d.sessions || 0} session(s)`}</span>
                        {d.verified
                          ? <span className="text-emerald-300 text-[10px] font-bold shrink-0">VERIFIED</span>
                          : <span className="text-slate-500 text-[10px] shrink-0">SEEN</span>}
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              {/* Live sessions */}
              <Section icon={HardDrive} title="Live sessions" count={data.live_sessions?.length || 0}>
                {!data.live_sessions?.length ? (
                  <p className="text-[11px] text-slate-500 italic">No live sessions.</p>
                ) : (
                  <div className="space-y-1.5">
                    {data.live_sessions.map(s => (
                      <div key={s.radacctid} className="text-[11px] bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 font-mono text-slate-300">
                        <div className="flex justify-between gap-2">
                          <span>{s.framed_ip || 'no IP'}</span>
                          <span className="text-slate-500">{s.nas_ip}</span>
                        </div>
                        <div className="text-slate-500 mt-0.5 truncate">{s.acctsessionid} • {s.mac || 'no MAC'}</div>
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              {/* Auth history with reject reasons */}
              <Section icon={History} title="Auth history (reject reasons)" count={data.auth_history?.length || 0}>
                {!data.auth_history?.length ? (
                  <p className="text-[11px] text-slate-500 italic">No auth attempts logged yet.</p>
                ) : (
                  <div className="space-y-1.5">
                    {data.auth_history.map((h, i) => (
                      <div key={i} className="text-[11px] bg-slate-900 border border-slate-800 rounded-xl px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`font-bold ${h.reply === 'Access-Accept' ? 'text-emerald-300' : 'text-rose-300'}`}>
                            {h.reply}
                          </span>
                          <span className="font-mono text-slate-500">{h.at ? formatDateTime(h.at) : ''}</span>
                        </div>
                        {h.reason && <div className="text-slate-400 mt-0.5">{h.reason}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </Section>
            </>
          )}
        </div>

        <div className="border-t border-slate-800 px-5 py-3 flex items-center justify-between gap-2 shrink-0">
          <span className="text-[10px] text-slate-500 font-mono">All times in your local timezone</span>
          <button onClick={onClose} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
