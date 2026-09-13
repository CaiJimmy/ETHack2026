import React, { useEffect, useState } from 'react';
import { X, Crosshair, ExternalLink, LoaderCircle, Info, Sparkles } from 'lucide-react';
import { CompanyLogo } from './CompanyLogo';
import { Metric } from './Metric';
import { fmt, compact, pct } from '../utils/formatters';

export function EvidenceDrawer({ item, onClose, onAsk }) {
  const [details, setDetails] = useState(null);
  const [error, setError] = useState('');
  const [showScore, setShowScore] = useState(false);
  const plume = Boolean(item?.plume_id);

  useEffect(() => {
    const onKey = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (plume) return;
    const controller = new AbortController();
    setDetails(null);
    setError('');
    fetch(`/api/companies/${encodeURIComponent(item.ticker)}`, { signal: controller.signal })
      .then(async r => {
        const b = await r.json();
        if (!r.ok) throw Error(b.error);
        return b;
      })
      .then(b => setDetails(b.data))
      .catch(e => {
        if (e.name !== 'AbortError') setError(e.message);
      });
    return () => controller.abort();
  }, [item, plume]);

  const e = details?.emissions || item;
  const a = details?.assessments || item;

  return (
    <aside className="evidence-sidebar" aria-labelledby="evidence-title">
      <div className="drawer-content">
        <div className="drawer-top">
          <span className="eyebrow">{plume ? 'OBSERVATION RECORD' : 'COMPANY EVIDENCE'}</span>
          <button className="icon-button" onClick={onClose} aria-label="Close evidence">
            <X />
          </button>
        </div>
        <div className={`record-icon ${plume ? '' : 'company-record-icon'}`}>
          {plume ? (
            <Crosshair />
          ) : (
            <CompanyLogo
              company={{ ...item, gics_sector: item.gics_sector || details?.listing.gics_sector }}
              size="large"
            />
          )}
        </div>
        <h2 id="evidence-title">
          {plume ? item.place || item.region || 'Plume observation' : item.company_name || item.ticker}
        </h2>
        <p className="subtle">
          {plume
            ? [item.region, item.country].filter(Boolean).join(', ')
            : `${item.ticker} · ${item.gics_sector || details?.listing.gics_sector || ''}`}
        </p>

        {plume ? (
          <>
            <div className="drawer-metrics">
              <Metric
                label="Estimated emission rate"
                value={fmt(item.emission_auto, 1)}
                unit={item.emission_auto != null ? `kg ${item.gas}/h` : ''}
              />
              <Metric
                label="Rate uncertainty"
                value={item.emission_uncertainty_auto == null ? 'Not available' : `± ${fmt(item.emission_uncertainty_auto, 1)}`}
                unit="kg/h"
              />
            </div>
            <h3>Observation details</h3>
            <dl>
              <dt>Observed</dt>
              <dd>{new Date(item.observed_at_utc).toLocaleString('en-GB', { timeZone: 'UTC' })} UTC</dd>
              <dt>Sector</dt>
              <dd>{item.ipcc_sector || 'Not available'}</dd>
              <dt>Platform</dt>
              <dd>{item.platform || 'Not available'}</dd>
              <dt>Provider</dt>
              <dd>{item.provider || 'Not available'}</dd>
              <dt>Coordinates</dt>
              <dd>{fmt(item.plume_latitude, 4)}, {fmt(item.plume_longitude, 4)}</dd>
              <dt>Company ownership</dt>
              <dd>Not verified</dd>
            </dl>
            <div className="notice">
              <Info size={17} />
              <p>This is an observation of a plume, not an annual total or a unique facility. Repeated observations may refer to the same source.</p>
            </div>
            <h3>Source record</h3>
            <code className="record-id">{item.plume_id}</code>
            <a className="text-link" href="https://data.carbonmapper.org/" target="_blank" rel="noreferrer">
              Carbon Mapper data portal <ExternalLink size={14} />
            </a>
          </>
        ) : (
          <>
            {error && <div role="alert" className="notice error">{error} · Showing available screening data.</div>}
            {!details && !error && (
              <p className="subtle"><LoaderCircle className="spin" size={16} /> Loading detailed evidence...</p>
            )}
            <button
              className="secondary full"
              aria-expanded={showScore}
              aria-controls="score-explanation"
              onClick={() => setShowScore(v => !v)}
            >
              <Info size={16} />
              {showScore ? 'Hide score explanation' : 'Explain company score'}
            </button>
            {showScore && (
              <section id="score-explanation" className="score-explanation" aria-label="Company score explanation">
                <h3>How this company is scored</h3>
                <p className="micro">This is a relative climate assessment under our methodology. A higher percentile is better; rank 1 is best.</p>
                <dl>
                  <dt>Rank range (5th to 95th)</dt>
                  <dd>{fmt(a.rank_p05)} to {fmt(a.rank_p95)}</dd>
                  <dt>Evidence coverage</dt>
                  <dd>{a.coverage_tier || 'Unavailable'}</dd>
                </dl>
                <h3>Four assessment areas</h3>
                <ol className="score-method">
                  <li>
                    <strong>Physical emissions and progress</strong>
                    <p>Measured Scope 1 emissions per revenue and the fitted annual emissions trend. Lower intensity and falling emissions improve performance.</p>
                  </li>
                  <li>
                    <strong>Promise versus progress</strong>
                    <p>Measured annual change minus promised annual change. A positive gap means slower cuts than promised.</p>
                  </li>
                  <li>
                    <strong>Carbon-price exposure</strong>
                    <p>Modeled carbon costs relative to operating income. Results depend on the scenario and its assumptions.</p>
                  </li>
                  <li>
                    <strong>Environmental conduct</strong>
                    <p>Historical environmental enforcement penalties relative to revenue. This measures the recorded compliance history.</p>
                  </li>
                </ol>
                <h3>Why a range, rather than one precise rank?</h3>
                <p className="micro">The scoring pipeline runs 10,000 simulations across weighting and other modeling choices. The interval describes sensitivity to those choices. A wide interval means the ranking is unstable.</p>
                <div className="notice">
                  <Info size={16} />
                  <p>Missing evidence is not zero emissions or proof of good performance. The detail API provides the final percentile and rank interval, but not exact per-area score contributions; those contributions are not reconstructed here.</p>
                </div>
                <p className="micro">Methodology: project scoring pipeline · source records: company assessments and emissions. This explanation is deterministic and does not require an AI request.</p>
              </section>
            )}
            <div className="drawer-metrics">
              <Metric label="Direct emissions · Scope 1" value={compact(e.scope1_t)} unit="tCO₂e" />
              <Metric label="Reporting year" value={e.scope1_year || 'Unknown'} />
            </div>
            <h3>Emissions coverage</h3>
            <dl>
              <dt>Scope 2 · purchased energy</dt>
              <dd>{e.scope2_market_t == null ? 'Not available' : `${fmt(e.scope2_market_t)} tCO₂e · ${e.scope2_year || 'year unknown'}`}</dd>
              <dt>Scope 2 basis</dt>
              <dd>{e.scope2_basis || 'Not available'}</dd>
              <dt>Scope 3 · value chain</dt>
              <dd>{e.scope3_total_t == null ? 'Not available' : `${fmt(e.scope3_total_t)} tCO₂e · ${e.scope3_year || 'year unknown'}`}</dd>
            </dl>
            <h3>Promises & progress</h3>
            <div className="rate-comparison">
              <div><span>Promised annual change</span><strong>{pct(e.promised_pct_yr)}</strong></div>
              <div><span>Measured annual change</span><strong>{pct(e.delivered_pct_yr)}</strong></div>
              <div className="gap-row"><span>Annual shortfall</span><strong>{e.gap_pct_yr == null ? 'Unknown' : `${fmt(e.gap_pct_yr, 1)} pp`}</strong></div>
            </div>
            <p className="micro">Negative change means falling emissions. Measured window: {e.delivered_year_start || 'N/A'} to {e.delivered_year_end || 'N/A'}. Corporate targets and US facility measurements may cover different boundaries.</p>
            <h3>Stored carbon-cost scenario</h3>
            <Metric label="Modeled enterprise-value impact" value={a.d_ev_pct_of_ev == null ? 'Not available' : `${fmt(a.d_ev_pct_of_ev, 1)}%`} />
            <dl>
              <dt>Carbon price</dt>
              <dd>{a.price_sector_usd_per_t == null ? 'Loading / unavailable' : `$${fmt(a.price_sector_usd_per_t, 2)}/t`}</dd>
              <dt>Customer pass-through</dt>
              <dd>{a.passthrough_pct == null ? 'Loading / unavailable' : `${a.passthrough_pct}% (assumed)`}</dd>
              <dt>Rank interval (5th to 95th)</dt>
              <dd>{fmt(a.rank_p05)} to {fmt(a.rank_p95)}</dd>
              <dt>Coverage tier</dt>
              <dd>{a.coverage_tier || 'Unknown'}</dd>
              <dt>Scope 1 basis</dt>
              <dd>{e.scope1_basis?.replaceAll('_', ' ') || 'Unknown'}</dd>
            </dl>
            <div className="notice">
              <Info size={17} />
              <p>Scenario results depend on assumptions. They are not forecasts of investment losses. Missing data is not zero emissions.</p>
            </div>
            <button
              className="primary full"
              onClick={() => {
                onAsk(`Investigate ${item.ticker}: what should I know before trusting its climate score? Retrieve its detailed company evidence and, where supported, compare its target gap with sector peers. State the strongest supported finding, the supporting records, reasons for caution, and the specific evidence to verify next. Check reporting periods and boundaries, target basis, missing data, and rank uncertainty. Distinguish measured facts from modeled estimates and interpretation. Do not infer misconduct or invent score contributions. If a comparison is unavailable, explain that limitation.`);
              }}
            >
              <Sparkles size={16} /> Investigate this company
            </button>
            <p className="micro">Compare evidence, identify limitations, and find what to verify next.</p>
          </>
        )}
      </div>
    </aside>
  );
}
