import React, { useState } from 'react';
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
  MessageSquare, 
  Mail 
} from 'lucide-react';

export default function CredResultModal({ cred, onClose, onCopy }) {
  if (!cred || !cred.show) return null;

  const [showPass, setShowPass] = useState(true);
  const [showQr, setShowQr] = useState(false);

  const portalUrl = typeof window !== 'undefined' ? `${window.location.origin}/radius/portal` : '/radius/portal';
  const validityText = cred.validity ? `\nValidity: ${cred.validity}` : '';
  const shareText = `RajLabs Enterprise Wi-Fi Credentials\nSSID: RajLabs-Enterprise\nUsername: ${cred.username}\nPassword: ${cred.password}${validityText}\nPortal: ${portalUrl}\n(Please keep this private)`;

  const qrImageUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(shareText)}`;

  const handleDownloadTxt = () => {
    const blob = new Blob([shareText + `\nIssued on ${new Date().toISOString()}\n`], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `RajLabs_${cred.username}_credentials.txt`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-emerald-500/30 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl relative overflow-hidden">
        
        {/* Glow Header */}
        <div className="flex items-center justify-between pb-2 border-b border-slate-800">
          <div className="flex items-center gap-2.5 text-emerald-300 font-bold text-base">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            <span>{cred.title || 'Credentials Issued'}</span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1 rounded-lg">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Credentials Info Box */}
        <div className="bg-slate-950 border border-slate-800/90 rounded-2xl p-4 space-y-3 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">Username</span>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-800">
                {cred.username}
              </span>
              <button 
                onClick={() => onCopy(cred.username, 'Username copied to clipboard')}
                className="text-slate-400 hover:text-white p-1"
                title="Copy Username"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-slate-400">Password</span>
            <div className="flex items-center gap-2">
              <span className="text-amber-300 font-bold bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-800">
                {showPass ? cred.password : '••••••••••••'}
              </span>
              <button 
                onClick={() => setShowPass(!showPass)}
                className="text-slate-400 hover:text-white p-1"
                title={showPass ? 'Hide password' : 'Show password'}
              >
                {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
              <button 
                onClick={() => onCopy(cred.password, 'Password copied to clipboard')}
                className="text-slate-400 hover:text-white p-1"
                title="Copy Password"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>

          {cred.validity && (
            <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-indigo-300 font-sans">
              <span className="text-slate-400 flex items-center gap-1">
                <Hourglass className="w-3.5 h-3.5 text-amber-400" /> Validity
              </span>
              <span className="font-semibold text-amber-300">{cred.validity}</span>
            </div>
          )}
        </div>

        {/* Dynamic QR Code Card */}
        {showQr && (
          <div className="flex flex-col items-center justify-center p-3 bg-white rounded-2xl">
            <img src={qrImageUrl} alt="Credential QR" className="w-40 h-40" />
            <span className="text-[10px] text-slate-800 font-sans mt-1">Scan to connect to Wi-Fi</span>
          </div>
        )}

        {/* Quick Action Share Buttons */}
        <div className="grid grid-cols-2 gap-2 text-xs font-sans">
          <button 
            onClick={() => onCopy(shareText, 'Credential share text copied')}
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl flex items-center justify-center gap-1.5 transition-colors"
          >
            <Copy className="w-3.5 h-3.5" />
            <span>Copy Details</span>
          </button>
          
          <button 
            onClick={handleDownloadTxt}
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl flex items-center justify-center gap-1.5 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Save .txt</span>
          </button>

          <a 
            href={`https://wa.me/?text=${encodeURIComponent(shareText)}`}
            target="_blank" 
            rel="noopener noreferrer"
            className="px-3 py-2 bg-emerald-700 hover:bg-emerald-600 text-white rounded-xl flex items-center justify-center gap-1.5 transition-colors font-medium text-center"
          >
            <i className="fa-brands fa-whatsapp text-sm" />
            <span>WhatsApp</span>
          </a>

          <a 
            href={`mailto:?subject=${encodeURIComponent(`RajLabs Wi-Fi Access for ${cred.username}`)}&body=${encodeURIComponent(shareText)}`}
            className="px-3 py-2 bg-sky-700 hover:bg-sky-600 text-white rounded-xl flex items-center justify-center gap-1.5 transition-colors font-medium text-center"
          >
            <Mail className="w-3.5 h-3.5" />
            <span>Email</span>
          </a>
        </div>

        <button 
          onClick={() => setShowQr(!showQr)}
          className="w-full text-center text-xs text-indigo-400 hover:text-indigo-300 font-medium py-1"
        >
          {showQr ? 'Hide QR Code' : 'Display Wi-Fi QR Code'}
        </button>

        <p className="text-[11px] text-slate-500 font-sans text-center">
          ⚠️ Make sure to save or send credentials now. For security, passwords are encrypted and not retrievable later.
        </p>

        <div className="flex justify-end pt-1">
          <button 
            onClick={onClose}
            className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-bold text-xs shadow-lg shadow-emerald-600/20 transition-all"
          >
            Done
          </button>
        </div>

      </div>
    </div>
  );
}
