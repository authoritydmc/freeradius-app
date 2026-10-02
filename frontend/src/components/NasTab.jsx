import React, { useState, useEffect } from 'react';
import { 
  Server, Plus, Trash2, Key, Globe, Shield, RefreshCw,
  Search, CheckCircle2, Copy, Check, Eye, EyeOff, Radio
} from 'lucide-react';
import { fetchJson } from '../utils/api';

const NAS_TYPES = [
  { value: 'other', label: 'Generic / Other' },
  { value: 'cisco', label: 'Cisco IOS / Catalyst / WLC' },
  { value: 'mikrotik', label: 'MikroTik RouterOS / CapsMan' },
  { value: 'aruba', label: 'Aruba Instant On / ClearPass' },
  { value: 'unifi', label: 'Ubiquiti UniFi AP / Gateway' },
  { value: 'ruijie', label: 'Ruijie Reyee Cloud AP' },
  { value: 'coovachilli', label: 'CoovaChilli Captive Portal' }
];

export default function NasTab({ onNotify }) {
  const [nasList, setNasList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [revealedSecrets, setRevealedSecrets] = useState({});

  const [form, setForm] = useState({
    nasname: '',
    shortname: '',
    type: 'other',
    secret: '',
    description: ''
  });

  const loadNas = async () => {
    try {
      setLoading(true);
      const data = await fetchJson('nas');
      setNasList(data || []);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load NAS clients', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadNas();
  }, []);

  const handleCopy = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const toggleSecret = (id) => {
    setRevealedSecrets(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const generateRandomSecret = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*';
    let s = '';
    for (let i = 0; i < 20; i++) s += chars.charAt(Math.floor(Math.random() * chars.length));
    setForm(prev => ({ ...prev, secret: s }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await fetchJson('nas', {
        method: 'POST',
        body: JSON.stringify(form)
      });
      onNotify?.(`NAS client '${form.shortname || form.nasname}' added successfully!`, 'success');
      setShowModal(false);
      setForm({
        nasname: '',
        shortname: '',
        type: 'other',
        secret: '',
        description: ''
      });
      loadNas();
    } catch (err) {
      onNotify?.(err.message || 'Failed to add NAS client', 'error');
    }
  };

  const handleDelete = async (id, shortname) => {
    if (!window.confirm(`Are you sure you want to delete NAS client '${shortname || id}'?`)) return;
    try {
      await fetchJson(`nas/${encodeURIComponent(id)}`, {
        method: 'DELETE'
      });
      onNotify?.(`NAS client removed`, 'success');
      loadNas();
    } catch (err) {
      onNotify?.(err.message || 'Failed to delete NAS client', 'error');
    }
  };

  const filtered = nasList.filter(n =>
    (n.nasname || '').toLowerCase().includes(search.toLowerCase()) ||
    (n.shortname || '').toLowerCase().includes(search.toLowerCase()) ||
    (n.type || '').toLowerCase().includes(search.toLowerCase()) ||
    (n.description || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-blue-500/10 rounded-xl border border-blue-500/20 text-blue-400">
            <Radio className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Network Access Servers (NAS Clients)</h2>
            <p className="text-xs text-slate-400">Manage APs, Routers, VPN gateways, and Authenticator shared secrets</p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search NAS by IP / name..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700/70 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <button
            onClick={loadNas}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700 transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-blue-400' : ''}`} />
          </button>
          <button
            onClick={() => {
              generateRandomSecret();
              setShowModal(true);
            }}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-sm font-medium shadow-md shadow-blue-500/20 transition"
          >
            <Plus className="w-4 h-4" />
            <span>Add NAS Client</span>
          </button>
        </div>
      </div>

      {/* NAS Grid */}
      {loading && nasList.length === 0 ? (
        <div className="flex items-center justify-center p-12 text-slate-400">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-400 mr-3" />
          <span>Loading NAS inventory...</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-12 text-center text-slate-400">
          <Server className="w-12 h-12 mx-auto mb-3 text-slate-600 opacity-60" />
          <h3 className="text-base font-semibold text-slate-300">No NAS Clients Registered</h3>
          <p className="text-xs text-slate-500 mt-1">Add your MikroTik, UniFi, Cisco APs, or VPN gateways to allow RADIUS authentication.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filtered.map(nas => {
            const id = nas.id || nas.nasname;
            const isRevealed = revealedSecrets[id];
            return (
              <div 
                key={id}
                className="bg-slate-900/70 border border-slate-800/90 hover:border-slate-700 rounded-2xl p-5 flex flex-col justify-between transition group shadow-lg"
              >
                <div>
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div className="flex items-center gap-2.5">
                      <div className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        <Server className="w-5 h-5" />
                      </div>
                      <div>
                        <h3 className="font-bold text-slate-100 flex items-center gap-1.5 text-base">
                          {nas.shortname || nas.nasname}
                        </h3>
                        <p className="text-xs font-mono text-cyan-400">{nas.nasname}</p>
                      </div>
                    </div>

                    <button
                      onClick={() => handleDelete(id, nas.shortname)}
                      className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition"
                      title="Delete NAS"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  {nas.description && (
                    <p className="text-xs text-slate-400 mb-3 line-clamp-1">{nas.description}</p>
                  )}

                  {/* Attributes Badges */}
                  <div className="space-y-2 mt-3 pt-3 border-t border-slate-800/80 text-xs">
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="text-slate-400">Vendor Type:</span>
                      <span className="font-mono text-blue-300 font-medium px-2 py-0.5 rounded bg-blue-500/10 border border-blue-500/20 uppercase text-[10px]">
                        {nas.type || 'other'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1 text-slate-400">
                        <Key className="w-3.5 h-3.5 text-amber-400" /> Shared Secret:
                      </span>
                      <div className="flex items-center gap-1">
                        <span className="font-mono text-xs bg-slate-950 px-2 py-0.5 rounded border border-slate-800 text-amber-300">
                          {isRevealed ? (nas.secret || '••••••••') : '••••••••••••'}
                        </span>
                        <button
                          onClick={() => toggleSecret(id)}
                          className="p-1 text-slate-400 hover:text-slate-200"
                          title={isRevealed ? "Hide" : "Show"}
                        >
                          {isRevealed ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                        <button
                          onClick={() => handleCopy(nas.secret, id)}
                          className="p-1 text-slate-400 hover:text-blue-400"
                          title="Copy Secret"
                        >
                          {copiedId === id ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-500">
                  <span className="flex items-center gap-1 text-emerald-400">
                    <CheckCircle2 className="w-3 h-3" /> Ready for Auth
                  </span>
                  <span>Ports: 1812/1813 UDP</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* New NAS Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="bg-slate-900 border border-slate-750 rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/50">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-blue-500/10 text-blue-400 rounded-xl border border-blue-500/20">
                  <Server className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-base">Add Network Access Server (NAS)</h3>
                  <p className="text-xs text-slate-400">Configure router or access point RADIUS client</p>
                </div>
              </div>
              <button 
                onClick={() => setShowModal(false)}
                className="text-slate-400 hover:text-slate-200 p-1 rounded-lg"
              >
                &times;
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">IP Address / CIDR / FQDN *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. 192.168.1.1 or 10.0.0.0/24"
                    value={form.nasname}
                    onChange={e => setForm({ ...form, nasname: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Short Identifier *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. core-router, mikrotik-ap-1"
                    value={form.shortname}
                    onChange={e => setForm({ ...form, shortname: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Equipment / Vendor Type</label>
                <select
                  value={form.type}
                  onChange={e => setForm({ ...form, type: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                >
                  {NAS_TYPES.map(t => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Shared Secret *</label>
                  <button
                    type="button"
                    onClick={generateRandomSecret}
                    className="text-[11px] text-blue-400 hover:text-blue-300"
                  >
                    Generate Random Secret
                  </button>
                </div>
                <input
                  type="text"
                  required
                  placeholder="Strong shared secret string"
                  value={form.secret}
                  onChange={e => setForm({ ...form, secret: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Description (Optional)</label>
                <input
                  type="text"
                  placeholder="Location or rack identifier"
                  value={form.description}
                  onChange={e => setForm({ ...form, description: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-sm font-medium transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-sm font-medium shadow-md shadow-blue-500/20 transition"
                >
                  Add NAS Client
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
