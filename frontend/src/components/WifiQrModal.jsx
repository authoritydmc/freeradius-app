import React, { useRef } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Wifi, Download, Copy, Check, X, Shield, Smartphone, Printer, ExternalLink } from 'lucide-react';

export default function WifiQrModal({ isOpen, onClose, ssid = 'RajLabs-Enterprise', password = '', username = '', authType = 'WPA', onNotify }) {
  const [copied, setCopied] = React.useState(false);
  const qrRef = useRef(null);

  if (!isOpen) return null;

  // Build standard Wi-Fi QR schema: WIFI:T:WPA;S:MySSID;P:MyPassword;;
  // For open: WIFI:T:nopass;S:MySSID;;
  const wifiString = password
    ? `WIFI:T:WPA;S:${ssid};P:${password};;`
    : `WIFI:T:nopass;S:${ssid};;`;

  // Direct portal onboarding URL
  const portalUrl = `${window.location.origin}/radius/portal`;

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    onNotify?.('Copied Wi-Fi connection string to clipboard', 'info');
    setTimeout(() => setCopied(false), 2000);
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in print:p-0 print:bg-white">
      <div className="bg-slate-900 border border-slate-750 rounded-3xl w-full max-w-md overflow-hidden shadow-2xl print:border-none print:shadow-none print:bg-white print:text-black">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/60 print:hidden">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
              <Wifi className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Direct Connect Wi-Fi QR</h3>
              <p className="text-xs text-slate-400">Scan with camera to connect immediately</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-lg transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 text-center space-y-5">
          {/* Printable Container */}
          <div ref={qrRef} className="space-y-4">
            <div className="inline-block p-4 bg-white rounded-2xl shadow-xl shadow-indigo-500/10 border-4 border-indigo-500/20">
              <QRCodeSVG
                value={wifiString}
                size={210}
                level="H"
                includeMargin={false}
                imageSettings={{
                  src: "/favicon.ico",
                  x: undefined,
                  y: undefined,
                  height: 32,
                  width: 32,
                  excavate: true,
                }}
              />
            </div>

            <div>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 font-mono">
                <Wifi className="w-3.5 h-3.5 text-indigo-400" />
                <span>SSID: {ssid}</span>
              </div>
              {username && (
                <p className="text-xs text-slate-300 font-mono mt-1.5">
                  User: <span className="font-bold text-white">{username}</span>
                </p>
              )}
            </div>
          </div>

          {/* Credentials Info Box */}
          <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 text-left space-y-2 text-xs print:border-slate-300">
            <div className="flex justify-between items-center text-slate-300">
              <span className="text-slate-400">Network (SSID):</span>
              <span className="font-mono font-bold text-white">{ssid}</span>
            </div>
            {password ? (
              <div className="flex justify-between items-center text-slate-300">
                <span className="text-slate-400">Wi-Fi Password:</span>
                <span className="font-mono font-bold text-amber-300">{password}</span>
              </div>
            ) : (
              <div className="flex justify-between items-center text-slate-300">
                <span className="text-slate-400">Security Mode:</span>
                <span className="font-mono text-emerald-400 font-semibold">{authType || 'Open / Captive Web Auth'}</span>
              </div>
            )}
            <div className="flex justify-between items-center text-slate-300">
              <span className="text-slate-400">Self-Service URL:</span>
              <span className="font-mono text-cyan-400 truncate max-w-[200px]">{portalUrl}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="grid grid-cols-2 gap-3 pt-2 print:hidden">
            <button
              onClick={() => handleCopy(wifiString)}
              className="flex items-center justify-center gap-2 py-2.5 px-3 bg-slate-800 hover:bg-slate-750 text-slate-200 rounded-xl text-xs font-semibold border border-slate-700 transition"
            >
              {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              <span>{copied ? 'Copied' : 'Copy String'}</span>
            </button>
            <button
              onClick={handlePrint}
              className="flex items-center justify-center gap-2 py-2.5 px-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition"
            >
              <Printer className="w-4 h-4" />
              <span>Print QR Badge</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
