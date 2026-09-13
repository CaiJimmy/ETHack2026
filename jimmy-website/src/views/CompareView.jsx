import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ChevronRight, Info, LoaderCircle, RotateCcw } from 'lucide-react';
import { CompanyLogo } from '../components/CompanyLogo';

/* -------------------------------------------------------------
   Reads /data/compare.json and reprices the index in the browser.

   A cost is charged per year, in US$ millions:
     cost = carbon_price * carbon_mt
          + water_surcharge * water_mt
          + conduct_multiple * conduct
          + credibility_charge * shortfall

   Ten years of that cost comes off market cap, the cap weights are
   renormalised, and the weight change is priced on a $1bn book.
   A coefficient of null is skipped and the driver is greyed for that
   company. It is never read as a zero.
   ------------------------------------------------------------- */

const YEARS = 10;
const BOOK_MUSD = 1000;

const UNITS = {
  carbon_price: '$ per tonne CO2e',
  water_surcharge: '$ per tonne in stressed basins',
  conduct_multiple: 'times the penalty already paid',
  credibility_charge: '$ per tonne per point of missed cut'
};

const GAPS = {
  carbon_price: 'no Scope 1',
  water_surcharge: 'no basin share',
  conduct_multiple: 'no penalty record',
  credibility_charge: 'no promise'
};

const COEFFICIENTS = {
  carbon_price: 'carbon_mt',
  water_surcharge: 'water_mt',
  conduct_multiple: 'conduct',
  credibility_charge: 'shortfall'
};

const FALLBACK_SLIDERS = [
  { id: 'carbon_price', label: 'Carbon price', default: 100, min: 0, max: 500, step: 5 },
  { id: 'water_surcharge', label: 'Water stress surcharge', default: 0, min: 0, max: 100, step: 5 },
  { id: 'conduct_multiple', label: 'Conduct multiple', default: 1, min: 0, max: 5, step: 0.25 },
  { id: 'credibility_charge', label: 'Credibility charge', default: 0, min: 0, max: 10, step: 0.5 }
];

const PRESETS = [
  { label: 'Policies', value: 22 },
  { label: 'Below 2°C', value: 50 },
  { label: 'Net zero', value: 284 }
];

function money(musd) {
  const v = Math.abs(musd);
  if (!(v > 0)) return '$0';
  if (v >= 100) return `$${v.toFixed(0)}m`;
  if (v >= 1) return `$${v.toFixed(1)}m`;
  if (v >= 0.01) return `$${(v * 1000).toFixed(0)}k`;
  return '$0';
}

async function load() {
  const paths = ['/data/compare.json', `${import.meta.env.BASE_URL || '/'}data/compare.json`];
  for (const path of paths) {
    try {
      const r = await fetch(path);
      if (r.ok) return await r.json();
    } catch (e) {
      /* try the next path */
    }
  }
  throw Error('Could not load the cost coefficients.');
}

function reasons(gaps) {
  if (gaps.length <= 2) return gaps.join(', ');
  return `${gaps.slice(0, 2).join(', ')} +${gaps.length - 2}`;
}

function sliderValue(id, v) {
  if (id === 'conduct_multiple') return `${v}×`;
  if (id === 'carbon_price' || id === 'water_surcharge') return `$${v}`;
  return `$${v}`;
}

