import React, { useState } from 'react';
import { 
  Shield, Key, Lock, User, FileCode, CheckCircle2, 
  AlertCircle, RefreshCw, ArrowRight, UploadCloud, Sparkles, Wifi
} from 'lucide-react';
import { setAuthToken, setUserToken, setUserInfo, fetchJson, apiRequest } from '../utils/api';

export default function LoginView({ onLoginSuccess }) {
  const [mode, setMode] = useState('password'); // 'password' or 'cert'
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [certFile, setCertFile] = useState(null);
  const [p12Password, setP12Password] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handlePasswordLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await fetchJson('auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password })
      });
      if (data.token) {
        const role = data.role || data.user?.role || (data.group === 'admins' || data.group === 'admin' ? 'admin' : 'user');
        const userObj = {
          username: data.username || data.user?.username || username,
          role: role,
          group: data.group || data.user?.group || (role === 'admin' ? 'admins' : 'default')
        };
        setUserInfo(userObj);
        if (role === 'admin') {
          setAuthToken(data.token);
        } else {
          setUserToken(data.token);
        }
        onLoginSuccess?.(userObj, data.token);
      } else {
        throw new Error('No token returned from server.');
      }
    } catch (err) {
      setError(err.message || 'Invalid username or password.');
    } finally {
      setLoading(false);
    }
  };

  const handleCertLogin = async (e) => {
    e.preventDefault();
    if (!certFile) {
      setError('Please select your .crt, .pem, or .p12 certificate file.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append('cert_file', certFile);
      if (p12Password) {
        formData.append('p12_password', p12Password);
      }

      const res = await apiRequest('auth/cert-login', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Certificate verification failed');
      }

      if (data.token) {
        const role = data.role || data.user?.role || (data.group === 'admins' || data.group === 'admin' ? 'admin' : 'user');
        const userObj = {
          username: data.username || data.user?.username || 'Certificate User',
          role: role,
          group: data.group || data.user?.group || (role === 'admin' ? 'admins' : 'default')
        };
        setUserInfo(userObj);
        if (role === 'admin') {
          setAuthToken(data.token);
        } else {
          setUserToken(data.token);
        }
        onLoginSuccess?.(userObj, data.token);
      } else {
        throw new Error('No token issued for certificate.');
      }
    } catch (err) {
      setError(err.message || 'Certificate authentication failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center items-center p-4 relative overflow-hidden">
      {/* Dynamic Background Glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-gradient-to-tr from-indigo-600/20 via-violet-600/15 to-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-md z-10">
        {/* Brand Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center p-3.5 bg-gradient-to-tr from-indigo-600 to-violet-600 rounded-2xl shadow-xl shadow-indigo-500/20 mb-3 border border-indigo-400/30">
            <Wifi className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-black text-white tracking-tight">RajLabs FreeRADIUS</h1>
          <p className="text-xs text-slate-400 mt-1">Enterprise AAA Authentication & Security Platform</p>
        </div>

        {/* Card */}
        <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-7 shadow-2xl shadow-black/50">
          {/* Switcher */}
          <div className="flex bg-slate-950 p-1.5 rounded-2xl border border-slate-800 mb-6">
            <button
              type="button"
              onClick={() => { setMode('password'); setError(''); }}
              className={`flex-1 py-2 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition ${mode === 'password' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-200'}`}
            >
              <Key className="w-3.5 h-3.5" />
              <span>Password Login</span>
            </button>
            <button
              type="button"
              onClick={() => { setMode('cert'); setError(''); }}
              className={`flex-1 py-2 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition ${mode === 'cert' ? 'bg-violet-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-200'}`}
            >
              <FileCode className="w-3.5 h-3.5" />
              <span>X.509 Certificate</span>
            </button>
          </div>

          {error && (
            <div className="mb-5 p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          {mode === 'password' ? (
            <form onSubmit={handlePasswordLogin} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Username</label>
                <div className="relative">
                  <User className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type="text"
                    required
                    placeholder="Admin or User username"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Password</label>
                <div className="relative">
                  <Lock className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type="password"
                    required
                    placeholder="Enter account password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition font-mono"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full mt-2 py-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-500/25 flex items-center justify-center gap-2 transition disabled:opacity-50 cursor-pointer"
              >
                {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
                <span>{loading ? 'Authenticating...' : 'Sign In to Console'}</span>
              </button>
            </form>
          ) : (
            <form onSubmit={handleCertLogin} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Upload X.509 Client Certificate</label>
                <div className="relative border-2 border-dashed border-slate-750 hover:border-violet-500/60 rounded-2xl p-5 text-center transition bg-slate-950/50">
                  <UploadCloud className="w-8 h-8 mx-auto mb-2 text-violet-400 opacity-80" />
                  <p className="text-xs font-medium text-slate-300">
                    {certFile ? certFile.name : 'Select .p12, .crt, or .pem client certificate'}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">Cryptographically validated against Root CA</p>
                  <input
                    type="file"
                    accept=".p12,.pfx,.crt,.pem"
                    onChange={e => setCertFile(e.target.files[0])}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  />
                </div>
              </div>

              {certFile && (certFile.name.endsWith('.p12') || certFile.name.endsWith('.pfx')) && (
                <div className="space-y-1.5 animate-fade-in">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">PKCS#12 Bundle Password</label>
                  <input
                    type="password"
                    placeholder="Enter certificate unlock password"
                    value={p12Password}
                    onChange={e => setP12Password(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-violet-500 font-mono"
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full mt-2 py-3 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-sm font-semibold shadow-lg shadow-violet-500/25 flex items-center justify-center gap-2 transition disabled:opacity-50 cursor-pointer"
              >
                {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
                <span>{loading ? 'Verifying Certificate...' : 'Authenticate with Certificate'}</span>
              </button>
            </form>
          )}

          <div className="mt-6 pt-5 border-t border-slate-800/80 text-center">
            <a
              href="/radius/portal"
              className="text-xs text-indigo-400 hover:text-indigo-300 transition flex items-center justify-center gap-1.5"
            >
              <span>Switch to Captive Wi-Fi Self-Service Portal</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
