import React, { useState, useRef, useEffect } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { portalUrlFor } from '../utils/api';
import { CopyButton } from './ActionButton';
import { 
  Wifi, 
  Download, 
  Copy, 
  Check, 
  X, 
  Shield, 
  Smartphone, 
  Printer, 
  ExternalLink,
  Share2,
  Mail,
  Send,
  Sparkles,
  Lock,
  Globe,
  CheckCircle2
} from 'lucide-react';

export default function WifiQrModal({ 
  isOpen, 
  onClose, 
  user = null,
  ssid = 'RajLabs-Enterprise', 
  password = '', 
  username = '', 
  authType = 'WPA', 
  onNotify 
}) {
  const effectiveUsername = user?.username || username || '';
  const effectiveGroup = user?.group || 'staff';
  const effectiveHasCert = Boolean(user?.has_certificate);
  const effectiveExpiry = user?.expiration || '';
  // Password may arrive via prop or via the user object (e.g. right after a
  // password reset, when the fresh secret is still known). Sync on open/user.
  const incomingPass = password || user?.password || '';

  const [activeTab, setActiveTab] = useState('portal'); // 'portal' | 'wifi' | 'cert'
  const [customSsid, setCustomSsid] = useState(ssid);
  const [customPass, setCustomPass] = useState(incomingPass);
  const [copied, setCopied] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const qrRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      setCustomSsid(ssid);
      setCustomPass(incomingPass);
    }
  }, [isOpen, effectiveUsername]);

  if (!isOpen) return null;

  const portalUrl = `${portalUrlFor()}?user=${encodeURIComponent(effectiveUsername)}`;
  const certProfileUrl = `${origin}/radius/api/certs/${encodeURIComponent(effectiveUsername)}/mobileconfig`;
  
  // Standard Wi-Fi barcode format: WIFI:T:WPA;S:MySSID;P:MyPassword;;
  const wifiConnectString = customPass 
    ? `WIFI:T:WPA;S:${customSsid};P:${customPass};;`
    : `WIFI:T:nopass;S:${customSsid};;`;

  // Determine current QR payload based on tab
  let currentQrValue = portalUrl;
  let qrLabel = 'Self-Service Portal';
  let qrSubtext = 'Scan to open self-service Wi-Fi onboarding';

  if (activeTab === 'wifi') {
    currentQrValue = wifiConnectString;
    qrLabel = `Wi-Fi SSID: ${customSsid}`;
    qrSubtext = 'Scan with camera to connect to network';
  } else if (activeTab === 'cert') {
    currentQrValue = certProfileUrl;
    qrLabel = 'Apple EAP-TLS Profile';
    qrSubtext = 'Scan on iOS/Mac to install 802.1X certificate profile';
  }

  // Share text template
  const shareMessage = `📡 RajLabs Wi-Fi Access Pass
👤 User: ${effectiveUsername}
👥 Group: ${effectiveGroup}
📶 SSID: ${customSsid}
${customPass ? `🔑 Password: ${customPass}\n` : ''}${effectiveExpiry ? `⏳ Expiry: ${effectiveExpiry}\n` : ''}🔗 Portal Link: ${portalUrl}
(Scan QR or click link above to connect your device)`;

  const handleCopy = (text, label = 'Copied to clipboard') => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    onNotify?.(label, 'success');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleNativeShare = async () => {
    if (navigator.share) {
      try {
        await navigator.share({
          title: `Wi-Fi Pass for ${effectiveUsername}`,
          text: shareMessage,
          url: portalUrl,
        });
        onNotify?.('Pass shared successfully!', 'success');
      } catch (err) {
        if (err.name !== 'AbortError') {
          handleCopy(shareMessage, 'Share text copied to clipboard');
        }
      }
    } else {
      handleCopy(shareMessage, 'Share text copied to clipboard');
    }
  };

  const handlePrint = () => {
    window.print();
  };

  const handleDownloadQrSvg = () => {
    const svgEl = qrRef.current?.querySelector('svg');
    if (!svgEl) return;
    const svgData = new XMLSerializer().serializeToString(svgEl);
    const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `RajLabs_WiFi_${effectiveUsername || 'Pass'}.svg`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/85 backdrop-blur-md animate-in fade-in duration-200 print:p-0 print:bg-white">
      <div className="bg-slate-900 border border-indigo-500/30 rounded-3xl w-full max-w-md max-h-[92vh] sm:max-h-[88vh] flex flex-col overflow-hidden shadow-2xl print:border-none print:shadow-none print:bg-white print:text-black">
        
        {/* Header - Fixed & Compact */}
        <div className="shrink-0 flex items-center justify-between px-5 py-3 border-b border-slate-800 bg-slate-950/80 print:hidden">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
              <Wifi className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-white text-sm flex items-center gap-1.5">
                <span>Wi-Fi Join Pass</span>
                {effectiveUsername && (
                  <span className="text-[11px] px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-300 font-mono border border-indigo-500/20">
                    {effectiveUsername}
                  </span>
                )}
              </h3>
              <p className="text-[10px] text-slate-400">Scan QR to connect or share credentials</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable Content Body */}
        <div className="p-4 sm:p-5 overflow-y-auto space-y-3.5 flex-1">
          
          {/* Mode Selector Tabs */}
          <div className="flex rounded-xl bg-slate-950 p-1 border border-slate-800 text-xs font-semibold print:hidden">
            <button
              onClick={() => setActiveTab('portal')}
              className={`flex-1 py-1.5 rounded-lg flex items-center justify-center gap-1 transition ${
                activeTab === 'portal'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Portal</span>
            </button>
            <button
              onClick={() => setActiveTab('wifi')}
              className={`flex-1 py-1.5 rounded-lg flex items-center justify-center gap-1 transition ${
                activeTab === 'wifi'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Wifi className="w-3.5 h-3.5" />
              <span>Wi-Fi SSID</span>
            </button>
            <button
              onClick={() => setActiveTab('cert')}
              className={`flex-1 py-1.5 rounded-lg flex items-center justify-center gap-1 transition ${
                activeTab === 'cert'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Shield className="w-3.5 h-3.5" />
              <span>Apple Profile</span>
            </button>
          </div>

          {/* QR Display Card (Mobile-Optimized Height) */}
          <div ref={qrRef} className="bg-slate-950/90 border border-slate-800/90 rounded-2xl p-3.5 text-center space-y-2.5 print:border-slate-300 print:bg-white print:p-4">
            
            {/* Top Badge for Print Only */}
            <div className="hidden print:block text-center border-b pb-2 mb-2">
              <h2 className="text-lg font-black text-indigo-900">RajLabs Wi-Fi Access Voucher</h2>
              <p className="text-[10px] text-gray-600">Scan QR code below with any smartphone camera</p>
            </div>

            {/* Compact QR Container */}
            <div className="inline-block p-2.5 bg-white rounded-xl shadow-lg shadow-indigo-500/10 border-2 border-indigo-500/20">
              <QRCodeSVG
                value={currentQrValue}
                size={140}
                level="H"
                includeMargin={false}
              />
            </div>

            {/* Label */}
            <div>
              <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 font-mono">
                <Wifi className="w-3 h-3 text-indigo-400" />
                <span>{qrLabel}</span>
              </div>
              <p className="text-[10px] text-slate-400 mt-1 max-w-xs mx-auto">
                {qrSubtext}
              </p>
            </div>

            {/* User Details Box */}
            <div className="bg-slate-900 print:bg-gray-100 p-2.5 rounded-xl border border-slate-800/80 print:border-gray-300 text-left text-[11px] font-mono space-y-1">
              <div className="flex justify-between items-center text-slate-300 print:text-black">
                <span className="text-slate-400 print:text-gray-600 font-sans">User:</span>
                <span className="font-bold text-white print:text-black">{effectiveUsername}</span>
              </div>
              <div className="flex justify-between items-center text-slate-300 print:text-black">
                <span className="text-slate-400 print:text-gray-600 font-sans">Policy:</span>
                <span className="text-indigo-400 font-bold">{effectiveGroup}</span>
              </div>
              {effectiveExpiry && (
                <div className="flex justify-between items-center text-slate-300 print:text-black">
                  <span className="text-slate-400 print:text-gray-600 font-sans">Expiry:</span>
                  <span className="text-amber-400 font-bold">{effectiveExpiry}</span>
                </div>
              )}
              {activeTab === 'wifi' && (
                <div className="flex justify-between items-center text-slate-300 print:text-black pt-1 border-t border-slate-800/80">
                  <span className="text-slate-400 font-sans">SSID:</span>
                  <span className="text-cyan-400 font-bold">{customSsid}</span>
                </div>
              )}
            </div>

          </div>

          {/* Wi-Fi SSID / Passphrase override (only in Direct SSID tab) */}
          {activeTab === 'wifi' && (
            <div className="text-xs bg-slate-950 p-2.5 rounded-xl border border-slate-800 print:hidden space-y-2">
              <p className="text-[11px] text-slate-400">
                {customPass
                  ? 'QR embeds this password — scanning joins directly.'
                  : 'No password set: enter it below so the QR joins directly (stored passwords are hashed and cannot be read back).'}
              </p>
              <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-slate-400 mb-0.5 text-[10px]">SSID</label>
                <input
                  type="text"
                  value={customSsid}
                  onChange={(e) => setCustomSsid(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-750 rounded-lg px-2 py-1 text-white font-mono text-xs focus:border-indigo-500 outline-none"
                  placeholder="SSID"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-0.5 text-[10px]">Password (embeds in QR)</label>
                <input
                  type="text"
                  value={customPass}
                  onChange={(e) => setCustomPass(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-750 rounded-lg px-2 py-1 text-white font-mono text-xs focus:border-indigo-500 outline-none"
                  placeholder="User Wi-Fi password"
                />
              </div>
              </div>
            </div>
          )}

          {/* Share Actions - Grid Layout */}
          <div className="space-y-2 print:hidden">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
              Send Pass to User:
            </span>

            {/* Row 1: Instant Messaging */}
            <div className="grid grid-cols-3 gap-1.5 text-xs">
              <a
                href={`https://wa.me/?text=${encodeURIComponent(shareMessage)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-1 py-2 px-2 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 rounded-xl border border-emerald-500/30 transition text-[11px] font-semibold"
              >
                <Send className="w-3 h-3 text-emerald-400 shrink-0" />
                <span>WhatsApp</span>
              </a>

              <a
                href={`mailto:?subject=${encodeURIComponent(`RajLabs Wi-Fi Pass for ${effectiveUsername}`)}&body=${encodeURIComponent(shareMessage)}`}
                className="flex items-center justify-center gap-1 py-2 px-2 bg-sky-600/20 hover:bg-sky-600/30 text-sky-300 rounded-xl border border-sky-500/30 transition text-[11px] font-semibold"
              >
                <Mail className="w-3 h-3 text-sky-400 shrink-0" />
                <span>Email</span>
              </a>

              <button
                onClick={handleNativeShare}
                className="flex items-center justify-center gap-1 py-2 px-2 bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 rounded-xl border border-violet-500/30 transition text-[11px] font-semibold"
              >
                <Share2 className="w-3 h-3 text-violet-400 shrink-0" />
                <span>Share App</span>
              </button>
            </div>

            {/* Row 2: Utilities */}
            <div className="grid grid-cols-3 gap-1.5 text-xs pt-0.5">
              <CopyButton
                text={portalUrl}
                title="Copy portal link"
                className="flex items-center justify-center gap-1 py-1.5 px-2 bg-slate-800 hover:bg-slate-750 text-slate-200 rounded-xl border border-slate-700 transition text-[11px]"
                iconClassName="w-3 h-3 shrink-0"
                onCopied={() => {
                  setCopiedLink(true);
                  onNotify?.('Portal link copied to clipboard', 'success');
                  setTimeout(() => setCopiedLink(false), 2000);
                }}
              >
                <span>{copiedLink ? 'Copied' : 'Link'}</span>
              </CopyButton>

              <button
                onClick={handleDownloadQrSvg}
                className="flex items-center justify-center gap-1 py-1.5 px-2 bg-slate-800 hover:bg-slate-750 text-slate-200 rounded-xl border border-slate-700 transition text-[11px]"
              >
                <Download className="w-3 h-3 shrink-0" />
                <span>SVG</span>
              </button>

              <button
                onClick={handlePrint}
                className="flex items-center justify-center gap-1 py-1.5 px-2 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl font-bold shadow-sm transition text-[11px]"
              >
                <Printer className="w-3 h-3 shrink-0" />
                <span>Print</span>
              </button>
            </div>
          </div>

        </div>

        {/* Footer - Fixed & Compact */}
        <div className="shrink-0 px-5 py-2.5 bg-slate-950 border-t border-slate-800 flex justify-end print:hidden">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold rounded-xl transition"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  );
}
