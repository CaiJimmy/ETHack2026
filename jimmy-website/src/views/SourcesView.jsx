import React, { useEffect, useState } from 'react';
import { AlertCircle, LoaderCircle } from 'lucide-react';

const CLASSES = [
  ['mandatory', 'Mandatory'],
  ['voluntary', 'Voluntary'],
  ['modelled', 'Modelled'],
  ['vendor', 'Vendor']
];

function ClassPill({ klass }) {
  return <span className={`src-class ${klass}`}>{klass}</span>;
}

function CoverageBar({ row }) {
  const width = Math.max(row.pct, row.count > 0 ? 1.5 : 0);
  return (
    <div className="src-cover">
      <span
        className={`src-bar-track ${row.class}`}
        role="img"
        aria-label={`${row.count} of ${row.of} companies`}
      >
        <span className="src-bar-fill" style={{ width: `${width}%` }} />
      </span>
      <span className="src-cover-value">
        {row.count}
        <i>/{row.of}</i>
      </span>
    </div>
  );
}

function QualityMark({ row }) {
  return (
    <div className="src-quality">
      {row.dq ? (
        <span className="src-dq" role="img" aria-label={`PCAF data quality ${row.dq} of 5`}>
          {[1, 2, 3, 4, 5].map(step => (
            <i key={step} className={step === row.dq ? 'on' : ''} />
          ))}
          <b>{row.dq}</b>
        </span>
      ) : null}
      <small>{row.dq_note}</small>
    </div>
  );
}

export function SourcesView() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/data/sources.json')
      .then(r => {
        if (!r.ok) throw Error('Could not load the source table.');
        return r.json();
      })
      .then(setData)
      .catch(e => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="empty-state" role="alert">
        <AlertCircle />
        <h3>Could not load the source table</h3>
        <p>{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="empty-state">
        <LoaderCircle className="spin" />
        <h3>Loading sources</h3>
      </div>
    );
  }

  const { meta, sources } = data;
  const built = new Date(meta.built_at).toISOString().slice(0, 10);
  const read = sources.map(r => r.retrieved).filter(Boolean).sort().at(-1);

  return (
    <div className="company-surface sources-view">
      <h2>Where every number comes from</h2>
      <p className="subtle">
        One row per source. Mandatory filings first. Vendor data sits at the bottom and feeds no
        score.
      </p>

      <div className="src-legend">
        {CLASSES.map(([key, label]) => (
          <span key={key} className="src-legend-item">
            <ClassPill klass={key} />
            <b>{meta.class_counts[key] || 0}</b>
            <span className="sr-only">{label}</span>
          </span>
        ))}
      </div>

      <div className="table-scroll">
        <table className="sources-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>What it gives</th>
              <th>Class</th>
              <th>
                Coverage<small>of {meta.universe}</small>
              </th>
              <th>Period</th>
              <th>Licence</th>
              <th>
                Quality<small>PCAF 1 to 5</small>
              </th>
            </tr>
          </thead>
          <tbody>
            {sources.map(row => (
              <tr key={row.id} className={`${row.class}${row.scored ? '' : ' src-off'}`}>
                <td data-label="Source" className="src-name">
                  <strong>{row.name}</strong>
                </td>
                <td data-label="Gives" className="src-gives">
                  <span>{row.gives}</span>
                  {row.scored ? null : <em className="src-tag">in no score</em>}
                </td>
                <td data-label="Class">
                  <ClassPill klass={row.class} />
                </td>
                <td data-label="Coverage">
                  <CoverageBar row={row} />
                </td>
                <td data-label="Period" className="src-period">
                  {row.period}
                </td>
                <td data-label="Licence" className="src-licence" title={row.licence_full || ''}>
                  {row.licence}
                </td>
                <td data-label="Quality">
                  <QualityMark row={row} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="micro">
        PCAF quality runs 1 measured to 5 sector average. Every source read {read}. Built {built}{' '}
        from {meta.n_sources} attestation files.
      </p>
    </div>
  );
}
