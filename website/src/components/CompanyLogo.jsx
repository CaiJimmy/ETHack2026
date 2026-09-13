import React, { useState } from 'react';
import { logoTicker } from '../utils/formatters';
import { sectorColors } from '../constants';

export function CompanyLogo({ company, size = 'medium', onDark = false }) {
  const [failed, setFailed] = useState(false);
  const ticker = company?.ticker || '';
  return (
    <span
      className={`company-logo ${size} ${onDark ? 'on-dark' : ''}`}
      style={{ '--logo-sector': sectorColors[company?.gics_sector] || '#64748b' }}
      aria-hidden="true"
    >
      {!failed && ticker ? (
        <img
          src={`https://images.financialmodelingprep.com/symbol/${encodeURIComponent(logoTicker(ticker))}.png`}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : null}
      <span className={failed || !ticker ? 'visible' : ''}>{ticker.slice(0, 4)}</span>
    </span>
  );
}
