import React, { useState, useEffect } from 'react';
import { CreditCard, Plus, Trash2, Edit3, RefreshCw, Tag } from 'lucide-react';
import { fetchJson } from '../utils/api';

const EMPTY_FORM = {
  name: '',
  price: 51.35,
  currency: 'INR',
  validity_days: 30,
  max_session_seconds: 86400,
  description: '',
  allowed_groups: []
};

/**
 * PlansManager — Wi-Fi subscription plan CRUD (pricing, validity, blurb).
 * Lives in Payments & Reconciliation (plans are the thing being sold).
 * Calls onPlansChanged after any mutation so parents (1-Click top-up,
 * portal, UserDashboard) reload fresh pricing.
 */
export default function PlansManager({ onNotify, onPlansChanged }) {
  const [plans, setPlans] = useState([]);
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setPlanForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const loadPlans = async () => {
    try {
      setLoading(true);
      const [pRes, gRes] = await Promise.all([
        fetchJson('plans'),
        fetchJson('groups').catch(() => [])
      ]);
      setPlans(Array.isArray(pRes) ? pRes : []);
      const gList = Array.isArray(gRes) ? gRes : [];
      setGroups(gList.map(g => g.groupname).filter(Boolean));
    } catch (err) {
      onNotify?.(err.message || 'Failed to load plans', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadPlans(); }, []);

  const openAdd = () => {
    setEditing(null);
    setPlanForm(EMPTY_FORM);
    setShowModal(true);
  };

  const openEdit = (plan) => {
    setEditing(plan);
    setPlanForm({
      name: plan.name,
      price: plan.price,
      currency: plan.currency || 'INR',
      validity_days: plan.validity_days,
      max_session_seconds: plan.max_session_seconds || 86400,
      description: plan.description || '',
      allowed_groups: [...(plan.allowed_groups || [])]
    });
    setShowModal(true);
  };

  const toggleGroup = (g) => {
    setPlanForm(prev => ({
      ...prev,
      allowed_groups: prev.allowed_groups.includes(g)
        ? prev.allowed_groups.filter(x => x !== g)
        : [...prev.allowed_groups, g]
    }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await fetchJson('plans', {
        method: 'POST',
        body: JSON.stringify({ ...form, id: editing ? editing.id : undefined })
      });
      onNotify?.(`Plan '${form.name}' saved successfully!`, 'success');
      setShowModal(false);
      setEditing(null);
      setPlanForm(EMPTY_FORM);
      await loadPlans();
      onPlansChanged?.();
    } catch (err) {
      onNotify?.(err.message || 'Failed to save plan', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (plan) => {
    if (!window.confirm(`Delete plan '${plan.name}' (₹${plan.price}, ${plan.validity_days}d)? Existing subscriptions keep working; only future sales stop.`)) return;
    try {
      await fetchJson(`plans/${plan.id}`, { method: 'DELETE' });
      onNotify?.(`Plan '${plan.name}' deleted`, 'success');
      await loadPlans();
      onPlansChanged?.();
    } catch (err) {
      onNotify?.(err.message || 'Failed to delete plan', 'error');
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/20">
            <CreditCard className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-white text-base flex items-center gap-2">
              <span>Wi-Fi Subscription Plans</span>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700 font-mono">
                {plans.length}
              </span>
            </h3>
            <p className="text-xs text-slate-400">What customers buy — pricing, validity and checkout description</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadPlans}
            title="Reload plans"
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={openAdd}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-500/20"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Plan</span>
          </button>
        </div>
      </div>

      {loading && plans.length === 0 ? (
        <div className="p-8 text-center text-xs text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-emerald-400" />
          Loading plans...
        </div>
      ) : plans.length === 0 ? (
        <div className="p-8 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl">
          No plans configured. Click “Add Plan” to create your first Wi-Fi recharge package.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {plans.map(plan => (
            <div
              key={plan.id}
              className="bg-slate-950 p-4 rounded-2xl border border-slate-800 hover:border-slate-700 transition flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h4 className="font-bold text-white text-sm">{plan.name}</h4>
                  <div className="flex items-center gap-1 shrink-0">
                    <button onClick={() => openEdit(plan)} title="Edit plan" className="p-1 text-slate-400 hover:text-indigo-400 rounded transition">
                      <Edit3 className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => handleDelete(plan)} title="Delete plan" className="p-1 text-slate-400 hover:text-rose-400 rounded transition">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                <div className="text-2xl font-black text-emerald-400 font-mono mb-2">
                  {(plan.currency || 'INR') === 'INR' ? '₹' : plan.currency} {plan.price}
                </div>

                <p className="text-xs text-slate-400 mb-3">{plan.description || 'Broadband Wi-Fi access pass'}</p>

                {(plan.allowed_groups?.length || 0) > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2">
                    {plan.allowed_groups.map(g => (
                      <span key={g} className="px-1.5 py-0.5 rounded-md bg-purple-500/10 text-purple-300 border border-purple-500/20 text-[10px] font-mono font-bold">
                        {g} only
                      </span>
                    ))}
                  </div>
                )}

                <div className="space-y-1.5 text-[11px] font-mono border-t border-slate-800/80 pt-2.5 text-slate-300">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Validity:</span>
                    <span className="font-bold text-indigo-300">{plan.validity_days} Days</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Max Session:</span>
                    <span>{Math.round((plan.max_session_seconds || 86400) / 3600)} Hours</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Per day:</span>
                    <span className="flex items-center gap-1"><Tag className="w-3 h-3 text-slate-500" />₹{(Number(plan.price) / Math.max(1, Number(plan.validity_days))).toFixed(2)}</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/50">
              <div className="flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-emerald-400" />
                <h3 className="font-bold text-white text-base">
                  {editing ? 'Edit Wi-Fi Plan' : 'Create New Wi-Fi Plan'}
                </h3>
              </div>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white text-lg">&times;</button>
            </div>

            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Plan Name *</label>
                <input
                  type="text" required placeholder="e.g. 1 Month Unlimited Pass"
                  value={form.name} onChange={e => setPlanForm({ ...form, name: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-medium"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Price (₹) *</label>
                  <input
                    type="number" step="0.01" min="0" required
                    value={form.price} onChange={e => setPlanForm({ ...form, price: parseFloat(e.target.value) || 0 })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono font-bold"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Validity (Days) *</label>
                  <input
                    type="number" min="1" required
                    value={form.validity_days} onChange={e => setPlanForm({ ...form, validity_days: parseInt(e.target.value) || 1 })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Description</label>
                <input
                  type="text" placeholder="Plan features, speed, device limit"
                  value={form.description} onChange={e => setPlanForm({ ...form, description: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Available to groups <span className="text-slate-500 font-normal">(none = everyone)</span></label>
                {groups.length === 0 ? (
                  <p className="text-[11px] text-slate-500 italic">No groups found — plan stays available to everyone.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {groups.map(g => (
                      <button
                        key={g} type="button" onClick={() => toggleGroup(g)}
                        className={`px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border transition ${
                          form.allowed_groups.includes(g)
                            ? 'bg-purple-500/20 text-purple-200 border-purple-500/40'
                            : 'bg-slate-950 text-slate-400 border-slate-800 hover:border-slate-600'
                        }`}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                )}
                {form.allowed_groups.length > 0 && (
                  <p className="text-[11px] text-purple-300/80">Only {form.allowed_groups.join(', ')} members can buy this plan.</p>
                )}
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button type="button" onClick={() => setShowModal(false)} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-medium">
                  Cancel
                </button>
                <button type="submit" disabled={saving} className="px-5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-500/20 disabled:opacity-50">
                  {saving ? 'Saving…' : (editing ? 'Update Plan' : 'Create Plan')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
