import React, { useState, useEffect } from 'react';
import { 
  Smartphone, Laptop, RefreshCw, Search, Shield, HardDrive,
  Globe, Clock, ArrowDown, ArrowUp, Activity, AlertTriangle, CheckCircle2
} from 'lucide-react';
import { fetchJson, formatBytes, formatDateTime } from '../utils/api';

export default function DevicesTab({ onNotify }) {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const loadDevices = async () => {
    try {
      setLoading(true);
      const data = await fetchJson('devices?limit=200');
      setDevices(data || []);
    } catch (err) {
      onNotify?.(err.message || 'Failed to load device inventory', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDevices();
  }, []);

  const filtered = devices.filter(d =>
    (d.mac || '').toLowerCase().includes(search.toLowerCase()) ||
    (d.vendor || '').toLowerCase().includes(search.toLowerCase()) ||
    (d.username || '').toLowerCase().includes(search.toLowerCase()) ||
    (d.ip || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-cyan-500/10 rounded-xl border border-cyan-500/20 text-cyan-400">
            <Smartphone className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Device Inventory & Station Fingerprints</h2>
            <p className="text-xs text-slate-400">Hardware OUI vendor identification, MAC addresses, and station usage</p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search MAC, vendor, user..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700/70 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            />
          </div>
          <button
            onClick={loadDevices}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl border border-slate-700 transition"
            title="Refresh Devices"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Devices Grid */}
      {loading && devices.length === 0 ? (
        <div className="flex items-center justify-center p-12 text-slate-400">
          <RefreshCw className="w-6 h-6 animate-spin text-cyan-400 mr-3" />
          <span>Analyzing station MAC records...</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-12 text-center text-slate-400">
          <Smartphone className="w-12 h-12 mx-auto mb-3 text-slate-600 opacity-60" />
          <h3 className="text-base font-semibold text-slate-300">No Station Devices Discovered</h3>
          <p className="text-xs text-slate-500 mt-1">Devices connecting to your Wi-Fi APs will be indexed automatically from Calling-Station-Id.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filtered.map(dev => {
            const isOnline = dev.is_online || dev.online_count > 0;
            const isRandomized = dev.mac && /^[0-9a-fA-F][26AEae]/.test(dev.mac.replace(/[:-]/g, ''));
            return (
              <div 
                key={dev.mac}
                className={`bg-slate-900/70 border rounded-2xl p-5 flex flex-col justify-between transition shadow-lg ${isOnline ? 'border-cyan-500/40 hover:border-cyan-500/70' : 'border-slate-800/90 hover:border-slate-700'}`}
              >
                <div>
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div className="flex items-center gap-2.5">
                      <div className={`p-2 rounded-xl ${isOnline ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                        <Smartphone className="w-5 h-5" />
                      </div>
                      <div>
                        <h3 className="font-bold text-slate-100 font-mono text-sm tracking-wider">
                          {dev.mac}
                        </h3>
                        <p className="text-xs text-slate-400 font-medium">{dev.vendor || 'Unknown Hardware Vendor'}</p>
                      </div>
                    </div>

                    <div>
                      {isOnline ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                          Online
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700 uppercase">
                          Offline
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Attributes Badges */}
                  <div className="space-y-2 mt-3 pt-3 border-t border-slate-800/80 text-xs">
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="text-slate-400">Owner User:</span>
                      <span className="font-mono text-indigo-300 font-semibold">{dev.username || '—'}</span>
                    </div>

                    <div className="flex items-center justify-between text-slate-300">
                      <span className="text-slate-400">Last Assigned IP:</span>
                      <span className="font-mono text-cyan-300">{dev.ip || '—'}</span>
                    </div>

                    <div className="flex items-center justify-between text-slate-300">
                      <span className="text-slate-400">Total Sessions:</span>
                      <span className="font-mono text-slate-200">{dev.sessions || 1}</span>
                    </div>

                    <div className="flex items-center justify-between text-slate-300">
                      <span className="text-slate-400">Data Transferred:</span>
                      <span className="font-mono text-emerald-400 font-medium">
                        {formatBytes((dev.up_bytes || 0) + (dev.down_bytes || 0))}
                      </span>
                    </div>

                    {isRandomized && (
                      <div className="flex items-center gap-1.5 text-[11px] text-amber-400/90 bg-amber-500/10 p-1.5 rounded-lg border border-amber-500/20 mt-2">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        <span>Private / Randomized MAC Address enabled</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-500">
                  <span>First: {formatDateTime(dev.first_seen)}</span>
                  <span>Last: {formatDateTime(dev.last_seen)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
