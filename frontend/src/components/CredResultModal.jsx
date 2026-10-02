import React, { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { 
  CheckCircle2, 
  Copy, 
  Eye, 
  EyeOff, 
  QrCode, 
  Download, 
  Share2, 
  X, 
  Hourglass, 
  Wifi,
  Mail 
} from 'lucide-react';

export default function CredResultModal({ data, cred, onClose, onCopy }) {
  const activeCred = data || cred;
  if (!activeCred) return null;

  const [showPass, setShowPass] = useState(true);
  const [showQr, setShowQr] = useState(true);

  const ssid = activeCred.ssid || 'RajLabs-Enterprise';
  const username = activeCred.username || '';
  const password = activeCred.password || '';
  const validity = activeCred.validity || '';
  const phoneDigits = String(activeCred.phone || '').replace(/\D/g, '');
  const portalUrl = typeof window !== 'undefined' ? `${window.location.origin}/radius/portal` : '/radius/portal';

  // Standard Wi-Fi direct connect string (scannable by iOS and Android cameras)
  const wifiString = password
    ? `WIFI:T:WPA;S:${ssid};P:${password};;`
    : `WIFI:T:nopass;S:${ssid};;`;

  const shareText = `RajLabs Wi-Fi Network Access\nSSID: ${ssid}\nUsername: ${username}\nPassword: ${password}${validity ? `\nValidity: ${validity}` : ''}\nPortal: ${portalUrl}\n(Scan the QR code to connect directly)`;

  const handleDownloadTxt = () => {
    const blob = new Blob([shareText + `\nIssued on ${new Date().toISOString()}\n`], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `RajLabs_${username}_credentials.txt`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 500);
  };

  const handleCopyText = (text, msg) => {
    if (onCopy) {
      onCopy(text, msg);
    } else {
      navigator.clipboard.writeText(text);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="bg-slate-900 border border-emerald-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-2 border-b border-slate-800">
          <div className="flex items-center gap-2.5 text-emerald-300 font-bold text-base">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            <span>{activeCred.title || 'Wi-Fi Credentials Issued'}</span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1 rounded-lg">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Credentials Info Box */}
        <div className="bg-slate-950 border border-slate-800/90 rounded-2xl p-4 space-y-3 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-slate-400 font-sans">Network SSID</span>
            <span className="text-indigo-300 font-bold bg-indigo-500/10 px-2.5 py-1 rounded-lg border border-indigo-500/20">
              {ssid}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-slate-400 font-sans">Username</span>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-800">
                {username}
              </span>
              <button 
                onClick={() => handleCopyText(username, 'Username copied to clipboard')}
                className="text-slate-400 hover:text-white p-1"
                title="Copy Username"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-slate-400 font-sans">Password</span>
            <div className="flex items-center gap-2">
              <span className="text-amber-300 font-bold bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-800">
                {showPass ? password : '••••••••••••'}
              </span>
              <button 
                onClick={() => setShowPass(!showPass)}
                className="text-slate-400 hover:text-white p-1"
                title={showPass ? 'Hide password' : 'Show password'}
              >
                {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
              <button 
                onClick={() => handleCopyText(password, 'Password copied to clipboard')}
                className="text-slate-400 hover:text-white p-1"
                title="Copy Password"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>

          {validity && (
            <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-indigo-300 font-sans">
              <span className="text-slate-400 flex items-center gap-1">
                <Hourglass className="w-3.5 h-3.5 text-amber-400" /> Duration
              </span>
              <span className="font-semibold text-amber-300">{validity}</span>
            </div>
          )}
        </div>

        {/* Direct Connect Wi-Fi QR Code */}
        {showQr && (
          <div className="flex flex-col items-center justify-center p-4 bg-white rounded-2xl shadow-inner border border-slate-200">
            <QRCodeSVG
              value={wifiString}
              size={180}
              level="H"
              includeMargin={false}
            />
            <div className="flex items-center gap-1.5 text-slate-800 font-bold text-xs mt-2">
              <Wifi className="w-3.5 h-3.5 text-indigo-600" />
              <span>Direct Connect QR (Scan to Join)</span>
            </div>
            <p className="text-[10px] text-slate-500 mt-0.5">Point phone camera at QR to connect instantly</p>
          </div>
        )}

        {/* Quick Action Share Buttons */}
        <div className="grid grid-cols-2 gap-2 text-xs font-sans">
          <button 
            onClick={() => handleCopyText(shareText, 'Credential share text copied')}
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl flex items-center justify-center gap-1.5 transition"
          >
            <Copy className="w-3.5 h-3.5" />
            <span>Copy Details</span>
          </button>
          
          <button 
            onClick={handleDownloadTxt}
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl flex items-center justify-center gap-1.5 transition"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Save .txt</span>
          </button>

          <a 
            href={phoneDigits ? `https://wa.me/${phoneDigits}?text=${encodeURIComponent(shareText)}` : `https://wa.me/?text=${encodeURIComponent(shareText)}`}
            target="_blank" 
            rel="noopener noreferrer"
            title={phoneDigits ? `Send to ${activeCred.phone} on WhatsApp` : 'Share via WhatsApp'}
            className="px-3 py-2 bg-emerald-700 hover:bg-emerald-600 text-white rounded-xl flex items-center justify-center gap-1.5 transition font-medium text-center"
          >
            <i className="fa-brands fa-whatsapp text-sm" />
            <span>{phoneDigits ? 'WhatsApp user' : 'WhatsApp'}</span>
          </a>

          <a 
            href={`mailto:?subject=${encodeURIComponent(`RajLabs Wi-Fi Access for ${username}`)}&body=${encodeURIComponent(shareText)}`}
            className="px-3 py-2 bg-sky-700 hover:bg-sky-600 text-white rounded-xl flex items-center justify-center gap-1.5 transition font-medium text-center"
          >
            <Mail className="w-3.5 h-3.5" />
            <span>Email</span>
          </a>
        </div>

        <button 
          onClick={() => setShowQr(!showQr)}
          className="w-full text-center text-xs text-indigo-400 hover:text-indigo-300 font-medium py-1"
        >
          {showQr ? 'Hide Wi-Fi QR Code' : 'Display Direct Connect Wi-Fi QR'}
        </button>

        <p className="text-[11px] text-slate-500 font-sans text-center">
          ⚠️ Passwords are cryptographically salted and not readable once closed.
        </p>

        <div className="flex justify-end pt-1">
          <button 
            onClick={onClose}
            className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-bold text-xs shadow-lg shadow-emerald-600/20 transition cursor-pointer"
          >
            Done
          </button>
        </div>

      </div>
    </div>
  );
}
