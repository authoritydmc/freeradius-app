import React, { useState, useRef, useEffect } from 'react';
import { MoreHorizontal } from 'lucide-react';

const MENU_W = 224;

/**
 * RowMenu — ⋯ overflow menu for table rows. Fixed-positioned so it escapes
 * horizontally-scrolling table containers (absolute popups get clipped).
 * Item: { icon: node, label, danger?, onSelect: () => false to stay open }.
 */
export default function RowMenu({ title = 'Row actions', items = [], buttonClassName = '' }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, up: false });
  const btnRef = useRef(null);
  const menuRef = useRef(null);

  const close = () => setOpen(false);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (menuRef.current?.contains(e.target) || btnRef.current?.contains(e.target)) return;
      close();
    };
    const onScroll = () => close();
    document.addEventListener('pointerdown', onDoc);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('pointerdown', onDoc);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', close);
    };
  }, [open ]);

  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const up = r.bottom > window.innerHeight - 320;
      setPos({
        left: Math.max(8, Math.min(r.right - MENU_W, window.innerWidth - MENU_W - 8)),
        top: up ? 0 : r.bottom + 6,
        bottom: up ? (window.innerHeight - r.top + 6) : 0,
        up
      });
    }
    setOpen(!open);
  };

  const run = async (item) => {
    try {
      const keep = await item.onSelect?.();
      if (keep !== false) close();
    } catch {
      close();
    }
  };

  return (
    <>
      <button
        ref={btnRef}
        onClick={toggle}
        title={title}
        className={`p-1.5 rounded-lg transition-colors ${open ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-700/50'} ${buttonClassName}`}
      >
        <MoreHorizontal className="w-4 h-4" />
      </button>
      {open && (
        <div
          ref={menuRef}
          style={pos.up ? { left: pos.left, bottom: pos.bottom } : { left: pos.left, top: pos.top }}
          className="fixed z-[70] w-56 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-1.5 space-y-0.5 animate-in fade-in duration-100"
        >
          {items.map((item, i) => (
            <button
              key={i}
              onClick={() => run(item)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium text-left transition ${
                item.danger
                  ? 'text-rose-300 hover:bg-rose-500/10'
                  : 'text-slate-200 hover:bg-slate-800'
              }`}
            >
              <span className="shrink-0">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
