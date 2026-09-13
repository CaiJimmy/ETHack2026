export const fmt = (n, digits = 0) =>
  n == null ? 'Not available' : Number(n).toLocaleString('en-US', { maximumFractionDigits: digits });

export const compact = n =>
  n == null ? 'N/A' : new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n);

export const pct = n =>
  n == null ? 'N/A' : `${n > 0 ? '+' : ''}${fmt(n, 1)}%`;

export const logoTicker = ticker =>
  ticker?.replaceAll('.', '-');
