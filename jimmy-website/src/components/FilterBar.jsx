import React from 'react';
import { SlidersHorizontal, X } from 'lucide-react';
import { Field } from './Field';
import { fmt } from '../utils/formatters';

export function FilterBar({
  view,
  filters,
  updateFilter,
  cf,
  updateCompany,
  countries,
  sectors,
  companySectors,
  activeResult,
  onResetActiveResult
}) {
  return (
    <>
      {activeResult && (
        <div className="result-filter">
          <span>
            {activeResult.filters?.place
              ? `Plume evidence around ${activeResult.filters.place}`
              : activeResult.filters?.tickers
              ? `Company records for ${activeResult.filters.tickers}`
              : activeResult.filters?.sector
              ? `Sector results for ${activeResult.filters.sector}`
              : `Showing ${fmt(activeResult.rows.length)} filtered records from the dataset assistant`}
          </span>
          <button className="secondary" onClick={onResetActiveResult}>
            <X size={14} />
            <span>Reset filter</span>
          </button>
        </div>
      )}

      <div className="filters">
        {view === 'map' ? (
          <>
            <Field label="Gas">
              <select value={filters.gas} onChange={e => updateFilter('gas', e.target.value)}>
                <option value="CH4">Methane · CH₄</option>
                <option value="CO2">Carbon dioxide · CO₂</option>
              </select>
            </Field>
            <Field label="Location">
              <select value={filters.country} onChange={e => updateFilter('country', e.target.value)}>
                <option value="">Worldwide</option>
                {countries.map(c => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>
            <Field label="Sector">
              <select value={filters.sector} onChange={e => updateFilter('sector', e.target.value)}>
                <option value="">All sectors</option>
                {sectors.map(s => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </Field>
            <details className="more-filters">
              <summary>
                <SlidersHorizontal size={16} />
                <span>More</span>
              </summary>
              <div>
                <Field label="From (inclusive)">
                  <input type="date" value={filters.start} onChange={e => updateFilter('start', e.target.value)} />
                </Field>
                <Field label="To (inclusive)">
                  <input type="date" value={filters.end} onChange={e => updateFilter('end', e.target.value)} />
                </Field>
                <Field label="Minimum rate · kg/h">
                  <input
                    type="number"
                    min="0"
                    value={filters.minRate}
                    placeholder="Any rate"
                    onChange={e => updateFilter('minRate', e.target.value)}
                  />
                </Field>
              </div>
            </details>
          </>
        ) : (
          <>
            <Field label="Sector">
              <select value={cf.sector} onChange={e => updateCompany('sector', e.target.value)}>
                <option value="">All sectors</option>
                {companySectors.map(s => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </Field>
            <Field label="Company">
              <input
                placeholder="Name or ticker"
                value={cf.search}
                onChange={e => updateCompany('search', e.target.value)}
              />
            </Field>
            <Field label="Sort by">
              <select value={cf.sort} onChange={e => updateCompany('sort', e.target.value)}>
                <option value="gap">Largest target gap</option>
                <option value="emissions">Largest Scope 1</option>
                <option value="risk">Scenario impact</option>
                <option value="name">Company name</option>
              </select>
            </Field>
            <Field label="Minimum gap · pp/yr">
              <input
                type="number"
                placeholder="Any gap"
                value={cf.minGap}
                onChange={e => updateCompany('minGap', e.target.value)}
              />
            </Field>
          </>
        )}
      </div>
    </>
  );
}
