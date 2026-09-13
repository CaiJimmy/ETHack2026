import React, { useEffect, useMemo, useRef, useState } from 'react';
import { hierarchy, treemap, treemapSquarify } from 'd3-hierarchy';
import { Info, Crosshair, ArrowUpRight } from 'lucide-react';
import { CompanyLogo } from '../components/CompanyLogo';
import { fmt, compact } from '../utils/formatters';
import { sectorColors } from '../constants';

export function CompanyTreemap({ rows, onSelect, onSector }) {
  const [metric, setMetric] = useState('market_cap_musd');
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState(null);
  const container = useRef(null);

  useEffect(() => {
    const o = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    if (container.current) o.observe(container.current);
    return () => o.disconnect();
  }, []);

  const height = width < 500 ? 570 : 510;
  const known = rows.filter(r => r[metric] != null && r[metric] > 0);
  const missing = rows.filter(r => r[metric] == null);
  const zero = rows.filter(r => r[metric] === 0);
  const total = known.reduce((s, r) => s + r[metric], 0);

  const root = useMemo(() => {
    const groups = new Map();
    for (const r of rows) {
      if (r[metric] == null || r[metric] <= 0) continue;
      const sector = r.gics_sector || 'Other';
      if (!groups.has(sector)) groups.set(sector, []);
      groups.get(sector).push(r);
    }
    const tree = hierarchy({
      children: [...groups].map(([name, children]) => ({ name, children }))
    })
      .sum(d => d[metric] || 0)
      .sort((a, b) => b.value - a.value);

    return treemap()
      .tile(treemapSquarify)
      .size([Math.max(1, width), height])
      .paddingOuter(3)
      .paddingInner(2)
      .paddingTop(d => (d.depth === 1 ? 23 : 2))
      .round(true)(tree);
  }, [rows, metric, width, height]);

  const value = r =>
    metric === 'market_cap_musd' ? `$${compact(r[metric] * 1e6)}` : `${compact(r[metric])} tCO₂e`;

  return (
    <div className="treemap-section">
      <div className="treemap-toolbar">
        <div className="metric-toggle" role="group" aria-label="Treemap tile size">
          <button
            className={metric === 'market_cap_musd' ? 'active' : ''}
            onClick={() => {
              setMetric('market_cap_musd');
              setHover(null);
            }}
          >
            Market value
          </button>
          <button
            className={metric === 'scope1_t' ? 'active' : ''}
            onClick={() => {
              setMetric('scope1_t');
              setHover(null);
            }}
          >
            Direct emissions
          </button>
        </div>
        <span>{known.length} companies shown</span>
      </div>
      <p className="treemap-explanation">
        {metric === 'market_cap_musd'
          ? 'Tile area represents company market capitalization.'
          : 'Tile area represents available Scope 1 emissions, combining different years and reporting boundaries.'}{' '}
        Color identifies sector.
      </p>
      <div
        ref={container}
        className="treemap"
        style={{ height }}
        aria-label={`Company treemap sized by ${metric === 'market_cap_musd' ? 'market value' : 'direct emissions'}`}
      >
        {!known.length ? (
          <div className="empty-state">
            <Info />
            <h3>No values to size these tiles</h3>
            <p>Try another metric or clear your filters.</p>
          </div>
        ) : (
          <>
            {root.children?.map(g => (
              <div
                className="sector-frame"
                key={g.data.name}
                style={{
                  left: g.x0,
                  top: g.y0,
                  width: Math.max(0, g.x1 - g.x0),
                  height: Math.max(0, g.y1 - g.y0),
                  background: sectorColors[g.data.name] || '#64748b'
                }}
              >
                {g.x1 - g.x0 > 85 && g.y1 - g.y0 > 35 && <span>{g.data.name.toUpperCase()}</span>}
              </div>
            ))}
            {root.leaves().map(leaf => {
              const r = leaf.data,
                w = leaf.x1 - leaf.x0,
                h = leaf.y1 - leaf.y0;
              if (w < 1 || h < 1) return null;
              return (
                <button
                  className="company-tile"
                  key={r.ticker}
                  style={{
                    left: leaf.x0,
                    top: leaf.y0,
                    width: w,
                    height: h,
                    background: sectorColors[r.gics_sector] || '#64748b'
                  }}
                  onMouseEnter={() => setHover(r)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(r)}
                  onBlur={() => setHover(null)}
                  onClick={() => onSelect(r)}
                  title={`${r.company_name} (${r.ticker}) · ${value(r)} · ${fmt((r[metric] / total) * 100, 2)}% of shown total`}
                  aria-label={`Inspect ${r.company_name}, ${value(r)}`}
                >
                  {w > 44 && h > 38 && (
                    <CompanyLogo company={r} size={w > 105 && h > 85 ? 'tile-large' : 'tile-small'} onDark />
                  )}
                  {w > 34 && h > 23 && (
                    <strong style={{ fontSize: Math.min(26, Math.max(12, Math.min(w / 4, h / 3))) }}>
                      {r.ticker}
                    </strong>
                  )}
                  {w > 75 && h > 62 && <small>{value(r)}</small>}
                  {w > 160 && h > 120 && <span>{r.company_name}</span>}
                </button>
              );
            })}
          </>
        )}
      </div>
      <div className="treemap-hover" aria-live="polite">
        {hover ? (
          <>
            <CompanyLogo company={hover} size="small" />
            <strong>{hover.company_name}</strong>
            <span>
              {value(hover)} · {fmt((hover[metric] / total) * 100, 2)}% of shown total
              {metric === 'scope1_t' ? ` · ${hover.scope1_year || 'Unknown year'}` : ''}
            </span>
            <span>
              Click to inspect <ArrowUpRight size={13} />
            </span>
          </>
        ) : (
          <>
            <Crosshair size={16} />
            <span>Hover to compare. Select any tile to inspect its evidence.</span>
          </>
        )}
      </div>
      <div className="sector-legend">
        {root.children?.map(g => (
          <button
            key={g.data.name}
            onClick={() => onSector(g.data.name)}
            title={`Filter to ${g.data.name}`}
          >
            <i style={{ background: sectorColors[g.data.name] }} />
            {g.data.name}
            <span>{fmt((g.value / total) * 100, 1)}%</span>
          </button>
        ))}
      </div>
      <div className="notice">
        <Info size={16} />
        <p>
          {missing.length}{' '}
          {metric === 'scope1_t'
            ? 'companies have no available Scope 1 value'
            : 'companies have no market-cap value'}
          {zero.length ? `; ${zero.length} have a recorded zero` : ''}. These companies have no area in the treemap.{' '}
          {metric === 'scope1_t'
            ? 'Missing emissions are unknown, not zero.'
            : 'Market capitalization reflects the stored company snapshot.'}{' '}
          Shares refer to the current selection, not a portfolio allocation.
        </p>
      </div>
    </div>
  );
}

