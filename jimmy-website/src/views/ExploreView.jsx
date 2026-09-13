import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, LoaderCircle, RotateCcw, Search } from 'lucide-react';
import { CompanyLogo } from '../components/CompanyLogo';
import '../explore.css';

/* -------------------------------------------------------------------------
   Explore. Ported from the vanilla app on origin/main (web/app.js), which
   held three things this app never got: the pillar weight sliders, the logo
   scatter, and the per-metric score card.

   The metric table, the pillar map and the source map are built by
   src/build_explore_json.py and read from /data/explore.json. The sector
   percentile ranking below is the old app's computeRanks, kept in the
   browser because it is a run-time thing, including its rule that a metric
   with fewer than three peer values in a sector does not rank.
   ------------------------------------------------------------------------- */

const DEFAULT_WEIGHTS = { E: 50, S: 25, G: 25, F: 25 };

const num = (v, d = 1) =>
  v == null ? 'no data' : Number(v).toLocaleString('en-US', { maximumFractionDigits: d });

const FORMATTERS = {
  t0: v => `${num(v, 0)} t`,
  pct: v => `${v >= 0 ? '+' : ''}${num(v, 1)}%`,
  n0: v => num(v, 0),
  n1: v => num(v, 1),
  n2: v => num(v, 2),
  degc: v => `${num(v, 1)} °C`,
  year: v => String(v),
  of6: v => `${num(v, 0)} of 6`,
  of9: v => `${num(v, 0)} of 9`,
  usdb: v => `$${num(v, 1)} bn`,
  mt: v => `${num(v, 2)} Mt`
};

const show = (v, kind) => (v == null ? 'no data' : (FORMATTERS[kind] || FORMATTERS.n1)(v));

/* Sequential ramp for one magnitude, our index score. Light is a low score,
   dark is a high one. One hue, no rainbow. */
const RAMP = [
  [0, [186, 198, 191]],
  [50, [125, 161, 143]],
  [100, [46, 94, 72]]
];
function scoreColour(s) {
  if (s == null) return 'var(--line-strong, #cfcdc4)';
  const t = Math.max(0, Math.min(100, s));
  const i = t <= 50 ? 0 : 1;
  const [a, ca] = RAMP[i];
  const [b, cb] = RAMP[i + 1];
  const k = (t - a) / (b - a);
  const mix = ca.map((c, j) => Math.round(c + (cb[j] - c) * k));
  return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
}

/* --- the old app's computeRanks, unchanged in behaviour ------------------ */
function computeRanks(rows, metrics) {
  const bySector = new Map();
  rows.forEach(c => {
    if (!bySector.has(c.sector)) bySector.set(c.sector, []);
    bySector.get(c.sector).push(c);
  });
  const ranks = new Map();
  rows.forEach(c => ranks.set(c.ticker, {}));
  for (const peers of bySector.values()) {
    for (const m of metrics) {
      const vals = peers.map(c => c[m.key]).filter(v => v != null).sort((a, b) => a - b);
      for (const c of peers) {
        const r = ranks.get(c.ticker);
        const v = c[m.key];
        if (v == null || vals.length < 3) {
          r[m.key] = null;
          continue;
        }
        const below = vals.filter(x => x < v).length;
        const eq = vals.filter(x => x === v).length;
        const p = (100 * (below + eq / 2)) / vals.length;
        r[m.key] = m.good === 'high' ? p : 100 - p;
      }
    }
  }
  return ranks;
}

/* --- the old app's score(), unchanged in behaviour ----------------------- */
function scoreOf(rank, metrics, pillarKeys, w) {
  const out = { n: 0, of: metrics.length };
  let numer = 0;
  let denom = 0;
  for (const p of pillarKeys) {
    const rs = metrics.filter(m => m.pillar === p).map(m => rank[m.key]).filter(r => r != null);
    out.n += rs.length;
    out[p] = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null;
    if (out[p] != null) {
      numer += out[p] * w[p];
      denom += w[p];
    }
  }
  out.total = denom ? numer / denom : null;
  return out;
}

