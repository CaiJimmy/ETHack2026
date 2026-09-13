import React, { useEffect, useMemo, useRef, useState } from 'react';
import { hierarchy, treemap, treemapSquarify } from 'd3-hierarchy';
import { Info, Crosshair, ArrowUpRight } from 'lucide-react';
import { CompanyLogo } from '../components/CompanyLogo';
import { fmt, compact } from '../utils/formatters';
import { sectorColors } from '../constants';
import { useParisIndex, parisTile } from './ParisView';

/* ---------- index weights ----------
   paris.json carries both weights for every company: w_cap_pct is the
   weight under our index, w_paris_pct the weight under the Paris index.
   Tile area reads whichever one the switch is on, so flipping the switch
   drops the barred companies and regrows everything still held.          */

let weightCache = null;
let weightPending = null;
const weightSubscribers = new Set();

function readWeights(json) {
  const map = new Map();
  const companies = json?.companies;
  if (!companies) return map;
  const rows = Array.isArray(companies)
    ? companies.map(r => [r?.ticker, r])
    : Object.entries(companies);
  for (const [ticker, r] of rows) {
    if (!ticker || !r) continue;
    const cap = Number(r.w_cap_pct);
    const paris = Number(r.w_paris_pct);
    map.set(ticker, {
      cap: Number.isFinite(cap) ? cap : null,
      paris: Number.isFinite(paris) ? paris : null,
      barred: Boolean(r.barred_by) || r.in_paris === false
    });
  }
  return map;
}

function useIndexWeights() {
  const [weights, setWeights] = useState(weightCache);

  useEffect(() => {
    if (weightCache) {
      setWeights(weightCache);
      return undefined;
    }
    weightSubscribers.add(setWeights);
    if (!weightPending) {
      weightPending = fetch('/data/paris.json')
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null)
        .then(json => {
          weightCache = readWeights(json);
          weightSubscribers.forEach(fn => fn(weightCache));
        });
    }
    return () => weightSubscribers.delete(setWeights);
  }, []);

  return weights;
}

