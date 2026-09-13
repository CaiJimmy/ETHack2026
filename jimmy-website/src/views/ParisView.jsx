import React, { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { CompanyLogo } from '../components/CompanyLogo';
import { fmt } from '../utils/formatters';

/* -------------------------------------------------------------
   Reads /data/paris.json. Every number below is a fallback read
   from site/data/portfolio.json and data/interim/pab_rules.json,
   used only while that file is missing.
   ------------------------------------------------------------- */

const FALLBACK_BARRED = [
  'AEE', 'AEP', 'AES', 'CEG', 'CMS', 'CNP', 'D', 'DTE', 'DUK', 'ED', 'EIX', 'ETR', 'EVRG', 'EXC',
  'FE', 'LNT', 'NEE', 'NI', 'NRG', 'PCG', 'PEG', 'PNW', 'PPL', 'SO', 'SRE', 'VST', 'WEC', 'XEL',
  'APA', 'COP', 'CVX', 'DVN', 'EOG', 'EQT', 'FANG', 'KMI', 'MPC', 'OKE', 'OXY', 'PSX', 'TPL',
  'TRGP', 'VLO', 'WMB', 'ATO', 'EXE', 'AXON', 'BA', 'GD', 'GE', 'HII', 'HONA', 'HWM', 'J', 'LHX',
  'LMT', 'NOC', 'RTX', 'TDG', 'TXT', 'CAT', 'FCX', 'CSX', 'NSC', 'MO', 'PM'
];

const FALLBACK = {
  celex: '32020R1818',
  rulesFile: 'data/interim/pab_rules.json',
  code: 'src/portfolio.py',
  retrieved: '12 September 2026',
  attribution: 'Source: EUR-Lex, © European Union, 1998-2026',
  barred: 67,
  universe: 499,
  barredWeightPct: 8.57,
  flags: 73,
  rules: [
    { article: '12(1)(a)', label: 'Makers of cluster munitions, landmines and other banned weapons', n: 14, tested: true },
    { article: '12(1)(b)', label: 'Tobacco growers and manufacturers', n: 2, tested: true },
    { article: '12(1)(c)', label: 'Companies in breach of the UN Global Compact or the OECD guidelines', n: 3, tested: true },
    { article: '12(1)(d)', label: 'Coal. Barred at 1% of revenue', n: 2, tested: true },
    { article: '12(1)(e)', label: 'Oil fuels. Barred at 10% of revenue', n: 17, tested: true },
    { article: '12(1)(f)', label: 'Gaseous fuels. Barred at 50% of revenue', n: 7, tested: true },
    { article: '12(1)(g)', label: 'Power generation above 100 gCO₂e per kWh, at 50% of revenue', n: 28, tested: true },
    { article: '12(2)', label: 'Companies that do significant harm to an EU Taxonomy objective', n: 0, tested: false }
  ],
  sold: [
    { ticker: 'NVDA', name: 'Nvidia', musd: -25.7 },
    { ticker: 'AAPL', name: 'Apple Inc.', musd: -19.8 },
    { ticker: 'XOM', name: 'ExxonMobil', musd: -9.8 },
    { ticker: 'GOOGL', name: 'Alphabet Inc. (Class A)', musd: -9.3 },
    { ticker: 'CVX', name: 'Chevron Corporation', musd: -6.1 }
  ],
  bought: [
    { ticker: 'AMZN', name: 'Amazon', musd: 10.1 },
    { ticker: 'AVGO', name: 'Broadcom', musd: 8.0 },
    { ticker: 'TSLA', name: 'Tesla, Inc.', musd: 6.7 },
    { ticker: 'MU', name: 'Micron Technology', musd: 5.1 },
    { ticker: 'LLY', name: 'Lilly (Eli)', musd: 4.8 }
  ],
  cutAchievedPct: 63.06,
  cutRequiredPct: 50,
  cutRequiredArticle: 'Article 11',
  trackingErrorPct: 1.5,
  reallocationPct: 97.4,
  improvementPct: 2.7,
  scores: null
};

/* ---------- tolerant readers, so a missing field degrades quietly ---------- */

const num = (...c) => {
  for (const v of c) {
    const n = typeof v === 'string' ? Number(v) : v;
    if (typeof n === 'number' && Number.isFinite(n)) return n;
  }
  return null;
};

const str = (...c) => {
  for (const v of c) if (typeof v === 'string' && v.trim()) return v.trim();
  return null;
};

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function humanDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

function readMoves(list) {
  if (!Array.isArray(list)) return null;
  const out = list
    .map(t => ({
      ticker: str(t?.ticker, t?.symbol) || '',
      name: str(t?.name, t?.company_name) || '',
      gics_sector: t?.gics_sector || t?.sector,
      musd: num(t?.musd, t?.usd_m, t?.value_musd, t?.delta_musd, t?.value)
    }))
    .filter(t => t.ticker && t.musd != null);
  return out.length ? out.slice(0, 5) : null;
}

function readRules(list) {
  if (!Array.isArray(list) || !list.length) return null;
  const out = list
    .map(r => ({
      article: (str(r?.article, r?.id) || '').replace(/^Article\s+/i, ''),
      label: (str(r?.label, r?.plain, r?.name) || '').replace(/\.$/, ''),
      n: num(r?.n_barred, r?.n, r?.count),
      tested: r?.tested !== false
    }))
    .filter(r => r.article && r.label);
  return out.length ? out : null;
}

function readScores(companies) {
  if (!companies || typeof companies !== 'object') return null;
  const rows = Array.isArray(companies)
    ? companies
    : Object.entries(companies).map(([ticker, v]) => ({ ticker, ...v }));
  const map = new Map();
  for (const r of rows) {
    const ticker = str(r?.ticker, r?.symbol);
    if (!ticker) continue;
    const barred = Boolean(r?.barred_by ?? r?.barred ?? r?.excluded ?? r?.in_paris === false);
    map.set(ticker, { score: num(r?.paris_score, r?.score), barred, rule: str(r?.barred_by) });
  }
  return map.size ? map : null;
}

function normalize(raw) {
  const meta = raw?.meta || raw || {};
  const head = meta.headline || raw?.headline || {};
  const rules = readRules(raw?.rules) || FALLBACK.rules;
  const flags = rules.filter(r => r.tested).reduce((s, r) => s + (r.n || 0), 0);
  const scores =
    readScores(raw?.companies) ||
    new Map(FALLBACK_BARRED.map(t => [t, { score: 0, barred: true, rule: null }]));

  return {
    celex: str(meta.celex) || FALLBACK.celex,
    rulesFile: str(meta.rules_read_from) || FALLBACK.rulesFile,
    code: str(meta.index_computed_by) || FALLBACK.code,
    retrieved: humanDate(str(meta.regulation_retrieved)) || FALLBACK.retrieved,
    attribution: (str(meta.attribution) || FALLBACK.attribution).replace('(c)', '©'),
    barred: num(head.n_excluded, head.n_barred, meta.n_excluded) ?? FALLBACK.barred,
    universe: num(head.n_universe, meta.universe?.n_companies) ?? FALLBACK.universe,
    barredWeightPct: num(head.cap_share_excluded_pct, head.barred_weight_pct) ?? FALLBACK.barredWeightPct,
    flags: flags || FALLBACK.flags,
    rules,
    sold: readMoves(raw?.moves?.cuts || raw?.cuts) || FALLBACK.sold,
    bought: readMoves(raw?.moves?.adds || raw?.adds) || FALLBACK.bought,
    cutAchievedPct: num(head.intensity_cut_achieved_pct) ?? FALLBACK.cutAchievedPct,
    cutRequiredPct: num(head.intensity_cut_required_pct) ?? FALLBACK.cutRequiredPct,
    cutRequiredArticle: str(head.intensity_cut_required_article) || FALLBACK.cutRequiredArticle,
    trackingErrorPct: num(head.tracking_error_pct) ?? FALLBACK.trackingErrorPct,
    reallocationPct: num(head.reallocation_share_pct) ?? FALLBACK.reallocationPct,
    improvementPct: num(head.improvement_share_pct) ?? FALLBACK.improvementPct,
    scores
  };
}

/* ---------- one shared fetch for the view and the treemap ---------- */

let cache = null;
let pending = null;
const subscribers = new Set();

export function useParisIndex() {
  const [data, setData] = useState(cache);

  useEffect(() => {
    if (cache) {
      setData(cache);
      return undefined;
    }
    subscribers.add(setData);
    if (!pending) {
      pending = fetch('/data/paris.json')
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null)
        .then(json => {
          cache = normalize(json);
          subscribers.forEach(fn => fn(cache));
        });
    }
    return () => subscribers.delete(setData);
  }, []);

  return data || normalize(null);
}

