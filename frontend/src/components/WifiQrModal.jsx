import React, { useState, useRef } from 'react';
import { QRCodeSVG } from 'qrcode.react';
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

  const [activeTab, setActiveTab] = useState('portal'); // 'portal' | 'wifi' | 'cert'
  const [customSsid, setCustomSsid] = useState(ssid);
  const [customPass, setCustomPass] = useState(password);
  const [copied, setCopied] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const qrRef = useRef(null);

  if (!isOpen) return null;

  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  const portalUrl = `${origin}/radius/portal?user=${encodeURIComponent(effectiveUsername)}`;
  const certProfileUrl = `${origin}/radius/api/certs/${encodeURIComponent(effectiveUsername)}/mobileconfig`;
  
  // Standard Wi-Fi barcode format: WIFI:T:WPA;S:MySSID;P:MyPassword;;
  const wifiConnectString = customPass 
    ? `WIFI:T:WPA;S:${customSsid};P:${customPass};;`
    : `WIFI:T:nopass;S:${customSsid};;`;

  // Determine current QR payload based on tab
  let currentQrValue = portalUrl;
  let qrLabel = 'Self-Service Wi-Fi Portal';
  let qrSubtext = 'Scan with camera to open personal Wi-Fi portal';

  if (activeTab === 'wifi') {
    currentQrValue = wifiConnectString;
    qrLabel = `Wi-Fi Direct Join: ${customSsid}`;
    qrSubtext = 'Scan with phone camera to prompt instant Wi-Fi network connection';
  } else if (activeTab === 'cert') {
    currentQrValue = certProfileUrl;
    qrLabel = 'EAP-TLS Apple Wi-Fi Profile';
    qrSubtext = 'Scan on iPhone/iPad/Mac to install enterprise 802.1X certificate profile';
  }

  // Share text template
  const shareMessage = `📡 RajLabs Enterprise Wi-Fi Pass
━━━━━━━━━━━━━━━━━━━━
👤 User: ${effectiveUsername}
👥 Group: ${effectiveGroup}
📶 SSID: ${customSsid}
${customPass ? `🔑 Password: ${customPass}\n` : ''}${effectiveExpiry ? `⏳ Expiry: ${effectiveExpiry}\n` : ''}
🔗 Self-Service Wi-Fi Link:
${portalUrl}

(Scan QR code or click link above to connect your device)`;

  const handleCopy = (text, label = 'Copied to clipboard') => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    onNotify?.(label, 'success');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCopyLink = () => {
    navigator.clipboard.writeText(portalUrl);
    setCopiedLink(true);
    onNotify?.('Portal join link copied to clipboard', 'success');
    setTimeout(() => setCopiedLink(false), 2000);
  };

  const handleNativeShare = async () => {
    if (navigator.share) {
      try {
        await navigator.share({
          title: `Wi-Fi Access Pass for ${effectiveUsername}`,
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
    a.download = `RajLabs_WiFi_QR_${effectiveUsername || 'Pass'}.svg`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md animate-in fade-in duration-200 print:p-0 print:bg-white">
      <div className="bg-slate-900 border border-indigo-500/30 rounded-3xl w-full max-w-lg overflow-hidden shadow-2xl print:border-none print:shadow-none print:bg-white print:text-black">
        
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/70 print:hidden">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-gradient-to-br from-indigo-500/20 to-violet-500/20 text-indigo-400 rounded-2xl border border-indigo-500/30">
              <Wifi className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base flex items-center gap-2">
                <span>Wi-Fi Join & QR Pass</span>
                {effectiveUsername && (
                  <span className="text-xs px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 font-mono border border-indigo-500/20">
                    {effectiveUsername}
                  </span>
                )}
              </h3>
              <p className="text-xs text-slate-400">Scan to connect immediately or send pass to user</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1.5 rounded-xl hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5">
          
          {/* Mode Selector Tabs */}
          <div className="flex rounded-2xl bg-slate-950 p-1 border border-slate-800 text-xs font-semibold print:hidden">
            <button
              onClick={() => setActiveTab('portal')}
              className={`flex-1 py-2 rounded-xl flex items-center justify-center gap-1.5 transition ${
                activeTab === 'portal'
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Portal Link</span>
            </button>
            <button
              onClick={() => setActiveTab('wifi')}
              className={`flex-1 py-2 rounded-xl flex items-center justify-center gap-1.5 transition ${
                activeTab === 'wifi'
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Wifi className="w-3.5 h-3.5" />
              <span>Direct SSID</span>
            </button>
            <button
              onClick={() => setActiveTab('cert')}
              className={`flex-1 py-2 rounded-xl flex items-center justify-center gap-1.5 transition ${
                activeTab === 'cert'
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Shield className="w-3.5 h-3.5" />
              <span>iOS / Cert Profile</span>
            </button>
          </div>

          {/* Printable Container / QR Card */}
          <div ref={qrRef} className="bg-slate-950/80 border border-slate-800/80 rounded-2xl p-5 text-center space-y-4 print:border-slate-300 print:bg-white print:p-6">
            
            {/* Top Badge for Print */}
            <div className="hidden print:block text-center border-b pb-3 mb-2">
              <h2 className="text-xl font-black text-indigo-900 tracking-tight">RajLabs Wi-Fi Access Voucher</h2>
              <p className="text-xs text-gray-600">Scan QR code below with any smartphone camera</p>
            </div>

            {/* QR Box */}
            <div className="inline-block p-4 bg-white rounded-2xl shadow-xl shadow-indigo-500/10 border-4 border-indigo-500/20">
              <QRCodeSVG
                value={currentQrValue}
                size={190}
                level="H"
                includeMargin={false}
              />
            </div>

            {/* Label & Instructions */}
            <div>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 font-mono">
                <Wifi className="w-3.5 h-3.5 text-indigo-400" />
                <span>{qrLabel}</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1.5 max-w-xs mx-auto">
                {qrSubtext}
              </p>
            </div>

            {/* User & Network Summary */}
            <div className="bg-slate-900/90 print:bg-gray-100 p-3.5 rounded-xl border border-slate-800 print:border-gray-300 text-left text-xs font-mono space-y-1.5">
              <div className="flex justify-between items-center text-slate-300 print:text-black">
                <span className="text-slate-400 print:text-gray-600 font-sans">Username:</span>
                <span className="font-bold text-white print:text-black">{effectiveUsername}</span>
              </div>
              <div className="flex justify-between items-center text-slate-300 print:text-black">
                <span className="text-slate-400 print:text-gray-600 font-sans">Group Policy:</span>
                <span className="text-indigo-400 font-bold">{effectiveGroup}</span>
              </div>
              {effectiveExpiry && (
                <div className="flex justify-between items-center text-slate-300 print:text-black">
                  <span className="text-slate-400 print:text-gray-600 font-sans">Expiration:</span>
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

          {/* Wi-Fi SSID / Password Config Override (when in Direct SSID tab) */}
          {activeTab === 'wifi' && (
            <div className="grid grid-cols-2 gap-2 text-xs bg-slate-950 p-3 rounded-xl border border-slate-800 print:hidden">
              <div>
                <label className="block text-slate-400 mb-1 text-[11px]">SSID</label>
                <input
                  type="text"
                  value={customSsid}
                  onChange={(e) => setCustomSsid(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-750 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs focus:border-indigo-500 outline-none"
                  placeholder="Network SSID"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1 text-[11px]">Password / PSK</label>
                <input
                  type="text"
                  value={customPass}
                  onChange={(e) => setCustomPass(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-750 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs focus:border-indigo-500 outline-none"
                  placeholder="Optional PSK / Leave blank"
                />
              </div>
            </div>
          )}

          {/* Send / Share Options ("Send QR / Scan to Join") */}
          <div className="space-y-2.5 print:hidden">
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider text-[10px]">
              Send / Share Access Pass:
            </span>

            <div className="grid grid-cols-3 gap-2 text-xs">
              {/* WhatsApp Share */}
              <a
                href={`https://wa.me/?text=${encodeURIComponent(shareMessage)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-1.5 py-2.5 px-3 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 rounded-xl border border-emerald-500/30 transition font-semibold"
              >
                <Send className="w-3.5 h-3.5 text-emerald-400" />
                <span>WhatsApp</span>
              </a>

              {/* Email Share */}
              <a
                href={`mailto:?subject=${encodeURIComponent(`RajLabs Wi-Fi Access for ${effectiveUsername}`)}&body=${encodeURIComponent(shareMessage)}`}
                className="flex items-center justify-center gap-1.5 py-2.5 px-3 bg-sky-600/20 hover:bg-sky-600/30 text-sky-300 rounded-xl border border-sky-500/30 transition font-semibold"
              >
                <Mail className="w-3.5 h-3.5 text-sky-400" />
                <span>Email</span>
              </a>

              {/* Native Device Share Sheet */}
              <button
                onClick={handleNativeShare}
                className="flex items-center justify-center gap-1.5 py-2.5 px-3 bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 rounded-xl border border-violet-500/30 transition font-semibold"
              >
                <Share2 className="w-3.5 h-3.5 text-violet-400" />
                <span>Share App</span>
              </button>
            </div>

            {/* Utility Actions (Copy link, download SVG, print badge) */}
            <div className="grid grid-cols-3 gap-2 text-xs pt-1">
              <button
                onClick={handleCopyLink}
                className="flex items-center justify-center gap-1.5 py-2 px-2.5 bg-slate-800 hover:bg-slate-750 text-slate-200 rounded-xl border border-slate-700 transition"
              >
                {copiedLink ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedLink ? 'Copied' : 'Copy Link'}</span>
              </button>

              <button
                onClick={handleDownloadQrSvg}
                className="flex items-center justify-center gap-1.5 py-2 px-2.5 bg-slate-800 hover:bg-slate-750 text-slate-200 rounded-xl border border-slate-700 transition"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Save SVG</span>
              </button>

              <button
                onClick={handlePrint}
                className="flex items-center justify-center gap-1.5 py-2 px-2.5 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl font-bold shadow-md shadow-indigo-600/20 transition"
              >
                <Printer className="w-3.5 h-3.5" />
                <span>Print Pass</span>
              </button>
            </div>
          </div>

        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3.5 bg-slate-950 border-t border-slate-800 flex justify-end print:hidden">
          <button
            onClick={onClose}
            className="px-5 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold rounded-xl transition"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  );
}