function order(rows, ranks, metrics, pillarKeys, w) {
  return rows
    .map(c => ({ t: c.ticker, s: scoreOf(ranks.get(c.ticker), metrics, pillarKeys, w).total }))
    .filter(r => r.s != null)
    .sort((a, b) => b.s - a.s || a.t.localeCompare(b.t))
    .map(r => r.t);
}

/* A callback ref, because the plot is only mounted once the data has landed. */
function useWidth() {
  const [node, setNode] = useState(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!node) return undefined;
    const ro = new ResizeObserver(entries => setW(entries[0].contentRect.width));
    ro.observe(node);
    setW(node.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, [node]);
  return [setNode, w];
}

export function ExploreView() {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState('');
  const [w, setW] = useState(DEFAULT_WEIGHTS);
  const [xKey, setXKey] = useState('market_cap_b');
  const [sector, setSector] = useState('');
  const [logX, setLogX] = useState(true);
  const [search, setSearch] = useState('');
  const [picked, setPicked] = useState(null);
  const [hover, setHover] = useState(null);

  const [plotRef, plotW] = useWidth();

  useEffect(() => {
    fetch('/data/explore.json')
      .then(r => {
        if (!r.ok) throw Error('Could not load the Explore dataset.');
        return r.json();
      })
      .then(setDoc)
      .catch(e => setError(e.message));
  }, []);

  /* Same universe as the old app: drop the dual-class duplicates and anything
     without a market value, then rank only what carries a sector. */
  const all = useMemo(() => {
    if (!doc) return [];
    const idx = Object.fromEntries(doc.columns.map((c, i) => [c, i]));
    return doc.rows
      .map(r => Object.fromEntries(doc.columns.map((c, i) => [c, r[i]])))
      .filter(c => !c.dual_class_duplicate && c.market_cap_b != null)
      .map(c => ({ ...c, _i: idx }));
  }, [doc]);

  const data = useMemo(() => all.filter(c => c.sector), [all]);
  const metrics = doc?.metrics || [];
  const pillarKeys = useMemo(() => Object.keys(doc?.pillars || {}), [doc]);
  const ranks = useMemo(
    () => (data.length ? computeRanks(data, metrics) : new Map()),
    [data, metrics]
  );

  const byTicker = useMemo(() => new Map(data.map(c => [c.ticker, c])), [data]);
  const sectors = useMemo(() => [...new Set(data.map(c => c.sector))].sort(), [data]);

  const scores = useMemo(() => {
    const m = new Map();
    data.forEach(c => m.set(c.ticker, scoreOf(ranks.get(c.ticker), metrics, pillarKeys, w)));
    return m;
  }, [data, ranks, metrics, pillarKeys, w]);

  /* How far the sliders move the ranking. */
  const defaultOrder = useMemo(
    () => (data.length ? order(data, ranks, metrics, pillarKeys, DEFAULT_WEIGHTS) : []),
    [data, ranks, metrics, pillarKeys]
  );
  const liveOrder = useMemo(
    () => (data.length ? order(data, ranks, metrics, pillarKeys, w) : []),
    [data, ranks, metrics, pillarKeys, w]
  );
  const drift = useMemo(() => {
    if (!defaultOrder.length) return 0;
    const pos = new Map(liveOrder.map((t, i) => [t, i]));
    const top = defaultOrder.slice(0, 10);
    const total = top.reduce((a, t, i) => a + Math.abs((pos.get(t) ?? i) - i), 0);
    return Math.round(total / top.length);
  }, [defaultOrder, liveOrder]);
  const atDefault = pillarKeys.every(p => w[p] === DEFAULT_WEIGHTS[p]);

  const term = search.trim().toLowerCase();
  const shown = useMemo(
    () =>
      data.filter(
        c =>
          (!sector || c.sector === sector) &&
          (!term || `${c.ticker} ${c.name}`.toLowerCase().includes(term))
      ),
    [data, sector, term]
  );

  const axis = doc?.axes.find(a => a.key === xKey);
  const points = useMemo(
    () =>
      shown
        .map(c => ({ c, x: c[xKey], y: scores.get(c.ticker)?.total }))
        .filter(p => p.x != null && p.y != null && (!logX || p.x > 0)),
    [shown, xKey, logX, scores]
  );

  const scored = useMemo(() => data.filter(c => scores.get(c.ticker)?.total != null).length, [data, scores]);

  const compact = plotW > 0 && plotW < 440;
  const H = compact ? 380 : 540;
  const P = compact ? { l: 34, r: 14, t: 14, b: 34 } : { l: 54, r: 20, t: 16, b: 46 };

  const geom = useMemo(() => {
    if (!plotW || !points.length) return null;
    const xs = points.map(p => p.x);
    const lo = Math.min(...xs);
    const hi = Math.max(...xs);
    const tx = v => (logX ? Math.log10(v) : v);
    const span = tx(hi) - tx(lo) || 1;
    const sx = v => P.l + ((tx(v) - tx(lo)) / span) * (plotW - P.l - P.r);
    const sy = v => H - P.b - (v / 100) * (H - P.t - P.b);
    const ticks = logX
      ? [...new Set(xs.map(v => Math.pow(10, Math.floor(Math.log10(v)))))].sort((a, b) => a - b)
      : [0, 0.25, 0.5, 0.75, 1].map(f => lo + f * (hi - lo));
    return { sx, sy, ticks };
  }, [plotW, points, logX, H, P.l, P.r, P.t, P.b]);

  const dot = points.length <= 90 ? (compact ? 26 : 32) : points.length <= 200 ? (compact ? 18 : 24) : compact ? 14 : 20;
  const labels = points.length <= 90 && !compact;

  const selected = picked ? byTicker.get(picked) : null;
  const detail = selected ? scores.get(selected.ticker) : null;
  const peers = useMemo(() => {
    if (!selected) return [];
    return data
      .filter(c => c.sector === selected.sector)
      .map(c => ({ t: c.ticker, s: scores.get(c.ticker)?.total }))
      .filter(p => p.s != null)
      .sort((a, b) => b.s - a.s);
  }, [selected, data, scores]);
  const place = peers.findIndex(p => p.t === picked) + 1;

  const matches = term
    ? data.filter(c => `${c.ticker} ${c.name}`.toLowerCase().includes(term)).slice(0, 6)
    : [];

  if (error) {
    return (
      <div className="xp-state" role="alert">
        <AlertCircle />
        <h3>Could not load Explore</h3>
        <p>{error}</p>
      </div>
    );
  }
  if (!doc) {
    return (
      <div className="xp-state">
        <LoaderCircle className="spin" />
        <h3>Loading the Explore dataset</h3>
      </div>
    );
  }

  const srcOf = key => doc.sources[key] || { short: key, name: key };

  return (
    <div className="xp-root">
      <header className="xp-head">
        <h2>Explore our index</h2>
        <p>
          Every metric is ranked against the company&apos;s own sector, averaged inside its pillar,
          then the four pillars are weighted. You set the weights.
        </p>
      </header>

      <div className="xp-grid">
        <aside className="xp-controls">
          <section className="xp-block">
            <h3>Find a company</h3>
            <div className="xp-search">
              <Search size={14} />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Name or ticker"
                aria-label="Search for a company"
              />
            </div>
            {matches.length > 0 && (
              <ul className="xp-matches">
                {matches.map(c => (
                  <li key={c.ticker}>
                    <button type="button" onClick={() => setPicked(c.ticker)}>
                      <CompanyLogo company={{ ticker: c.ticker, gics_sector: c.sector }} size="small" />
                      <span className="xp-m-tick">{c.ticker}</span>
                      <span className="xp-m-name">{c.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="xp-block">
            <h3>Chart</h3>
            <label className="xp-field">
              <span>Sector</span>
              <select value={sector} onChange={e => setSector(e.target.value)}>
                <option value="">All sectors</option>
                {sectors.map(s => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="xp-field">
              <span>Horizontal axis</span>
              <select value={xKey} onChange={e => setXKey(e.target.value)}>
                {doc.axes.map(a => (
                  <option key={a.key} value={a.key}>
                    {a.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="xp-check">
              <input type="checkbox" checked={logX} onChange={e => setLogX(e.target.checked)} />
              <span>Log scale on the horizontal axis</span>
            </label>
          </section>

          <section className="xp-block">
            <h3>How much each pillar counts</h3>
            {pillarKeys.map(p => (
              <label key={p} className="xp-slider">
                <span className="xp-s-top">
                  <span>{doc.pillars[p]}</span>
                  <b>{w[p]}%</b>
                </span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={w[p]}
                  onChange={e => setW(v => ({ ...v, [p]: Number(e.target.value) }))}
                />
              </label>
            ))}
            <div className="xp-drift">
              <p className={atDefault ? 'xp-quiet' : ''}>
                {atDefault
                  ? 'Sliders are at their starting values.'
                  : `The top ten moved ${drift} ${drift === 1 ? 'place' : 'places'} on average, out of ${liveOrder.length}.`}
              </p>
              <button
                type="button"
                className="xp-reset"
                onClick={() => setW(DEFAULT_WEIGHTS)}
                disabled={atDefault}
              >
                <RotateCcw size={13} />
                Reset
              </button>
            </div>
            <p className="xp-note">
              Weights move 5.9% of the variance in a rank; what we assume about companies that report
              nothing moves 20.1%.
            </p>
          </section>
        </aside>

        <section className="xp-chartwrap">
          <p className="xp-charthead">
            Our index score, 0 is worst in sector and 100 is best in sector. Pick a logo for the
            detail. Filter by sector, or search, to spread the logos out.
          </p>
          <div className="xp-plot" ref={plotRef} style={{ height: `${H}px` }}>
            {geom && (
              <svg className="xp-axes" width={plotW} height={H} aria-hidden="true">
                {[0, 20, 40, 60, 80, 100].map(y => (
                  <g key={y}>
                    <line x1={P.l} x2={plotW - P.r} y1={geom.sy(y)} y2={geom.sy(y)} />
                    <text x={P.l - 8} y={geom.sy(y) + 4} textAnchor="end">
                      {y}
                    </text>
                  </g>
                ))}
                {geom.ticks.map(t => (
                  <g key={t}>
                    <line x1={geom.sx(t)} x2={geom.sx(t)} y1={P.t} y2={H - P.b} />
                    <text x={geom.sx(t)} y={H - P.b + 16} textAnchor="middle">
                      {num(t, 2)}
                    </text>
                  </g>
                ))}
              </svg>
            )}
            {geom &&
              points.map(p => {
                const on = picked === p.c.ticker;
                return (
                  <button
                    type="button"
                    key={p.c.ticker}
                    className={`xp-dot${on ? ' on' : ''}`}
                    style={{
                      left: `${geom.sx(p.x)}px`,
                      top: `${geom.sy(p.y)}px`,
                      '--xp-dot': `${dot}px`,
                      '--xp-ring': scoreColour(p.y)
                    }}
                    onMouseEnter={() => setHover({ t: p.c.ticker, x: geom.sx(p.x), y: geom.sy(p.y) })}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => setPicked(p.c.ticker)}
                    aria-label={`${p.c.name}, score ${num(p.y, 0)}`}
                  >
                    <CompanyLogo
                      company={{ ticker: p.c.ticker, gics_sector: p.c.sector }}
                      size="small"
                    />
                    {labels && <i>{p.c.ticker}</i>}
                  </button>
                );
              })}
            {hover && byTicker.get(hover.t) && (
              <div
                className="xp-tip"
                style={{
                  left: `${Math.min(Math.max(hover.x, 70), Math.max(plotW - 70, 70))}px`,
                  top: `${hover.y - dot / 2 - 8}px`
                }}
              >
                <strong>{byTicker.get(hover.t).name}</strong>
                <span>
                  Score {num(scores.get(hover.t)?.total, 0)} · {axis?.label.split(' (')[0]}{' '}
                  {show(byTicker.get(hover.t)[xKey], axis?.fmt)}
                </span>
              </div>
            )}
            {geom && !compact && (
              <span className="xp-ylabel">Our index score</span>
            )}
            {!points.length && <p className="xp-empty">No company matches those filters.</p>}
          </div>
          <div className="xp-legend">
            <span className="xp-swatch" aria-hidden="true" />
            <span>Low score</span>
            <span className="xp-legend-gap" />
            <span>High score</span>
          </div>
          <p className="xp-axislabel">
            {axis?.label} · source: {srcOf(axis?.src).short}
          </p>
          <p className="xp-coverage">
            {points.length} companies on the chart. Across the whole list, {scored} of {all.length}{' '}
            carry enough data to score.
          </p>
        </section>

        <aside className="xp-card">
          {!selected && (
            <p className="xp-quiet xp-placeholder">
              Pick a logo, or search for a company, to see every metric behind its score and where
              each one came from.
            </p>
          )}
          {selected && (
            <>
              <div className="xp-c-head">
                <CompanyLogo
                  company={{ ticker: selected.ticker, gics_sector: selected.sector }}
                  size="medium"
                />
                <div>
                  <h3>{selected.name}</h3>
                  <p className="xp-quiet">
                    {selected.sector}
                    {selected.industry ? ` · ${selected.industry}` : ''}
                  </p>
                </div>
              </div>

              <div className="xp-big" style={{ color: scoreColour(detail.total) }}>
                {num(detail.total, 0)}
              </div>
              <p className="xp-quiet">
                Rank {place} of {peers.length} in {selected.sector}. Data for {detail.n} of{' '}
                {detail.of} metrics.
              </p>

              <div className="xp-pillars">
                {pillarKeys.map(p => (
                  <div key={p} className="xp-pillar">
                    <span className="xp-p-top">
                      <span>{doc.pillars[p]}</span>
                      <b>{detail[p] == null ? 'no data' : num(detail[p], 0)}</b>
                    </span>
                    <span className="xp-bar">
                      <i
                        style={{
                          width: `${detail[p] || 0}%`,
                          background: scoreColour(detail[p])
                        }}
                      />
                    </span>
                  </div>
                ))}
              </div>

              <table className="xp-table">
                <tbody>
                  {metrics.map(m => {
                    const v = selected[m.key];
                    const r = ranks.get(selected.ticker)[m.key];
                    return (
                      <tr key={m.key}>
                        <td>
                          <span className="xp-m-label">{m.label}</span>
                          <span className="xp-m-src">
                            <span className={`xp-class ${m.class}`}>{m.class}</span>
                            {srcOf(m.src).short}
                          </span>
                        </td>
                        <td className={v == null ? 'xp-na' : ''}>{show(v, m.fmt)}</td>
                        <td className="xp-pctl">{r == null ? '' : `p${num(r, 0)}`}</td>
                      </tr>
                    );
                  })}
                  {doc.extra.map(x => (
                    <tr key={`x-${x.key}`} className="xp-extra">
                      <td>
                        <span className="xp-m-label">{x.label}</span>
                        <span className="xp-m-src">
                          <span className={`xp-class ${x.class}`}>{x.class}</span>
                          {srcOf(x.src).short}
                        </span>
                      </td>
                      <td className={selected[x.key] == null ? 'xp-na' : ''}>
                        {x.key === 'ghgrp_scope1_mt' && selected[x.key] == null
                          ? 'no US site above 25 kt'
                          : show(selected[x.key], x.fmt)}
                      </td>
                      <td className="xp-pctl" />
                    </tr>
                  ))}
                </tbody>
              </table>

              <p className="xp-quiet xp-foot">
                p85 means better than 85% of the sector on that metric. A metric with fewer than
                three peer values in a sector does not rank, and is left out of the pillar average.
              </p>
            </>
          )}
        </aside>
      </div>

      <footer className="xp-sources">
        <h3>Where these numbers came from</h3>
        <ul>
          {Object.entries(doc.sources).map(([k, s]) => (
            <li key={k}>
              <strong>{s.short}</strong>
              <span>{s.name}</span>
              {s.url && (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.url}
                </a>
              )}
            </li>
          ))}
        </ul>
      </footer>
    </div>
  );
}
