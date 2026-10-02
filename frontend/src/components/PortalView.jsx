import React, { useState, useEffect } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { 
  Wifi, Shield, Smartphone, Key, Download, CheckCircle2, 
  AlertCircle, RefreshCw, Apple, Globe, CreditCard, Phone, 
  HelpCircle, ExternalLink, ArrowRight, Copy, Check, Lock, Sparkles, QrCode, Printer,
  X, CheckCircle, Info, Monitor, Cpu, Laptop, ShieldCheck, BadgeCheck
} from 'lucide-react';
import { fetchJson, apiRequest } from '../utils/api';

export default function PortalView() {
  const [config, setConfig] = useState(null);
  const [plans, setPlans] = useState([]);
  const [activeTab, setActiveTab] = useState('qr'); // 'qr', 'plans', 'enroll', 'setup', 'help'
  const [enrollForm, setEnrollForm] = useState({ username: '', password: '', cert_password: '' });
  const [enrolling, setEnrolling] = useState(false);
  const [enrollResult, setEnrollResult] = useState(null);
  const [enrollError, setEnrollError] = useState('');
  const [copiedPass, setCopiedPass] = useState(false);
  const [copiedQrString, setCopiedQrString] = useState(false);
  const [copiedUpi, setCopiedUpi] = useState(false);
  const [selectedPlanForUpi, setSelectedPlanForUpi] = useState(null);
  const [payerUsername, setPayerUsername] = useState('');
  const [utrRef, setUtrRef] = useState('');
  const [verifyingPayment, setVerifyingPayment] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState(null);
  const [osTab, setOsTab] = useState('android'); // 'android', 'ios', 'windows', 'linux'

  useEffect(() => {
    fetchJson('public-config').then(setConfig).catch(() => {});
    fetchJson('plans').then(setPlans).catch(() => {});
  }, []);

  const ssid = config?.wifi_ssid || 'RajLabs-Enterprise';
  const wifiString = `WIFI:T:WPA;S:${ssid};;`;
  const upiVpa = config?.payment_config?.upi_vpa || 'wifi@rajlabs';
  const upiMerchant = config?.payment_config?.merchant_name || 'RajLabs Enterprise WiFi';

  const handleEnroll = async (e) => {
    e.preventDefault();
    setEnrollError('');
    setEnrollResult(null);
    setEnrolling(true);
    try {
      const res = await fetchJson('portal/enroll-certificate', {
        method: 'POST',
        body: JSON.stringify(enrollForm)
      });
      setEnrollResult(res);
    } catch (err) {
      setEnrollError(err.message || 'Enrollment failed. Please verify your credentials.');
    } finally {
      setEnrolling(false);
    }
  };

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text);
    setCopiedPass(true);
    setTimeout(() => setCopiedPass(false), 2000);
  };

  const handleCopyQr = () => {
    navigator.clipboard.writeText(wifiString);
    setCopiedQrString(true);
    setTimeout(() => setCopiedQrString(false), 2000);
  };

  const handleCopyUpi = (upiId) => {
    navigator.clipboard.writeText(upiId);
    setCopiedUpi(true);
    setTimeout(() => setCopiedUpi(false), 2000);
  };

  const handleVerifyUtr = (e) => {
    e.preventDefault();
    if (!utrRef.trim()) return;
    setVerifyingPayment(true);
    setPaymentStatus(null);
    setTimeout(() => {
      setVerifyingPayment(false);
      setPaymentStatus({
        status: 'submitted',
        message: `Recharge request with Ref #${utrRef.trim()} recorded for user '${payerUsername || 'Guest'}'. If your account isn't auto-activated in 2 minutes, WhatsApp your screenshot to support desk.`
      });
    }, 1200);
  };

  const getUpiUrl = (plan, user = '') => {
    const userNote = user ? ` for ${user}` : '';
    const note = encodeURIComponent(`${plan.name} WiFi Recharge${userNote}`);
    const merchant = encodeURIComponent(upiMerchant);
    return `upi://pay?pa=${encodeURIComponent(upiVpa)}&pn=${merchant}&am=${plan.price}&cu=INR&tn=${note}`;
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between relative overflow-hidden">
      {/* Glow Effects */}
      <div className="absolute -top-40 -left-40 w-96 h-96 bg-indigo-600/15 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute top-1/2 -right-40 w-96 h-96 bg-violet-600/15 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-tr from-indigo-600 to-violet-600 rounded-xl text-white shadow-md shadow-indigo-500/20">
              <Wifi className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-extrabold text-white text-base tracking-tight">RajLabs Wi-Fi Onboarding</h1>
              <p className="text-[11px] text-slate-400">Enterprise WPA2/WPA3-Enterprise & EAP-TLS Portal</p>
            </div>
          </div>

          <a
            href="/radius"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-medium border border-slate-700 transition"
          >
            <Shield className="w-3.5 h-3.5 text-indigo-400" />
            <span>Admin Console</span>
          </a>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-4xl mx-auto px-4 py-8 w-full z-10 flex-1 flex flex-col justify-center">
        {/* Navigation Tabs */}
        <div className="flex bg-slate-900/90 p-1.5 rounded-2xl border border-slate-800 max-w-2xl mx-auto mb-8 shadow-xl overflow-x-auto">
          <button
            onClick={() => setActiveTab('qr')}
            className={`flex-1 min-w-[100px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'qr' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <QrCode className="w-3.5 h-3.5" />
            <span>Wi-Fi QR</span>
          </button>
          <button
            onClick={() => setActiveTab('plans')}
            className={`flex-1 min-w-[110px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'plans' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <CreditCard className="w-3.5 h-3.5" />
            <span>Pay & Recharge</span>
          </button>
          <button
            onClick={() => setActiveTab('enroll')}
            className={`flex-1 min-w-[110px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'enroll' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Certificates</span>
          </button>
          <button
            onClick={() => setActiveTab('setup')}
            className={`flex-1 min-w-[110px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'setup' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Download className="w-3.5 h-3.5" />
            <span>Root CA</span>
          </button>
          <button
            onClick={() => setActiveTab('help')}
            className={`flex-1 min-w-[90px] py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition ${activeTab === 'help' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Phone className="w-3.5 h-3.5" />
            <span>Support</span>
          </button>
        </div>

        {/* Tab: Direct Wi-Fi QR Code */}
        {activeTab === 'qr' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-md mx-auto w-full text-center space-y-5 animate-fade-in">
            <div className="text-center">
              <div className="inline-flex p-3 bg-indigo-500/10 text-indigo-400 rounded-2xl mb-2 border border-indigo-500/20">
                <Wifi className="w-6 h-6" />
              </div>
              <h2 className="text-xl font-bold text-white">Scan to Connect Wi-Fi</h2>
              <p className="text-xs text-slate-400 mt-1">
                Point your phone or tablet camera at the QR code below to connect to the network automatically.
              </p>
            </div>

            <div className="inline-block p-4 bg-white rounded-3xl shadow-xl border-4 border-indigo-500/30">
              <QRCodeSVG
                value={wifiString}
                size={200}
                level="H"
                includeMargin={false}
              />
            </div>

            <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 text-left space-y-2 text-xs font-mono">
              <div className="flex justify-between items-center">
                <span className="text-slate-400 font-sans">SSID:</span>
                <span className="font-bold text-white">{ssid}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400 font-sans">Security:</span>
                <span className="text-indigo-300 font-semibold">{config?.wifi_auth_type || 'WPA2-Enterprise / EAP-TLS'}</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 pt-1">
              <button
                onClick={handleCopyQr}
                className="flex items-center justify-center gap-2 py-2.5 px-3 bg-slate-800 hover:bg-slate-750 text-slate-200 rounded-xl text-xs font-semibold border border-slate-700 transition cursor-pointer"
              >
                {copiedQrString ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                <span>{copiedQrString ? 'Copied' : 'Copy String'}</span>
              </button>
              <button
                onClick={() => window.print()}
                className="flex items-center justify-center gap-2 py-2.5 px-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition cursor-pointer"
              >
                <Printer className="w-4 h-4" />
                <span>Print QR Badge</span>
              </button>
            </div>
          </div>
        )}

        {/* Tab: Plans & Pricing + UPI QR Payment */}
        {activeTab === 'plans' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-3xl mx-auto w-full space-y-6 animate-fade-in">
            <div className="text-center max-w-md mx-auto">
              <div className="inline-flex p-3 bg-emerald-500/10 text-emerald-400 rounded-2xl mb-2 border border-emerald-500/20">
                <CreditCard className="w-6 h-6" />
              </div>
              <h2 className="text-xl font-bold text-white">Instant Wi-Fi Subscription & Recharge</h2>
              <p className="text-xs text-slate-400 mt-1">
                Select your desired plan to generate a live UPI QR code for GPay, PhonePe, Paytm, or BHIM.
              </p>
            </div>

            {plans.length === 0 ? (
              <div className="text-center py-10 border border-dashed border-slate-800 rounded-2xl text-slate-400 text-xs">
                No active plans currently published. Contact the network administrator for recharge details.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {plans.map((p) => {
                  const currSymbol = p.currency === 'INR' ? '₹' : p.currency === 'USD' ? '$' : p.currency + ' ';
                  const isPopular = p.validity_days === 30 || p.name.toLowerCase().includes('monthly');
                  return (
                    <div
                      key={p.id}
                      className={`bg-slate-950/80 border rounded-2xl p-5 flex flex-col justify-between transition group relative ${
                        isPopular ? 'border-emerald-500/60 shadow-lg shadow-emerald-500/10' : 'border-slate-800 hover:border-indigo-500/50'
                      }`}
                    >
                      {isPopular && (
                        <span className="absolute -top-2.5 right-4 bg-gradient-to-r from-emerald-600 to-teal-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full shadow">
                          BEST VALUE
                        </span>
                      )}
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold uppercase tracking-wider text-emerald-400 font-mono">
                            {p.validity_days} {p.validity_days === 1 ? 'Day' : 'Days'}
                          </span>
                          <span className="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">
                            {p.max_session_seconds ? `${Math.round(p.max_session_seconds / 3600)}h session` : 'Unlimited'}
                          </span>
                        </div>
                        <div>
                          <h3 className="font-bold text-white text-base">{p.name}</h3>
                          <div className="text-2xl font-extrabold text-white mt-1">
                            {currSymbol}{p.price}
                            <span className="text-xs font-normal text-slate-400 ml-1">/ {p.validity_days}d</span>
                          </div>
                        </div>
                        {p.description && (
                          <p className="text-xs text-slate-400 leading-relaxed border-t border-slate-900 pt-2">
                            {p.description}
                          </p>
                        )}
                      </div>

                      <div className="pt-4 mt-4 border-t border-slate-800/80">
                        <button
                          onClick={() => {
                            setSelectedPlanForUpi(p);
                            setPaymentStatus(null);
                            setUtrRef('');
                          }}
                          className="w-full py-2.5 px-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 shadow-md shadow-emerald-600/20 transition cursor-pointer"
                        >
                          <QrCode className="w-3.5 h-3.5" />
                          <span>Pay with UPI (₹{p.price})</span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* UPI Info Bar */}
            <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg">
                  <CreditCard className="w-4 h-4 shrink-0" />
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Direct VPA for all Indian UPI Apps (GPay, PhonePe, Paytm, BHIM):</span>
                  <span className="font-mono font-bold text-emerald-400 text-sm">{upiVpa}</span>
                </div>
              </div>
              <button
                onClick={() => handleCopyUpi(upiVpa)}
                className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold flex items-center gap-1.5 border border-slate-700 transition cursor-pointer shrink-0"
              >
                {copiedUpi ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedUpi ? 'Copied VPA' : 'Copy VPA'}</span>
              </button>
            </div>
          </div>
        )}

        {/* UPI Payment Modal */}
        {selectedPlanForUpi && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto animate-fade-in">
            <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-lg w-full p-6 shadow-2xl relative my-8">
              {/* Close Button */}
              <button
                onClick={() => setSelectedPlanForUpi(null)}
                className="absolute top-4 right-4 p-2 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white rounded-full transition cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>

              <div className="text-center space-y-1 pb-4 border-b border-slate-800">
                <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-400 font-mono">
                  UPI Instant Payment
                </span>
                <h3 className="text-lg font-bold text-white">{selectedPlanForUpi.name}</h3>
                <div className="text-2xl font-extrabold text-emerald-400">
                  ₹{selectedPlanForUpi.price} <span className="text-xs text-slate-400 font-normal">/ {selectedPlanForUpi.validity_days} Days Access</span>
                </div>
              </div>

              {/* Username Input for Note */}
              <div className="py-4 space-y-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                    <span>Your Wi-Fi Username / Mobile</span>
                    <span className="text-slate-500 font-normal lowercase">(for auto-activation)</span>
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. john or 9876543210"
                    value={payerUsername}
                    onChange={(e) => setPayerUsername(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
                  />
                </div>

                {/* QR Code */}
                <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 flex flex-col items-center justify-center space-y-3">
                  <div className="p-3 bg-white rounded-2xl shadow-lg border-2 border-emerald-500/40">
                    <QRCodeSVG
                      value={getUpiUrl(selectedPlanForUpi, payerUsername)}
                      size={180}
                      level="H"
                      includeMargin={false}
                    />
                  </div>
                  <div className="text-center space-y-0.5">
                    <p className="text-xs font-semibold text-slate-200">Scan using any UPI App</p>
                    <p className="text-[11px] text-slate-400">Google Pay • PhonePe • Paytm • BHIM • Cred</p>
                  </div>
                </div>

                {/* Direct App Button (Mobile only) */}
                <a
                  href={getUpiUrl(selectedPlanForUpi, payerUsername)}
                  className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/20 transition sm:hidden"
                >
                  <Smartphone className="w-4 h-4" />
                  <span>Open UPI App on Phone (₹{selectedPlanForUpi.price})</span>
                </a>

                {/* Payment Notes & Guide */}
                <div className="p-3 bg-slate-950/70 rounded-xl border border-slate-800 space-y-1.5 text-[11px] text-slate-400">
                  <div className="flex items-center gap-1.5 text-slate-300 font-semibold">
                    <Info className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                    <span>Payment Notes:</span>
                  </div>
                  <ul className="list-disc list-inside space-y-0.5 pl-1 text-[11px] text-slate-400">
                    <li>Payee: <strong className="text-slate-200">{upiMerchant}</strong> (<span className="text-emerald-400 font-mono">{upiVpa}</span>)</li>
                    <li>Remark / Note in UPI: <strong className="text-slate-200">{selectedPlanForUpi.name} {payerUsername ? `(${payerUsername})` : ''}</strong></li>
                    <li>Keep the 12-digit UTR / Transaction Reference Number handy after payment.</li>
                  </ul>
                </div>

                {/* UTR Verification / Claim Form */}
                <form onSubmit={handleVerifyUtr} className="space-y-2 pt-1 border-t border-slate-800/80">
                  <label className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider block">
                    Already Paid? Submit UTR / Reference No.
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="12-digit UPI UTR (e.g. 402918273645)"
                      value={utrRef}
                      onChange={(e) => setUtrRef(e.target.value)}
                      className="flex-1 px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                    />
                    <button
                      type="submit"
                      disabled={verifyingPayment || !utrRef.trim()}
                      className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition cursor-pointer flex items-center gap-1"
                    >
                      {verifyingPayment ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                      <span>Verify</span>
                    </button>
                  </div>
                </form>

                {paymentStatus && (
                  <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-300 text-xs flex items-start gap-2 animate-fade-in">
                    <CheckCircle className="w-4 h-4 shrink-0 mt-0.5 text-emerald-400" />
                    <span>{paymentStatus.message}</span>
                  </div>
                )}
              </div>

              <div className="pt-2 text-center border-t border-slate-800">
                <button
                  onClick={() => setSelectedPlanForUpi(null)}
                  className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
                >
                  Done / Close
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Tab 1: Certificate Enrollment */}
        {activeTab === 'enroll' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-xl mx-auto w-full">
            <div className="text-center mb-6">
              <div className="inline-flex p-3 bg-indigo-500/10 text-indigo-400 rounded-2xl mb-2 border border-indigo-500/20">
                <Shield className="w-6 h-6" />
              </div>
              <h2 className="text-xl font-bold text-white">Enroll Device for EAP-TLS Wi-Fi</h2>
              <p className="text-xs text-slate-400 mt-1">
                Enter your account credentials to generate your encrypted client certificate bundle (.p12) and Apple profile (.mobileconfig).
              </p>
            </div>

            {enrollError && (
              <div className="mb-5 p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
                <span>{enrollError}</span>
              </div>
            )}

            {enrollResult ? (
              <div className="space-y-5 animate-fade-in">
                <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-2xl flex items-start gap-3">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-bold text-emerald-300 text-sm">Certificate Issued Successfully!</h4>
                    <p className="text-xs text-emerald-400/90 mt-0.5">{enrollResult.message}</p>
                  </div>
                </div>

                {/* Password Box */}
                {enrollResult.p12_password && (
                  <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Certificate Bundle Password</span>
                    <div className="flex items-center justify-between">
                      <code className="font-mono text-amber-300 font-bold text-sm tracking-wider">
                        {enrollResult.p12_password}
                      </code>
                      <button
                        onClick={() => handleCopy(enrollResult.p12_password)}
                        className="flex items-center gap-1 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs transition cursor-pointer"
                      >
                        {copiedPass ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedPass ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* Download Actions */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <a
                    href={`/radius/api/portal/download-mobileconfig?username=${encodeURIComponent(enrollForm.username)}&password=${encodeURIComponent(enrollForm.password)}`}
                    className="flex items-center justify-center gap-2 p-3 bg-slate-800 hover:bg-slate-750 border border-slate-700 text-white rounded-xl text-xs font-semibold shadow transition cursor-pointer"
                  >
                    <Apple className="w-4 h-4 text-slate-200" />
                    <span>Download Apple Profile</span>
                  </a>

                  <a
                    href={`/radius/api/portal/download-cert?username=${encodeURIComponent(enrollForm.username)}&password=${encodeURIComponent(enrollForm.password)}`}
                    className="flex items-center justify-center gap-2 p-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition cursor-pointer"
                  >
                    <Download className="w-4 h-4" />
                    <span>Download .p12 Bundle</span>
                  </a>
                </div>

                <div className="text-center pt-2">
                  <button
                    onClick={() => setEnrollResult(null)}
                    className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
                  >
                    ← Enroll another device
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleEnroll} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Account Username</label>
                  <input
                    type="text"
                    required
                    placeholder="Enter assigned username"
                    value={enrollForm.username}
                    onChange={e => setEnrollForm({ ...enrollForm, username: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Account Password</label>
                  <input
                    type="password"
                    required
                    placeholder="Enter account password"
                    value={enrollForm.password}
                    onChange={e => setEnrollForm({ ...enrollForm, password: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>

                <button
                  type="submit"
                  disabled={enrolling}
                  className="w-full mt-3 py-3 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-500/25 flex items-center justify-center gap-2 transition disabled:opacity-50 cursor-pointer"
                >
                  {enrolling ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                  <span>{enrolling ? 'Generating EAP-TLS Certificate...' : 'Generate & Download Certificate'}</span>
                </button>
              </form>
            )}
          </div>
        )}

        {/* Tab 2: Root CA & Configuration Profiles */}
        {activeTab === 'setup' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-3xl mx-auto w-full space-y-6 animate-fade-in">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-violet-500/10 text-violet-400 rounded-2xl border border-violet-500/20">
                  <ShieldCheck className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-base">Root CA Certificate & OS Installation</h3>
                  <p className="text-xs text-slate-400">Install and trust the Authority certificate for seamless 802.1X EAP-TLS / PEAP roaming</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className={`px-2.5 py-1 rounded-full text-[11px] font-bold border flex items-center gap-1.5 ${
                  config?.signer_configured
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30'
                }`}>
                  <BadgeCheck className="w-3.5 h-3.5" />
                  <span>{config?.signer_configured ? 'RajLabs-CA PKI Active' : 'FreeRADIUS Local CA Active'}</span>
                </span>
              </div>
            </div>

            {/* Root CA Direct Download Card */}
            <div className="p-5 bg-slate-950 rounded-2xl border border-slate-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="space-y-1">
                <h4 className="font-bold text-slate-100 text-sm flex items-center gap-2">
                  <span>Download Root Authority Certificate (ca.pem)</span>
                </h4>
                <p className="text-xs text-slate-400">
                  Required by Android, Windows, macOS, and Linux to verify the RADIUS server identity without security warnings.
                </p>
              </div>
              <a
                href="/radius/api/certs/ca"
                download="RajLabs_Root_CA.pem"
                className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-violet-500/20 transition whitespace-nowrap cursor-pointer shrink-0"
              >
                <Download className="w-4 h-4" />
                <span>Download ca.pem</span>
              </a>
            </div>

            {/* OS Navigation Tabs */}
            <div className="space-y-3">
              <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs overflow-x-auto">
                <button
                  onClick={() => setOsTab('android')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'android' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Smartphone className="w-3.5 h-3.5" />
                  <span>Android</span>
                </button>
                <button
                  onClick={() => setOsTab('ios')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'ios' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Apple className="w-3.5 h-3.5" />
                  <span>iOS / macOS</span>
                </button>
                <button
                  onClick={() => setOsTab('windows')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'windows' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Monitor className="w-3.5 h-3.5" />
                  <span>Windows 10/11</span>
                </button>
                <button
                  onClick={() => setOsTab('linux')}
                  className={`flex-1 py-2 px-3 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition ${osTab === 'linux' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  <Cpu className="w-3.5 h-3.5" />
                  <span>Linux</span>
                </button>
              </div>

              {/* OS Instruction Contents */}
              <div className="p-4 bg-slate-950/70 rounded-2xl border border-slate-800 text-xs text-slate-300 space-y-3">
                {osTab === 'android' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-emerald-400 text-xs flex items-center gap-1.5">
                      <Smartphone className="w-4 h-4" /> Android 11+ Wi-Fi & Certificate Setup Guide:
                    </h5>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Click <strong>Download ca.pem</strong> above.</li>
                      <li>Go to <strong>Settings → Security & Privacy → More Security Settings → Install from device storage → Wi-Fi Certificate</strong>.</li>
                      <li>Select the downloaded <code className="text-indigo-300">ca.pem</code> file and name it <strong className="text-white">RajLabs CA</strong>.</li>
                      <li>Connect to SSID <strong>{ssid}</strong>:
                        <ul className="list-disc list-inside pl-4 text-slate-400 text-[11px] mt-1 space-y-0.5">
                          <li>EAP method: <strong>EAP-TLS</strong> (if certificate generated) or <strong>PEAP / MSCHAPv2</strong>.</li>
                          <li>CA certificate: Select <strong>RajLabs CA</strong>.</li>
                          <li>Online Certificate Status: <strong>Don't validate</strong> or <strong>Validate</strong>.</li>
                          <li>Domain: <code className="text-indigo-300">rajlabs.in</code> (or your server domain).</li>
                        </ul>
                      </li>
                    </ol>
                  </div>
                )}

                {osTab === 'ios' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-indigo-400 text-xs flex items-center gap-1.5">
                      <Apple className="w-4 h-4" /> Apple iOS, iPadOS & macOS One-Click Profile:
                    </h5>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Generate your certificate in the <strong>Certificates Tab</strong> and download the <strong>.mobileconfig</strong> profile.</li>
                      <li>Open <strong>Settings → Profile Downloaded</strong> (or System Settings → Profiles on macOS).</li>
                      <li>Tap <strong>Install</strong> and authenticate with your device passcode.</li>
                      <li>Your Apple device will automatically trust the Root CA and auto-connect to <strong>{ssid}</strong>!</li>
                    </ol>
                  </div>
                )}

                {osTab === 'windows' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-cyan-400 text-xs flex items-center gap-1.5">
                      <Monitor className="w-4 h-4" /> Windows 10 & 11 Setup Guide:
                    </h5>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Download <code className="text-indigo-300">ca.pem</code> (or rename to <code className="text-indigo-300">ca.crt</code>).</li>
                      <li>Double-click the file and click <strong>Install Certificate → Current User → Place all certificates in the following store</strong>.</li>
                      <li>Browse and select <strong>Trusted Root Certification Authorities</strong>, then click Finish.</li>
                      <li>Double-click your user <code className="text-indigo-300">.p12</code> bundle from Tab 1 to import your client key into the Personal certificate store.</li>
                      <li>Click the Wi-Fi icon, choose <strong>{ssid}</strong> and click Connect.</li>
                    </ol>
                  </div>
                )}

                {osTab === 'linux' && (
                  <div className="space-y-2">
                    <h5 className="font-bold text-amber-400 text-xs flex items-center gap-1.5">
                      <Cpu className="w-4 h-4" /> Linux / NetworkManager Setup:
                    </h5>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-300 pl-1">
                      <li>Download <code className="text-indigo-300">ca.pem</code> to <code className="text-indigo-300">~/.config/wifi/ca.pem</code>.</li>
                      <li>Open NetworkManager or edit <code className="text-indigo-300">/etc/NetworkManager/system-connections/{ssid}.nmconnection</code>:</li>
                      <li>Set <code className="text-indigo-300">key-mgmt=wpa-eap</code>, <code className="text-indigo-300">eap=tls</code>, <code className="text-indigo-300">ca-cert=path/to/ca.pem</code>, <code className="text-indigo-300">client-cert=path/to/user.crt</code>, <code className="text-indigo-300">private-key=path/to/user.key</code>.</li>
                    </ol>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Support & UPI */}
        {activeTab === 'help' && (
          <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl max-w-xl mx-auto w-full space-y-6 animate-fade-in">
            <div className="text-center">
              <div className="inline-flex p-3 bg-emerald-500/10 text-emerald-400 rounded-2xl mb-2 border border-emerald-500/20">
                <Phone className="w-6 h-6" />
              </div>
              <h3 className="font-bold text-white text-base">Network Support & Recharge</h3>
              <p className="text-xs text-slate-400 mt-1">Get immediate assistance or renew Wi-Fi subscription</p>
            </div>

            <div className="p-4 bg-slate-950 rounded-2xl border border-slate-800 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Support Desk:</span>
                <span className="font-semibold text-slate-200">{config?.admin_contact?.name || 'RajLabs Network Operations'}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">WhatsApp / Phone:</span>
                <a
                  href={`tel:${config?.admin_contact?.phone || '+91'}`}
                  className="font-mono text-cyan-400 hover:underline font-bold"
                >
                  {config?.admin_contact?.phone || 'Contact Admin'}
                </a>
              </div>
              <div className="flex items-center justify-between text-xs border-t border-slate-800 pt-3">
                <span className="text-slate-400">UPI Payment VPA:</span>
                <span className="font-mono text-emerald-400 font-bold">{upiVpa}</span>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 py-4 text-center text-xs text-slate-500 bg-slate-950/80">
        <p>© {new Date().getFullYear()} RajLabs FreeRADIUS Enterprise AAA • WPA2/WPA3 EAP-TLS</p>
      </footer>
    </div>
  );
}

