import React, { useState, useEffect } from 'react';
import {
  Plus, Trash2, Edit3, Shield, RefreshCw,
  Search, Layers, CreditCard, Smartphone
} from 'lucide-react';
import { fetchJson } from '../utils/api';
import { AsyncButton } from './ActionButton';

const PRESETS = [
  { id: 'enterprise', name: 'Enterprise Pro (100M / 100M)', rate: '104857600/104857600', session: 86400, simultaneous: 3, vlan: '10', recharge_required: true, require_device_verification: true },
  { id: 'standard', name: 'Standard Staff (25M / 25M)', rate: '26214400/26214400', session: 43200, simultaneous: 2, vlan: '20', recharge_required: false, require_device_verification: false },
  { id: 'guest', name: 'Guest Paid Pass (10M / 5M)', rate: '10485760/5242880', session: 86400, simultaneous: 1, vlan: '30', recharge_required: true, require_device_verification: false },
  { id: 'iot', name: 'IoT Free Isolated (2M / 2M)', rate: '2097152/2097152', session: 0, simultaneous: 1, vlan: '40', recharge_required: false, require_device_verification: true }
];

export default function GroupsTab({ onNotify }) {
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState({
    groupname: '',
    description: '',
    rate_limit: '26214400/26214400',
    session_timeout: 43200,
    idle_timeout: 600,
    simultaneous_use: 2,
    vlan_id: '',
    is_admin: false,
    recharge_required: true,
    require_device_verification: false
  });

  const loadGroups = async () => {
    try {
      setLoading(true);
      const data = await fetchJson('groups');
      setGroups(data || []);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load policy groups', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGroups();
  }, []);

  const handleOpenAdd = () => {
    setIsEditing(false);
    setForm({
      groupname: '',
      description: '',
      rate_limit: '26214400/26214400',
      session_timeout: 43200,
      idle_timeout: 600,
      simultaneous_use: 2,
      vlan_id: '',
      is_admin: false,
      recharge_required: true,
      require_device_verification: false
    });
    setShowModal(true);
  };

  const handleOpenEdit = (group) => {
    setIsEditing(true);
    const gName = group.groupname || group.name || '';
    const isAdmin = Boolean(group.is_admin || gName === 'admins' || gName === 'admin');
    const rateLimit = group.rate_limit || group.reply_attributes?.find?.(a => a.attribute === 'Mikrotik-Rate-Limit')?.value || '';
    const simUseRaw = group.simultaneous_use ?? group.check_attributes?.find?.(a => a.attribute === 'Simultaneous-Use')?.value ?? '';
    const simUseParsed = parseInt(simUseRaw);
    const simUse = simUseRaw === '' || Number.isNaN(simUseParsed) ? '' : simUseParsed;
    const sessTimeout = parseInt(group.session_timeout || group.reply_attributes?.find?.(a => a.attribute === 'Session-Timeout')?.value) || 0;
    const idleTimeout = parseInt(group.idle_timeout || group.reply_attributes?.find?.(a => a.attribute === 'Idle-Timeout')?.value) || 600;
    const vlanId = group.vlan_id || group.reply_attributes?.find?.(a => a.attribute === 'Tunnel-Private-Group-ID')?.value || '';
    const isExempt = group.recharge_required === false || group.reply_attributes?.some?.(a => a.attribute === 'RajLabs-Recharge-Exempt' && a.value === '1');
    const reqDeviceLock = Boolean(group.require_device_verification || group.reply_attributes?.some?.(a => a.attribute === 'RajLabs-Require-Device-Lock' && a.value === '1'));

    setForm({
      groupname: gName,
      description: group.description || '',
      rate_limit: rateLimit,
      session_timeout: sessTimeout,
      idle_timeout: idleTimeout,
      simultaneous_use: simUse,
      vlan_id: vlanId,
      is_admin: isAdmin,
      recharge_required: !isAdmin && !isExempt,
      require_device_verification: reqDeviceLock
    });
    setShowModal(true);
  };

  const handlePresetChange = (e) => {
    const preset = PRESETS.find(p => p.id === e.target.value);
    if (preset) {
      setForm(prev => ({
        ...prev,
        rate_limit: preset.rate,
        session_timeout: preset.session,
        simultaneous_use: preset.simultaneous,
        vlan_id: preset.vlan,
        recharge_required: preset.recharge_required,
        require_device_verification: Boolean(preset.require_device_verification)
      }));
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        groupname: form.groupname.trim(),
        description: form.description || '',
        mikrotik_rate_limit: form.rate_limit || '',
        rate_limit: form.rate_limit || '',
        session_timeout: parseInt(form.session_timeout) || 0,
        idle_timeout: parseInt(form.idle_timeout) || 600,
        // '' / 0 / negative = no concurrent-device limit (backend skips the row).
        simultaneous_use: form.simultaneous_use === '' || form.simultaneous_use === null || form.simultaneous_use === undefined
          ? null
          : (parseInt(form.simultaneous_use) > 0 ? parseInt(form.simultaneous_use) : null),
        vlan_id: form.vlan_id && form.vlan_id.toString().trim() ? parseInt(form.vlan_id) : null,
        is_admin: form.is_admin || form.groupname === 'admins' || form.groupname === 'admin',
        recharge_required: form.recharge_required,
        require_device_verification: form.require_device_verification
      };

      await fetchJson('groups', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      onNotify?.(`Policy group '${form.groupname}' ${isEditing ? 'updated' : 'created'} successfully!`, 'success');
      setShowModal(false);
      setForm({
        groupname: '',
        description: '',
        rate_limit: '26214400/26214400',
        session_timeout: 43200,
        idle_timeout: 600,
        simultaneous_use: 2,
        vlan_id: '',
        is_admin: false,
        recharge_required: true,
        require_device_verification: false
      });
      loadGroups();
    } catch (err) {
      onNotify?.(err.message || 'Failed to save policy group', 'error');
    }
  };

  const handleDelete = async (groupname) => {
    if (!window.confirm(`Are you sure you want to delete policy group '${groupname}'?`)) return false;
    try {
      await fetchJson(`groups/${encodeURIComponent(groupname)}`, {
        method: 'DELETE'
      });
      onNotify?.(`Group '${groupname}' deleted`, 'success');
      loadGroups();
    } catch (err) {
      onNotify?.(err.message || 'Failed to delete group', 'error');
      throw err;
    }
  };

  const filteredGroups = groups.filter(g => 
    (g.groupname || g.name || '').toLowerCase().includes(search.toLowerCase()) ||
    (g.description || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-indigo-500/10 rounded-xl border border-indigo-500/20 text-indigo-400">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Policy Groups & QoS Profiles</h2>
            <p className="text-xs text-slate-400">Configure bandwidth QoS, VLAN tags, session constraints, and recharge requirements</p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search groups..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700/70 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <button
            onClick={loadGroups}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700 transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
          <button
            onClick={handleOpenAdd}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-sm font-medium shadow-md shadow-indigo-500/20 transition"
          >
            <Plus className="w-4 h-4" />
            <span>New Group</span>
          </button>
        </div>
      </div>

      {/* Groups Table (compact rows) */}
      {loading && groups.length === 0 ? (
        <div className="flex items-center justify-center p-12 text-slate-400">
          <RefreshCw className="w-6 h-6 animate-spin text-indigo-400 mr-3" />
          <span>Loading policy profiles...</span>
        </div>
      ) : filteredGroups.length === 0 ? (
        <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-12 text-center text-slate-400">
          <Layers className="w-12 h-12 mx-auto mb-3 text-slate-600 opacity-60" />
          <h3 className="text-base font-semibold text-slate-300">No Policy Groups Found</h3>
          <p className="text-xs text-slate-500 mt-1">Create groups like 'admins', 'vip', 'staff', or 'guests' to enforce RADIUS policies.</p>
        </div>
      ) : (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-xl">
          <div className="table-scroll overflow-x-auto rounded-2xl" style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="bg-slate-950/60 text-slate-400 uppercase border-b border-slate-800 text-[10px] tracking-wider">
              <tr>
                <th className="px-4 py-3 whitespace-nowrap">Group</th>
                <th className="px-4 py-3 whitespace-nowrap">Users</th>
                <th className="px-4 py-3 whitespace-nowrap">Recharge</th>
                <th className="px-4 py-3 whitespace-nowrap">Rate Limit</th>
                <th className="px-4 py-3 whitespace-nowrap">Session / Devices</th>
                <th className="px-4 py-3 whitespace-nowrap">Extras</th>
                <th className="px-4 py-3 text-right whitespace-nowrap">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filteredGroups.map(group => {
                const groupName = group.groupname || group.name || '';
                const isAdmin = group.is_admin || groupName === 'admins' || groupName === 'admin';
                const isRechargeRequired = !isAdmin && group.recharge_required !== false;
                const rate = group.rate_limit || group.reply_attributes?.find?.(a => a.attribute === 'Mikrotik-Rate-Limit')?.value || '—';
                const sess = group.session_timeout ? `${group.session_timeout}s` : '—';
                const sim = group.simultaneous_use ?? group.check_attributes?.find?.(a => a.attribute === 'Simultaneous-Use')?.value ?? 'No limit';
                const macLock = group.require_device_verification || group.reply_attributes?.some?.(a => a.attribute === 'RajLabs-Require-Device-Lock' && a.value === '1');
                return (
                  <tr key={groupName} className="hover:bg-slate-800/40 transition-colors">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className={`font-mono font-bold px-2 py-0.5 rounded-lg border text-[11px] ${isAdmin ? 'bg-amber-500/10 text-amber-300 border-amber-500/20' : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20'}`}>
                          {groupName}
                        </span>
                        {group.description && <span className="text-slate-500 truncate max-w-[180px]" title={group.description}>{group.description}</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap font-mono text-slate-300">
                      {group.user_count !== undefined ? group.user_count : '—'}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {isRechargeRequired ? (
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">Paid</span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">Free</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap font-mono text-indigo-300">{rate}</td>
                    <td className="px-4 py-3 whitespace-nowrap font-mono text-slate-300">{sess} / {sim}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="flex items-center gap-1">
                        {group.vlan_id && <span className="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20 text-[10px] font-mono">VLAN {group.vlan_id}</span>}
                        {macLock && <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20 text-[10px] font-bold">MAC🔒</span>}
                        {!group.vlan_id && !macLock && <span className="text-slate-600">—</span>}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <button onClick={() => handleOpenEdit(group)} title="Edit Policy Group" className="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-indigo-500/10 rounded-lg transition">
                        <Edit3 className="w-4 h-4" />
                      </button>
                      <AsyncButton
                        onClick={() => handleDelete(groupName)} disabled={groupName === 'admins'}
                        title={groupName === 'admins' ? "Default 'admins' system group cannot be deleted" : 'Delete Group'}
                        className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition disabled:opacity-30 disabled:hover:bg-transparent"
                        idleContent={<Trash2 className="w-4 h-4" />}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </div>
      )}

      {/* New Group Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="bg-slate-900 border border-slate-750 rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/50">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
                  <Layers className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-base">
                    {isEditing ? `Edit Policy Group '${form.groupname}'` : 'Create Policy Group'}
                  </h3>
                  <p className="text-xs text-slate-400">Define QoS, VLANs, and recharge requirement policies</p>
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
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Quick Preset Template</label>
                <select
                  onChange={handlePresetChange}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="">-- Apply a standard policy template --</option>
                  {PRESETS.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Group Name *</label>
                  <input
                    type="text"
                    required
                    disabled={isEditing}
                    placeholder="e.g. staff, guests, vip"
                    value={form.groupname}
                    onChange={e => setForm({ ...form, groupname: e.target.value })}
                    className={`w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono ${
                      isEditing ? 'opacity-60 cursor-not-allowed' : ''
                    }`}
                  />
                  {isEditing && (
                    <p className="text-[10px] text-slate-500">Group identifier cannot be renamed while editing.</p>
                  )}
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">VLAN ID (Optional)</label>
                  <input
                    type="text"
                    placeholder="e.g. 10, 20"
                    value={form.vlan_id}
                    onChange={e => setForm({ ...form, vlan_id: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Description</label>
                <input
                  type="text"
                  placeholder="Group purpose or department"
                  value={form.description}
                  onChange={e => setForm({ ...form, description: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Rate Limit (Rx/Tx bytes or bits)</label>
                <input
                  type="text"
                  placeholder="e.g. 26214400/26214400 or 25M/25M"
                  value={form.rate_limit}
                  onChange={e => setForm({ ...form, rate_limit: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Session Timeout (s)</label>
                  <input
                    type="number"
                    value={form.session_timeout}
                    onChange={e => setForm({ ...form, session_timeout: parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Simultaneous Use <span className="text-slate-500 font-normal normal-case">(devices per user — blank = no limit)</span></label>
                  <input
                    type="number"
                    min="0"
                    placeholder="Blank = no limit"
                    value={form.simultaneous_use}
                    onChange={e => setForm({ ...form, simultaneous_use: e.target.value === '' ? '' : parseInt(e.target.value) })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-750 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
              </div>

              {/* Policy Toggles */}
              <div className="space-y-3 pt-2 border-t border-slate-800">
                <label className="flex items-center gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={form.recharge_required}
                    onChange={e => setForm({ ...form, recharge_required: e.target.checked })}
                    className="w-4 h-4 rounded text-pink-600 bg-slate-950 border-slate-700 focus:ring-pink-500"
                  />
                  <div>
                    <span className="text-xs font-medium text-slate-200 flex items-center gap-1.5">
                      <CreditCard className="w-3.5 h-3.5 text-pink-400" />
                      Require Active Paid Recharge / Subscription for Access
                    </span>
                    <p className="text-[11px] text-slate-400">If unchecked, members of this group are exempt from recharge (Free/Staff/VIP).</p>
                  </div>
                </label>

                <label className="flex items-center gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={form.require_device_verification}
                    onChange={e => setForm({ ...form, require_device_verification: e.target.checked })}
                    className="w-4 h-4 rounded text-sky-600 bg-slate-950 border-slate-700 focus:ring-sky-500"
                  />
                  <div>
                    <span className="text-xs font-medium text-slate-200 flex items-center gap-1.5">
                      <Smartphone className="w-3.5 h-3.5 text-sky-400" />
                      Enforce Verified Device MAC Lock by Default
                    </span>
                    <p className="text-[11px] text-slate-400">When enabled, newly created members in this group are locked to verified MACs by default.</p>
                  </div>
                </label>

                <label className="flex items-center gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={form.is_admin}
                    onChange={e => setForm({ ...form, is_admin: e.target.checked })}
                    className="w-4 h-4 rounded text-indigo-600 bg-slate-950 border-slate-700 focus:ring-indigo-500"
                  />
                  <div>
                    <span className="text-xs font-medium text-slate-200 flex items-center gap-1.5">
                      <Shield className="w-3.5 h-3.5 text-amber-400" />
                      Grant Administrative AAA Console Permissions to Members
                    </span>
                  </div>
                </label>
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
                  className="px-5 py-2 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-sm font-medium shadow-md shadow-indigo-500/20 transition"
                >
                  {isEditing ? 'Update Policy Group' : 'Save Group Policy'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
