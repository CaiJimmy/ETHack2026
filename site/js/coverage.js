/* What we cannot see: coverage, disclosure bias, limitations, provenance.

   Coverage is a judged criterion, so it is built as a finding rather than an
   apology: the partition of the index is the first chart, and the reason the
   missing half is not random follows immediately after it.

   Everything numeric is read from the five JSON files, with one declared
   exception: DOC_FACTS below. Those figures live in the two audit documents
   under docs/ and nowhere in the JSON. Each carries the document it came from
   and both documents are linked from the page. */
(function () {
  'use strict';

  var F = window.FILED;
  var fmt = F.fmt;

  /* Figures that exist only in the audit documents. Kept in one place, each
     with its source, so nothing on the page is an unattributed number. */
  var DOC_FACTS = {
    trace_named:        { v: 73,    of: 503, src: 'coverage_and_validation.md, section 3' },
    trace_companies:    { v: 25,             src: 'coverage_and_validation.md, section 3' },
    us_mmt:             { v: 375.7,          src: 'coverage_and_validation.md, section 3' },
    nonus_mmt:          { v: 582.8,          src: 'coverage_and_validation.md, section 3' },
    visible_share:      { v: 0.39,           src: 'coverage_and_validation.md, section 3' },
    visible_share_adj:  { v: 0.73,           src: 'coverage_and_validation.md, section 3' },
    threshold_t:        { v: 25000,          src: '40 CFR Part 98, quoted in scores.json meta' },
    uncovered_sampled:  { v: 30,             src: 'entity_resolution_audit.md, recall' },
    uncovered_no_plant: { v: 25,             src: 'entity_resolution_audit.md, recall' },
    ghgrp_next_year:    { v: 2025,           src: 'coverage_and_validation.md, what is still missing' },
    ghgrp_next_due:     { s: '30 October 2026', src: 'coverage_and_validation.md, what is still missing' },
    scope3_total:       { v: 74,   of: 503,  src: 'coverage_and_validation.md, provenance table' },
    scope3_detail:      { v: 7,              src: 'coverage_and_validation.md, provenance table' },
    scope3_newest_fy:   { v: 2022,           src: 'coverage_and_validation.md, what is still missing' },
    survivors_gone:     { v: 62,   of: 503,  src: 'coverage_and_validation.md, what is still missing' },
    index_asof:         { s: '2023-08-30',   src: 'coverage_and_validation.md, what is still missing' },
    audit_correct:      { v: 49,             src: 'entity_resolution_audit.md, headline' },
    audit_sample:       { v: 50,             src: 'entity_resolution_audit.md, headline' },
    audit_precision:    { v: 0.98,           src: 'entity_resolution_audit.md, headline' },
    audit_ci:           { s: '89.5% to 99.6%', src: 'entity_resolution_audit.md, headline' },
    audit_tonnes_prec:  { v: 1.0,            src: 'entity_resolution_audit.md, headline' }
  };

  var DOC_COVERAGE = 'docs/coverage_and_validation.md';
  var DOC_AUDIT = 'docs/entity_resolution_audit.md';

  /* The register each indicator is read from. The JSON records the provenance
     class of every indicator but not the name of the register, so the names
     live here. No figure does. */
  var INDICATOR_SOURCE = {
    intensity: 'EPA GHGRP, 40 CFR Part 98, with SEC XBRL revenue',
    trend:     'EPA GHGRP, 40 CFR Part 98, 2010 to 2023',
    saydo:     'EPA GHGRP against the company’s own published target',
    ear:       'EPA GHGRP with SEC XBRL operating income, priced by NGFS',
    penalty:   'Good Jobs First violation tracker, 2000 to 2026'
  };
  var INDICATOR_LABEL = {
    intensity: 'Scope 1 intensity',
    trend:     'Emissions trend',
    saydo:     'Say-do gap',
    ear:       'Earnings at risk',
    penalty:   'Penalty record'
  };
  /* the same five, set to sit inside a sentence in the tooltip */
  var INDICATOR_SHORT = {
    intensity: 'intensity',
    trend:     'trend',
    saydo:     'say-do gap',
    ear:       'earnings at risk',
    penalty:   'penalties'
  };

  var CLASS_DESC = {
    mandatory: 'filed under legal penalty. The only class that scores.',
    voluntary: 'published because the company chose to. Never an input.',
    vendor:    'a commercial rating. Benchmark only, never an input.',
    modelled:  'estimated by us or by a third party. Never an input.'
  };

  F.onReady(function (D) {
    injectCss();
    var host = document.getElementById('coverage-body');
    if (!host) return;
    sectionHead(D);
    registerDrawer(D);
    host.innerHTML = '';
    host.appendChild(partitionPanel(D));
    host.appendChild(biasPanel(D));
    host.appendChild(examplePanel(D));
    host.appendChild(limitsPanel(D));
    host.appendChild(F.details('Where every number on this site comes from',
      '<b>' + fmt.int(D.scores.meta.indicators.length) + '</b> scored series, <b>7</b> reference series',
      provenancePanel(D)));
    wireWaffle(D);
    wireBiasCharts(D);
    wireLedgerFilter();
  });

  /* The heading carries the number, the reconciliation of the two counts a
     reader will otherwise trip over, and the three limits of the source. */
  function sectionHead(D) {
    var cov = D.scores.coverage.by_tier;
    var noMandatory = cov.reported + cov.unmeasurable;
    var t = document.getElementById('cov-title');
    var l = document.getElementById('cov-lede');
    if (t) t.textContent = fmt.int(noMandatory) + ' of ' + fmt.int(D.scores.meta.n_companies) +
      ' file no legally required emissions figure';
    if (l) l.innerHTML = 'We invent nothing for them. That is ' + fmt.int(cov.unmeasurable) +
      ' companies with no emissions number anywhere, plus ' + fmt.int(cov.reported) +
      ' whose only number is one they published themselves. What we do have is US ' +
      'facilities above 25 000 tonnes a year, and it stops at reporting year 2023.';
  }

  function registerDrawer(D) {
    F.drawer.add('tiers', 'The three coverage tiers',
      '<p>Every company sits in exactly one. A company we cannot measure is a declared ' +
      'state, never a zero and never a deletion.</p><dl>' +
      F.tierOrder.map(function (t) {
        return '<dt>' + F.tier(t).label + ' <span class="mono">' +
          fmt.int(D.scores.coverage.by_tier[t]) + '</span></dt><dd>' + F.tier(t).desc + '</dd>';
      }).join('') + '</dl>' +
      '<p>Two counts of the same idea run on this site and they are not the same number. ' +
      fmt.int(D.scores.coverage.by_tier.unmeasurable) + ' companies have no mandatory tonnage ' +
      'in the score. ' + fmt.int(D.scores.coverage.by_tier.reported +
      D.scores.coverage.by_tier.unmeasurable) + ' have none once the self-reporters are ' +
      'counted with them, which is the figure the fund uses. The control surface on screen ' +
      'one works on a third: the 181 that carry no Scope 1 figure from any source at all.</p>');

    F.drawer.add('classes', 'The four kinds of source',
      '<p>Only one of them is allowed to move a score.</p><dl>' +
      ['mandatory', 'voluntary', 'vendor', 'modelled'].map(function (c) {
        return '<dt>' + c + '</dt><dd>' + CLASS_DESC[c] + '</dd>';
      }).join('') + '</dl>');
  }

  /* ============================ 1. the partition ============================ */

  function partitionPanel(D) {
    var cov = D.scores.coverage;
    var cs = D.scores.companies;
    var n = cs.length;

    var panel = el('div', 'panel');
    panel.appendChild(head(
      'Three coverage tiers, and every company sits in one',
      'One cell per company, ordered by sector inside each tier. Hover a sector to find it in all three.',
      '<b>n = ' + fmt.int(n) + '</b> companies, ' + fmt.int(D.say_do.meta.n_listings) + ' listings'
    ));

    /* sector filter chips */
    var bySector = {};
    cs.forEach(function (c) {
      var s = bySector[c.s] || (bySector[c.s] = { n: 0, measured: 0, reported: 0, unmeasurable: 0 });
      s.n++; s[c.tier]++;
    });
    var sectors = Object.keys(bySector).sort(function (a, b) { return bySector[b].n - bySector[a].n; });

    var bar = el('div', 'cv-secbar');
    sectors.forEach(function (s) {
      var chip = el('span', 'cv-sec');
      chip.dataset.sector = s;
      chip.innerHTML = s + '<b>' + fmt.int(bySector[s].n) + '</b>';
      bar.appendChild(chip);
    });
    panel.appendChild(bar);

    var line = el('div', 'cv-secline');
    line.id = 'cv-secline';
    line.textContent = 'Utilities are almost entirely measured. Financials are almost entirely not.';
    panel.appendChild(line);

    /* the waffle: one row group per tier, cells in sector order */
    var waffle = el('div', 'cv-waffle');
    waffle.id = 'cv-waffle';
    F.tierOrder.forEach(function (t) {
      var tier = F.tier(t);
      var rows = cs.filter(function (c) { return c.tier === t; })
        .sort(function (a, b) {
          return a.s === b.s ? (a.t < b.t ? -1 : 1) : (bySector[b.s].n - bySector[a.s].n);
        });

      var grp = el('div', 'cv-tier');
      grp.style.borderLeftColor = tier.css;
      var lab = el('div', 'cv-tier-h');
      lab.innerHTML =
        '<span class="cv-tier-n mono">' + fmt.int(rows.length) + '</span>' +
        '<span class="cv-tier-k">' + tier.label + '</span>' +
        '<span class="cv-tier-p mono">' + fmt.share(rows.length / n, 1) + ' of the index</span>' +
        '<span class="cv-tier-d">' + tier.desc + '</span>';
      grp.appendChild(lab);

      var cells = el('div', 'cv-cells');
      cells.dataset.tier = t;
      rows.forEach(function (c) {
        var cell = el('span', 'cv-cell');
        cell.style.background = tier.css;
        cell.dataset.t = c.t;
        cell.dataset.sector = c.s;
        cells.appendChild(cell);
      });
      grp.appendChild(cells);
      waffle.appendChild(grp);
    });
    panel.appendChild(waffle);

    /* indicator coverage, the same 500 companies seen indicator by indicator */
    var sub = el('div', 'cv-subhead');
    sub.innerHTML = 'What we hold, indicator by indicator' +
      '<span>Every indicator is mandatory. A company missing one is carried as missing, never as a zero.</span>';
    panel.appendChild(sub);

    var inds = el('div', 'cv-inds');
    D.scores.meta.indicators.forEach(function (ind) {
      var k = cov.by_indicator[ind.key];
      var row = el('div', 'cv-ind');
      row.innerHTML =
        '<div class="cv-ind-k">' + (INDICATOR_LABEL[ind.key] || ind.key) + '</div>' +
        '<div class="cv-bar"><span style="width:' + (k / n * 100).toFixed(2) + '%"></span></div>' +
        '<div class="cv-ind-n mono">' + fmt.int(k) + '<span class="u-dim"> / ' + fmt.int(n) + '</span></div>' +
        '<div class="cv-ind-d">' + ind.description + '</div>';
      inds.appendChild(row);
    });
    panel.appendChild(inds);

    var pill = el('div', 'cv-pillnote');
    pill.innerHTML =
      '<span class="mono">' + fmt.int(cov.all_four_pillars) + '</span> companies carry all four pillars. ' +
      '<span class="mono">' + fmt.int(cov.one_pillar_only) + '</span> carry one only, which is the penalty ' +
      'record every listed company files. That imbalance is why a single rank cannot be defended, and it is ' +
      'the reason we publish an interval rather than a rank.';
    panel.appendChild(pill);

    panel.appendChild(note(D.scores.meta.coverage_note
      .replace('coverage_tier unmeasurable', 'the not-measurable tier')));
    panel.appendChild(el2('div', 'u-mt4', F.drawer.linkHTML('tiers',
      'Three different counts of what we cannot measure appear on this site. ' +
      'Here is how 181, 273 and ' + fmt.int(D.scores.coverage.by_tier.reported +
      D.scores.coverage.by_tier.unmeasurable) + ' relate.')));
    panel.appendChild(prov('scores.json', 'coverage.by_tier, coverage.by_indicator', 'mandatory'));
    return panel;
  }

  /* the tooltip body shared by the waffle and the two scatters */
  function companyTip(D, ticker) {
    var sc = F.index.scores[ticker];
    if (!sc) return '<div class="tip-t">' + ticker + '</div>';
    var tier = F.tier(sc.tier);
    var held = [], missing = [];
    D.scores.meta.indicators.forEach(function (ind) {
      (sc[ind.key] === null || sc[ind.key] === undefined ? missing : held)
        .push(INDICATOR_SHORT[ind.key] || ind.key);
    });
    var bp = biasPoint(D, ticker);
    return '<div class="tip-t">' + sc.t + '</div>' +
      '<div>' + sc.n + '</div>' +
      '<div class="u-dim">' + sc.s + '</div>' +
      '<div style="margin-top:6px;color:' + tier.css + '">' + tier.label + ': ' + tier.desc + '</div>' +
      '<div style="margin-top:6px">Holds ' + held.length + ' of ' +
        D.scores.meta.indicators.length + ': ' + held.join(', ') + '</div>' +
      (missing.length
        ? '<div class="u-dim">Missing: ' + missing.join(', ') + '</div>' : '') +
      (bp ? '<div class="u-dim">Voluntary checklist: ' + bp.nd + ' of ' +
        D.bias.components.length + ' items filed</div>' : '') +
      '<div style="margin-top:6px">Rank band <span class="mono">' + fmt.int(sc.p05) + '–' +
        fmt.int(sc.p95) + '</span>, median <span class="mono">' + fmt.int(sc.med) + '</span></div>';
  }

  function biasPoint(D, ticker) {
    if (!D._biasIx) {
      D._biasIx = {};
      D.bias.points.forEach(function (p) { D._biasIx[p.t] = p; });
    }
    return D._biasIx[ticker] || null;
  }

  function wireWaffle(D) {
    var waffle = document.getElementById('cv-waffle');
    var line = document.getElementById('cv-secline');
    if (!waffle) return;
    var cells = [].slice.call(waffle.querySelectorAll('.cv-cell'));
    var groups = [].slice.call(waffle.querySelectorAll('.cv-cells'));
    var pinned = null;

    waffle.addEventListener('mouseover', function (ev) {
      var cell = ev.target.closest ? ev.target.closest('.cv-cell') : null;
      if (!cell) return;
      F.tip.show(companyTip(D, cell.dataset.t), ev);
    });
    waffle.addEventListener('mousemove', function (ev) { F.tip.move(ev); });
    waffle.addEventListener('mouseout', function (ev) {
      if (ev.target.classList && ev.target.classList.contains('cv-cell')) F.tip.hide();
    });

    function applyFilter(sector) {
      groups.forEach(function (g) { g.classList.toggle('is-filtered', !!sector); });
      cells.forEach(function (c) {
        c.classList.toggle('is-on', !!sector && c.dataset.sector === sector);
      });
      document.querySelectorAll('.cv-sec').forEach(function (chip) {
        chip.classList.toggle('is-on', chip.dataset.sector === sector);
      });
      if (!sector) {
        line.textContent = 'Utilities are almost entirely measured. Financials are almost entirely not.';
        return;
      }
      var c = { measured: 0, reported: 0, unmeasurable: 0, n: 0 };
      D.scores.companies.forEach(function (x) { if (x.s === sector) { c.n++; c[x.tier]++; } });
      line.innerHTML = '<b>' + sector + '</b>, ' + fmt.int(c.n) + ' companies: ' +
        '<span class="u-cool mono">' + fmt.int(c.measured) + '</span> measured, ' +
        '<span class="mono" style="color:var(--tier-reported)">' + fmt.int(c.reported) + '</span> reported, ' +
        '<span class="u-muted mono">' + fmt.int(c.unmeasurable) + '</span> not measurable.';
    }

    document.querySelectorAll('.cv-sec').forEach(function (chip) {
      chip.addEventListener('mouseenter', function () {
        if (!pinned) applyFilter(chip.dataset.sector);
      });
      chip.addEventListener('mouseleave', function () {
        if (!pinned) applyFilter(null);
      });
      chip.addEventListener('click', function () {
        pinned = pinned === chip.dataset.sector ? null : chip.dataset.sector;
        applyFilter(pinned);
      });
    });

    /* same escape hatch as the say-do card, so a pinned sector is never a trap */
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && pinned) { pinned = null; applyFilter(null); }
    });
  }

  /* ========================== 2. the disclosure bias ========================= */

  function biasPanel(D) {
    var spec = D.bias.chart;
    var panel = el('div', 'panel');
    panel.id = 'cv-bias';
    panel.appendChild(head(
      spec.title,
      /* GICS is the sector classification; the reader needs the sector, not its vendor */
      spec.subtitle.replace('own GICS sector mean', 'own sector average'),
      '<b>n = ' + fmt.int(spec.panels[0].annotation.n) + '</b> rated, <b>' +
        fmt.int(spec.panels[1].annotation.n) + '</b> measured'
    ));

    var two = el('div', 'cv-two');
    spec.panels.forEach(function (p, i) {
      var col = el('div', 'cv-col');
      col.innerHTML =
        '<div class="cv-col-h" style="border-top-color:' + (i === 0 ? 'var(--accent)' : 'var(--cool)') + '">' +
          '<div class="cv-col-t">' + p.label + '</div>' +
          '<div class="cv-col-s">' + p.y.label + '</div>' +
        '</div>';
      var host = el('div', 'cv-chart');
      host.id = 'cv-chart-' + p.key;
      col.appendChild(host);
      col.appendChild(el2('div', 'cv-read', i === 0
        ? 'Filing the whole checklist instead of none of it is worth ' +
          fmt.signed(p.annotation.beta, 1) + ' percentile points of vendor standing, inside the ' +
          'company’s own sector.'
        : 'The same move is worth ' + fmt.signed(p.annotation.beta, 1) + ' points in ours, which is not ' +
          'distinguishable from zero. Nothing here is bought by filing.'));
      col.appendChild(el2('div', 'cv-reg u-mt4', F.detailsHTML('The regression', '',
        statLine(p.annotation, i === 0).outerHTML)));
      two.appendChild(col);
    });
    panel.appendChild(two);
    panel.appendChild(el2('div', 'cv-caption',
      'Coverage is a count out of ' + D.bias.components.length + ' items, so the points stand in ' +
      'columns. Both panels share one vertical scale. ' + fmt.int(D.bias.counts.disclose_nothing) +
      ' companies file none of the checklist and sit on the left edge.'));

    panel.appendChild(chain(D));

    var defence = '<div class="note">' + D.bias.note + '</div>' +
      '<div class="note u-mt4">Reported as it ran. The vendor consensus does not load on ' +
      'market cap directly either: ' + regText(D, '1') + '. The mechanism is disclosure, ' +
      'not size, and with both terms in one model size turns negative and insignificant ' +
      '(t = ' + fmt.num(D.bias.multivariate.t_log_market_cap, 2) + ') while disclosure holds ' +
      '(t = ' + fmt.num(D.bias.multivariate.t_disclosure_coverage, 2) + ', n = ' +
      fmt.int(D.bias.multivariate.n) + ').</div>' +
      '<div class="note u-mt4">The benchmark is not six independent raters. Three of the six ' +
      'public sources are re-uploads of one dead pull, one is generated by a language model, ' +
      'and one appears to measure disclosure volume rather than performance. The disagreement ' +
      'survives all of that. Any claim about one vendor’s method does not.</div>' +
      '<ul class="note-list u-mt4">' + D.bias.citations.map(function (c) {
        return '<li>' + c.text + '</li>';
      }).join('') + '</ul>';
    panel.appendChild(el2('div', 'u-mt4', F.detailsHTML(
      'What we checked before publishing this', '4 notes', defence)));

    panel.appendChild(prov('bias.json', 'regressions A, B, 1, 7 and multivariate, ' +
      fmt.int(D.bias.bootstrap_draws) + ' bootstrap draws', 'voluntary and vendor material, tested, never scored'));
    return panel;
  }

  function statLine(a, isAccent) {
    var d = el('div', 'cv-stats mono');
    d.innerHTML =
      '<span class="' + (isAccent ? 'u-accent' : 'u-cool') + '">β ' + fmt.signed(a.beta, 1) + '</span>' +
      '<span>t ' + fmt.signed(a.t, 2) + '</span>' +
      '<span>' + pval(a.p) + '</span>' +
      '<span>R² ' + fmt.num(a.r2, 3) + '</span>' +
      '<span>n ' + fmt.int(a.n) + '</span>';
    return d;
  }

  function pval(p) {
    return p < 0.0001 ? 'p < 0.0001' : 'p ' + fmt.num(p, 3);
  }

  function reg(D, id) {
    var out = null;
    D.bias.regressions.forEach(function (r) { if (r.id === id) out = r; });
    return out;
  }

  function regText(D, id) {
    var r = reg(D, id);
    return 'β ' + fmt.signed(r.beta, 2) + ', t ' + fmt.signed(r.t, 2) +
      ', R² ' + fmt.num(r.r2, 4) + ', n ' + fmt.int(r.n);
  }

  /* size buys disclosure, disclosure buys the rating, and buys nothing in ours */
  function chain(D) {
    var r7 = reg(D, '7'), rA = reg(D, 'A'), rB = reg(D, 'B');
    var wrap = el('div', 'cv-chain');
    wrap.innerHTML =
      '<div class="cv-chain-h">The mechanism is a chain, not a size effect</div>' +
      '<div class="cv-chain-row">' +
        node('Market cap', 'how big the company is') +
        arrow(r7, 'checklist items per 10&times; of market cap', 3) +
        node('Voluntary disclosure', D.bias.components.length + '-item checklist') +
        '<div class="cv-forks">' +
          '<div class="cv-fork">' + arrow(rA, 'percentile points, within sector', 1) +
            node('Vendor ESG rating', 'what the market reads', 'accent') + '</div>' +
          '<div class="cv-fork">' + arrow(rB, 'points, within sector', 1) +
            node('Our score', 'measured tonnes per $m', 'cool') + '</div>' +
        '</div>' +
      '</div>';
    return wrap;
  }

  function sub10() { return '<sub>10</sub>'; }

  function node(t, s, tone) {
    return '<div class="cv-node' + (tone ? ' is-' + tone : '') + '">' +
      '<div class="cv-node-t">' + t + '</div><div class="cv-node-s">' + s + '</div></div>';
  }

  function arrow(r, unit, dec) {
    var sig = r.p < 0.05;
    return '<div class="cv-arrowbox' + (sig ? '' : ' is-null') + '">' +
      '<div class="cv-arrow-v mono">' + fmt.signed(r.beta, dec) + '</div>' +
      '<div class="cv-arrow-l">' + unit + '</div>' +
      '<div class="cv-arrow-line"></div>' +
      /* the verdict in words first, then the statistic it rests on. A bare
         "t +6.89" is the same species of jargon as a Sobol index. */
      '<div class="cv-arrow-s mono">' + (r.p < 0.05 ? 'holds up' : 'not distinguishable from zero') +
        ' · t ' + fmt.signed(r.t, 2) + ' · n ' + fmt.int(r.n) + '</div>' +
      '</div>';
  }

  /* ---- the two scatters ---- */

  function wireBiasCharts(D) {
    drawBias(D);
    var t = null;
    window.addEventListener('resize', function () {
      clearTimeout(t);
      t = setTimeout(function () { drawBias(D); }, 180);
    });
  }

  function drawBias(D) {
    var spec = D.bias.chart;
    /* one y domain for both panels, so the eye can compare the slopes */
    var lim = 0;
    spec.panels.forEach(function (p) {
      D.bias.points.forEach(function (pt) {
        var v = pt[p.y.field];
        if (v !== null && v !== undefined) lim = Math.max(lim, Math.abs(v));
      });
    });
    lim = Math.ceil(lim / 10) * 10;
    spec.panels.forEach(function (p, i) {
      drawBiasPanel(D, p, lim, i === 0 ? 'var(--accent)' : 'var(--cool)');
    });
  }

  function drawBiasPanel(D, p, lim, colour) {
    var host = document.getElementById('cv-chart-' + p.key);
    if (!host) return;
    host.innerHTML = '';

    var W = Math.max(260, host.clientWidth || 450);
    var H = 288;
    var M = { t: 12, r: 10, b: 52, l: W < 360 ? 40 : 58 };
    var px0 = M.l, px1 = W - M.r, py0 = H - M.b, py1 = M.t;

    var x = F.scale([0, 1], [px0, px1]);
    var y = F.scale([-lim, lim], [py0, py1]);

    var svg = F.svg('svg', {
      width: W, height: H, role: 'img',
      'aria-label': p.label + ' against disclosure coverage, n = ' + p.annotation.n
    });
    svg.appendChild(F.svg('rect', {
      x: px0, y: py1, width: px1 - px0, height: py0 - py1, fill: 'var(--bg-sunk)'
    }));

    F.axisY(svg, y, {
      x: px0, ticks: 5, grid: [px0, px1],
      fmt: function (v) { return fmt.signed(v, 0); },
      label: 'points from the sector mean', labelX: 13
    });
    F.axisX(svg, x, {
      y: py0, values: [0, 0.25, 0.5, 0.75, 1],
      fmt: function (v) { return fmt.num(v * 100, 0) + '%'; },
      label: D.bias.chart.x.label
    });

    /* the sector mean itself. The zero tick and the y label name it, so the
       line carries no text of its own and never lands on top of the fit. */
    svg.appendChild(F.svg('line', {
      class: 'ref-line', x1: px0, x2: px1, y1: y(0).toFixed(1), y2: y(0).toFixed(1)
    }));

    var pts = D.bias.points.filter(function (pt) {
      var v = pt[p.y.field];
      return v !== null && v !== undefined && pt[D.bias.chart.x.field] !== null;
    });

    var g = F.svg('g', {});
    svg.appendChild(g);
    var named = [];
    pts.forEach(function (pt) {
      var cx = x(pt[D.bias.chart.x.field]);
      var cy = y(Math.max(-lim, Math.min(lim, pt[p.y.field])));
      var isNamed = pt.t === 'BA' || pt.t === 'MLM';
      var c = F.svg('circle', {
        cx: cx.toFixed(1), cy: cy.toFixed(1), r: isNamed ? 5 : 2.7,
        fill: isNamed ? colour : colour,
        'fill-opacity': isNamed ? 1 : 0.42,
        stroke: isNamed ? 'var(--ink)' : 'none',
        'stroke-width': isNamed ? 1.4 : 0
      });
      c.style.cursor = 'pointer';
      c.addEventListener('mouseenter', function (ev) { F.tip.show(companyTip(D, pt.t), ev); });
      c.addEventListener('mousemove', function (ev) { F.tip.move(ev); });
      c.addEventListener('mouseleave', function () { F.tip.hide(); });
      g.appendChild(c);
      if (isNamed) named.push({ t: pt.t, x: cx, y: cy });
    });

    /* the fitted line, over the full checklist range */
    var f = p.fit;
    svg.appendChild(F.svg('line', {
      x1: x(0).toFixed(1), y1: y(clamp(f.intercept, lim)).toFixed(1),
      x2: x(1).toFixed(1), y2: y(clamp(f.intercept + f.slope, lim)).toFixed(1),
      stroke: colour, 'stroke-width': 2.5
    }));

    named.forEach(function (nm) {
      svg.appendChild(F.svg('text', {
        x: (nm.x + 9).toFixed(1), y: (nm.y + 4).toFixed(1),
        class: 'pt-label', text: nm.t
      }));
    });

    host.appendChild(svg);
  }

  function clamp(v, lim) { return Math.max(-lim, Math.min(lim, v)); }

  /* ========================= 3. the two named companies ===================== */

  function examplePanel(D) {
    var A = biasPoint(D, 'BA'), B = biasPoint(D, 'MLM');
    var panel = el('div', 'panel');
    panel.appendChild(head(
      'What that buys, on two companies',
      'The EPA measures both of them, so both are scored on filed tonnes. Only one of them files the paperwork.',
      '<b>n = 2</b> of ' + fmt.int(D.bias.counts.with_measured_intensity) + ' with a measured intensity'
    ));

    var grid = el('div', 'cv-two');
    grid.appendChild(exCard(D, A, 'accent'));
    grid.appendChild(exCard(D, B, 'cool'));
    panel.appendChild(grid);

    var ratio = B.intensity / A.intensity;
    panel.appendChild(note(
      F.index.scores.BA.n + ' files ' + fmt.int(A.nd) + ' of the ' + D.bias.components.length +
      ' voluntary checklist items and emits ' + fmt.num(ratio, 0) + ' times less per dollar of revenue than ' +
      F.index.scores.MLM.n + ', which files ' + fmt.int(B.nd) + ' of them. The vendor consensus puts ' +
      F.index.scores.MLM.n + ' ' + fmt.num(B.vendor - A.vendor, 1) + ' percentile points above ' +
      F.index.scores.BA.n + '. On measured tonnes the order reverses by ' +
      fmt.num(A.ours - B.ours, 1) + ' points.'));
    panel.appendChild(prov('bias.json', 'points[BA], points[MLM]',
      'measured intensity mandatory, checklist voluntary, percentile vendor'));
    return panel;
  }

  function exCard(D, p, tone) {
    var sc = F.index.scores[p.t];
    var ea = F.index.ear[p.t];
    var card = el('div', 'cv-ex is-' + tone);
    var boxes = '';
    for (var i = 0; i < D.bias.components.length; i++) {
      boxes += '<span class="cv-box' + (i < p.nd ? ' is-on' : '') + '"></span>';
    }
    card.innerHTML =
      '<div class="cv-ex-h">' +
        '<div class="cv-ex-t mono">' + p.t + '</div>' +
        '<div class="cv-ex-n">' + sc.n + '</div>' +
        '<div class="card-meta"><span class="chip chip--' + p.tier + '">' + F.tier(p.tier).label +
          '</span><span class="card-sector">' + p.s + '</span></div>' +
      '</div>' +
      '<div class="cv-ex-checklist">' +
        '<div class="cv-ex-k">Voluntary disclosure checklist</div>' +
        '<div class="cv-boxes">' + boxes + '</div>' +
        '<div class="cv-ex-sub mono">' + fmt.int(p.nd) + ' of ' + D.bias.components.length +
          ' filed · ' + fmt.share(p.cov, 0) + '</div>' +
      '</div>' +
      '<div class="cv-ex-rows">' +
        exRow('Vendor ESG percentile', fmt.num(p.vendor, 1),
              fmt.signed(p.vendor_rel, 1) + ' vs its sector') +
        exRow('Measured Scope 1 intensity', fmt.num(p.intensity, 2) + ' <small>t / $m</small>',
              'EPA GHGRP ' + (ea && ea.emissions_year ? ea.emissions_year : '') +
              ', SEC revenue') +
        exRow('Our measured intensity percentile', fmt.num(p.ours, 1),
              'cleaner than ' + fmt.num(p.ours, 0) + '% of the ' +
              fmt.int(D.bias.counts.with_measured_intensity) + ' we can measure') +
        exRow('Rank band', fmt.int(sc.p05) + '–' + fmt.int(sc.p95),
              'median ' + fmt.int(sc.med) + ' of ' + fmt.int(D.scores.meta.n_companies)) +
      '</div>';
    return card;
  }

  function exRow(k, v, sub) {
    return '<div class="cv-ex-row">' +
      '<div class="cv-ex-rk">' + k + '</div>' +
      '<div class="cv-ex-rv mono">' + v + '</div>' +
      '<div class="cv-ex-rs">' + sub + '</div></div>';
  }

  /* ============================ 4. the limitations ========================== */

  function limitsPanel(D) {
    var ec = D.ear.coverage;
    var panel = el('div', 'panel');
    panel.appendChild(head(
      'Six things this score cannot see',
      'Named here rather than found later. Each one is sized.',
      '<b>' + fmt.int(D.say_do.meta.n_listings) + '</b> listings in scope'
    ));

    var items = [
      {
        fig: fmt.share(DOC_FACTS.visible_share.v, 0),
        unit: 'of their global Scope 1 is visible',
        t: 'US facilities only',
        p: 'EPA GHGRP is a US programme. Climate TRACE names an asset owner for ' +
           fmt.int(DOC_FACTS.trace_named.v) + ' of ' + fmt.int(DOC_FACTS.trace_named.of) +
           ' listings; the ' + fmt.int(DOC_FACTS.trace_companies.v) +
           ' holding at least a quarter million tonnes abroad file ' +
           fmt.num(DOC_FACTS.us_mmt.v, 1) + ' million tonnes with the EPA and carry ' +
           fmt.num(DOC_FACTS.nonus_mmt.v, 1) + ' million tonnes outside it. Remove the three names where the ' +
           'ownership layer cannot see US assets either and the visible share is ' +
           fmt.share(DOC_FACTS.visible_share_adj.v, 0) + '. A company whose plants sit abroad looks ' +
           'clean on this spine. That is a limit of the source, not a finding about the company.',
        src: DOC_FACTS.visible_share.src
      },
      {
        fig: fmt.int(DOC_FACTS.threshold_t.v),
        unit: 'tCO₂e per facility per year',
        t: 'The reporting threshold',
        p: 'Below it a facility files nothing, so a company of many small sites is invisible to the ' +
           'programme. That is coverage, not a join failure: of ' + fmt.int(DOC_FACTS.uncovered_sampled.v) +
           ' uncovered tickers the resolution audit sampled, ' + fmt.int(DOC_FACTS.uncovered_no_plant.v) +
           ' operate no US facility over the line and none were matching misses.',
        src: DOC_FACTS.threshold_t.src
      },
      {
        fig: fmt.int(ec.measured_emissions_year_2023 + ec.measured_emissions_year_older),
        unit: 'measured companies, ' + fmt.int(ec.measured_emissions_year_older) + ' on an older year',
        t: 'The EPA record stops at reporting year 2023',
        p: fmt.int(ec.measured_emissions_year_2023) + ' of the measured set are on 2023 and ' +
           fmt.int(ec.measured_emissions_year_older) + ' sit on an earlier year, the latest each one ' +
           'filed. Reporting year ' + DOC_FACTS.ghgrp_next_year.v + ' is not due until ' +
           DOC_FACTS.ghgrp_next_due.s + '. Stack monitors under CAMD are the only current mandatory ' +
           'feed and they see power generation only.',
        src: 'ear.json coverage, and ' + DOC_FACTS.ghgrp_next_year.src
      },
      {
        fig: fmt.int(DOC_FACTS.scope3_total.v),
        unit: 'of ' + fmt.int(DOC_FACTS.scope3_total.of) + ' publish a Scope 3 total',
        t: 'Scope 2 and 3 are voluntary, and labelled voluntary',
        p: 'None of those totals is newer than FY' + DOC_FACTS.scope3_newest_fy.v +
           ' and every filer draws the boundary differently, so they cannot be ranked. ' +
           fmt.int(DOC_FACTS.scope3_detail.v) + ' carry category detail. Scope 3 is the majority of most ' +
           'footprints and this score says almost nothing about it.',
        src: DOC_FACTS.scope3_total.src
      },
      {
        fig: fmt.int(DOC_FACTS.survivors_gone.v),
        unit: 'of ' + fmt.int(DOC_FACTS.survivors_gone.of) + ' tickers have left the index',
        t: 'Companies that left the index are counted, not corrected for',
        p: 'Today’s membership is applied to historical emissions. Of the tickers in the index on ' +
           DOC_FACTS.index_asof.s + ', ' + fmt.int(DOC_FACTS.survivors_gone.v) +
           ' are gone, and the departed set is energy-heavy, which flatters every trend on this site.',
        src: DOC_FACTS.survivors_gone.src
      },
      {
        fig: fmt.share(DOC_FACTS.audit_precision.v, 1),
        unit: 'precision, ' + fmt.int(DOC_FACTS.audit_correct.v) + ' of ' +
              fmt.int(DOC_FACTS.audit_sample.v) + ' hand-checked',
        t: 'Matching filings to companies is audited, not assumed',
        p: 'Facility filings name a parent string, not a ticker. A separate adversarial pass checked ' +
           fmt.int(DOC_FACTS.audit_sample.v) + ' matches by hand: 95% confidence interval ' +
           DOC_FACTS.audit_ci.s + ', and ' + fmt.share(DOC_FACTS.audit_tonnes_prec.v, 0) +
           ' precision once weighted by current-year tonnes, because the one bad row carries none. ' +
           'Every error found lives in years before 2023. ' +
           link(DOC_AUDIT, 'Read the audit') + '.',
        src: DOC_FACTS.audit_precision.src
      }
    ];

    /* Each limit is its own disclosure: the number and the name of the thing we
       cannot see stay on screen, and the paragraph that sizes it is one click
       down, verbatim. Nothing here is cut, because this is the part that must
       never be cut. */
    var list = el('div', 'cv-limits');
    items.forEach(function (it) {
      var row = el('details', 'cv-limit dd');
      row.innerHTML =
        '<summary>' +
          '<div class="cv-limit-f"><div class="cv-limit-fig mono">' + it.fig + '</div>' +
            '<div class="cv-limit-u">' + it.unit + '</div></div>' +
          '<div class="cv-limit-t">' + it.t + '</div>' +
        '</summary>' +
        '<div class="dd-body"><div class="cv-limit-p">' + it.p + '</div>' +
        '<div class="cv-limit-s mono">' + it.src + '</div></div>';
      list.appendChild(row);
    });
    panel.appendChild(list);

    panel.appendChild(el2('div', 'u-mt4', F.detailsHTML('What the whole score is not', '4 notes',
      '<div class="note">' + D.scores.meta.us_only_note + '</div>' +
      '<div class="note u-mt4">' + D.ear.meta.caveat + '</div>' +
      '<div class="note u-mt4">' +
      D.scores.meta.what_this_is_not.replace('revenue_exclusions.parquet',
        'a separate revenue table') + '</div>' +
      '<div class="note u-mt4">Figures on this panel that are not in the five JSON files are ' +
      'read from ' + link(DOC_COVERAGE, 'the coverage and validation audit') + ' and ' +
      link(DOC_AUDIT, 'the entity resolution audit') + ', both of which reproduce from the ' +
      'repo.</div>')));
    panel.appendChild(prov('scores.json, ear.json and the two audit documents',
      'meta.us_only_note, meta.what_this_is_not, ear coverage', 'mandatory and modelled'));
    return panel;
  }

  /* ========================== 5. the provenance ledger ====================== */

  function provenancePanel(D) {
    var cov = D.scores.coverage;
    var n = D.scores.meta.n_companies;
    var panel = el('div', 'panel');
    panel.id = 'cv-ledger';

    var rows = [];
    D.scores.meta.indicators.forEach(function (ind) {
      rows.push({
        k: INDICATOR_LABEL[ind.key] || ind.key,
        d: ind.description,
        src: INDICATOR_SOURCE[ind.key] || '',
        cls: ind.provenance_class,
        n: cov.by_indicator[ind.key],
        use: 'scored, pillar ' + ind.pillar
      });
    });
    rows.push({
      k: 'Vendor ESG consensus',
      d: 'percentile across six public ESG datasets',
      src: 'public vendor score datasets, pooled to one percentile',
      cls: 'vendor', n: D.bias.counts.with_vendor_score,
      use: 'benchmark and the bias test above'
    });
    rows.push({
      k: 'Disclosure checklist',
      d: D.bias.components.length + ' voluntary items: scopes, CDP, SBTi, targets, transition plan',
      src: 'company reports, CDP, SBTi, Net Zero Tracker, WBA',
      cls: 'voluntary', n: D.bias.points.length,
      use: 'the bias test above'
    });
    rows.push({
      k: 'Climate targets',
      d: 'the promised rate the say-do gap is measured against',
      src: 'Net Zero Tracker and SBTi',
      cls: 'voluntary', n: D.say_do.meta.n_promise,
      use: 'the say-do gap'
    });
    rows.push({
      k: 'Carbon price path',
      d: 'US carbon price path to 2050, ' + D.ear.meta.price_source.unit,
      src: D.ear.meta.price_source.dataset,
      cls: 'modelled', n: cov.by_indicator.ear,
      use: 'pricing earnings at risk'
    });
    rows.push({
      k: 'Climate TRACE ownership',
      d: 'satellite-derived asset emissions with an equity owner',
      src: 'Climate TRACE bulk sector packages',
      cls: 'modelled', n: DOC_FACTS.trace_named.v, of: DOC_FACTS.trace_named.of,
      use: 'sizing the non-US gap only'
    });
    rows.push({
      k: 'Benchmark rulebook',
      d: fmt.int(D.portfolio.rules_used.length) + ' rules encoded with article citations',
      src: 'Commission Delegated Regulation (EU) ' + euNum(D.portfolio.meta.regulation) +
        ', via EUR-Lex',
      cls: 'mandatory', n: D.portfolio.universe.n_companies,
      use: 'the $1bn fund'
    });

    panel.appendChild(head(
      'Where every number on this site comes from',
      'Four kinds of source. Only one of them is allowed to move a score.',
      '<b>' + fmt.int(D.scores.meta.indicators.length) + '</b> scored indicators, <b>' +
        fmt.int(rows.length - D.scores.meta.indicators.length) + '</b> reference series'
    ));

    var classes = ['mandatory', 'voluntary', 'vendor', 'modelled'];
    var filt = el('div', 'cv-filter');
    filt.innerHTML = '<span class="cv-filter-k">Filter by class</span>' +
      '<span class="cv-cls is-all is-on" data-cls="">all</span>' +
      classes.map(function (c) {
        return '<span class="cv-cls cv-cls-' + c + '" data-cls="' + c + '">' + c + '</span>';
      }).join('');
    panel.appendChild(filt);

    var tbl = el('table', 'tbl cv-ledger-tbl');
    tbl.innerHTML =
      '<thead><tr><th>Series</th><th>Source</th><th>Class</th><th>Companies</th><th>Used for</th></tr></thead>' +
      '<tbody>' + rows.map(function (r) {
        return '<tr data-cls="' + r.cls + '">' +
          '<td class="t-name"><b>' + r.k + '</b><div class="cv-led-d">' + r.d + '</div></td>' +
          '<td class="t-name cv-led-src">' + r.src + '</td>' +
          '<td><span class="cv-cls cv-cls-' + r.cls + '">' + r.cls + '</span></td>' +
          '<td class="cv-led-n">' + fmt.int(r.n) +
            '<span class="u-dim"> / ' + fmt.int(r.of || n) + '</span></td>' +
          '<td class="t-name cv-led-use">' + r.use + '</td>' +
          '</tr>';
      }).join('') + '</tbody>';
    /* every column stays: the source and class columns are the ledger */
    var tblWrap = el('div', 'scroll-x');
    tblWrap.appendChild(tbl);
    panel.appendChild(tblWrap);

    var legend = el('div', 'cv-classnotes');
    legend.innerHTML = classes.map(function (c) {
      return '<div class="cv-classnote"><span class="cv-cls cv-cls-' + c + '">' + c + '</span>' +
        '<span>' + CLASS_DESC[c] + '</span></div>';
    }).join('');
    panel.appendChild(legend);

    panel.appendChild(note(D.scores.meta.provenance_note + ' ' + D.bias.note));
    panel.appendChild(note(D.portfolio.meta.attribution + '. Carbon prices: ' +
      D.ear.meta.price_source.dataset + ', model ' + D.ear.meta.price_source.model + '.'));
    panel.appendChild(prov('scores.json, bias.json, ear.json, portfolio.json',
      'meta.indicators, meta.price_source, rules_used', 'this table is the index of every class'));
    return panel;
  }

  /* 32020R1818 is the CELEX id. The citation reads 2020/1818. */
  function euNum(celex) {
    var m = /^3(\d{4})R(\d{4})$/.exec(celex);
    return m ? m[1] + '/' + m[2] : celex;
  }

  function wireLedgerFilter() {
    var panel = document.getElementById('cv-ledger');
    if (!panel) return;
    var chips = [].slice.call(panel.querySelectorAll('.cv-filter .cv-cls'));
    var rows = [].slice.call(panel.querySelectorAll('tbody tr'));
    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        var want = chip.dataset.cls;
        chips.forEach(function (c) { c.classList.toggle('is-on', c === chip); });
        rows.forEach(function (r) {
          r.classList.toggle('is-off', !!want && r.dataset.cls !== want);
        });
      });
    });
  }

  /* ================================ helpers ================================ */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function el2(tag, cls, html) {
    var n = el(tag, cls);
    n.innerHTML = html;
    return n;
  }

  function head(title, sub, nHtml) {
    var h = el('div', 'panel-head');
    h.innerHTML = '<div><div class="panel-title">' + title + '</div>' +
      '<div class="panel-sub">' + sub + '</div></div>' +
      '<div class="panel-n">' + nHtml + '</div>';
    return h;
  }

  function note(text) {
    return el2('div', 'note u-mt4', text);
  }

  /* This used to print under every panel as a debug line. It is one disclosure
     per panel now, and the wording says what it is. */
  function prov(file, path, cls) {
    return el2('details', 'dd cv-prov-dd',
      '<summary><span class="dd-t">Source file and field</span></summary>' +
      '<div class="dd-body cv-prov">' +
      '<span class="cv-prov-k">source</span>' +
      '<span class="mono">' + file + '</span>' +
      '<span class="cv-prov-p">' + path + '</span>' +
      '<span class="cv-prov-c">' + cls + '</span>');
  }

  function link(href, text) {
    return '<a class="cv-link" href="' + href + '">' + text + '</a>';
  }

  /* ================================= styles =================================
     Scoped to this section. No shared token is redefined here; app.css stays
     the single palette. */

  function injectCss() {
    if (document.getElementById('cv-css')) return;
    var s = document.createElement('style');
    s.id = 'cv-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  var CSS = [
    /* sector filter */
    '.cv-secbar{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:var(--s3)}',
    '.cv-sec{font-family:var(--font-mono);font-size:13px;padding:3px 8px;border:1px solid var(--rule-2);',
    'color:var(--ink-3);white-space:nowrap;cursor:pointer;user-select:none}',
    '.cv-sec b{color:var(--ink-2);font-weight:600;margin-left:7px}',
    '.cv-sec:hover,.cv-sec.is-on{color:var(--ink);border-color:var(--ink-3);background:var(--bg-2)}',
    '.cv-secline{font-size:var(--fs-sm);color:var(--ink-3);min-height:24px;margin-bottom:var(--s3)}',
    '.cv-secline b{color:var(--ink);font-weight:600}',

    /* the waffle */
    '.cv-waffle{display:grid;gap:var(--s4)}',
    '.cv-tier{border-left:3px solid var(--rule-2);padding-left:var(--s3)}',
    '.cv-tier-h{display:flex;align-items:baseline;gap:var(--s3);flex-wrap:wrap;margin-bottom:7px}',
    '.cv-tier-n{font-size:30px;font-weight:600;line-height:1;letter-spacing:-0.02em}',
    '.cv-tier-k{font-size:var(--fs-sm);font-weight:600}',
    '.cv-tier-p{font-size:13px;color:var(--ink-2)}',
    '.cv-tier-d{font-size:13px;color:var(--ink-3)}',
    '.cv-cells{display:grid;grid-template-columns:repeat(60,1fr);gap:2px;align-content:start}',
    '.cv-cell{aspect-ratio:1;cursor:pointer;background:var(--muted)}',
    '.cv-cells.is-filtered .cv-cell{opacity:0.10}',
    '.cv-cells.is-filtered .cv-cell.is-on{opacity:1}',
    '.cv-cell:hover{outline:1px solid var(--ink);outline-offset:1px}',

    /* indicator coverage */
    '.cv-subhead{margin:var(--s5) 0 var(--s3) 0;padding-top:var(--s4);border-top:1px solid var(--rule);',
    'font-size:var(--fs-h3);font-weight:600}',
    '.cv-subhead span{display:block;font-size:var(--fs-sm);font-weight:400;color:var(--ink-3);margin-top:2px}',
    '.cv-inds{display:grid;gap:7px}',
    '.cv-ind{display:grid;grid-template-columns:168px 210px 104px 1fr;gap:var(--s4);align-items:center}',
    '.cv-ind-k{font-size:var(--fs-sm);font-weight:600}',
    '.cv-ind-n{font-size:var(--fs-sm)}',
    '.cv-ind-d{font-size:13px;color:var(--ink-3)}',
    '.cv-bar{height:9px;background:var(--bg-sunk);border:1px solid var(--rule)}',
    '.cv-bar>span{display:block;height:100%;background:var(--cool)}',
    '.cv-pillnote{margin-top:var(--s4);font-size:var(--fs-sm);color:var(--ink-2);max-width:92ch}',
    '.cv-pillnote .mono{color:var(--ink);font-weight:600}',

    /* two column charts and cards */
    '.cv-two{display:grid;grid-template-columns:1fr 1fr;gap:var(--s5);align-items:stretch}',
    '.cv-col-h{border-top:2px solid var(--rule-2);padding-top:var(--s2);margin-bottom:var(--s2)}',
    '.cv-col-t{font-size:var(--fs-sm);font-weight:600}',
    '.cv-col-s{font-size:13px;color:var(--ink-3)}',
    '.cv-chart{background:var(--bg-1)}',
    '.cv-stats{display:flex;gap:var(--s4);flex-wrap:wrap;font-size:var(--fs-sm);color:var(--ink-2);',
    'border-top:1px solid var(--rule);padding-top:var(--s2);margin-top:var(--s2)}',
    '.cv-read{font-size:var(--fs-sm);color:var(--ink-3);margin-top:var(--s2);line-height:1.45}',
    '.cv-caption{font-size:13px;color:var(--ink-3);margin-top:var(--s3);line-height:1.45}',

    /* mediation chain */
    '.cv-chain{margin-top:var(--s5);border-top:1px solid var(--rule);padding-top:var(--s4)}',
    '.cv-chain-h{font-size:var(--fs-sm);font-weight:600;margin-bottom:var(--s3)}',
    '.cv-chain-row{display:grid;grid-template-columns:auto 1fr auto 1.35fr;gap:var(--s3);align-items:center}',
    '.cv-node{border:1px solid var(--rule-2);background:var(--bg-2);padding:var(--s2) var(--s3);min-width:118px}',
    '.cv-node-t{font-size:var(--fs-sm);font-weight:600;white-space:nowrap}',
    '.cv-node-s{font-size:12px;color:var(--ink-3);white-space:nowrap}',
    '.cv-node.is-accent{border-color:var(--accent)}',
    '.cv-node.is-cool{border-color:var(--cool)}',
    '.cv-forks{display:grid;gap:var(--s2)}',
    '.cv-fork{display:grid;grid-template-columns:1fr auto;gap:var(--s3);align-items:center}',
    '.cv-arrowbox{text-align:center;min-width:120px}',
    '.cv-arrow-v{font-size:19px;font-weight:600;color:var(--ink)}',
    '.cv-arrow-l{font-size:12px;color:var(--ink-3);line-height:1.25}',
    '.cv-arrow-line{height:1px;background:var(--ink-3);margin:5px 0 4px 0;position:relative}',
    '.cv-arrow-line::after{content:"";position:absolute;right:0;top:-3px;border-left:6px solid var(--ink-3);',
    'border-top:3.5px solid transparent;border-bottom:3.5px solid transparent}',
    '.cv-arrowbox.is-null .cv-arrow-v{color:var(--ink-3)}',
    '.cv-arrowbox.is-null .cv-arrow-line{background:var(--rule-2)}',
    '.cv-arrowbox.is-null .cv-arrow-line::after{border-left-color:var(--rule-2)}',
    '.cv-arrow-s{font-size:12px;color:var(--ink-3)}',

    /* named companies */
    '.cv-ex{border:1px solid var(--rule-2);background:var(--bg-2);padding:var(--s4)}',
    '.cv-ex.is-accent{border-top:2px solid var(--accent)}',
    '.cv-ex.is-cool{border-top:2px solid var(--cool)}',
    '.cv-ex-h{border-bottom:1px solid var(--rule);padding-bottom:var(--s3)}',
    '.cv-ex-t{font-size:26px;font-weight:600;letter-spacing:0.02em;line-height:1.1}',
    '.cv-ex-n{font-size:var(--fs-sm);color:var(--ink-2)}',
    '.cv-ex-checklist{margin:var(--s4) 0}',
    '.cv-ex-k{font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:var(--ink-3)}',
    '.cv-boxes{display:flex;gap:3px;margin:6px 0 4px 0}',
    '.cv-box{width:22px;height:14px;background:var(--bg-sunk);border:1px solid var(--rule-2)}',
    '.cv-box.is-on{background:var(--tier-reported);border-color:var(--tier-reported)}',
    '.cv-ex-sub{font-size:13px;color:var(--ink-2)}',
    '.cv-ex-rows{border-top:1px solid var(--rule)}',
    '.cv-ex-row{display:grid;grid-template-columns:1fr auto;gap:var(--s2) var(--s3);',
    'padding:7px 0;border-bottom:1px solid var(--rule)}',
    '.cv-ex-row:last-child{border-bottom:0}',
    '.cv-ex-rk{font-size:var(--fs-sm);color:var(--ink-3)}',
    '.cv-ex-rv{font-size:var(--fs-sm);color:var(--ink);text-align:right;white-space:nowrap}',
    '.cv-ex-rv small{font-family:var(--font-sans);color:var(--ink-3);font-size:13px}',
    '.cv-ex-rs{grid-column:1 / -1;font-size:12px;color:var(--ink-3);margin-top:-4px}',

    /* limitations */
    '.cv-limits{display:grid;gap:var(--s2)}',
    /* each limit is a disclosure: the figure and the name of the thing we
       cannot see are the summary, the paragraph that sizes it is the body */
    '.cv-limit{border:0;border-top:1px solid var(--rule);background:none}',
    '.cv-limit:first-child{border-top:0}',
    '.cv-limit > summary{display:grid;grid-template-columns:186px 1fr;gap:var(--s5);',
    'align-items:baseline;padding:var(--s3) 0;border-left:0}',
    '.cv-limit > summary:hover{background:none}',
    '.cv-limit > summary:hover .cv-limit-t{color:var(--accent-2)}',
    '.cv-limit > summary::after{content:"+";font-family:var(--font-mono);color:var(--accent);',
    'position:absolute;right:2px;top:var(--s3)}',
    '.cv-limit[open] > summary::after{content:"\\2212"}',
    '.cv-limit > summary{position:relative;padding-right:var(--s5)}',
    '.cv-limit > .dd-body{border-top:0;padding:0 var(--s5) var(--s4) 186px}',
    '.cv-limit .cv-limit-f{display:block}',
    '.cv-limit-fig{font-size:30px;font-weight:600;letter-spacing:-0.02em;line-height:1.05;color:var(--accent)}',
    '.cv-limit-u{font-size:12px;color:var(--ink-3);line-height:1.35;margin-top:3px}',
    '.cv-limit-t{font-size:var(--fs-sm);font-weight:600}',
    '.cv-limit-p{font-size:var(--fs-sm);color:var(--ink-2);line-height:1.5;margin-top:3px;max-width:92ch}',
    '.cv-limit-s{font-size:12px;color:var(--ink-3);margin-top:5px}',
    '.cv-link{color:var(--accent-2);border-bottom:1px solid var(--rule-2)}',
    '.cv-link:hover{border-bottom-color:var(--accent)}',

    /* provenance */
    '.cv-filter{display:flex;align-items:center;gap:var(--s2);margin-bottom:var(--s4)}',
    '.cv-filter-k{font-size:13px;color:var(--ink-3);margin-right:var(--s2)}',
    '.cv-cls{display:inline-block;font-family:var(--font-mono);font-size:12px;letter-spacing:0.06em;',
    'text-transform:uppercase;padding:2px 7px;border:1px solid currentColor;color:var(--ink-3)}',
    '.cv-filter .cv-cls{cursor:pointer;opacity:0.55}',
    '.cv-filter .cv-cls.is-on{opacity:1;background:var(--bg-2)}',
    '.cv-cls-mandatory{color:var(--cool)}',
    '.cv-cls-voluntary{color:var(--tier-reported)}',
    '.cv-cls-vendor{color:var(--accent)}',
    '.cv-cls-modelled{color:var(--muted-ink)}',
    '.cv-ledger-tbl td{vertical-align:top}',
    '.cv-ledger-tbl tr.is-off{opacity:0.22}',
    '.cv-led-d{font-size:12px;color:var(--ink-3);font-weight:400;margin-top:2px}',
    '.tbl.cv-ledger-tbl td.cv-led-src,.tbl.cv-ledger-tbl td.cv-led-use',
    '{font-size:13px;color:var(--ink-2);text-align:left}',
    '.tbl.cv-ledger-tbl td.cv-led-n{white-space:nowrap}',
    '.cv-ledger-tbl th:nth-child(2),.cv-ledger-tbl th:nth-child(3),.cv-ledger-tbl th:last-child{text-align:left}',
    '.cv-ledger-tbl td:nth-child(3){text-align:left}',
    '.cv-classnotes{display:grid;grid-template-columns:1fr 1fr;gap:6px var(--s5);margin-top:var(--s4)}',
    '.cv-classnote{display:flex;gap:var(--s3);align-items:baseline;font-size:13px;color:var(--ink-3)}',
    '.cv-classnote .cv-cls{flex:none}',

    /* the per panel provenance stamp */
    '.cv-prov{display:flex;gap:var(--s3);align-items:baseline;flex-wrap:wrap;margin-top:var(--s4);',
    'padding-top:var(--s2);border-top:1px solid var(--rule);font-size:12px;color:var(--ink-3)}',
    '.cv-prov-k{font-family:var(--font-mono);letter-spacing:0.14em;text-transform:uppercase;color:var(--rule-2)}',
    '.cv-prov .mono{color:var(--ink-2)}',
    '.cv-prov-c{color:var(--ink-3);border-left:1px solid var(--rule-2);padding-left:var(--s3)}',

    '@media (prefers-reduced-motion: no-preference){',
    '.cv-cell{transition:opacity 140ms linear}',
    '.cv-ledger-tbl tr{transition:opacity 140ms linear}}'
  ].join('\n');

}());