export function CompareView() {
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [values, setValues] = useState(null);
  const [open, setOpen] = useState({});

  useEffect(() => {
    let live = true;
    load()
      .then(d => {
        if (!live) return;
        setFile(d);
        const start = {};
        for (const s of d?.sliders?.length ? d.sliders : FALLBACK_SLIDERS) start[s.id] = s.default ?? 0;
        setValues(start);
      })
      .catch(e => live && setError(e.message));
    return () => {
      live = false;
    };
  }, []);

  const sliders = file?.sliders?.length ? file.sliders : FALLBACK_SLIDERS;
  const sectorNames = file?.meta?.sectors || [];
  const coverage = file?.meta?.coverage || {};

  const book = useMemo(() => {
    const rows = Object.entries(file?.companies || {});
    if (!rows.length || !values) return null;

    const active = sliders.filter(s => Number(values[s.id]) > 0);
    const priced = [];
    let weightSum = 0;

    for (const [ticker, c] of rows) {
      const base = Number(c?.w_idx) || 0;
      const mcap = Number(c?.mcap) || 0;
      let cost = 0;
      const gaps = [];
      for (const s of active) {
        const coef = c?.[COEFFICIENTS[s.id] || s.coefficient];
        if (coef == null || Number.isNaN(Number(coef))) {
          gaps.push(GAPS[s.id] || 'not priced');
          continue;
        }
        cost += Number(values[s.id]) * Number(coef);
      }
      const hit = mcap > 0 ? Math.min(1, (YEARS * cost) / mcap) : 0;
      const next = base * (1 - hit);
      weightSum += next;
      priced.push({
        ticker,
        name: c?.name || ticker,
        sector: sectorNames[c?.sec] || 'Other',
        base,
        next,
        cost,
        gaps
      });
    }
    if (!(weightSum > 0)) return null;

    const bySector = new Map();
    let moved = 0;
    for (const r of priced) {
      r.trade = ((r.next / weightSum) * 100 - r.base) * (BOOK_MUSD / 100);
      if (r.trade > 0) moved += r.trade;
      if (!bySector.has(r.sector)) bySector.set(r.sector, { name: r.sector, net: 0, rows: [] });
      const s = bySector.get(r.sector);
      s.net += r.trade;
      s.rows.push(r);
    }

    const sectors = [...bySector.values()];
    for (const s of sectors) {
      s.rows.sort((a, b) => (s.net < 0 ? a.trade - b.trade : b.trade - a.trade));
      s.rows = s.rows.slice(0, 8);
    }

    return {
      moved,
      sold: sectors.filter(s => s.net < -0.005).sort((a, b) => a.net - b.net),
      bought: sectors.filter(s => s.net > 0.005).sort((a, b) => b.net - a.net)
    };
  }, [file, values, sliders, sectorNames]);

  const broken = !!file && !book;

  if (error || broken) {
    return (
      <div className="company-surface compare-view">
        <div className="compare-state" role="alert">
          <AlertCircle />
          <h3>Could not load the cost coefficients</h3>
          <p>{error || 'The file holds no company rows.'}</p>
        </div>
      </div>
    );
  }

  if (!book || !values) {
    return (
      <div className="company-surface compare-view">
        <div className="compare-state">
          <LoaderCircle className="spin" />
          <h3>Loading the coefficients</h3>
        </div>
      </div>
    );
  }

  const touched = sliders.some(s => Number(values[s.id]) !== (s.default ?? 0));

  return (
    <div className="company-surface compare-view">
      <div className="compare-head">
        <div>
          <span className="compare-eyebrow">Against the cap weighted S&amp;P 500</span>
          <h2>Put a price on it</h2>
        </div>
        <div className="compare-headline">
          <strong>{money(book.moved)}</strong>
          <span>moves on a $1bn book</span>
        </div>
      </div>

      <div className="compare-sliders">
        {sliders.map(s => {
          const cov = coverage[s.id];
          const value = Number(values[s.id]);
          return (
            <div className="compare-slider" key={s.id}>
              <div className="compare-slider-top">
                <label htmlFor={`cmp-${s.id}`}>{s.label}</label>
                <b>{sliderValue(s.id, value)}</b>
              </div>
              <input
                id={`cmp-${s.id}`}
                type="range"
                min={s.min ?? 0}
                max={s.max ?? 100}
                step={s.step ?? 1}
                value={value}
                onChange={e => setValues(v => ({ ...v, [s.id]: Number(e.target.value) }))}
              />
              <span className="compare-unit">
                {UNITS[s.id] || s.unit}
                {cov ? <em>{cov.n_priced} of {cov.n_companies}</em> : null}
              </span>
              {s.id === 'carbon_price' ? (
                <div className="compare-presets">
                  {PRESETS.map(p => (
                    <button
                      key={p.label}
                      className={value === p.value ? 'active' : ''}
                      onClick={() => setValues(v => ({ ...v, carbon_price: p.value }))}
                    >
                      {p.label} <i>{p.value}</i>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {book.sold.length || book.bought.length ? (
      <div className="compare-columns">
        <TradeColumn
          side="sold"
          title="Sold"
          sectors={book.sold}
          open={open}
          onToggle={key => setOpen(o => ({ ...o, [key]: !o[key] }))}
        />
        <TradeColumn
          side="bought"
          title="Bought"
          sectors={book.bought}
          open={open}
          onToggle={key => setOpen(o => ({ ...o, [key]: !o[key] }))}
        />
      </div>
      ) : (
        <p className="compare-quiet">Nothing priced.</p>
      )}

      <div className="compare-foot">
        <div className="notice">
          <Info size={16} />
          <p>Ten years of cost comes off market cap. A driver we cannot price is greyed, never zeroed.</p>
        </div>
        {touched ? (
          <button
            className="secondary"
            onClick={() => {
              const start = {};
              for (const s of sliders) start[s.id] = s.default ?? 0;
              setValues(start);
            }}
          >
            <RotateCcw size={14} />
            Reset
          </button>
        ) : null}
      </div>
    </div>
  );
}

function TradeColumn({ side, title, sectors, open, onToggle }) {
  return (
    <section className={`compare-col ${side}`} aria-label={title}>
      <h3>{title}</h3>
      <ul>
        {sectors.map(s => {
          const key = `${side}:${s.name}`;
          const isOpen = !!open[key];
          return (
            <li key={key} className={isOpen ? 'open' : ''}>
              <button className="compare-sector" onClick={() => onToggle(key)} aria-expanded={isOpen}>
                <ChevronRight size={13} className="compare-caret" />
                <span>{s.name}</span>
                <b>{money(s.net)}</b>
              </button>
              {isOpen ? (
                <ul className="compare-companies">
                  {s.rows.map(r => (
                    <li key={r.ticker} className={r.gaps.length ? 'greyed' : ''}>
                      <span className="company-name">
                        <CompanyLogo company={{ ticker: r.ticker, gics_sector: s.name }} size="small" />
                        <span>
                          <strong>{r.name}</strong>
                          {r.gaps.length ? <small>{reasons(r.gaps)}</small> : null}
                        </span>
                      </span>
                      <b>{money(r.trade)}</b>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
