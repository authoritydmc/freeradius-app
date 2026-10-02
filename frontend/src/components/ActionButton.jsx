import React, { useState, useRef, useEffect } from 'react';
import { Copy, Check, X, RefreshCw } from 'lucide-react';

/**
 * AsyncButton — click -> spinner -> inline ✓ / ✗, then settles back.
 * Gives every action button inline feedback without relying on toasts.
 * onClick may be async; thrown errors optionally surface via onError too.
 */
export function AsyncButton({
  onClick, title, className = '', children, idleContent = null,
  okText = null, holdMs = 1600, disabled = false
}) {
  const [state, setState] = useState('idle'); // idle | busy | ok | err
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const settle = (next) => {
    setState(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState('idle'), holdMs);
  };

  const handle = async (e) => {
    e?.preventDefault?.();
    if (state === 'busy' || disabled) return;
    setState('busy');
    try {
      const r = await onClick?.(e);
      if (r === false) {
        // Handler declined (e.g. confirm dismissed) — back to idle, no flash
        setState('idle');
        return;
      }
      settle('ok');
    } catch (err) {
      settle('err');
    }
  };

  return (
    <button type="button" title={title} onClick={handle} disabled={disabled || state === 'busy'} className={className}>
      {state === 'busy' ? (
        <RefreshCw className="w-4 h-4 animate-spin" />
      ) : state === 'ok' ? (
        <span className="flex items-center gap-1 text-emerald-300">
          <Check className="w-4 h-4" />
          {okText && <span className="text-[11px] font-bold">{okText}</span>}
        </span>
      ) : state === 'err' ? (
        <X className="w-4 h-4 text-rose-400" />
      ) : (
        idleContent || children
      )}
    </button>
  );
}

/**
 * CopyButton — copies text, flips to a check briefly. Replaces all the
 * ad-hoc copied/copiedLink state pairs.
 */
export function CopyButton({ text, title = 'Copy', className = '', iconClassName = 'w-4 h-4', onCopied, children }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const handle = async (e) => {
    e?.stopPropagation?.();
    try {
      await navigator.clipboard.writeText(text ?? '');
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text ?? '';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    setCopied(true);
    onCopied?.();
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1600);
  };

  return (
    <button type="button" title={title} onClick={handle} className={className}>
      {copied ? <Check className={`${iconClassName} text-emerald-400`} /> : <Copy className={iconClassName} />}
      {children}
    </button>
  );
}