/* ---------- treemap fill ----------
   paris_score is 1 to 100, where 100 is the lowest Scope 1 intensity
   in the sector. Barred companies score 0 and are hatched instead of
   filled, so a rule and a bad score never read as the same thing.  */

const RAMP = ['#fdeadf', '#fac8ac', '#f8a274', '#f6783c', '#f54e00', '#c73f00'];
const UNSCORED = '#cfcdc4';

export function parisTile(row, paris) {
  const rec = paris?.scores?.get?.(row?.ticker);
  if (!rec) return { barred: false, background: UNSCORED, light: true };
  if (rec.barred) return { barred: true, background: undefined, light: false };
  if (rec.score == null) return { barred: false, background: UNSCORED, light: true };
  const t = Math.min(1, Math.max(0, (100 - rec.score) / 99));
  const i = Math.round(t * (RAMP.length - 1));
  return { barred: false, background: RAMP[i], light: i < 2 };
}

/* ---------- the view ---------- */

const dec = (n, d) =>
  n == null
    ? 'n/a'
    : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const one = n => dec(n, 1);

function Rows({ items }) {
  return (
    <dl className="paris-rows">
      {items.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function TradeColumn({ title, side, items }) {
  return (
    <div className={`paris-trade-col ${side}`}>
      <h4>{title}</h4>
      <ul>
        {items.map(t => (
          <li key={t.ticker}>
            <CompanyLogo company={t} size="small" />
            <strong title={t.name || t.ticker}>{t.ticker}</strong>
            <span>
              {t.musd > 0 ? '+' : '−'}
              {one(Math.abs(t.musd))}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ParisView() {
  const p = useParisIndex();

  return (
    <div className="company-surface paris-view">
      <div className="paris-head">
        <span className="paris-eyebrow">EU 2020/1818 applied to the S&amp;P 500</span>
        <h2>Paris index</h2>
      </div>

      <div className="paris-headline">
        <div>
          <strong>{fmt(p.barred)}</strong>
          <span>of {fmt(p.universe)} companies barred</span>
        </div>
        <div>
          <strong>{one(p.barredWeightPct)}%</strong>
          <span>of index market cap</span>
        </div>
      </div>

      <div className="paris-pair">
        <div className="paris-card">
          <h3>Rules read from the regulation</h3>
          <Rows
            items={[
              ['Source', `EUR-Lex, CELEX ${p.celex}`],
              ['Parsed into', <code key="f">{p.rulesFile}</code>],
              ['Provenance', 'Article and source sentence on every rule'],
              ['Retrieved', p.retrieved]
            ]}
          />
        </div>
        <div className="paris-card">
          <h3>Index computed here</h3>
          <Rows
            items={[
              ['Code', <code key="c">{p.code}</code>],
              ['Administrator', 'None'],
              ['Authorisation', 'None'],
              ['Annual review', 'None'],
              ['Scope', 'Scope 1, where Articles 9 and 11 ask for 1, 2 and 3']
            ]}
          />
          <p className="paris-caveat">Not a registered benchmark.</p>
        </div>
      </div>

      <section className="paris-block">
        <div className="section-heading">
          <h3>What Article 12 bars</h3>
          <span>
            {fmt(p.flags)} flags on {fmt(p.barred)} companies
          </span>
        </div>
        <ul className="paris-rules">
          {p.rules.map(r => (
            <li key={r.article}>
              <code>{r.article}</code>
              <span>{r.label}</span>
              {r.tested ? <b>{fmt(r.n)}</b> : <em>not tested</em>}
            </li>
          ))}
        </ul>
      </section>

      <section className="paris-block">
        <div className="section-heading">
          <h3>Largest trades on $1bn</h3>
          <span>$m</span>
        </div>
        <div className="paris-trades">
          <TradeColumn title="Sold" side="sold" items={p.sold} />
          <TradeColumn title="Bought" side="bought" items={p.bought} />
        </div>
      </section>

      <div className="paris-outcomes">
        <div className="metric">
          <span>Intensity cut</span>
          <strong>
            {one(p.cutAchievedPct)}%
            <small>
              {p.cutRequiredArticle} asks {fmt(p.cutRequiredPct)}%
            </small>
          </strong>
        </div>
        <div className="metric">
          <span>Tracking error</span>
          <strong>
            {dec(p.trackingErrorPct, 2)}%<small>against the S&amp;P 500</small>
          </strong>
        </div>
      </div>

      <p className="paris-note">
        Moving money between sectors accounts for {one(p.reallocationPct)}% of the intensity cut. Companies getting
        cleaner accounts for {one(p.improvementPct)}%.
      </p>

      <div className="notice">
        <Info size={16} />
        <p>{p.attribution}</p>
      </div>
    </div>
  );
}
