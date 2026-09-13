import React from 'react';
import { Factory, FileText, Ban } from 'lucide-react';
import { Metric } from '../components/Metric';

// Every number below is read from the built artefacts, not typed by hand:
//   site/data/scores.json      sobol_first_order, rank_interval_summary, coverage
//   site/data/portfolio.json   exclusions, portfolios.pab_compliant
const SOBOL = [
  { label: 'Missing data', share: 20 },
  { label: 'Which pillars', share: 11 },
  { label: 'Scaling', share: 7 },
  { label: 'Weights', share: 6 }
];
const SOBOL_AXIS = 25;

const MEASURED = 139;
const UNSCORED = 361;
const UNIVERSE = MEASURED + UNSCORED;

export function MethodsView({ index }) {
  return (
    <div className="company-surface methods-surface">
      <h2>How both indices are built</h2>

      <section className="methods-block">
        <div className="section-heading">
          <h3>Data in</h3>
        </div>
        <div className="methods-sources">
          <div className="methods-source">
            <Factory size={15} />
            <strong>EPA GHGRP</strong>
            <span>Emissions each plant reports under penalty of law</span>
          </div>
          <div className="methods-source">
            <FileText size={15} />
            <strong>SEC filings</strong>
            <span>Market value and debt</span>
          </div>
          <div className="methods-source off">
            <Ban size={15} />
            <strong>ESG vendor scores</strong>
            <span>Not an input</span>
          </div>
        </div>
      </section>

      <section className="methods-block">
        <div className="methods-grid">
          <article className={`methods-card ${index === 'ours' ? 'active' : ''}`}>
            <span className="methods-eyebrow">Our index</span>
            <p>
              Rank each company against its own sector. Average the four pillars. Rebuild the index
              10,000 ways, varying every modelling choice, and report the range instead of a single
              rank.
            </p>
            <div className="methods-metrics">
              <Metric label="Median range" value="312" unit="of 500" />
            </div>
          </article>

          <article className={`methods-card ${index === 'paris' ? 'active' : ''}`}>
            <span className="methods-eyebrow">Paris index</span>
            <p>
              The rules are read from EU Regulation 2020/1818, article by article. We compute the
              index here, and it is not a registered benchmark.
            </p>
            <div className="methods-metrics">
              <Metric label="Barred" value="67" unit="of 499" />
              <Metric label="Intensity cut" value="63.1%" unit="Article 11 asks 50%" />
            </div>
          </article>
        </div>
      </section>

      <section className="methods-block narrow">
        <div className="section-heading">
          <h3>What decides a company's place</h3>
          <span>Sobol share of rank variance</span>
        </div>
        <div className="methods-bars">
          {SOBOL.map((d, i) => (
            <div className="methods-bar-row" key={d.label}>
              <span className="methods-bar-label">{d.label}</span>
              <span className="methods-bar-track">
                <span
                  className={`methods-bar-fill ${i === 0 ? 'lead' : ''}`}
                  style={{ width: `${(d.share / SOBOL_AXIS) * 100}%` }}
                />
              </span>
              <span className="methods-bar-value">{d.share}%</span>
            </div>
          ))}
        </div>
        <p className="methods-note">
          Changing the weights moves a company about six places. Changing what we assume about
          non-reporters moves it twenty.
        </p>
      </section>

      <section className="methods-block narrow">
        <div className="section-heading">
          <h3>Mandatory filings</h3>
        </div>
        <div className="methods-split" role="img" aria-label={`${MEASURED} of ${UNIVERSE} companies report an emissions number`}>
          <span className="methods-split-known" style={{ width: `${(MEASURED / UNIVERSE) * 100}%` }} />
          <span className="methods-split-blank" style={{ width: `${(UNSCORED / UNIVERSE) * 100}%` }} />
        </div>
        <div className="methods-legend">
          <span><i className="known" />{MEASURED} file a number</span>
          <span><i className="blank" />{UNSCORED} file none, left unscored rather than guessed</span>
        </div>
      </section>

      <p className="micro">Source: EUR-Lex, © European Union, 1998-2026.</p>
    </div>
  );
}
