import React, { useState } from 'react';
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
  Trash2, 
  Clock, 
  Hourglass, 
  Check, 
  Plus, 
  X, 
  Dice5, 
  Eye, 
  EyeOff, 
  Copy, 
  Smartphone 
} from 'lucide-react';
import { calculatePasswordStrength } from '../utils/api';

export default function UsersTab({
  users = [],
  groups = [],
  currentUser,
  onSaveUser,
  onDeleteUser,
  onResetPassword,
  onGenerateGuest,
  onOpenDevicePolicy,
  onTestAuth,
  onIssueCert,
  onCopyText
}) {
  const [search, setSearch] = useState('');
  const [groupFilter, setGroupFilter] = useState('');
  
  // Guest Generator Modal & State
  const [guestModalOpen, setGuestModalOpen] = useState(false);
  const [guestDuration, setGuestDuration] = useState('24h');
  const [guestGroup, setGuestGroup] = useState(groups[0]?.groupname || 'guests');
  const [guestPrefix, setGuestPrefix] = useState('guest');
  const [guestLoading, setGuestLoading] = useState(false);

  // User Add/Edit Modal
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [userForm, setUserForm] = useState({ username: '', password: '', group: 'staff', static_ip: '' });
  const [showPass, setShowPass] = useState(false);
  const [userModalSaving, setUserModalSaving] = useState(false);

  // Reset Password Modal
  const [resetModalOpen, setResetModalOpen] = useState(false);
  const [resetUsername, setResetUsername] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [resetDisconnect, setResetDisconnect] = useState(false);
  const [resetSaving, setResetSaving] = useState(false);
  const [showResetPass, setShowResetPass] = useState(true);

  // Generate random password helper
  const generateRandomPass = () => {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%&*";
    let pass = "";
    for (let i = 0; i < 14; i++) {
      pass += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return pass;
  };

  const handleOpenAdd = () => {
    setIsEditing(false);
    setUserForm({
      username: '',
      password: generateRandomPass(),
      group: groups[0]?.groupname || 'staff',
      static_ip: ''
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
      static_ip: framed ? framed.value : ''
    });
    setShowPass(false);
    setUserModalOpen(true);
  };

  const handleSaveUser = async (e) => {
    e.preventDefault();
    setUserModalSaving(true);
    try {
      await onSaveUser({
        username: userForm.username,
        password: userForm.password,
        group: userForm.group,
        framed_ip: userForm.static_ip
      }, isEditing);
      setUserModalOpen(false);
    } finally {
      setUserModalSaving(false);
    }
  };

  const handleOpenReset = (username) => {
    setResetUsername(username);
    setResetPassword(generateRandomPass());
    setResetDisconnect(false);
    setShowResetPass(true);
    setResetModalOpen(true);
  };

  const handleSaveReset = async () => {
    setResetSaving(true);
    try {
      await onResetPassword(resetUsername, resetPassword, resetDisconnect);
      setResetModalOpen(false);
    } finally {
      setResetSaving(false);
    }
  };

  const handleQuickGuest = async (dur = '24h') => {
    setGuestLoading(true);
    try {
      await onGenerateGuest({
        duration: dur,
        group: guestGroup,
        prefix: guestPrefix
      });
      setGuestModalOpen(false);
    } finally {
      setGuestLoading(false);
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

      {/* Users Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-sm">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-950/60 text-slate-400 uppercase border-b border-slate-800 text-[10px] tracking-wider">
            <tr>
              <th className="px-6 py-4">Username & Status</th>
              <th className="px-6 py-4">Group Policy</th>
              <th className="px-6 py-4">EAP-TLS Certificate</th>
              <th className="px-6 py-4">Network Attributes</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/80">
            {filteredUsers.map((user) => (
              <tr key={user.username} className="hover:bg-slate-800/40 transition-colors">
                
                {/* Username + Expiry + Online Status */}
                <td className="px-6 py-4 font-semibold text-white">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-xl bg-slate-800 border border-slate-700/80 flex items-center justify-center text-xs text-slate-300 font-mono font-bold">
                      {user.username.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div className="font-bold text-slate-100 flex items-center gap-2">
                        <span>{user.username}</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 mt-1">
                        {user.active_sessions > 0 && (
                          <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 text-[9px] font-mono border border-emerald-500/20 flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                            {user.active_sessions} online
                          </span>
                        )}
                        {user.expiration && (
                          <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 text-[9px] font-mono border border-amber-500/20 flex items-center gap-1" title={`FreeRADIUS Expiration: ${user.expiration}`}>
                            <Hourglass className="w-2.5 h-2.5 text-amber-400" />
                            <span>Exp: {user.expiration}</span>
                          </span>
                        )}
                        {user.last_auth && (
                          <span className="text-[10px] text-slate-500 font-mono">
                            last: {user.last_auth}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </td>

                {/* Group Policy */}
                <td className="px-6 py-4">
                  {user.group ? (
                    <span className={`px-2.5 py-1 rounded-xl text-[10px] font-mono border font-semibold ${
                      user.group === 'admins' || user.group === 'admin'
                        ? 'bg-purple-500/10 text-purple-300 border-purple-500/20'
                        : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20'
                    }`}>
                      {user.group}
                    </span>
                  ) : (
                    <span className="text-slate-600 italic">No Group</span>
                  )}
                </td>

                {/* EAP-TLS Cert */}
                <td className="px-6 py-4">
                  {user.has_certificate ? (
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-[10px] font-medium border border-emerald-500/20 flex items-center gap-1">
                        <Check className="w-3 h-3 text-emerald-400" /> Issued
                      </span>
                      <a 
                        href={`/radius/api/certs/${user.username}/download`} 
                        download 
                        className="text-indigo-400 hover:text-indigo-300 text-xs font-semibold underline"
                      >
                        .p12
                      </a>
                      <a 
                        href={`/radius/api/certs/${user.username}/mobileconfig`} 
                        download 
                        className="text-cyan-400 hover:text-cyan-300 text-xs font-semibold underline"
                      >
                        Profile
                      </a>
                    </div>
                  ) : (
                    <button
                      onClick={() => onIssueCert(user.username)}
                      className="text-slate-400 hover:text-indigo-300 text-[10px] border border-slate-700 px-2.5 py-1 rounded-lg hover:border-indigo-500 transition-colors flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Issue Cert
                    </button>
                  )}
                </td>

                {/* Reply Attributes */}
                <td className="px-6 py-4">
                  <div className="flex flex-wrap gap-1">
                    {(user.reply_attributes || []).map((attr) => (
                      <span 
                        key={attr.id}
                        className="px-2 py-0.5 rounded-md bg-cyan-950/60 text-cyan-300 text-[10px] font-mono border border-cyan-800/40"
                      >
                        {attr.attribute} {attr.op} {attr.value}
                      </span>
                    ))}
                    {(!user.reply_attributes || user.reply_attributes.length === 0) && (
                      <span className="text-slate-600 italic text-[11px]">Group Default</span>
                    )}
                  </div>
                </td>

                {/* Action Buttons */}
                <td className="px-6 py-4 text-right space-x-1 whitespace-nowrap">
                  <button
                    onClick={() => onOpenDevicePolicy(user.username)}
                    title="Verified Device MAC Lock Policy"
                    className="p-1.5 text-sky-400 hover:text-sky-300 hover:bg-sky-500/10 rounded-lg transition-colors"
                  >
                    <Smartphone className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleOpenReset(user.username)}
                    title="Reset password (1-click secure regenerate)"
                    className="p-1.5 text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 rounded-lg transition-colors"
                  >
                    <Key className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleOpenEdit(user)}
                    title="Edit user settings"
                    className="p-1.5 text-slate-300 hover:text-white hover:bg-slate-700/50 rounded-lg transition-colors"
                  >
                    <Edit className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => onTestAuth(user.username)}
                    title="Test RADIUS Auth"
                    className="p-1.5 text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 rounded-lg transition-colors"
                  >
                    <Play className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => onDeleteUser(user.username)}
                    title="Delete User"
                    className="p-1.5 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>

              </tr>
            ))}

            {filteredUsers.length === 0 && (
              <tr>
                <td colSpan={5} className="px-6 py-10 text-center text-slate-500 italic">
                  No users found matching current filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
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
                    Password <span className="text-slate-500 font-normal">(min 12 chars: Aa 0 $)</span>
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
              <div>
                <label className="block text-slate-300 mb-1 font-medium">New Password</label>
                <div className="flex gap-1.5">
                  <div className="relative flex-1">
                    <input 
                      type={showResetPass ? 'text' : 'password'} 
                      value={resetPassword} 
                      onChange={(e) => setResetPassword(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-white focus:border-amber-500 outline-none font-mono"
                    />
                    <button 
                      type="button" 
                      onClick={() => setShowResetPass(!showResetPass)}
                      className="absolute right-2.5 top-2.5 text-slate-500 hover:text-white"
                    >
                      {showResetPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
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
                  onClick={handleSaveReset}
                  disabled={resetSaving}
                  className="px-5 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-xl font-bold disabled:opacity-50 shadow-lg shadow-amber-600/20"
                >
                  {resetSaving ? 'Saving...' : 'Save New Password'}
                </button>
              </div>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}
