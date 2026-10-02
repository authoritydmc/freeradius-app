import React, { useState, useEffect } from 'react';
import { 
  Users, 
  UserPlus, 
  Bolt, 
  ChevronDown, 
  Search, 
  ShieldCheck,
  Key,
  Edit,
  Play,
  Check,
  Trash2,
  Plus, 
  X, 
  Dice5, 
  Eye, 
  EyeOff, 
  Smartphone,
  RefreshCw,
  QrCode,
  Lock,
  Unlock,
  ShieldAlert,
  MessageCircle,
  Ban,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { calculatePasswordStrength, fetchJson, formatDateTime, timeLeft } from '../utils/api';
import WifiQrModal from './WifiQrModal';
import ResponsiveTable from './ResponsiveTable';
import UserDetailModal from './UserDetailModal';
import CertIssuedModal from './CertIssuedModal';
import OnboardModal from './OnboardModal';
import RowMenu from './RowMenu';
import { AsyncButton, CopyButton } from './ActionButton';

/** Single-line presence: banned > online > expiring > last seen > idle. */
function presenceOf(u) {
  if (u.banned) return { dot: 'bg-rose-400', text: 'Banned', cls: 'text-rose-300 font-bold', title: 'Account banned — RADIUS rejects immediately' };
  if (u.active_sessions > 0) return { dot: 'bg-emerald-400 animate-pulse', text: `${u.active_sessions} online`, cls: 'text-emerald-300', title: `${u.active_sessions} live session(s)` };
  if (u.expiration) return { dot: 'bg-amber-400', text: `Exp ${formatDateTime(u.expiration)}`, cls: 'text-amber-300', title: `FreeRADIUS Expiration (server UTC): ${u.expiration}` };
  if (u.last_auth) return { dot: 'bg-slate-500', text: `last ${formatDateTime(u.last_auth)}`, cls: 'text-slate-500', title: `Last attempt: ${u.last_auth}` };
  return { dot: 'bg-slate-600', text: 'idle', cls: 'text-slate-600', title: 'No recent activity' };
}

export default function UsersTab({
  users: propUsers,
  groups: propGroups,
  currentUser,
  onSaveUser: propOnSaveUser,
  onDeleteUser: propOnDeleteUser,
  onResetPassword: propOnResetPassword,
  onGenerateGuest: propOnGenerateGuest,
  onOpenDevicePolicy: propOnOpenDevicePolicy,
  onTestAuth: propOnTestAuth,
  onIssueCert: propOnIssueCert,
  onCopyText: propOnCopyText,
  onShowCredModal,
  onNotify
}) {
  const [internalUsers, setInternalUsers] = useState([]);
  const [internalGroups, setInternalGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [groupFilter, setGroupFilter] = useState('');
  
  // Guest Generator Modal & State
  const [guestModalOpen, setGuestModalOpen] = useState(false);
  const [guestDuration, setGuestDuration] = useState('24h');
  const [guestGroup, setGuestGroup] = useState('guests');
  const [guestPrefix, setGuestPrefix] = useState('guest');
  const [guestLoading, setGuestLoading] = useState(false);

  // User Add/Edit Modal
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [userForm, setUserForm] = useState({ username: '', password: '', group: 'staff', static_ip: '', phone: '' });
  const [showPass, setShowPass] = useState(false);
  const [userModalSaving, setUserModalSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null); // {ok, msg} inline confirmation
  // Edit-modal admin actions
  const [editBanned, setEditBanned] = useState(false);
  const [editHasCert, setEditHasCert] = useState(false);
  const [editBusy, setEditBusy] = useState(''); // 'ban' | 'revoke' | ''
  // Bulk selection (usernames)
  const [selected, setSelected] = useState([]);
  const [bulkBusy, setBulkBusy] = useState('');

  // Reset Password Modal
  const [resetModalOpen, setResetModalOpen] = useState(false);
  const [resetUsername, setResetUsername] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [resetDisconnect, setResetDisconnect] = useState(false);
  const [resetSaving, setResetSaving] = useState(false);
  const [resetResult, setResetResult] = useState(null); // {ok, msg} inline confirmation
  const [showResetPass, setShowResetPass] = useState(true);

  // Device Policy Modal
  const [deviceModalOpen, setDeviceModalOpen] = useState(false);
  const [deviceUser, setDeviceUser] = useState('');
  const [devicePolicy, setDevicePolicy] = useState(null);
  const [deviceLoading, setDeviceLoading] = useState(false);
  const [newMac, setNewMac] = useState('');
  const [newMacDesc, setNewMacDesc] = useState('');

  // Wi-Fi QR Access Pass Modal
  const [qrModalUser, setQrModalUser] = useState(null);

  // Inline RADIUS auth test (username + password -> real verdict)
  const [authTest, setAuthTest] = useState(null); // {username, password, result, loading}

  // Onboarding invite (WhatsApp/SMS)
  const [onboardUser, setOnboardUser] = useState(null);
  // Fresh secret from the last in-session creation (lets invites include it)
  const [lastCreatedCreds, setLastCreatedCreds] = useState(null);

  // Subscriber dossier popup (subscription + stats + devices + history)
  const [detailUser, setDetailUser] = useState(null);

  // Issued-certificate handoff (password shown once, close gated on save)
  const [certIssued, setCertIssued] = useState(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [uData, gData] = await Promise.all([
        fetchJson('users'),
        fetchJson('groups')
      ]);
      setInternalUsers(uData || []);
      setInternalGroups(gData || []);
      if (gData && gData.length > 0) {
        setGuestGroup(gData[0].groupname);
      }
    } catch (err) {
      onNotify?.(err.message || 'Failed to load users from database', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!propUsers) {
      loadData();
    }
  }, [propUsers]);

  const users = propUsers || internalUsers;
  const groups = propGroups || internalGroups;

  // Generate random password helper (crypto RNG, backend-aligned charset)
  const generateRandomPass = () => {
    const chars = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#$%^*-_=+";
    const len = 14;
    const buf = new Uint32Array(len);
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      crypto.getRandomValues(buf);
      let pass = "";
      for (let i = 0; i < len; i++) pass += chars.charAt(buf[i] % chars.length);
      return pass;
    }
    let pass = "";
    for (let i = 0; i < len; i++) {
      pass += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return pass;
  };

  const handleOpenAdd = () => {
    setIsEditing(false);
    setSaveResult(null);
    setUserForm({
      username: '',
      password: generateRandomPass(),
      group: groups[0]?.groupname || 'staff',
      static_ip: '',
      phone: ''
    });
    setShowPass(false);
    setUserModalOpen(true);
  };

  const handleOpenEdit = (user) => {
    setIsEditing(true);
    const framed = user.reply_attributes?.find(a => a.attribute.toLowerCase() === 'framed-ip-address');
    setUserForm({
      username: user.username,
      password: '',
      group: user.group || (groups[0]?.groupname || 'staff'),
      static_ip: framed ? framed.value : '',
      phone: user.phone || ''
    });
    setShowPass(false);
    setSaveResult(null);
    setEditBanned(Boolean(user.banned));
    setEditHasCert(Boolean(user.has_certificate));
    setEditBusy('');
    setUserModalOpen(true);
  };

  const handleToggleBan = async () => {
    const toBan = !editBanned;
    if (toBan && !window.confirm(`Ban '${userForm.username}'? They will be rejected immediately (password kept).`)) return;
    setEditBusy('ban');
    try {
      const res = await fetchJson(`users/${encodeURIComponent(userForm.username)}/${toBan ? 'ban' : 'unban'}`, {
        method: 'POST',
        body: JSON.stringify({ disconnect: true })
      });
      setEditBanned(toBan);
      onNotify?.(res.message || (toBan ? 'User banned' : 'User unbanned'), toBan ? 'warning' : 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to update ban state', 'error');
    } finally {
      setEditBusy('');
    }
  };

  const handleRevokeCertInEdit = async () => {
    if (!window.confirm(`Revoke the certificate for '${userForm.username}' (upstream CRL + local removal)?`)) return;
    setEditBusy('revoke');
    try {
      const res = await fetchJson(`certs/${encodeURIComponent(userForm.username)}/revoke`, { method: 'POST' });
      setEditHasCert(false);
      onNotify?.(res.message || 'Certificate revoked', 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to revoke certificate', 'error');
    } finally {
      setEditBusy('');
    }
  };

  const runBulkAction = async (action, label) => {
    if (!selected.length) return;
    if (!window.confirm(`${label} ${selected.length} selected user(s)?`)) return;
    setBulkBusy(action);
    try {
      const res = await fetchJson('users/bulk-action', {
        method: 'POST',
        body: JSON.stringify({ usernames: selected, action, disconnect: action === 'ban' })
      });
      const ok = res.succeeded ?? 0;
      const fail = res.failed ?? 0;
      const firstErr = (res.results || []).find(r => !r.ok);
      onNotify?.(
        `${label}: ${ok} succeeded${fail ? `, ${fail} failed${firstErr ? ` (e.g. ${firstErr.username}: ${firstErr.error})` : ''}` : ''}`,
        fail ? 'warning' : 'success'
      );
      setSelected([]);
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Bulk action failed', 'error');
    } finally {
      setBulkBusy('');
    }
  };

  const handleSaveUser = async (e) => {
    e.preventDefault();
    setUserModalSaving(true);
    setSaveResult(null);
    try {
      if (propOnSaveUser) {
        await propOnSaveUser({
          username: userForm.username,
          password: userForm.password,
          group: userForm.group,
          framed_ip: userForm.static_ip,
          phone: userForm.phone?.trim() || undefined
        }, isEditing);
        setSaveResult({ ok: true, msg: `User '${userForm.username}' saved.` });
      } else {
        const endpoint = isEditing ? `users/${encodeURIComponent(userForm.username)}` : 'users';
        const method = isEditing ? 'PUT' : 'POST';
        const res = await fetchJson(endpoint, {
          method,
          body: JSON.stringify({
            username: userForm.username,
            password: userForm.password,
            group: userForm.group,
            framed_ip: userForm.static_ip,
            phone: userForm.phone?.trim() || undefined
          })
        });
        const msg = res.message || `User '${userForm.username}' saved successfully!`;
        setSaveResult({ ok: true, msg });
        onNotify?.(msg, 'success');
        if (!isEditing && onShowCredModal) {
          setLastCreatedCreds({ username: userForm.username, password: userForm.password });
          onShowCredModal({
            username: userForm.username,
            password: userForm.password,
            group: userForm.group,
            static_ip: userForm.static_ip,
            phone: userForm.phone?.trim() || ''
          });
        }
        loadData();
      }
      // Inline confirmation inside the modal; auto-close shortly on success
      setTimeout(() => setUserModalOpen(false), 1200);
    } catch (err) {
      const msg = err.message || 'Failed to save user';
      setSaveResult({ ok: false, msg });
      onNotify?.(msg, 'error');
    } finally {
      setUserModalSaving(false);
    }
  };

  const handleOpenReset = (username) => {
    setResetUsername(username);
    setResetPassword(generateRandomPass());
    setResetDisconnect(false);
    setShowResetPass(true);
    setResetResult(null);
    setResetModalOpen(true);
  };

  const handleSaveReset = async (showQr = false) => {
    setResetSaving(true);
    setResetResult(null);
    try {
      if (propOnResetPassword) {
        await propOnResetPassword(resetUsername, resetPassword, resetDisconnect);
      } else {
        const res = await fetchJson(`users/${encodeURIComponent(resetUsername)}/password`, {
          method: 'PUT',
          body: JSON.stringify({
            password: resetPassword,
            disconnect_active: resetDisconnect
          })
        });
        onNotify?.(res.message || `Password reset for '${resetUsername}'!`, 'success');
        loadData();
      }
      const savedUser = resetUsername;
      const savedPass = resetPassword;
      setResetResult({ ok: true, msg: `Password saved for '${savedUser}'.` });
      setTimeout(() => {
        setResetModalOpen(false);
        setResetResult(null);
        if (showQr) {
          // Fresh secret is still known: open a QR that joins directly
          setQrModalUser({ username: savedUser, password: savedPass });
        }
      }, 900);
    } catch (err) {
      const msg = err.message || 'Failed to reset password';
      setResetResult({ ok: false, msg });
      onNotify?.(msg, 'error');
    } finally {
      setResetSaving(false);
    }
  };

  const handleQuickGuest = async (dur = '24h') => {
    setGuestLoading(true);
    try {
      if (propOnGenerateGuest) {
        await propOnGenerateGuest({
          duration: dur,
          group: guestGroup,
          prefix: guestPrefix
        });
      } else {
        const res = await fetchJson('users/guest', {
          method: 'POST',
          body: JSON.stringify({
            duration: dur,
            group: guestGroup,
            prefix: guestPrefix
          })
        });
        onNotify?.(`Guest account '${res.username}' created (${res.validity_label || dur})!`, 'success');
        if (onShowCredModal) {
          onShowCredModal(res);
        }
        loadData();
      }
      setGuestModalOpen(false);
    } catch (err) {
      onNotify?.(err.message || 'Failed to generate guest user', 'error');
    } finally {
      setGuestLoading(false);
    }
  };

  const handleDeleteUser = async (username) => {
    if (!window.confirm(`Are you sure you want to delete user '${username}'?`)) return false;
    try {
      if (propOnDeleteUser) {
        await propOnDeleteUser(username);
      } else {
        await fetchJson(`users/${encodeURIComponent(username)}`, { method: 'DELETE' });
        onNotify?.(`User '${username}' deleted successfully`, 'success');
        loadData();
      }
    } catch (err) {
      onNotify?.(err.message || 'Failed to delete user', 'error');
      throw err;
    }
  };

  const handleSaveOnboardPhone = async (phone) => {
    if (!onboardUser) return;
    await fetchJson(`users/${encodeURIComponent(onboardUser.username)}`, {
      method: 'PUT',
      body: JSON.stringify({ phone })
    });
    setOnboardUser(prev => (prev ? { ...prev, phone } : prev));
    loadData();
  };

  const quickBan = async (username, toBan) => {
    if (toBan && !window.confirm(`Ban '${username}'? They will be rejected immediately (password kept).`)) return false;
    try {
      const res = await fetchJson(`users/${encodeURIComponent(username)}/${toBan ? 'ban' : 'unban'}`, {
        method: 'POST',
        body: JSON.stringify({ disconnect: true })
      });
      onNotify?.(res.message || (toBan ? 'User banned' : 'User unbanned'), toBan ? 'warning' : 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to update ban state', 'error');
      throw err;
    }
  };

  const quickRevoke = async (username) => {
    if (!window.confirm(`Revoke the certificate for '${username}' (upstream CRL + local removal)?`)) return false;
    try {
      const res = await fetchJson(`certs/${encodeURIComponent(username)}/revoke`, { method: 'POST' });
      onNotify?.(res.message || 'Certificate revoked', 'success');
      loadData();
    } catch (err) {
      onNotify?.(err.message || 'Failed to revoke certificate', 'error');
      throw err;
    }
  };

  const handleIssueCert = async (username) => {
    try {
      if (propOnIssueCert) {
        await propOnIssueCert(username);
      } else {
        const res = await fetchJson('certs/issue', {
          method: 'POST',
          body: JSON.stringify({ username, valid_days: 365 })
        });
        // Password exists only in this response — hand it over via the gated popup
        setCertIssued({ username: res.username || username, p12_password: res.p12_password, authority: res.authority });
        loadData();
      }
    } catch (err) {
      onNotify?.(err.message || 'Failed to issue certificate', 'error');
      throw err;
    }
  };

  const handleTestAuth = async (username) => {
    if (propOnTestAuth) {
      // Jump to the RADIUS tester with this user prefilled
      propOnTestAuth(username);
      return;
    }
    // Fallback when embedded without a tester tab: prompt + test inline.
    setAuthTest({ username, password: '', result: null, loading: false });
  };

  const runAuthTest = async (e) => {
    e?.preventDefault();
    if (!authTest?.password) {
      onNotify?.('Enter the user password to test', 'warning');
      return;
    }
    setAuthTest(prev => ({ ...prev, loading: true, result: null }));
    try {
      const res = await fetchJson('test-auth', {
        method: 'POST',
        body: JSON.stringify({ username: authTest.username, password: authTest.password })
      });
      setAuthTest(prev => ({ ...prev, result: res }));
      if (res.success) {
        onNotify?.(`Test Auth for '${authTest.username}': Access-Accept!`, 'success');
      } else {
        onNotify?.(`Test Auth for '${authTest.username}': ${res.status || 'Access-Reject'}`, 'warning');
      }
    } catch (err) {
      setAuthTest(prev => ({ ...prev, result: { success: false, status: 'Error', output: err.message } }));
      onNotify?.(err.message || 'Test auth request failed', 'error');
    } finally {
      setAuthTest(prev => (prev ? { ...prev, loading: false } : prev));
    }
  };

  const handleOpenDevicePolicy = async (username) => {
    if (propOnOpenDevicePolicy) {
      propOnOpenDevicePolicy(username);
      return;
    }
    setDeviceUser(username);
    setDeviceModalOpen(true);
    setDeviceLoading(true);
    setNewMac('');
    setNewMacDesc('');
    try {
      const data = await fetchJson(`users/${encodeURIComponent(username)}/devices`);
      setDevicePolicy(data);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load device policy', 'error');
    } finally {
      setDeviceLoading(false);
    }
  };

  const handleToggleDeviceLock = async (enabled) => {
    try {
      const res = await fetchJson(`users/${encodeURIComponent(deviceUser)}/device-policy`, {
        method: 'PUT',
        body: JSON.stringify({ require_verified: enabled })
      });
      setDevicePolicy(prev => prev ? { ...prev, require_verified: enabled } : { require_verified: enabled, devices: [] });
      onNotify?.(res.message || `Hardware lock ${enabled ? 'enabled' : 'disabled'} for '${deviceUser}'`, 'success');
    } catch (err) {
      onNotify?.(err.message || 'Failed to update device lock policy', 'error');
    }
  };

  const handleAddDevice = async (e) => {
    e?.preventDefault();
    if (!newMac.trim()) {
      onNotify?.('Please enter a valid MAC address', 'warning');
      return;
    }
    try {
      const res = await fetchJson(`users/${encodeURIComponent(deviceUser)}/devices`, {
        method: 'POST',
        body: JSON.stringify({ mac: newMac.trim(), label: newMacDesc.trim() })
      });
      onNotify?.(res.message || `Device ${newMac} added`, 'success');
      setNewMac('');
      setNewMacDesc('');
      // Reload device list
      const data = await fetchJson(`users/${encodeURIComponent(deviceUser)}/devices`);
      setDevicePolicy(data);
    } catch (err) {
      onNotify?.(err.message || 'Failed to add verified device', 'error');
    }
  };

  const handleDeleteDevice = async (mac) => {
    if (!window.confirm(`Remove verified MAC '${mac}' for user '${deviceUser}'?`)) return;
    try {
      const res = await fetchJson(`users/${encodeURIComponent(deviceUser)}/devices/${encodeURIComponent(mac)}`, {
        method: 'DELETE'
      });
      onNotify?.(res.message || `Device ${mac} removed`, 'success');
      const data = await fetchJson(`users/${encodeURIComponent(deviceUser)}/devices`);
      setDevicePolicy(data);
    } catch (err) {
      onNotify?.(err.message || 'Failed to remove verified device', 'error');
    }
  };

  // Filter users
  const filteredUsers = users.filter((u) => {
    const matchSearch = u.username.toLowerCase().includes(search.toLowerCase());
    const matchGroup = !groupFilter || (groupFilter === '__none' ? !u.group : u.group === groupFilter);
    return matchSearch && matchGroup;
  });

  const passStrength = calculatePasswordStrength(userForm.password);
  const resetStrength = calculatePasswordStrength(resetPassword);

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      
      {/* Top Header & Search / Actions */}
      <div className="flex flex-wrap gap-3 justify-between items-center bg-slate-900/60 p-4 rounded-3xl border border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Users className="w-5 h-5 text-indigo-400" />
            <span>Configured RADIUS Users</span>
            <span className="text-xs font-normal text-slate-400">
              ({filteredUsers.length} / {users.length})
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">Manage 802.1X enterprise identities, policy memberships, and credentials.</p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* Search Box */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3.5 top-3 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search username..."
              className="bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2 text-xs text-white focus:border-indigo-500 outline-none w-44"
            />
          </div>

          {/* Group Filter */}
          <select
            value={groupFilter}
            onChange={(e) => setGroupFilter(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-white focus:border-indigo-500 outline-none"
          >
            <option value="">All Groups</option>
            {groups.map((g) => (
              <option key={g.groupname} value={g.groupname}>{g.groupname}</option>
            ))}
            <option value="__none">No Group</option>
          </select>

          {/* 1-Click Guest Generator with 1-Day Default & Dropdown */}
          <div className="flex items-center rounded-xl bg-gradient-to-r from-amber-600 to-amber-500 p-0.5 shadow-lg shadow-amber-600/20">
            <button
              onClick={() => handleQuickGuest('24h')}
              disabled={guestLoading}
              title="1-Click generate temporary guest user valid for 1 Day (24 Hours)"
              className="px-3 py-1.5 text-white rounded-l-lg text-xs font-bold flex items-center gap-1.5 hover:bg-white/10 transition-colors disabled:opacity-50"
            >
              <Bolt className={`w-3.5 h-3.5 ${guestLoading ? 'animate-spin' : ''}`} />
              <span>Guest (1-Day)</span>
            </button>
            <button
              onClick={() => setGuestModalOpen(true)}
              title="Customize guest validity (1h, 6h, 12h, 1d, 3d, 7d, 30d)"
              className="px-2 py-1.5 text-white/90 hover:text-white rounded-r-lg border-l border-amber-400/40 text-xs font-bold hover:bg-white/10 transition-colors"
            >
              <ChevronDown className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Add User Button */}
          <button
            onClick={handleOpenAdd}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-lg shadow-indigo-600/20 transition-all"
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>Add User</span>
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 bg-indigo-950/60 border border-indigo-500/30 p-3 rounded-2xl text-xs">
          <span className="font-bold text-indigo-200 px-1">{selected.length} selected</span>
          {[
            { action: 'ban', label: 'Ban', cls: 'bg-rose-600 hover:bg-rose-500' },
            { action: 'unban', label: 'Unban', cls: 'bg-emerald-600 hover:bg-emerald-500' },
            { action: 'revoke_certs', label: 'Revoke certs', cls: 'bg-purple-600 hover:bg-purple-500' },
            { action: 'delete', label: 'Delete', cls: 'bg-slate-700 hover:bg-rose-600' }
          ].map(b => (
            <button
              key={b.action}
              onClick={() => runBulkAction(b.action, b.label)}
              disabled={!!bulkBusy}
              className={`px-3 py-1.5 text-white rounded-xl font-bold transition disabled:opacity-50 flex items-center gap-1.5 ${b.cls}`}
            >
              {bulkBusy === b.action ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : bulkBusy ? null : null}
              <span>{bulkBusy === b.action ? 'Working…' : b.label}</span>
            </button>
          ))}
          <button onClick={() => setSelected([])} className="px-3 py-1.5 text-slate-400 hover:text-white">
            Clear
          </button>
        </div>
      )}

      {/* Users Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-3xl shadow-sm">
        <ResponsiveTable className="rounded-3xl">
        <table className="w-full min-w-[760px] text-left text-xs">
          <thead className="bg-slate-950/60 text-slate-400 uppercase border-b border-slate-800 text-[10px] tracking-wider">
            <tr>
              <th className="pl-3 sm:pl-4 pr-1 py-3 whitespace-nowrap w-10 sticky left-0 bg-slate-950/95 z-10">
                <input
                  type="checkbox"
                  title="Select all"
                  checked={filteredUsers.length > 0 && filteredUsers.every(u => selected.includes(u.username))}
                  onChange={(e) => setSelected(e.target.checked ? filteredUsers.map(u => u.username) : [])}
                  className="w-4 h-4 rounded text-indigo-600 bg-slate-900 border-slate-700"
                />
              </th>
              <th className="px-3 py-3 whitespace-nowrap sticky left-10 bg-slate-950/95 z-10">User</th>
              <th className="px-3 py-3 whitespace-nowrap">Plan</th>
              <th className="px-3 py-3 whitespace-nowrap">Group</th>
              <th className="px-3 py-3 whitespace-nowrap">Cert</th>
              <th className="px-3 py-3 whitespace-nowrap">Network</th>
              <th className="px-3 py-3 text-right whitespace-nowrap">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/80">
            {filteredUsers.map((user) => {
              const presence = presenceOf(user);
              return (
              <tr key={user.username} className={`hover:bg-slate-800/40 transition-colors ${selected.includes(user.username) ? 'bg-indigo-500/5' : ''}`}>
                <td className="pl-3 sm:pl-4 pr-1 py-3 whitespace-nowrap sticky left-0 bg-slate-900 z-10">
                  <input
                    type="checkbox"
                    checked={selected.includes(user.username)}
                    onChange={(e) => setSelected(e.target.checked
                      ? [...selected, user.username]
                      : selected.filter(u => u !== user.username))}
                    className="w-4 h-4 rounded text-indigo-600 bg-slate-900 border-slate-700"
                  />
                </td>
                {/* User + single-line presence */}
                <td className="px-2 sm:px-3 py-3 whitespace-nowrap sticky left-10 bg-slate-900 z-10 border-r border-slate-800/70">
                  <div className="flex items-center gap-1.5 sm:gap-2">
                    <div className={`w-6 h-6 sm:w-7 sm:h-7 rounded-lg border flex items-center justify-center text-[10px] sm:text-[11px] font-mono font-bold shrink-0 ${user.banned ? 'bg-rose-500/10 border-rose-500/30 text-rose-300' : 'bg-slate-800 border-slate-700/80 text-slate-300'}`}>
                      {user.username.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <button
                        onClick={() => setDetailUser(user.username)}
                        title="Open subscriber dossier (subscription, stats, devices, history)"
                        className="font-bold text-[12px] sm:text-[13px] text-slate-100 hover:text-indigo-300 hover:underline text-left truncate block max-w-[104px] sm:max-w-[160px]"
                      >
                        {user.username}
                      </button>
                      <div className={`flex items-center gap-1 mt-0.5 text-[10px] font-mono ${presence.cls}`} title={presence.title}>
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${presence.dot}`} />
                        <span className="truncate max-w-[104px] sm:max-w-[160px]">{presence.text}</span>
                      </div>
                    </div>
                  </div>
                </td>

                {/* Subscription */}
                <td className="px-3 py-3 whitespace-nowrap">
                  {user.subscription ? (
                    <button
                      onClick={() => setDetailUser(user.username)}
                      title={`Open dossier — expires ${user.subscription.expires_at ? formatDateTime(user.subscription.expires_at) : '—'}`}
                      className="text-left group"
                    >
                      <span className="px-2 py-1 rounded-lg text-[10px] font-mono border font-semibold bg-emerald-500/10 text-emerald-300 border-emerald-500/20 group-hover:bg-emerald-500/20">
                        {user.subscription.plan_name}
                      </span>
                      <span className="block text-[10px] text-slate-500 font-mono mt-0.5">
                        {timeLeft(user.subscription.expires_at) || 'active'}
                      </span>
                    </button>
                  ) : user.recharge_required === false ? (
                    <button
                      onClick={() => setDetailUser(user.username)}
                      title={`Exempt from recharge (${user.recharge_policy || 'policy'}) — no subscription needed. Click for dossier.`}
                      className="px-2 py-1 rounded-lg text-[10px] font-mono border font-semibold bg-slate-800 text-slate-400 border-slate-700 hover:border-indigo-500"
                    >
                      Exempt
                    </button>
                  ) : (
                    <button
                      onClick={() => setDetailUser(user.username)}
                      title="No active subscription — open dossier"
                      className="px-2 py-1 rounded-lg text-[10px] font-mono border font-semibold bg-rose-500/10 text-rose-300 border-rose-500/20 hover:bg-rose-500/20"
                    >
                      No sub
                    </button>
                  )}
                </td>

                {/* Group */}
                <td className="px-3 py-3 whitespace-nowrap">
                  {user.group ? (
                    <span className={`px-2 py-0.5 rounded-lg text-[10px] font-mono border font-semibold ${
                      user.group === 'admins' || user.group === 'admin'
                        ? 'bg-purple-500/10 text-purple-300 border-purple-500/20'
                        : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20'
                    }`}>
                      {user.group}
                    </span>
                  ) : (
                    <span className="text-slate-600 italic text-[11px]">—</span>
                  )}
                </td>

                {/* Cert */}
                <td className="px-3 py-3 whitespace-nowrap">
                  {user.has_certificate ? (
                    <span title="EAP-TLS certificate issued" className="inline-flex px-2 py-0.5 rounded-lg bg-emerald-500/10 text-emerald-400 text-[10px] font-bold border border-emerald-500/20 items-center gap-1">
                      <Check className="w-3 h-3 text-emerald-400" /> TLS
                    </span>
                  ) : (
                    <AsyncButton
                      onClick={() => handleIssueCert(user.username)}
                      title="Issue certificate"
                      className="text-slate-500 hover:text-indigo-300 text-[10px] border border-slate-800 px-2 py-0.5 rounded-lg hover:border-indigo-500 transition-colors flex items-center gap-1"
                      idleContent={<><Plus className="w-3 h-3" /> TLS</>}
                      okText="✓"
                    />
                  )}
                </td>

                {/* Network */}
                <td className="px-3 py-3 whitespace-nowrap">
                  {(user.reply_attributes || []).length ? (
                    <span className="flex items-center gap-1" title={(user.reply_attributes || []).map(a => `${a.attribute} ${a.op} ${a.value}`).join('\n')}>
                      {(user.reply_attributes || []).slice(0, 2).map((attr) => (
                        <span
                          key={attr.id}
                          className="px-1.5 py-0.5 rounded bg-cyan-950/60 text-cyan-300 text-[10px] font-mono border border-cyan-800/40"
                        >
                          {attr.attribute === 'Session-Timeout' ? `⏱ ${attr.value}s` : attr.attribute === 'Framed-IP-Address' ? `IP ${attr.value}` : `${attr.attribute} ${attr.value}`}
                        </span>
                      ))}
                      {(user.reply_attributes || []).length > 2 && (
                        <span className="text-[10px] text-slate-500 font-mono">+{user.reply_attributes.length - 2}</span>
                      )}
                    </span>
                  ) : (
                    <span className="text-slate-600 italic text-[11px]">default</span>
                  )}
                </td>

                {/* Actions: primary trio + overflow menu */}
                <td className="px-3 py-3 text-right whitespace-nowrap">
                  <span className="inline-flex items-center gap-0.5">
                    <button
                      onClick={() => handleOpenReset(user.username)}
                      title="Reset password"
                      className="p-1.5 text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 rounded-lg transition-colors"
                    >
                      <Key className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleOpenEdit(user)}
                      title="Edit user"
                      className="p-1.5 text-slate-300 hover:text-white hover:bg-slate-700/50 rounded-lg transition-colors"
                    >
                      <Edit className="w-4 h-4" />
                    </button>
                    <RowMenu
                      title={`More actions for ${user.username}`}
                      items={[
                        { icon: <MessageCircle className="w-4 h-4 text-emerald-400" />, label: 'Onboarding invite', onSelect: async () => { setOnboardUser(user); } },
                        { icon: <QrCode className="w-4 h-4 text-indigo-400" />, label: 'Wi-Fi QR pass', onSelect: async () => { setQrModalUser(user); } },
                        { icon: <Smartphone className="w-4 h-4 text-sky-400" />, label: 'Device MAC lock', onSelect: async () => { handleOpenDevicePolicy(user.username); } },
                        { icon: <Play className="w-4 h-4 text-indigo-400" />, label: 'Open in tester', onSelect: async () => { handleTestAuth(user.username); } },
                        user.banned
                          ? { icon: <Unlock className="w-4 h-4 text-emerald-400" />, label: 'Unban account', onSelect: () => quickBan(user.username, false) }
                          : { icon: <Lock className="w-4 h-4 text-rose-400" />, label: 'Ban account', onSelect: () => quickBan(user.username, true) },
                        ...(user.has_certificate
                          ? [{ icon: <Ban className="w-4 h-4 text-purple-400" />, label: 'Revoke certificate', onSelect: () => quickRevoke(user.username) }]
                          : []),
                        { icon: <Trash2 className="w-4 h-4 text-rose-400" />, label: 'Delete user', danger: true, onSelect: () => handleDeleteUser(user.username) },
                      ]}
                    />
                  </span>
                </td>

              </tr>
              );
            })}

            {filteredUsers.length === 0 && (
              <tr>
                <td colSpan={7} className="px-6 py-10 text-center text-slate-500 italic">
                  No users found matching current filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        </ResponsiveTable>
      </div>

      {/* ---------------------------------------------------- */}
      {/* 1. GUEST USER GENERATOR MODAL */}
      {/* ---------------------------------------------------- */}
      {guestModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-amber-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Bolt className="w-5 h-5 text-amber-400" />
                <span>Generate Temporary Guest Account</span>
              </h3>
              <button onClick={() => setGuestModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <p className="text-xs text-slate-400">
              Instant one-click Wi-Fi login generation with automated FreeRADIUS protocol expiration and session limits.
            </p>

            <form onSubmit={(e) => { e.preventDefault(); handleQuickGuest(guestDuration); }} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Access Duration (Expiry)</label>
                <select 
                  value={guestDuration} 
                  onChange={(e) => setGuestDuration(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-amber-500 outline-none font-medium"
                >
                  <option value="1h">1 Hour (Quick Pass)</option>
                  <option value="6h">6 Hours (Half Day)</option>
                  <option value="12h">12 Hours (Event Pass)</option>
                  <option value="24h">1 Day (24 Hours) — Default</option>
                  <option value="3d">3 Days (Weekend Pass)</option>
                  <option value="7d">7 Days (1 Week Pass)</option>
                  <option value="30d">30 Days (1 Month Pass)</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Policy Group</label>
                <select 
                  value={guestGroup} 
                  onChange={(e) => setGuestGroup(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-amber-500 outline-none"
                >
                  {groups.map((g) => (
                    <option key={g.groupname} value={g.groupname}>{g.groupname}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Username Prefix</label>
                <input 
                  type="text" 
                  value={guestPrefix} 
                  onChange={(e) => setGuestPrefix(e.target.value)}
                  placeholder="guest" 
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-amber-500 outline-none font-mono"
                />
              </div>

              <div className="bg-amber-950/30 border border-amber-500/20 rounded-2xl p-3 text-[11px] text-amber-200/80 flex items-start gap-2">
                <Clock className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
                <span>FreeRADIUS checks the <code>Expiration</code> attribute during auth and terminates active sessions when time expires.</span>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button 
                  type="button" 
                  onClick={() => setGuestModalOpen(false)}
                  className="px-4 py-2 text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  disabled={guestLoading}
                  className="px-5 py-2.5 bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 text-white rounded-xl font-bold flex items-center gap-2 shadow-lg shadow-amber-600/20 disabled:opacity-50"
                >
                  <Bolt className={`w-3.5 h-3.5 ${guestLoading ? 'animate-spin' : ''}`} />
                  <span>{guestLoading ? 'Generating...' : 'Generate Guest Credentials'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- */}
      {/* 2. ADD / EDIT USER MODAL */}
      {/* ---------------------------------------------------- */}
      {userModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Users className="w-5 h-5 text-indigo-400" />
                <span>{isEditing ? `Edit User: ${userForm.username}` : 'Add New RADIUS User'}</span>
              </h3>
              <button onClick={() => setUserModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveUser} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Username</label>
                <input 
                  type="text" 
                  value={userForm.username} 
                  disabled={isEditing}
                  onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                  required 
                  placeholder="e.g. user1 or member" 
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono disabled:opacity-60"
                />
              </div>

              {!isEditing && (
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">
                    Password <span className="text-slate-500 font-normal">(min 10 chars, any 3 of Aa 0 $ — e.g. 9876543210Ram@)</span>
                  </label>
                  <div className="flex gap-1.5">
                    <div className="relative flex-1">
                      <input 
                        type={showPass ? 'text' : 'password'} 
                        value={userForm.password} 
                        onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                        required 
                        placeholder="••••••••••••" 
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono"
                      />
                      <button 
                        type="button" 
                        onClick={() => setShowPass(!showPass)}
                        className="absolute right-2.5 top-2.5 text-slate-500 hover:text-white"
                      >
                        {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                    <button 
                      type="button" 
                      onClick={() => setUserForm({ ...userForm, password: generateRandomPass() })}
                      title="Generate secure random password" 
                      className="px-3 py-2 bg-amber-600/20 border border-amber-500/30 text-amber-300 rounded-xl hover:bg-amber-600/30 font-bold whitespace-nowrap flex items-center gap-1"
                    >
                      <Dice5 className="w-3.5 h-3.5" /> Generate
                    </button>
                  </div>
                  {userForm.password && (
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                        <div className="h-full rounded-full transition-all" style={{ width: `${passStrength.pct}%`, background: passStrength.color }} />
                      </div>
                      <span className="text-[10px] font-mono" style={{ color: passStrength.color }}>
                        {passStrength.label} ({passStrength.bits} bits)
                      </span>
                    </div>
                  )}
                </div>
              )}

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Policy Group</label>
                <select 
                  value={userForm.group} 
                  onChange={(e) => setUserForm({ ...userForm, group: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none"
                >
                  {groups.map((g) => (
                    <option key={g.groupname} value={g.groupname}>
                      {g.groupname} {g.is_admin ? ' ★ (Admin Privileges)' : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">
                  Static IP Address <span className="text-slate-500 font-normal">(optional — blank = DHCP)</span>
                </label>
                <input 
                  type="text" 
                  value={userForm.static_ip} 
                  onChange={(e) => setUserForm({ ...userForm, static_ip: e.target.value })}
                  placeholder="e.g. 192.168.1.50 (blank = DHCP)" 
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">
                  Phone Number <span className="text-slate-500 font-normal">(for WhatsApp/SMS onboarding)</span>
                </label>
                <input
                  type="tel"
                  value={userForm.phone || ''}
                  onChange={(e) => setUserForm({ ...userForm, phone: e.target.value })}
                  placeholder="e.g. +919876543210"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono"
                />
              </div>

              {isEditing && (
                <div className="bg-slate-950/60 border border-slate-800 rounded-2xl p-3 space-y-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-300 font-medium">Account status</span>
                    <button
                      type="button"
                      onClick={handleToggleBan}
                      disabled={editBusy === 'ban'}
                      title={editBanned ? 'Unban account' : 'Ban account (immediate reject, sessions kicked)'}
                      className={`px-3 py-1.5 rounded-xl text-[11px] font-bold border transition disabled:opacity-50 flex items-center gap-1.5 ${
                        editBanned
                          ? 'bg-rose-500/15 text-rose-300 border-rose-500/30 hover:bg-rose-500/25'
                          : 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20 hover:bg-emerald-500/20'
                      }`}
                    >
                      {editBusy === 'ban' ? (
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      ) : editBanned ? (
                        <Unlock className="w-3.5 h-3.5" />
                      ) : (
                        <Lock className="w-3.5 h-3.5" />
                      )}
                      <span>{editBusy === 'ban' ? 'Working…' : editBanned ? 'BANNED — click to unban' : 'Active — click to ban'}</span>
                    </button>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-300 font-medium">EAP-TLS certificate</span>
                    {editHasCert ? (
                      <button
                        type="button"
                        onClick={handleRevokeCertInEdit}
                        disabled={editBusy === 'revoke'}
                        className="px-3 py-1.5 rounded-xl text-[11px] font-bold bg-purple-500/10 text-purple-300 border border-purple-500/20 hover:bg-purple-500/20 transition disabled:opacity-50 flex items-center gap-1.5"
                      >
                        {editBusy === 'revoke' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
                        <span>{editBusy === 'revoke' ? 'Revoking…' : 'Revoke certificate'}</span>
                      </button>
                    ) : (
                      <span className="text-slate-600 italic">No certificate issued</span>
                    )}
                  </div>
                </div>
              )}

              {saveResult && (
                <div className={`rounded-xl border p-3 text-xs font-semibold flex items-center gap-2 ${saveResult.ok ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-rose-500/10 border-rose-500/20 text-rose-300'}`}>
                  {saveResult.ok ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                  <span>{saveResult.msg}</span>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button 
                  type="button" 
                  onClick={() => setUserModalOpen(false)}
                  className="px-4 py-2 text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  disabled={userModalSaving}
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold shadow-lg shadow-indigo-600/20 disabled:opacity-50"
                >
                  {userModalSaving ? 'Saving...' : 'Save User'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- */}
      {/* 3. RESET PASSWORD MODAL */}
      {/* ---------------------------------------------------- */}
      {resetModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Key className="w-5 h-5 text-amber-400" />
                <span>Reset Password: <code className="text-amber-300">{resetUsername}</code></span>
              </h3>
              <button onClick={() => setResetModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            {resetUsername === (typeof currentUser === 'string' ? currentUser : currentUser?.username) && (
              <div className="bg-rose-950/50 border border-rose-500/30 text-rose-200 text-xs rounded-xl p-3">
                ⚠️ You are resetting your <strong>own admin login</strong>. You will need to sign in again with the new password.
              </div>
            )}

            <div className="space-y-3.5 text-xs">
              <p className="-mb-1 text-[11px] text-slate-500">
                The current password can't be displayed (only hashes are stored) — this generates a
                <span className="text-amber-300 font-semibold"> new password that replaces it on save</span>.
              </p>
              <div>
                <label className="block text-slate-300 mb-1 font-medium">New auto-generated password</label>
                <div className="flex gap-1.5">
                  <div className="relative flex-1">
                    <input 
                      type={showResetPass ? 'text' : 'password'} 
                      value={resetPassword} 
                      onChange={(e) => setResetPassword(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 pr-16 text-white focus:border-amber-500 outline-none font-mono"
                    />
                    <div className="absolute right-2 top-2 flex items-center gap-1">
                      <CopyButton
                        text={resetPassword}
                        title="Copy new password"
                        className="text-slate-500 hover:text-white p-0.5"
                        iconClassName="w-4 h-4"
                        onCopied={() => onNotify?.('New password copied — save it to apply', 'success')}
                      />
                      <button 
                        type="button" 
                        onClick={() => setShowResetPass(!showResetPass)}
                        className="text-slate-500 hover:text-white p-0.5"
                      >
                        {showResetPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>
                  <button 
                    type="button" 
                    onClick={() => setResetPassword(generateRandomPass())}
                    className="px-3 py-2 bg-amber-600/20 border border-amber-500/30 text-amber-300 rounded-xl hover:bg-amber-600/30 font-bold whitespace-nowrap flex items-center gap-1"
                  >
                    <Dice5 className="w-3.5 h-3.5" /> Regenerate
                  </button>
                </div>

                <div className="mt-1.5 flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${resetStrength.pct}%`, background: resetStrength.color }} />
                  </div>
                  <span className="text-[10px] font-mono" style={{ color: resetStrength.color }}>
                    {resetStrength.label} ({resetStrength.bits} bits)
                  </span>
                </div>
              </div>

              <label className="flex items-center gap-2.5 text-xs text-slate-300 bg-slate-950 border border-slate-800 rounded-xl p-3 cursor-pointer">
                <input 
                  type="checkbox" 
                  checked={resetDisconnect} 
                  onChange={(e) => setResetDisconnect(e.target.checked)}
                  className="w-4 h-4 rounded text-amber-600 bg-slate-900 border-slate-700"
                />
                <span>Disconnect active sessions now (CoA / Port 3799)</span>
              </label>

              {resetResult && (
                <div className={`rounded-xl border p-3 text-xs font-semibold flex items-center gap-2 ${resetResult.ok ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-rose-500/10 border-rose-500/20 text-rose-300'}`}>
                  {resetResult.ok ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                  <span>{resetResult.msg}</span>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button 
                  type="button" 
                  onClick={() => setResetModalOpen(false)}
                  className="px-4 py-2 text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button 
                  type="button" 
                  onClick={() => handleSaveReset(false)}
                  disabled={resetSaving}
                  className="px-5 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-xl font-bold disabled:opacity-50 shadow-lg shadow-amber-600/20"
                >
                  {resetSaving ? 'Saving...' : 'Save'}
                </button>
                <button 
                  type="button" 
                  onClick={() => handleSaveReset(true)}
                  disabled={resetSaving}
                  title="Save, then open a Wi-Fi QR with the new password"
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold disabled:opacity-50 shadow-lg shadow-indigo-600/20 flex items-center gap-1.5"
                >
                  <QrCode className="w-4 h-4" />
                  <span>{resetSaving ? 'Saving...' : 'Save & QR'}</span>
                </button>
              </div>
            </div>

          </div>
        </div>
      )}

      {/* ---------------------------------------------------- */}
      {/* 3b. TEST RADIUS AUTH (password prompt + live verdict) */}
      {/* ---------------------------------------------------- */}
      {authTest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-indigo-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Play className="w-5 h-5 text-indigo-400" />
                <span>Test Auth: <code className="text-indigo-300">{authTest.username}</code></span>
              </h3>
              <button onClick={() => setAuthTest(null)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={runAuthTest} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">User password to test with</label>
                <input
                  type="password"
                  autoFocus
                  value={authTest.password}
                  onChange={(e) => setAuthTest({ ...authTest, password: e.target.value, result: null })}
                  placeholder="Enter current password"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-indigo-500 outline-none font-mono"
                />
                <p className="text-[11px] text-slate-500 mt-1">Stored passwords are hashes — enter the real secret to get a true verdict.</p>
              </div>
              <button
                type="submit"
                disabled={authTest.loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {authTest.loading ? 'Testing…' : 'Run test'}
              </button>
            </form>

            {authTest.result && (
              <div className={`rounded-2xl border p-3.5 text-xs ${authTest.result.success ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-rose-500/10 border-rose-500/20'}`}>
                <div className={`font-bold flex items-center gap-1.5 ${authTest.result.success ? 'text-emerald-300' : 'text-rose-300'}`}>
                  <span>{authTest.result.success ? '✓ Access-Accept' : `✗ ${authTest.result.status || 'Access-Reject'}`}</span>
                </div>
                {authTest.result.output && (
                  <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] text-slate-300 max-h-40 overflow-y-auto">{authTest.result.output}</pre>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- */}
      {/* 4. VERIFIED DEVICE MAC LOCK POLICY MODAL */}
      {/* ---------------------------------------------------- */}
      {deviceModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-sky-500/30 rounded-3xl max-w-xl w-full p-6 space-y-5 shadow-2xl relative max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="flex items-start justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-sky-500/10 text-sky-400 border border-sky-500/20 flex items-center justify-center">
                  <Smartphone className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <span>Verified Devices & MAC Lock:</span>
                    <span className="font-mono text-sky-300">{deviceUser}</span>
                  </h3>
                  <p className="text-xs text-slate-400">Lock RADIUS authentication to specific hardware MAC addresses</p>
                </div>
              </div>
              <button onClick={() => setDeviceModalOpen(false)} className="text-slate-400 hover:text-white p-1 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Lockdown Policy Switch */}
            <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  {devicePolicy?.require_verified ? (
                    <div className="p-2 rounded-xl bg-rose-500/10 text-rose-400 border border-rose-500/20">
                      <Lock className="w-4 h-4" />
                    </div>
                  ) : (
                    <div className="p-2 rounded-xl bg-slate-800 text-slate-400 border border-slate-700">
                      <Unlock className="w-4 h-4" />
                    </div>
                  )}
                  <div>
                    <div className="text-xs font-bold text-white flex items-center gap-2">
                      <span>Hardware MAC Lockdown:</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-mono ${
                        devicePolicy?.require_verified
                          ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30 font-bold'
                          : 'bg-slate-800 text-slate-400 border border-slate-700'
                      }`}>
                        {devicePolicy?.require_verified ? 'Enforced (Locked)' : 'Disabled (Open)'}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      {devicePolicy?.require_verified
                        ? "Only devices listed below can authenticate with this user's credentials."
                        : "Any device can authenticate with valid credentials (standard 802.1X behavior)."}
                    </p>
                  </div>
                </div>

                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(devicePolicy?.require_verified)}
                    onChange={(e) => handleToggleDeviceLock(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-sky-600"></div>
                </label>
              </div>
            </div>

            {/* Add Device Form */}
            <form onSubmit={handleAddDevice} className="bg-slate-950/60 border border-slate-800 rounded-2xl p-4 space-y-3 text-xs">
              <span className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                <Plus className="w-4 h-4 text-sky-400" /> Add Verified Device
              </span>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium text-[11px]">MAC Address *</label>
                  <input
                    type="text"
                    required
                    placeholder="AA:BB:CC:DD:EE:FF"
                    value={newMac}
                    onChange={(e) => setNewMac(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono placeholder:text-slate-600 focus:border-sky-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium text-[11px]">Device Name / Label (Optional)</label>
                  <input
                    type="text"
                    placeholder="e.g. Office MacBook Pro, iPhone 15"
                    value={newMacDesc}
                    onChange={(e) => setNewMacDesc(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white placeholder:text-slate-600 focus:border-sky-500 outline-none"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-1">
                <button
                  type="submit"
                  className="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-md shadow-sky-600/20 transition-all"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Verify & Allow MAC</span>
                </button>
              </div>
            </form>

            {/* List of Verified MACs */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-slate-300 uppercase tracking-wider">
                  Verified MAC Allowlist ({devicePolicy?.devices?.length || 0})
                </span>
                {devicePolicy?.require_verified && (devicePolicy?.devices?.length === 0) && (
                  <span className="text-rose-400 text-[11px] font-medium flex items-center gap-1">
                    <ShieldAlert className="w-3.5 h-3.5" /> No MACs allowed — user cannot connect!
                  </span>
                )}
              </div>

              {deviceLoading ? (
                <div className="p-8 text-center text-slate-500 text-xs flex items-center justify-center gap-2">
                  <RefreshCw className="w-4 h-4 animate-spin text-sky-400" />
                  <span>Loading verified devices...</span>
                </div>
              ) : !devicePolicy?.devices || devicePolicy.devices.length === 0 ? (
                <div className="p-6 bg-slate-950/40 border border-slate-800/80 rounded-2xl text-center text-slate-500 text-xs italic">
                  No verified MAC addresses registered for this user yet.
                </div>
              ) : (
                <div className="space-y-2 max-h-60 overflow-y-auto scrollbar-thin">
                  {devicePolicy.devices.map((d) => (
                    <div
                      key={d.mac}
                      className="bg-slate-950 border border-slate-800/90 rounded-2xl p-3.5 flex items-center justify-between gap-3 text-xs"
                    >
                      <div className="flex items-center gap-3 truncate">
                        <div className="w-8 h-8 rounded-xl bg-sky-500/10 text-sky-400 border border-sky-500/20 flex items-center justify-center shrink-0">
                          <Smartphone className="w-4 h-4" />
                        </div>
                        <div className="truncate">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-white font-bold">{d.pretty || d.mac}</span>
                            {d.vendor && (
                              <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-medium truncate">
                                {d.vendor}
                              </span>
                            )}
                          </div>
                          <div className="text-slate-400 text-[11px] truncate mt-0.5">
                            {d.label ? <span className="text-slate-300 font-medium">{d.label}</span> : 'Unlabeled Device'}
                            {d.added_at && <span className="text-slate-500 ml-1.5">• Added {new Date(d.added_at).toLocaleDateString()}</span>}
                          </div>
                        </div>
                      </div>

                      <button
                        onClick={() => handleDeleteDevice(d.mac)}
                        title="Remove verified MAC"
                        className="p-1.5 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors border border-rose-500/20 shrink-0"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-end pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setDeviceModalOpen(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- */}
      {/* 5. WI-FI QR ACCESS PASS / SCAN / SEND MODAL */}
      {/* ---------------------------------------------------- */}
      <WifiQrModal
        isOpen={Boolean(qrModalUser)}
        onClose={() => setQrModalUser(null)}
        user={qrModalUser}
        onNotify={onNotify}
      />

      {/* 6. SUBSCRIBER DOSSIER POPUP */}
      {detailUser && (
        <UserDetailModal
          username={detailUser}
          onClose={() => setDetailUser(null)}
          onNotify={onNotify}
        />
      )}

      {/* 7. ISSUED-CERT HANDOFF (gated on copy/download) */}
      {certIssued && (
        <CertIssuedModal
          data={certIssued}
          onClose={() => setCertIssued(null)}
          onNotify={onNotify}
        />
      )}

      {/* 8. ONBOARDING INVITE (WhatsApp/SMS) */}
      {onboardUser && (
        <OnboardModal
          user={onboardUser}
          initialPassword={lastCreatedCreds?.username === onboardUser.username ? lastCreatedCreds.password : ''}
          onClose={() => setOnboardUser(null)}
          onSavePhone={handleSaveOnboardPhone}
          onNotify={onNotify}
        />
      )}

    </div>
  );
}
