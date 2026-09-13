import React, { useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { fmt } from '../utils/formatters';

export function Pagination({ page, totalPages, totalItems, pageSize, onPageChange, onPageSizeChange }) {
  const start = totalItems === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalItems);

  const pages = useMemo(() => {
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
    const set = new Set([1, totalPages, page, page - 1, page + 1]);
    const sorted = [...set].filter(p => p >= 1 && p <= totalPages).sort((a, b) => a - b);
    const result = [];
    for (let i = 0; i < sorted.length; i++) {
      if (i > 0 && sorted[i] - sorted[i - 1] > 1) {
        result.push(sorted[i] - sorted[i - 1] === 2 ? sorted[i - 1] + 1 : 'dots');
      }
      result.push(sorted[i]);
    }
    return result;
  }, [page, totalPages]);

  return (
    <div className="pagination-bar" aria-label="Company pagination">
      <div className="pagination-info">
        <span>Showing <strong>{fmt(start)}-{fmt(end)}</strong> of <strong>{fmt(totalItems)}</strong> companies</span>
        <label className="page-size-selector">
          <span>Rows:</span>
          <select value={pageSize} onChange={e => onPageSizeChange(Number(e.target.value))}>
            <option value={15}>15</option>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
      </div>

      <div className="pagination-controls">
        <button
          className="pagination-btn"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          aria-label="Previous page"
        >
          <ChevronLeft size={14} />
          <span>Previous</span>
        </button>

        <div className="pagination-pages">
          {pages.map((p, i) =>
            p === 'dots' ? (
              <span key={`dots-${i}`} className="page-num dots">...</span>
            ) : (
              <button
                key={p}
                className={`page-num ${p === page ? 'active' : ''}`}
                onClick={() => onPageChange(p)}
                aria-current={p === page ? 'page' : undefined}
              >
                {p}
              </button>
            )
          )}
        </div>

        <button
          className="pagination-btn"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          aria-label="Next page"
        >
          <span>Next</span>
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
