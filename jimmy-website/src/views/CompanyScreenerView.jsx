import React from 'react';
import { Search, Info } from 'lucide-react';
import { CompanyLogo } from '../components/CompanyLogo';
import { Pagination } from '../components/Pagination';
import { compact, pct, fmt } from '../utils/formatters';

export function CompanyScreenerView({
  companies,
  pagedCompanies,
  validPage,
  totalPages,
  pageSize,
  onPageChange,
  onPageSizeChange,
  onSelect
}) {
  return (
    <div className="company-surface">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>
                Scope 1 <small>tCO₂e · year</small>
              </th>
              <th>
                Promised <small>% / year</small>
              </th>
              <th>
                Measured <small>% / year</small>
              </th>
              <th>
                Gap <small>pp / year</small>
              </th>
              <th>Coverage</th>
            </tr>
          </thead>
          <tbody>
            {pagedCompanies.map(r => (
              <tr key={r.ticker} onClick={() => onSelect(r)}>
                <td>
                  <button
                    className="company-name"
                    onClick={ev => {
                      ev.stopPropagation();
                      onSelect(r);
                    }}
                  >
                    <CompanyLogo company={r} />
                    <span>
                      <strong>{r.company_name}</strong>
                      <small>
                        {r.ticker} · {r.gics_sector}
                      </small>
                    </span>
                  </button>
                </td>
                <td>
                  {compact(r.scope1_t)}
                  <small>{r.scope1_year || 'Unknown year'}</small>
                </td>
                <td>{pct(r.promised_pct_yr)}</td>
                <td>{pct(r.delivered_pct_yr)}</td>
                <td>
                  <span
                    className={
                      r.gap_pct_yr == null
                        ? ''
                        : r.gap_pct_yr > 0
                        ? 'gap-badge'
                        : 'gap-badge good'
                    }
                  >
                    {r.gap_pct_yr == null ? 'N/A' : `${r.gap_pct_yr > 0 ? '+' : ''}${fmt(r.gap_pct_yr, 1)}`}
                  </span>
                </td>
                <td>
                  <span className={`coverage ${r.coverage_tier}`}>{r.coverage_tier}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!companies.length && (
        <div className="empty-state">
          <Search />
          <h3>No matching companies</h3>
          <p>Adjust the search or sector filter.</p>
        </div>
      )}

      {companies.length > 0 && (
        <Pagination
          page={validPage}
          totalPages={totalPages}
          totalItems={companies.length}
          pageSize={pageSize}
          onPageChange={onPageChange}
          onPageSizeChange={onPageSizeChange}
        />
      )}

      <div className="notice">
        <Info size={16} />
        <p>
          A positive gap means slower reductions than promised. Reporting periods and boundaries vary; missing figures remain unknown.
        </p>
      </div>
    </div>
  );
}
