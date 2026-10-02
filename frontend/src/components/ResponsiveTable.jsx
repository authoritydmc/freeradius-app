import React from 'react';

/**
 * ResponsiveTable — mobile-friendly horizontal scroll wrapper for all admin tables.
 * - overflow-x-auto with touch momentum on mobile
 * - visible scrollbar hint + min-width so columns never crush
 * - sticky header styling left to the inner <table>
 */
export default function ResponsiveTable({ children, className = '' }) {
  return (
    <div
      className={`table-scroll ${className}`}
      role="region"
      aria-label="Scrollable table"
      tabIndex={0}
      style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch', display: 'block', width: '100%' }}
    >
      {children}
    </div>
  );
}