export function CompanyTreemap({ rows, onSelect, onSector, index = 'ours' }) {
  const [metric, setMetric] = useState('weight');
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState(null);
  const [leaving, setLeaving] = useState([]);
  const container = useRef(null);
  const placed = useRef(new Map());
  const paris = useParisIndex();
  const weights = useIndexWeights();

  useEffect(() => {
    const o = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    if (container.current) o.observe(container.current);
    return () => o.disconnect();
  }, []);

  const height = width < 500 ? 570 : 510;

  const entries = useMemo(
    () =>
      rows.map(r => {
        const w = weights?.get(r.ticker) || null;
        const cap = w && w.cap != null ? w.cap : r.index_weight_pct ?? null;
        const barred = Boolean(index === 'paris' && w && w.barred);
        let v;
        if (metric === 'scope1_t') v = barred ? 0 : r.scope1_t ?? null;
        else if (barred) v = 0;
        else if (index === 'paris') v = w ? w.paris : null;
        else v = cap;
        return { row: r, ticker: r.ticker, v, cap, barred };
      }),
    [rows, weights, index, metric]
  );

  const stats = useMemo(() => {
    const known = entries.filter(e => e.v != null && e.v > 0);
    const gone = entries.filter(e => e.barred).sort((a, b) => (b.cap ?? 0) - (a.cap ?? 0));
    return {
      known,
      missing: entries.filter(e => e.v == null).length,
      zero: entries.filter(e => e.v === 0 && !e.barred).length,
      gone,
      goneCap: gone.reduce((s, e) => s + (e.cap ?? 0), 0),
      total: known.reduce((s, e) => s + e.v, 0)
    };
  }, [entries]);

  const root = useMemo(() => {
    const groups = new Map();
    for (const e of stats.known) {
      const sector = e.row.gics_sector || 'Other';
      if (!groups.has(sector)) groups.set(sector, []);
      groups.get(sector).push(e);
    }
    const tree = hierarchy({
      children: [...groups].map(([name, children]) => ({ name, children }))
    })
      .sum(d => d.v || 0)
      .sort((a, b) => b.value - a.value);

    return treemap()
      .tile(treemapSquarify)
      .size([Math.max(1, width), height])
      .paddingOuter(3)
      .paddingInner(2)
      .paddingTop(d => (d.depth === 1 ? 23 : 2))
      .round(true)(tree);
  }, [stats, width, height]);

  const tiles = useMemo(() => {
    const map = new Map();
    for (const leaf of root.leaves()) {
      const w = leaf.x1 - leaf.x0;
      const h = leaf.y1 - leaf.y0;
      if (w < 1 || h < 1) continue;
      map.set(leaf.data.ticker, { entry: leaf.data, x: leaf.x0, y: leaf.y0, w, h });
    }
    return map;
  }, [root]);

  /* Tiles render in ticker order, never in layout order. A tile that keeps
     its place in the DOM transitions to its new rectangle; one React moves
     is torn down and rebuilt, which reads as a jump. */
  const ordered = useMemo(
    () => [...tiles.values()].sort((a, b) => (a.entry.ticker < b.entry.ticker ? -1 : 1)),
    [tiles]
  );
  const frames = useMemo(
    () => [...(root.children || [])].sort((a, b) => (a.data.name < b.data.name ? -1 : 1)),
    [root]
  );

  /* A tile that leaves is held at its last rectangle for one animation,
     so a viewer sees it shrink out instead of blinking away. */
  useEffect(() => {
    const gone = [];
    for (const [ticker, t] of placed.current) if (!tiles.has(ticker)) gone.push({ ticker, ...t });
    placed.current = tiles;
    if (!gone.length) {
      setLeaving(current => (current.length ? [] : current));
      return undefined;
    }
    setLeaving(gone);
    const id = setTimeout(() => setLeaving([]), 460);
    return () => clearTimeout(id);
  }, [tiles]);

  const label = e =>
    metric === 'scope1_t' ? `${compact(e.v)} tCO₂e` : `${fmt(e.v, 2)}% of the index`;
  const share = e => (stats.total > 0 ? (e.v / stats.total) * 100 : 0);
  const fill = e =>
    index === 'paris' ? parisTile(e.row, paris) : { barred: false, background: null, light: false };

  const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;

  const sizeNote =
    metric === 'scope1_t'
      ? 'Tile area is the Scope 1 tonnage a company reports.'
      : index === 'paris'
        ? 'Tile area is the weight a company holds in the Paris index.'
        : 'Tile area is the weight a company holds in our index.';
  const colourNote =
    index === 'paris'
      ? 'Colour is the Paris score, deeper orange for a higher Scope 1 intensity inside the sector, grey where no tonnage is filed.'
      : 'Colour is the sector.';

  return (
    <div className="treemap-section">
      <div className="treemap-toolbar">
        <div className="metric-toggle" role="group" aria-label="Treemap tile size">
          <button
            className={metric === 'weight' ? 'active' : ''}
            onClick={() => {
              setMetric('weight');
              setHover(null);
            }}
          >
            Index weight
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
        <span>{stats.known.length} companies shown</span>
      </div>
      <p className="treemap-explanation">
        {sizeNote} {colourNote} Size and colour carry different numbers.
      </p>
      <div
        ref={container}
        className="treemap"
        style={{ height }}
        aria-label={`Company treemap sized by ${metric === 'scope1_t' ? 'direct emissions' : 'index weight'}`}
      >
        {!stats.known.length ? (
          <div className="empty-state">
            <Info />
            <h3>No values to size these tiles</h3>
            <p>Try another metric or clear your filters.</p>
          </div>
        ) : (
          <>
            {frames.map(g => (
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
            {ordered.map(({ entry: e, x, y, w, h }) => {
              const r = e.row;
              const pt = fill(e);
              return (
                <button
                  className={`company-tile${pt.barred ? ' barred' : ''}${pt.light ? ' on-light' : ''}`}
                  key={r.ticker}
                  style={{
                    left: x,
                    top: y,
                    width: w,
                    height: h,
                    background: pt.barred ? undefined : pt.background || sectorColors[r.gics_sector] || '#64748b'
                  }}
                  onMouseEnter={() => setHover(e)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(e)}
                  onBlur={() => setHover(null)}
                  onClick={() => onSelect(r)}
                  title={`${r.company_name} (${r.ticker}) · ${label(e)} · ${fmt(share(e), 2)}% of shown total`}
                  aria-label={`Inspect ${r.company_name}, ${label(e)}`}
                >
                  {w > 44 && h > 38 && (
                    <CompanyLogo company={r} size={w > 105 && h > 85 ? 'tile-large' : 'tile-small'} onDark />
                  )}
                  {w > 34 && h > 23 && (
                    <strong style={{ fontSize: Math.min(26, Math.max(12, Math.min(w / 4, h / 3))) }}>
                      {r.ticker}
                    </strong>
                  )}
                  {w > 75 && h > 62 && <small>{label(e)}</small>}
                  {w > 160 && h > 120 && <span>{r.company_name}</span>}
                </button>
              );
            })}
            {leaving.map(t => (
              <div
                className="company-tile is-leaving"
                key={`out-${t.ticker}`}
                aria-hidden="true"
                style={{
                  left: t.x,
                  top: t.y,
                  width: t.w,
                  height: t.h,
                  background: sectorColors[t.entry.row.gics_sector] || '#64748b'
                }}
              >
                {t.w > 34 && t.h > 23 && <strong>{t.ticker}</strong>}
              </div>
            ))}
          </>
        )}
      </div>

      {index === 'paris' && stats.gone.length > 0 && (
        <div className="treemap-departed">
          <strong>{plural(stats.gone.length, 'company left', 'companies left')} the index</strong>
          <ul>
            {stats.gone.slice(0, 8).map(e => (
              <li key={e.ticker}>
                <button onClick={() => onSelect(e.row)} title={e.row.company_name}>
                  {e.ticker}
                  <span>{fmt(e.cap, 2)}%</span>
                </button>
              </li>
            ))}
          </ul>
          <span>
            Article 12 bars them. Their {fmt(stats.goneCap, 1)}% of the index goes to the companies
            still held.
          </span>
        </div>
      )}

      <div className="treemap-hover" aria-live="polite">
        {hover ? (
          <>
            <CompanyLogo company={hover.row} size="small" />
            <strong>{hover.row.company_name}</strong>
            <span>
              {label(hover)} · {fmt(share(hover), 2)}% of shown total
              {metric === 'scope1_t' ? ` · ${hover.row.scope1_year || 'Unknown year'}` : ''}
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
        {frames.map(g => (
          <button
            key={g.data.name}
            onClick={() => onSector(g.data.name)}
            title={`Filter to ${g.data.name}`}
          >
            <i style={{ background: sectorColors[g.data.name] }} />
            {g.data.name}
            <span>{fmt(stats.total > 0 ? (g.value / stats.total) * 100 : 0, 1)}%</span>
          </button>
        ))}
      </div>
      <div className="notice">
        <Info size={16} />
        <p>
          {metric === 'scope1_t'
            ? `${plural(stats.missing, 'company files', 'companies file')} no Scope 1 value${stats.zero ? `, and ${plural(stats.zero, 'files', 'file')} a zero` : ''}. Missing tonnage is unknown rather than zero.`
            : `${plural(stats.missing, 'company carries', 'companies carry')} no index weight${stats.zero ? `, and ${plural(stats.zero, 'carries', 'carry')} a zero` : ''}.`}{' '}
          They have no area here. Shares refer to the companies on screen.
        </p>
      </div>
    </div>
  );
}

export function TreemapView({ companies, snapshot, onSelect, onSector, index = 'ours' }) {
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
        <CompanyTreemap rows={mergedRows} onSelect={onSelect} onSector={onSector} index={index} />
      </div>
    </>
  );
}