export function TreemapView({ companies, snapshot, onSelect, onSector }) {
  const mergedRows = useMemo(() => {
    return companies.map(r => ({
      ...(snapshot?.companies?.find(s => s.ticker === r.ticker) || {}),
      ...r
    }));
  }, [companies, snapshot]);

  return (
    <>
      <div className="finding-banner">
        <div className="finding-main">
          <span className="finding-badge">CONCENTRATION FINDING</span>
          <p>
            <strong>The 85/5 Concentration Paradox:</strong> 30 companies account for <strong>85%</strong> of S&P 500 direct Scope 1 emissions, but only <strong>5.1%</strong> of index market value. Toggle sizing below to see Big Tech collapse and Utilities dominate the index footprint.
          </p>
        </div>
        <div className="finding-metrics">
          <div className="finding-stat">
            <span>Top 10 Emitters</span>
            <strong>49% <small>of emissions</small></strong>
          </div>
          <div className="finding-stat">
            <span>Top 30 Emitters</span>
            <strong>85% <small>of emissions</small></strong>
          </div>
          <div className="finding-stat highlight">
            <span>Top 30 Market Weight</span>
            <strong>5.1% <small>of index cap</small></strong>
          </div>
        </div>
      </div>

      <div className="company-surface">
        <CompanyTreemap rows={mergedRows} onSelect={onSelect} onSector={onSector} />
      </div>
    </>
  );
}
