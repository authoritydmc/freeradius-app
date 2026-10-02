import React from 'react';
import { AlertTriangle, RefreshCw, LogOut, Copy, Check, ChevronDown, ChevronUp } from 'lucide-react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      copied: false,
      showDetails: false
    };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error(`[ErrorBoundary] Caught in ${this.props.section || 'App'}:`, error, errorInfo);
    this.setState({ errorInfo });
  }

  handleCopy = () => {
    const details = `[RajLabs Error Report]
Time: ${new Date().toISOString()}
Section: ${this.props.section || 'Global Application'}
Error: ${this.state.error?.name}: ${this.state.error?.message}
Stack:
${this.state.error?.stack || 'No stack trace available'}
Component Stack:
${this.state.errorInfo?.componentStack || 'No component stack'}
User Agent: ${navigator.userAgent}
URL: ${window.location.href}`;

    navigator.clipboard?.writeText(details);
    this.setState({ copied: true });
    setTimeout(() => this.setState({ copied: false }), 2500);
  };

  handleReset = () => {
    try {
      localStorage.removeItem('admin_token');
      localStorage.removeItem('user_token');
      localStorage.removeItem('auth_user_info');
    } catch {}
    window.location.href = '/radius';
  };

  handleReload = () => {
    window.location.reload();
  };

  handleRetry = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      const isScoped = Boolean(this.props.scoped);

      if (isScoped) {
        return (
          <div className="bg-slate-900/90 border border-rose-500/30 rounded-3xl p-6 my-4 shadow-xl text-left space-y-4 animate-in fade-in">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-rose-500/10 text-rose-400 rounded-2xl border border-rose-500/20">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-sm">
                    {this.props.title || 'Component Error'}
                  </h3>
                  <p className="text-xs text-rose-300/80">
                    {this.state.error?.message || 'An unexpected rendering error occurred in this view.'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={this.handleRetry}
                  className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition shadow-sm"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Retry View</span>
                </button>
              </div>
            </div>

            {/* Error Details Toggle */}
            <div className="pt-2 border-t border-slate-800/80">
              <button
                type="button"
                onClick={() => this.setState({ showDetails: !this.state.showDetails })}
                className="text-[11px] text-slate-400 hover:text-slate-200 flex items-center gap-1 font-mono"
              >
                <span>{this.state.showDetails ? 'Hide' : 'Show'} Technical Details</span>
                {this.state.showDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </button>

              {this.state.showDetails && (
                <div className="mt-2 p-3 bg-slate-950 rounded-xl border border-slate-800 text-[11px] font-mono text-slate-300 space-y-2 overflow-x-auto">
                  <div className="text-rose-400 font-bold">{String(this.state.error)}</div>
                  <pre className="text-slate-500 whitespace-pre-wrap text-[10px]">
                    {this.state.error?.stack || this.state.errorInfo?.componentStack}
                  </pre>
                  <button
                    type="button"
                    onClick={this.handleCopy}
                    className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-[10px] flex items-center gap-1 border border-slate-700 mt-1"
                  >
                    {this.state.copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{this.state.copied ? 'Copied Details' : 'Copy Error Diagnostic'}</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      }

      // Full Application Error Screen
      return (
        <div className="min-h-screen bg-slate-950 text-white flex flex-col justify-center items-center p-6 relative overflow-hidden">
          <div className="w-full max-w-lg bg-slate-900/90 backdrop-blur-2xl border border-rose-500/30 rounded-3xl p-8 shadow-2xl space-y-6 text-center z-10">
            <div className="w-16 h-16 rounded-3xl bg-rose-500/10 text-rose-400 flex items-center justify-center mx-auto border border-rose-500/30 shadow-lg shadow-rose-500/10">
              <AlertTriangle className="w-8 h-8" />
            </div>

            <div>
              <h1 className="text-xl font-black text-white tracking-tight">RajLabs UI Exception Caught</h1>
              <p className="text-xs text-rose-300/90 mt-1.5 font-medium">
                {this.state.error?.message || 'A runtime rendering exception was intercepted by the application guard.'}
              </p>
            </div>

            {/* Technical Diagnostics */}
            <div className="bg-slate-950 p-3.5 rounded-2xl border border-slate-800/90 text-left font-mono text-[11px] text-slate-300 space-y-1">
              <div className="text-slate-500 text-[10px] flex justify-between border-b border-slate-800 pb-1">
                <span>Diagnostic Context:</span>
                <span>{new Date().toLocaleTimeString()}</span>
              </div>
              <div className="text-rose-400 truncate font-bold pt-1">
                {this.state.error?.name || 'Error'}: {this.state.error?.message}
              </div>
              <div className="text-slate-500 text-[10px] truncate">
                Origin: {window.location.pathname || '/radius'}
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
              <button
                type="button"
                onClick={this.handleReload}
                className="w-full sm:w-auto px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-500/20 flex items-center justify-center gap-2 transition cursor-pointer"
              >
                <RefreshCw className="w-4 h-4" />
                <span>Reload Dashboard</span>
              </button>

              <button
                type="button"
                onClick={this.handleReset}
                className="w-full sm:w-auto px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 border border-slate-700 transition cursor-pointer"
              >
                <LogOut className="w-4 h-4" />
                <span>Reset Session & Login</span>
              </button>

              <button
                type="button"
                onClick={this.handleCopy}
                className="w-full sm:w-auto p-2.5 bg-slate-800/60 hover:bg-slate-700 text-slate-400 hover:text-white rounded-xl text-xs transition border border-slate-800"
                title="Copy Error Diagnostic Details"
              >
                {this.state.copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
