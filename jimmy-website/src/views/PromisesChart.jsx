import React from 'react';
import { Info } from 'lucide-react';
import { fmt, logoTicker } from '../utils/formatters';

export function CompanyChart({ rows, onSelect }) {
  const plotted = rows.filter(
    r => r.promised_pct_yr != null && r.delivered_pct_yr != null && r.gap_pct_yr != null
  );
  const points = plotted.map(r => ({
    ...r,
    promisedCut: -r.promised_pct_yr,
    measuredCut: -r.delivered_pct_yr
  }));
  const xMin = 0,
    xMax = Math.max(30, ...points.map(r => r.promisedCut)) + 2,
    yMin = Math.min(-12, ...points.map(r => r.measuredCut)) - 2,
    yMax = Math.max(30, ...points.map(r => r.measuredCut)) + 2;
  const symlog = v => Math.sign(v) * Math.log1p(Math.abs(v) / 2),
    xTransform = v => Math.log1p(Math.max(0, v) / 2);
  const x = v => 72 + (xTransform(v) / xTransform(xMax)) * 650,
    y = v => 338 - ((symlog(v) - symlog(yMin)) / (symlog(yMax) - symlog(yMin))) * 286;
  const ticks = [-40, -20, -10, -5, 0, 5, 10, 20, 40].filter(v => v >= yMin && v <= yMax);
  const xTicks = [0, 2, 5, 10, 20, 30].filter(v => v <= xMax);
  const equalityMax = Math.min(xMax, yMax),
    equalityPath = Array.from({ length: 41 }, (_, i) => {
      const v = (equalityMax * i) / 40;
      return `${i ? 'L' : 'M'}${x(v)},${y(v)}`;
    }).join(' ');
  const emissionLogs = points.map(r => Math.log10(Math.max(1, r.scope1_t || 1))),
    logMin = Math.min(...emissionLogs),
    logMax = Math.max(...emissionLogs);
  const displayPoints = points.map((r, i) => {
    const radius = 5.5 + ((emissionLogs[i] - logMin) / Math.max(1, logMax - logMin)) * 3;
    return {
      ...r,
      ax: x(r.promisedCut),
      ay: y(r.measuredCut),
      cx: x(r.promisedCut) + ((i % 7) - 3) * 0.25,
      cy: y(r.measuredCut) + ((i % 5) - 2) * 0.25,
      radius
    };
  });
  for (let iteration = 0; iteration < 180; iteration++) {
    for (let i = 0; i < displayPoints.length; i++)
      for (let j = i + 1; j < displayPoints.length; j++) {
        const a = displayPoints[i],
          b = displayPoints[j],
          dx = b.cx - a.cx,
          dy = b.cy - a.cy,
          d = Math.hypot(dx, dy) || 0.01,
          minD = a.radius + b.radius + 2;
        if (d < minD) {
          const push = (minD - d) * 0.28,
            nx = dx / d,
            ny = dy / d;
          a.cx -= nx * push;
          a.cy -= ny * push;
          b.cx += nx * push;
          b.cy += ny * push;
        }
      }
    for (const p of displayPoints) {
      p.cx += (p.ax - p.cx) * 0.006;
      p.cy += (p.ay - p.cy) * 0.006;
      p.cx = Math.max(74 + p.radius, Math.min(720 - p.radius, p.cx));
      p.cy = Math.max(44 + p.radius, Math.min(336 - p.radius, p.cy));
    }
  }

  return (
    <div className="scatter-wrap">
      <div className="section-heading">
        <div>
          <h3>Are companies cutting emissions as fast as promised?</h3>
          <p className="subtle">Both axes show reduction rates. Higher means a faster annual emissions cut.</p>
        </div>
        <span>{plotted.length} comparable records</span>
      </div>
      <div className="progress-legend">
        <span className="ahead">
          <i />Ahead of promise
        </span>
        <span className="behind">
          <i />Behind promise
        </span>
        <span><b>0%</b> = no change · below 0% = emissions rising</span>
      </div>
      <svg
        viewBox="0 0 790 410"
        role="img"
        aria-label="Company promised emissions reduction versus measured emissions reduction"
      >
        <rect x="72" y="42" width="650" height={y(0) - 42} fill="#eef6f0" />
        <rect x="72" y={y(0)} width="650" height={338 - y(0)} fill="#fcf2ec" />
        {xTicks.map(v => (
          <g key={`x${v}`}>
            <line x1={x(v)} y1="42" x2={x(v)} y2="338" stroke="#dfe7e3" />
            <text x={x(v)} y="361" textAnchor="middle">
              {v}%
            </text>
          </g>
        ))}
        {ticks.map(v => (
          <g key={`y${v}`}>
            <line
              x1="72"
              y1={y(v)}
              x2="722"
              y2={y(v)}
              stroke={v === 0 ? '#9aaaa5' : '#dfe7e3'}
              strokeWidth={v === 0 ? 1.5 : 1}
            />
            <text x="58" y={y(v) + 4} textAnchor="end">
              {v}%
            </text>
          </g>
        ))}
        <path d={equalityPath} fill="none" stroke="#60756d" strokeWidth="1.5" strokeDasharray="6 5" />
        <text className="zone-label ahead" x="105" y="60">
          FASTER REDUCTIONS
        </text>
        <text className="zone-label behind" x="530" y="324">
          EMISSIONS INCREASING
        </text>
        {displayPoints.map(r => {
          const clip = `logo-${r.ticker.replace(/[^a-zA-Z0-9]/g, '')}`,
            shift = Math.hypot(r.cx - r.ax, r.cy - r.ay),
            inner = r.radius * 2 - 3;
          return (
            <g
              className="company-point"
              key={r.ticker}
              tabIndex="0"
              role="button"
              aria-label={`Inspect ${r.company_name}. Promised reduction ${fmt(r.promisedCut, 1)} percent per year; measured reduction ${fmt(r.measuredCut, 1)} percent per year.`}
              onClick={() => onSelect(r)}
              onKeyDown={ev => {
                if (ev.key === 'Enter' || ev.key === ' ') {
                  ev.preventDefault();
                  onSelect(r);
                }
              }}
            >
              {shift > 3 && <line className="point-leader" x1={r.ax} y1={r.ay} x2={r.cx} y2={r.cy} />}
              <circle className="true-position" cx={r.ax} cy={r.ay} r="1.7" />
              <defs>
                <clipPath id={clip}>
                  <circle cx={r.cx} cy={r.cy} r={r.radius - 1} />
                </clipPath>
              </defs>
              <circle
                className={r.gap_pct_yr > 0 ? 'point-ring behind' : 'point-ring ahead'}
                cx={r.cx}
                cy={r.cy}
                r={r.radius + 1.5}
              />
              <circle cx={r.cx} cy={r.cy} r={r.radius - 1} fill="#fff" />
              <text className="point-fallback" x={r.cx} y={r.cy + 2.5} textAnchor="middle">
                {r.ticker.slice(0, 3)}
              </text>
              <image
                href={`https://images.financialmodelingprep.com/symbol/${encodeURIComponent(logoTicker(r.ticker))}.png`}
                x={r.cx - (r.radius - 1)}
                y={r.cy - (r.radius - 1)}
                width={inner}
                height={inner}
                preserveAspectRatio="xMidYMid meet"
                clipPath={`url(#${clip})`}
                onError={ev => (ev.currentTarget.style.display = 'none')}
              />
              <title>
                {r.company_name}: promised cut {fmt(r.promisedCut, 1)}%/yr; measured cut {fmt(r.measuredCut, 1)}%/yr;{' '}
                {r.gap_pct_yr > 0
                  ? `${fmt(r.gap_pct_yr, 1)} pp/yr behind`
                  : `${fmt(Math.abs(r.gap_pct_yr), 1)} pp/yr ahead`}
                . Logo size reflects available Scope 1 emissions.
              </title>
            </g>
          );
        })}
        <text x="397" y="398" textAnchor="middle">
          Promised emissions reduction (% per year)
        </text>
        <text transform="translate(18 190) rotate(-90)" textAnchor="middle">
          Measured emissions reduction (% per year)
        </text>
      </svg>
      <p className="scale-note">
        <Info size={13} />
        <span>
          <strong>Expanded scale:</strong> spacing is nonlinear to separate the crowded low-rate range. Axis labels remain actual annual percentages.
        </span>
      </p>
      <p className="micro">
        Logo size reflects available Scope 1 emissions. Faint lines connect displaced logos to their exact values. The curved dashed line is the promised pace: above it is ahead; below it is behind.
      </p>
    </div>
  );
}

export function PromisesChartView({ companies, onSelect }) {
  return (
    <>
      <div className="finding-banner">
        <div className="finding-main">
          <span className="finding-badge">TARGET AUDIT</span>
          <p>
            <strong>Promises vs Measured Pace:</strong> 108 companies have both a usable reduction target and a measured Scope 1 trend. Above the dashed line means emissions are falling faster than promised; below it means the company is behind its promised pace. Below 0% means measured emissions increased.
          </p>
        </div>
        <div className="finding-metrics">
          <div className="finding-stat">
            <span>Audited With Targets</span>
            <strong>108 <small>companies</small></strong>
          </div>
          <div className="finding-stat alert">
            <span>Lagging Promised Pace</span>
            <strong>78% <small>84 of 108</small></strong>
          </div>
          <div className="finding-stat">
            <span>Average Shortfall</span>
            <strong>3.0 <small>pp / year</small></strong>
          </div>
        </div>
      </div>

      <div className="company-surface">
        <CompanyChart rows={companies} onSelect={onSelect} />
        <div className="notice">
          <Info size={16} />
          <p>
            Dots represent companies with verified targets and historical reporting windows. A positive gap indicates annual progress is trailing the pledged target rate.
          </p>
        </div>
      </div>
    </>
  );
}
