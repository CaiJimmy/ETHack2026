/* The $1bn book.

   Three portfolios built against Commission Delegated Regulation (EU) 2020/1818,
   article by article, then decomposed to find out where the carbon cut came from.

   Everything is precomputed in data/portfolio.json. This file reads, draws and
   tweens. The only arithmetic here is division: a component over the total, a
   weight minus the index weight, a sum of 499 weights by sector. Nothing that
   changes a published figure. */
(function () {
  'use strict';

  var F = window.FILED;
  var fmt = F.fmt;

  /* the three selectable books, in the order they get harder */
  var BOOKS = [
    {
      key: 'naive_exclusion', name: 'Naive exclusion',
      wf: 'w_naive',
      sub: 'Drop the fossil producers and the high carbon power. Renormalise. Nothing else.'
    },
    {
      key: 'pab_compliant', name: 'Paris-aligned',
      wf: 'w_pab',
      sub: 'Every Article 12 exclusion, the 5% position cap, the Article 3 sector floor.'
    },
    {
      key: 'transition_leader', name: 'Transition leader',
      wf: 'w_lead',
      sub: 'The Paris-aligned book, tilted toward companies whose filed emissions are falling.'
    }
  ];

  /* the control: the same index with the position cap and nothing else. It is
     the only way to read a tracking error honestly. */
  var CONTROL = 'capped_index_only';

  /* waterfall columns. The order matters: improvement first, so the running
     level after it lands exactly on the universe's own 2023 intensity. */
  var COLS = [
    { kind: 'anchor', key: 'base', t1: 'Index 2018', t2: 'universe, base weights' },
    { kind: 'step', key: 'improvement', t1: 'Improvement', t2: 'what companies did' },
    { kind: 'step', key: 'reallocation', t1: 'Reallocation', t2: 'what the manager did' },
    { kind: 'step', key: 'selection', t1: 'Selection', t2: 'picks inside a sector' },
    { kind: 'step', key: 'interaction', t1: 'Interaction', t2: 'weight off the improvers' },
    { kind: 'anchor', key: 'waci', t1: 'The book 2023', t2: 'what $1bn finances' }
  ];

  var STEP_FILL = {
    improvement: 'var(--cool)',
    reallocation: 'var(--accent)',
    selection: 'var(--muted)',
    interaction: 'var(--accent-dim)'
  };

  var SECTOR_SHORT = {
    'Information Technology': 'Info Tech',
    'Communication Services': 'Comm Svcs',
    'Consumer Discretionary': 'Cons Disc.',
    'Consumer Staples': 'Cons Staples'
  };

  var BASIS_SHORT = {
    measured_mandatory: 'EPA filing',
    ghgrp_threshold_bound: 'below the limit',
    sector_median_imputed: 'our estimate'
  };

  var REDUCED = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var D = null;       /* the portfolio file */
  var P = null;       /* D.portfolios */
  var SEL = 'pab_compliant';
  var liveState = null;
  var tweenToken = 0;
  var wf = null;      /* waterfall updater */

  F.onReady(function (data) {
    D = data.portfolio;
    P = D.portfolios;
    injectCss();
    registerDrawer();
    build();
    select('pab_compliant', true);
  });

  /* the regulation, the decomposition and the two acronyms, written once */
  function registerDrawer() {
    F.drawer.add('rulebook', 'The rulebook the fund is built from',
      '<p>' + D.meta.regulation_title + '</p>' +
      '<p class="mono">EUR-Lex CELEX ' + D.meta.regulation + ', retrieved ' +
      String(D.meta.regulation_retrieved).slice(0, 10) + '.</p>' +
      '<p>' + D.meta.attribution + '.</p>' +
      '<p>' + fmt.int(D.rules_used.length) + ' rules are encoded from the operative text, ' +
      'each one with its article number. The article table quotes every one of them.</p>');

    F.drawer.add('decomposition', 'How the carbon cut is split',
      '<p>The waterfall is a Brinson decomposition, the standard way to split a change ' +
      'into the part that came from picking names and the part that came from moving ' +
      'weight between sectors. Four terms:</p>' +
      '<dl><dt>Improvement</dt><dd>the same companies, cleaner. Measured at base-year ' +
      'weights, so it is the same figure in every book.</dd>' +
      '<dt>Reallocation</dt><dd>the same year, different companies. Money leaving one ' +
      'sector for another.</dd>' +
      '<dt>Selection</dt><dd>picks inside a sector.</dd>' +
      '<dt>Interaction</dt><dd>the overlap between the two, which is positive here ' +
      'because the book sold the companies that were improving fastest.</dd></dl>' +
      '<p>Carbon intensity is Scope 1 tonnes divided by EVIC, enterprise value including ' +
      'cash, which is what the regulation uses. A sector median is imputed at PCAF data ' +
      'quality 5, the weakest grade there is.</p>');
  }

  /* ================= state ================= */

  /* every animated number for one book, in one flat object */
  function stateOf(key) {
    var p = P[key];
    var d = p.decomposition;
    return {
      waci: p.waci,
      cut: p.cut_vs_universe,
      names: p.names,
      wExcl: p.cap_share_dropped,
      te: p.tracking_error.te,
      teLo: p.tracking_error.te_p05,
      teHi: p.tracking_error.te_p95,
      financed: p.financed_tonnes,
      effN: p.effective_n,
      activeShare: p.active_share,
      art3: p.art3_high_impact,
      art12: p.art12_names_held,
      base: p.waci - d.total,
      improvement: d.improvement,
      reallocation: d.reallocation,
      selection: d.selection,
      interaction: d.interaction,
      held: d.improvement_held,
      total: d.total
    };
  }

  function select(key, immediate) {
    SEL = key;
    var to = stateOf(key);
    var from = liveState || to;

    /* the parts that are not worth tweening: swap them, let css move the bars */
    paintStatic(key);

    var token = ++tweenToken;
    if (immediate || REDUCED) { paint(to); return; }

    var keys = Object.keys(to);
    animate(520, function (u) {
      if (token !== tweenToken) return false;
      var s = {};
      keys.forEach(function (k) { s[k] = from[k] + (to[k] - from[k]) * u; });
      paint(s);
      return true;
    });
  }

  function animate(ms, step) {
    var t0 = null;
    function frame(ts) {
      if (t0 === null) t0 = ts;
      var u = Math.min(1, (ts - t0) / ms);
      /* ease in out cubic: the rebuild should start and land softly */
      var e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
      if (step(e) === false) return;
      if (u < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /* ================= build ================= */

  /* The argument is three objects: the three books, the waterfall, and who kept
     the improvement. Everything else is evidence for it and sits behind a bar
     that names what is inside. Nothing was deleted, and every panel below is
     still in the DOM, so the figures update whichever book is selected. */
  function build() {
    var host = document.getElementById('portfolio-body');
    var x = D.exclusions;
    host.innerHTML = '';
    host.appendChild(mandate());
    host.appendChild(picker());
    host.appendChild(revealPanel());
    host.appendChild(evidenceRow());
    host.appendChild(F.details('The book in six figures', '<b id="pf-book-name2"></b>',
      bookPanel()));
    host.appendChild(F.details('Article by article', ARTICLES.length + ' tests',
      articlePanel()));
    host.appendChild(F.details('Largest holdings',
      'top <b>12</b> of <span id="pf-hold-n"></span>', holdingsPanel()));
    host.appendChild(F.details('What Article 12 takes out',
      '<b>' + fmt.int(x.n_excluded) + '</b> names, <b>' + fmt.share(x.w_excluded, 2) +
      '</b> of index weight', exclusionPanel()));
    host.appendChild(F.details('Tracking error, and the cut under four missing-data rules',
      '2 panels', riskRow()));
    host.appendChild(F.details('What this is not', '<b>8</b> caveats', notesPanel()));
  }

  /* ---- the mandate strip ---- */

  function mandate() {
    var m = D.meta;
    var u = D.universe;
    return F.el('div', { class: 'pf-mandate' }, [
      F.el('div', { class: 'pf-aum' }, [
        F.el('div', { class: 'pf-aum-fig mono', text: '$1bn' }),
        F.el('div', { class: 'pf-aum-k', text: 'allocated across the S&P 500 on ' +
          m.latest_year + ' weights' })
      ]),
      F.el('div', { class: 'pf-mandate-kv' }, [
        kv('Share of index market cap', fmt.share(m.aum_share_of_index, 5)),
        kv('Index market cap', fmt.usd(u.market_cap_usd)),
        kv('Investable universe', fmt.int(u.n_companies) + ' names'),
        kv('Base year to latest', m.base_year + ' to ' + m.latest_year),
        kvHtml('Carbon intensity', 'tonnes per $m of ' + F.g('EVIC')),
        kvHtml('The regulation', F.drawer.linkHTML('rulebook', 'EU 2020/1818'))
      ])
    ]);
  }

  function kv(k, v) {
    return F.el('div', { class: 'pf-kv' }, [
      F.el('div', { class: 'pf-kv-k', text: k }),
      F.el('div', { class: 'pf-kv-v mono', text: v })
    ]);
  }

  function kvHtml(k, v) {
    return F.el('div', { class: 'pf-kv' }, [
      F.el('div', { class: 'pf-kv-k', text: k }),
      F.el('div', { class: 'pf-kv-v mono', html: v })
    ]);
  }

  /* ---- the three way switch ---- */

  function picker() {
    var wrap = F.el('div', { class: 'pf-pick' });
    BOOKS.forEach(function (b) {
      var p = P[b.key];
      var card = F.el('button', {
        class: 'pf-card', type: 'button', id: 'pf-card-' + b.key,
        'aria-pressed': 'false',
        onclick: function () { select(b.key); }
      }, [
        F.el('div', { class: 'pf-card-top' }, [
          F.el('span', { class: 'pf-card-name', text: b.name })
        ]),
        F.el('div', { class: 'pf-card-sub', text: b.sub }),
        F.el('div', { class: 'pf-card-figs' }, [
          cardFig(fmt.share(p.cut_vs_universe, 1), 'carbon cut'),
          cardFig(fmt.share(p.tracking_error.te, 2), 'tracking error'),
          cardFig(fmt.int(p.names), 'names')
        ]),
        F.el('div', { class: 'pf-card-flags' }, summaryChip(b.key))
      ]);
      wrap.appendChild(card);
    });
    var w = F.el('div', {}, [wrap, F.el('div', { class: 'pf-pick-note note' })]);
    /* the obvious question, answered before anyone has to ask it */
    var na = P.naive_exclusion, pa = P.pab_compliant;
    w.lastChild.innerHTML =
      'A deeper cut is not a better book. Naive exclusion cuts ' + fmt.share(na.cut_vs_universe, 1) +
      ' against the whole index, more than the Paris-aligned book\'s ' + fmt.share(pa.cut_vs_universe, 1) +
      ', and still fails two articles: it keeps ' + fmt.int(na.art12_names_held) +
      ' of the ' + fmt.int(D.exclusions.n_excluded) + ' names Article 12 bars, and it drops its ' +
      'exposure to the ' + F.g('high impact sectors') + ' to ' +
      fmt.share(na.art3_high_impact, 2) + ' when Article 3 requires ' +
      fmt.share(na.art3_universe, 2) + '. Compliance is a set of constraints, not a leaderboard.';
    return w;
  }

  function cardFig(v, k) {
    return F.el('div', { class: 'pf-card-fig' }, [
      F.el('div', { class: 'pf-card-fig-v mono', text: v }),
      F.el('div', { class: 'pf-card-fig-k', text: k })
    ]);
  }

  /* one chip per card: compliant, or the articles it fails */
  function summaryChip(key) {
    var p = P[key];
    var fails = [];
    if (!p.art3_pass) fails.push('3');
    if (!p.art9_pass) fails.push('9');
    if (!p.art11_pass) fails.push('11');
    if (!p.art12_pass) fails.push('12');
    return F.el('span', {
      class: 'pf-vchip ' + (fails.length ? 'is-fail' : 'is-pass'),
      text: fails.length
        ? 'fails Article' + (fails.length > 1 ? 's ' : ' ') + fails.join(' and ')
        : 'passes all four tests'
    });
  }

  /* ---- panel 1: the selected book in six figures ---- */

  var TILES = [
    { id: 'waci', k: 'Carbon intensity of the book',
      u: function () { return 'tonnes per $m of company value'; },
      f: function (s) { return fmt.num(s.waci, 2); } },
    { id: 'cut', k: 'Cut against the whole index', cool: true,
      u: function () {
        return 'Article 11 asks for ' +
          fmt.num(D.thresholds.pab_baseline_reduction.min_reduction_vs_universe_pct, 0) + '%';
      },
      f: function (s) { return fmt.share(s.cut, 1); } },
    { id: 'names', k: 'Names held',
      u: function () { return 'of ' + fmt.int(D.universe.n_companies) + ' in the universe'; },
      f: function (s) { return fmt.int(s.names); } },
    { id: 'wexcl', k: 'Index weight not held',
      u: function () { return 'dropped or capped away'; },
      f: function (s) { return fmt.share(s.wExcl, 2); } },
    { id: 'te', k: 'Tracking error',
      u: function () { return 'how far its returns drift from the index'; },
      f: function (s) { return fmt.share(s.te, 2); } },
    { id: 'fin', k: 'Tonnes financed by the $1bn',
      u: function () { return 'index finances ' + fmt.int(D.universe.financed_tonnes_per_bn); },
      f: function (s) { return fmt.int(s.financed); } }
  ];

  function bookPanel() {
    var p = F.el('div', { class: 'panel' });
    p.appendChild(panelHead('', '', '<b id="pf-book-name"></b> / $1bn'));
    var row = F.el('div', { class: 'pf-tiles' });
    TILES.forEach(function (t) {
      row.appendChild(F.el('div', { class: 'pf-tile' + (t.cool ? ' is-cool' : '') }, [
        F.el('div', { class: 'pf-tile-v mono', id: 'pf-t-' + t.id, text: '' }),
        F.el('div', { class: 'pf-tile-k', text: t.k }),
        F.el('div', { class: 'pf-tile-u mono', id: 'pf-u-' + t.id, text: t.u() })
      ]));
    });
    p.appendChild(row);
    p.appendChild(F.el('div', { class: 'note u-mt4', id: 'pf-book-note' }));
    return p;
  }

  /* ---- panel 2: article by article ---- */

  function ruleQuote(id) {
    var r = D.rules_used.filter(function (x) { return x.id === id; })[0];
    return r ? r.quote : '';
  }
  function ruleArticle(id) {
    var r = D.rules_used.filter(function (x) { return x.id === id; })[0];
    return r ? r.article : '';
  }

  var ARTICLES = [
    {
      id: 'art3', rule: 'equity_allocation_constraint', label: 'Article 3',
      test: 'Sector floor. The book must hold at least as much of the high-emitting ' +
        'industries as the index does.',
      req: function () { return 'at least ' + fmt.share(P[SEL].art3_universe, 2); },
      got: function (s) { return fmt.share(s.art3, 2); },
      pass: function (k) { return P[k].art3_pass; }
    },
    {
      id: 'art7', rule: 'decarbonisation_trajectory_equity', label: 'Article 7',
      test: 'Falling every year. At least 7% off the carbon intensity a year, compounding, ' +
        'from the base year.',
      req: function () { return fmt.num(D.thresholds.decarbonisation_trajectory_equity.min_annual_reduction_pct, 1) + '%/yr'; },
      got: function () { return 'we do not claim this one'; },
      pass: function () { return null; }
    },
    {
      id: 'art9', rule: 'ctb_baseline_reduction', label: 'Article 9',
      test: 'The lower bar, the Climate Transition Benchmark. At least 30% below the whole index.',
      req: function () { return 'at least ' + fmt.num(D.thresholds.ctb_baseline_reduction.min_reduction_vs_universe_pct, 0) + '%'; },
      got: function (s) { return fmt.share(s.cut, 1); },
      pass: function (k) { return P[k].art9_pass; }
    },
    {
      id: 'art11', rule: 'pab_baseline_reduction', label: 'Article 11',
      test: 'The Paris bar. At least 50% below the whole index.',
      req: function () { return 'at least ' + fmt.num(D.thresholds.pab_baseline_reduction.min_reduction_vs_universe_pct, 0) + '%'; },
      got: function (s) { return fmt.share(s.cut, 1); },
      pass: function (k) { return P[k].art11_pass; }
    },
    {
      id: 'art12', rule: 'pab_exclusion_power_generation', label: 'Article 12',
      test: 'Exclusions, tests (a) to (g). We built (g) ourselves from the EPA\u2019s ' +
        'stack monitors on power plants, which is why it is quoted here.',
      req: function () { return 'hold 0 of ' + fmt.int(D.exclusions.n_excluded); },
      got: function (s) { return fmt.num(s.art12, 0) + ' held'; },
      pass: function (k) { return P[k].art12_pass; }
    }
  ];

  function articlePanel() {
    var p = F.el('div', { class: 'panel' });
    p.appendChild(panelHead('',
      D.meta.regulation_title.split(' supplementing')[0] + '. Quoted from the operative text.',
      'EUR-Lex <b>' + D.meta.regulation + '</b>'));

    var t = F.el('table', { class: 'tbl pf-art' });
    t.appendChild(colgroup([160, 392, 124, 128, 140]));
    t.appendChild(F.el('thead', {}, F.el('tr', {}, [
      th('Article', 'left'), th('Test', 'left'), th('Required'), th('This book'), th('Verdict')
    ])));
    var tb = F.el('tbody');
    ARTICLES.forEach(function (a) {
      tb.appendChild(F.el('tr', { id: 'pf-row-' + a.id }, [
        F.el('td', { class: 'pf-art-no mono', text: ruleArticle(a.rule) }),
        F.el('td', { class: 'pf-art-test' }, [
          F.el('div', { text: a.test }),
          F.el('div', { class: 'pf-quote', text: '“' + ruleQuote(a.rule) + '”' })
        ]),
        F.el('td', { class: 'mono t-dim', id: 'pf-req-' + a.id }),
        F.el('td', { class: 'mono pf-art-got', id: 'pf-got-' + a.id }),
        F.el('td', {}, F.el('span', { class: 'pf-vchip', id: 'pf-pass-' + a.id }))
      ]));
    });
    t.appendChild(tb);
    p.appendChild(t);

    p.appendChild(F.el('div', { class: 'note u-mt4', id: 'pf-art7-note' }));
    return p;
  }

  /* fixed column widths, so a long EUR-Lex quote cannot squeeze the figures */
  function colgroup(widths) {
    return F.el('colgroup', {}, widths.map(function (w) {
      return F.el('col', { style: { width: w + 'px' } });
    }));
  }

  function th(text, align) {
    return F.el('th', { text: text, style: align === 'left' ? { 'text-align': 'left' } : null });
  }

  /* ---- panel 3: holdings ---- */

  function holdingsPanel() {
    var p = F.el('div', { class: 'panel' });
    p.appendChild(panelHead('', 'Weight against the index, and where each intensity ' +
      'came from. 100 bp is 1%.', 'top <b>12</b> of <span id="pf-hold-n2"></span>'));
    var t = F.el('table', { class: 'tbl pf-hold' });
    t.appendChild(colgroup([72, 196, 130, 88, 124, 92, 112, 130]));
    t.appendChild(F.el('thead', {}, F.el('tr', {}, [
      th('Ticker', 'left'), th('Company', 'left'), th('Sector', 'left'),
      th('Intensity'), th('Where it came from', 'left'), th('Index wt'), th('Book wt'),
      th('Change (bp)')
    ])));
    t.appendChild(F.el('tbody', { id: 'pf-hold-body' }));
    p.appendChild(t);
    p.appendChild(F.el('div', { class: 'note u-mt4', id: 'pf-hold-note' }));
    return p;
  }

  /* ---- panel 4: what article 12 takes out ---- */

  function exclusionPanel() {
    var p = F.el('div', { class: 'panel' });
    var x = D.exclusions;
    p.appendChild(panelHead('', 'Seven revenue and conduct tests. A name can fail more ' +
      'than one.', ''));

    var grid = F.el('div', { class: 'pf-excl-grid' });

    /* left: the seven rules */
    var t = F.el('table', { class: 'tbl pf-rules' });
    t.appendChild(F.el('thead', {}, F.el('tr', {}, [
      th('Test', 'left'), th('Names'), th('Index wt'), th('Still held')
    ])));
    var tb = F.el('tbody');
    var rules = Object.keys(x.by_rule).map(function (id) {
      return { id: id, r: x.by_rule[id] };
    }).sort(function (a, b) { return b.r.weight - a.r.weight; });

    rules.forEach(function (row) {
      tb.appendChild(F.el('tr', {}, [
        F.el('td', { class: 'pf-rule-k' }, [
          F.el('span', { class: 'mono pf-art-no', text: row.r.article }),
          F.el('span', { class: 'pf-rule-t', text: ' ' + shortRule(row.id) })
        ]),
        F.el('td', { class: 'mono', text: fmt.int(row.r.names.length) }),
        F.el('td', { class: 'mono', text: fmt.share(row.r.weight, 2) }),
        F.el('td', { class: 'mono', id: 'pf-rule-held-' + row.id })
      ]));
    });
    t.appendChild(tb);
    grid.appendChild(F.el('div', {}, [t,
      F.el('div', { class: 'note u-mt4', text:
        D.meta.power_test_note.replace('revenue_exclusions.parquet',
          'the revenue screen') }),
      F.el('div', { class: 'note', id: 'pf-power-note' })
    ]));

    /* right: every excluded ticker, lit if this book still holds it */
    var chips = F.el('div', { class: 'pf-chips', id: 'pf-chips' });
    var seen = {};
    rules.forEach(function (row) {
      row.r.names.forEach(function (tk) {
        if (seen[tk]) return;
        seen[tk] = true;
        var c = F.el('span', { class: 'pf-x mono', 'data-t': tk, text: tk });
        c.addEventListener('mouseenter', function (ev) { chipTip(tk, ev); });
        c.addEventListener('mousemove', function (ev) { F.tip.move(ev); });
        c.addEventListener('mouseleave', function () { F.tip.hide(); });
        chips.appendChild(c);
      });
    });
    grid.appendChild(F.el('div', {}, [
      F.el('div', { class: 'pf-chips-head', text: 'Every excluded ticker. Lit means this book still owns it.' }),
      chips,
      F.el('div', { class: 'pf-chips-foot', id: 'pf-chips-foot' })
    ]));

    p.appendChild(grid);
    return p;
  }

  function shortRule(id) {
    return id.replace('pab_exclusion_', '').replace(/_/g, ' ')
      .replace('ungc oecd', 'UNGC or OECD breach')
      .replace('power generation', 'power above 100 g/kWh')
      .replace('controversial weapons', 'controversial weapons');
  }

  function chipTip(tk, ev) {
    var c = F.index.portfolio[tk];
    if (!c) return;
    var held = c[BOOKS.filter(function (b) { return b.key === SEL; })[0].wf] > 0;
    var pt = (D.exclusions.power_test || []).filter(function (p) { return p.ticker === tk; })[0];
    var html = '<div class="tip-t">' + tk + '</div>' + esc(c.name) +
      '<div style="margin-top:6px;color:var(--ink-3)">' + esc(c.excl_articles || '') + '</div>' +
      '<div style="margin-top:6px">Index weight ' + fmt.share(c.w_cap, 3) + '</div>' +
      '<div>Intensity ' + fmt.num(c.intensity, 2) + ' tCO2e/$m</div>' +
      (pt ? '<div>Fossil fleet ' + fmt.num(pt.g_per_kwh, 0) + ' gCO2e/kWh over ' +
        fmt.int(pt.plants) + ' plants</div>' : '') +
      '<div style="margin-top:6px;color:' + (held ? 'var(--accent-2)' : 'var(--ink-3)') + '">' +
      (held ? 'still held by this book' : 'not held') + '</div>';
    F.tip.show(html, ev);
  }

  /* ---- panel 5: the reveal ---- */

  var WF_W = 912, WF_H = 388;
  var WF_M = { t: 34, r: 8, b: 74, l: 56 };

  function revealPanel() {
    var p = F.el('div', { class: 'panel pf-reveal' });
    p.appendChild(panelHead('Where the carbon cut actually comes from',
      'We split the fall in carbon intensity into the part companies delivered and the ' +
      'part the manager bought by changing who they own.',
      'base <b>' + D.meta.base_year + '</b> to <b>' + D.meta.latest_year + '</b>'));

    p.appendChild(F.el('div', { class: 'pf-verdict' }, [
      F.el('div', { class: 'pf-verdict-fig mono', id: 'pf-realloc-fig' }),
      F.el('div', { class: 'pf-verdict-txt', id: 'pf-verdict-txt' })
    ]));

    var svg = F.svg('svg', {
      id: 'pf-wf', viewBox: '0 0 ' + WF_W + ' ' + WF_H, width: '100%',
      height: WF_H, preserveAspectRatio: 'xMidYMid meet',
      role: 'img', 'aria-label': 'waterfall decomposition of the intensity cut'
    });
    p.appendChild(F.el('div', { class: 'pf-plot' }, svg));
    wf = buildWaterfall(svg);

    p.appendChild(F.el('div', { class: 'legend pf-legend' }, [
      legendItem('var(--cool)', 'Improvement: the same companies, cleaner'),
      legendItem('var(--accent)', 'Reallocation: the same year, different companies'),
      legendItem('var(--muted)', 'Selection: picks inside a sector'),
      legendItem('var(--accent-dim)', 'Interaction: weight moved off the companies that improved',
        'var(--accent)')
    ]));
    p.appendChild(F.el('div', { class: 'pf-plot-note', id: 'pf-plot-note' }));
    p.appendChild(F.el('div', { class: 'pf-plot-note', html:
      F.drawer.linkHTML('decomposition', 'How the four terms are worked out') }));

    p.appendChild(F.el('div', { class: 'pf-reveal-say', id: 'pf-reveal-say' }));
    return p;
  }

  function legendItem(color, label, stroke) {
    return F.el('span', { class: 'legend-item' }, [
      F.el('span', {
        class: 'swatch swatch--sq',
        style: { background: color, 'box-shadow': stroke ? 'inset 0 0 0 1px ' + stroke : 'none' }
      }),
      F.el('span', { text: label })
    ]);
  }

  function buildWaterfall(svg) {
    var x0 = WF_M.l, x1 = WF_W - WF_M.r;
    var y0 = WF_M.t, y1 = WF_H - WF_M.b;
    /* one fixed y domain for all three books, so switching moves the bars and
       not the axis. The tallest anchor is the shared base-year universe. */
    var top = P.pab_compliant.waci - P.pab_compliant.decomposition.total;
    var y = F.scale([0, top * 1.06], [y1, y0]);

    F.axisY(svg, y, {
      x: x0, ticks: 4, fmt: function (v) { return fmt.num(v, 0); },
      grid: [x0, x1], label: 'tCO2e per $m EVIC', labelX: 14
    });
    svg.appendChild(F.svg('line', {
      class: 'axis-line', x1: x0, x2: x1, y1: y1 + 0.5, y2: y1 + 0.5
    }));

    /* the universe's own latest-year level. The improvement step lands on it. */
    var uref = F.svg('line', { class: 'ref-line', x1: x0, x2: x1 });
    svg.appendChild(uref);
    var urefLab = F.svg('text', {
      class: 'pf-ref-lab', x: x1, 'text-anchor': 'end', style: 'fill:var(--ink-2)'
    });
    svg.appendChild(urefLab);

    var band = (x1 - x0) / COLS.length;
    var bw = Math.min(96, band - 44);

    var parts = COLS.map(function (c, i) {
      var cx = x0 + band * i + band / 2;
      var conn = i > 0 ? F.svg('line', { class: 'pf-conn' }) : null;
      if (conn) svg.appendChild(conn);

      var rect = F.svg('rect', {
        x: cx - bw / 2, width: bw, class: 'pf-bar',
        fill: c.kind === 'anchor'
          ? (i === 0 ? 'var(--pf-anchor)' : 'var(--pf-anchor-2)')
          : STEP_FILL[c.key],
        stroke: c.key === 'interaction' ? 'var(--accent)' : 'none'
      });
      svg.appendChild(rect);

      var v = F.svg('text', {
        class: 'pf-bar-v', x: cx, 'text-anchor': 'middle', style: 'fill:var(--ink)'
      });
      var s = F.svg('text', {
        class: 'pf-bar-s', x: cx, 'text-anchor': 'middle',
        style: 'fill:' + (c.kind === 'anchor' ? 'var(--ink-3)'
          : c.key === 'improvement' ? 'var(--cool)'
            : c.key === 'selection' ? 'var(--muted-ink)' : 'var(--accent-2)')
      });
      svg.appendChild(v); svg.appendChild(s);

      svg.appendChild(F.svg('text', {
        class: 'pf-cat', x: cx, y: y1 + 26, 'text-anchor': 'middle',
        style: 'fill:var(--ink)', text: c.t1
      }));
      svg.appendChild(F.svg('text', {
        class: 'pf-cat2', x: cx, y: y1 + 44, 'text-anchor': 'middle',
        style: 'fill:var(--ink-3)', text: c.t2
      }));

      return { c: c, rect: rect, v: v, s: s, conn: conn, cx: cx, bw: bw };
    });

    return function update(st) {
      var run = st.base;
      parts.forEach(function (p, i) {
        var lo, hi, label, sub;
        if (p.c.kind === 'anchor') {
          hi = p.c.key === 'base' ? st.base : st.waci;
          lo = 0;
          label = fmt.num(hi, 2);
          sub = (p.c.key === 'base' ? D.meta.base_year : D.meta.latest_year) + ' level';
          run = hi;
        } else {
          var dv = st[p.c.key];
          lo = Math.min(run, run + dv);
          hi = Math.max(run, run + dv);
          label = fmt.signed(dv, 2);
          /* the interaction term adds intensity back, so as a share of a cut it
             is negative. Drawn as a positive bar, "-17.8% of the cut" reads as
             an error. It is said as what it is instead. */
          sub = fmt.share(Math.abs(dv / st.total), 1) + (dv > 0 ? ' back' : ' of the cut');
          run = run + dv;
        }
        var ytop = y(hi);
        p.rect.setAttribute('y', ytop);
        p.rect.setAttribute('height', Math.max(1.5, y(lo) - ytop));
        p.v.setAttribute('y', ytop - 22);
        p.v.textContent = label;
        p.s.setAttribute('y', ytop - 7);
        p.s.textContent = sub;

        /* the connector carries the running level into the next column */
        if (i + 1 < parts.length && parts[i + 1].conn) {
          var yr = Math.round(y(run)) + 0.5;
          var c = parts[i + 1].conn;
          c.setAttribute('x1', p.cx + p.bw / 2);
          c.setAttribute('x2', parts[i + 1].cx - parts[i + 1].bw / 2);
          c.setAttribute('y1', yr); c.setAttribute('y2', yr);
        }
      });

      var ulev = st.base + st.improvement;
      var uy = Math.round(y(ulev)) + 0.5;
      uref.setAttribute('y1', uy); uref.setAttribute('y2', uy);
      urefLab.setAttribute('y', uy - 8);
      urefLab.textContent = 'universe ' + D.meta.latest_year + ' \u00b7 ' + fmt.num(ulev, 2);
    };
  }

  /* ---- panel 6: sector shift and captured improvement ---- */

  function evidenceRow() {
    var row = F.el('div', { class: 'pf-row2' });

    var a = F.el('div', { class: 'panel' });
    a.appendChild(panelHead('Where the weight went',
      'Book weight minus index weight, biggest cut first.',
      '<b>11</b> sectors / ' + fmt.int(D.universe.n_companies) + ' names'));
    a.appendChild(F.el('div', { class: 'pf-sectors', id: 'pf-sectors' }));
    row.appendChild(a);

    var b = F.el('div', { class: 'panel' });
    b.appendChild(panelHead('Who kept the improvement',
      'Improvement plus interaction: the cut companies delivered, measured at each book\'s own weights.',
      'of <span id="pf-avail" class="mono"></span> available'));
    var t = F.el('table', { class: 'tbl pf-keep' });
    t.appendChild(F.el('thead', {}, F.el('tr', {}, [
      th('Book', 'left'), th('Kept'), th('Share of what companies delivered')
    ])));
    t.appendChild(F.el('tbody', { id: 'pf-keep-body' }));
    b.appendChild(t);
    b.appendChild(F.el('div', { class: 'note u-mt4', id: 'pf-keep-note' }));
    row.appendChild(b);
    return row;
  }

  /* ---- panel 7: tracking error and the missing data schemes ---- */

  function riskRow() {
    var row = F.el('div', { class: 'pf-row2' });

    var a = F.el('div', { class: 'panel' });
    a.appendChild(panelHead('What the tracking error is made of',
      'How far each book drifts from the index. Bootstrap over weekly returns, ' +
      '5th to 95th percentile.',
      '<b>' + fmt.int(P[CONTROL].tracking_error.filled_cells) + '</b> return cells filled'));
    a.appendChild(F.el('div', { class: 'pf-te', id: 'pf-te' }));
    a.appendChild(F.el('div', { class: 'note u-mt4', id: 'pf-te-note' }));
    row.appendChild(a);

    var b = F.el('div', { class: 'panel' });
    b.appendChild(panelHead('The cut under four missing-data rules',
      '361 of 500 companies file no mandatory tonnage. Each rule is a different answer to that.',
      'Article 11 line at <b>50%</b>'));
    b.appendChild(F.el('div', { class: 'pf-schemes', id: 'pf-schemes' }));
    b.appendChild(F.el('div', { class: 'note u-mt4', id: 'pf-scheme-note' }));
    row.appendChild(b);
    return row;
  }

  /* ---- panel 8: the caveats, lifted out of meta ---- */

  function notesPanel() {
    var p = F.el('div', { class: 'panel' });
    p.appendChild(panelHead('', '', '<b>' + D.rules_used.length +
      '</b> rules read from the regulation'));
    var ul = F.el('ul', { class: 'note-list' });

    /* the file's own note ends with a rounded share of market cap that does not
       match aum_share_of_index. Quote the substantive half, compute the rest. */
    [D.meta.what_this_is_not.split(/\.\s+\$1bn is/)[0] + '.',
      'The $1bn is ' + fmt.share(D.meta.aum_share_of_index, 5) + ' of the ' +
      fmt.usd(D.universe.market_cap_usd) + ' this file measures. It moves no capital any company would notice.',
      D.meta.scope_note, D.meta.intensity_definition, D.meta.missing_data_note].forEach(function (t) {
      if (t) ul.appendChild(F.el('li', { text: t }));
    });
    ul.appendChild(F.el('li', {
      text: 'Position limits: no name above ' +
        fmt.share(D.meta.position_limits.max_absolute, 0) + ' of the book and no more than ' +
        fmt.num(D.meta.position_limits.max_relative, 0) + ' times its index weight.'
    }));
    ul.appendChild(F.el('li', {
      text: 'One name, ' + D.universe.dropped_no_market_cap.join(' and ') +
        ', is out of the universe because we could not read a market cap for it.'
    }));
    p.appendChild(ul);
    return p;
  }

  function panelHead(title, sub, nHtml) {
    var left = F.el('div');
    if (title) left.appendChild(F.el('div', { class: 'panel-title', text: title }));
    if (sub) left.appendChild(F.el('div', { class: 'panel-sub', html: sub }));
    return F.el('div', { class: 'panel-head' + (title ? '' : ' is-quiet') }, [
      left, F.el('div', { class: 'panel-n', html: nHtml })
    ]);
  }

  /* ================= paint ================= */

  /* the tweened half: figures and the waterfall */
  function paint(s) {
    liveState = s;
    TILES.forEach(function (t) {
      var el = document.getElementById('pf-t-' + t.id);
      if (el) el.textContent = t.f(s);
    });
    setText('pf-u-te', fmt.share(s.teLo, 2) + ' to ' + fmt.share(s.teHi, 2));

    ARTICLES.forEach(function (a) {
      setText('pf-got-' + a.id, a.got(s));
    });

    setText('pf-realloc-fig', fmt.share(s.reallocation / s.total, 1));
    if (wf) wf(s);
  }

  /* the swapped half: text, tables, bars */
  function paintStatic(key) {
    var b = BOOKS.filter(function (x) { return x.key === key; })[0];
    var p = P[key];
    var s = stateOf(key);

    BOOKS.forEach(function (x) {
      var c = document.getElementById('pf-card-' + x.key);
      c.classList.toggle('is-on', x.key === key);
      c.setAttribute('aria-pressed', x.key === key ? 'true' : 'false');
    });

    setHtml('pf-book-name', b.name);
    setHtml('pf-book-name2', b.name);
    setText('pf-hold-n', fmt.int(p.names));
    setText('pf-hold-n2', fmt.int(p.names));

    setText('pf-book-note',
      b.name + ' finances ' + fmt.int(p.financed_tonnes) + ' tonnes of Scope 1 a year for the $1bn, ' +
      'against ' + fmt.int(D.universe.financed_tonnes_per_bn) + ' for the index. It holds ' +
      fmt.int(p.names) + ' names but it behaves like ' + fmt.num(p.effective_n, 0) +
      ' equal positions, because the position cap still leaves the five largest at ' +
      fmt.share(D.meta.position_limits.max_absolute, 0) + ' each. Active share ' +
      fmt.share(p.active_share, 1) + '.');

    ARTICLES.forEach(function (a) {
      setText('pf-req-' + a.id, a.req());
      var pass = a.pass(key);
      var chip = document.getElementById('pf-pass-' + a.id);
      chip.className = 'pf-vchip ' + (pass === null ? 'is-open' : pass ? 'is-pass' : 'is-fail');
      chip.textContent = pass === null ? 'not asserted' : pass ? 'pass' : 'fail';
      var row = document.getElementById('pf-row-' + a.id);
      row.classList.toggle('is-fail', pass === false);
    });

    var org = D.article7.organic[key];
    setText('pf-art7-note',
      'Article 7 is the one we will not mark as passed. Any book meets a 7% a year trajectory on paper by ' +
      'selling more of the index every year, which is what the ' + D.article7.path[key].length +
      ' year path in this file does. What the companies in this book actually deliver is ' +
      fmt.rate(org.delivered_pct_yr) + ', measured over the ' + fmt.share(org.weight_covered, 1) +
      ' of book weight that has a filed emissions trend. The index itself delivers ' +
      fmt.rate(D.article7.index_delivered_pct_yr) + '. Article 6 counts ' +
      D.article7.article6_qualifiers.length + ' companies in the whole index that cut ' +
      fmt.num(D.thresholds.target_setter_overweight.min_annual_reduction_pct, 0) + '% a year for ' +
      D.thresholds.target_setter_overweight.min_consecutive_years + ' consecutive years.');

    paintHoldings(b);
    paintChips(b);
    paintSectors(b);
    paintKeep(key);
    paintTe(key);
    paintSchemes(key);
    paintSay(key, s);
  }

  /* --- holdings table --- */

  function paintHoldings(b) {
    var body = document.getElementById('pf-hold-body');
    var rows = D.companies.slice().sort(function (x, y) { return y[b.wf] - x[b.wf]; }).slice(0, 12);
    var maxw = rows[0][b.wf];
    var cap = D.meta.position_limits.max_absolute;

    body.classList.add('is-swap');
    window.setTimeout(function () {
      body.innerHTML = '';
      rows.forEach(function (c) {
        var d = c[b.wf] - c.w_cap;
        body.appendChild(F.el('tr', {}, [
          F.el('td', { class: 'mono pf-tick', text: c.ticker }),
          F.el('td', { class: 't-name pf-l', text: c.name }),
          F.el('td', { class: 't-name pf-l t-dim', text: SECTOR_SHORT[c.sector] || c.sector }),
          F.el('td', { class: 'mono', text: fmt.num(c.intensity, 2) }),
          F.el('td', { class: 't-name pf-l pf-basis-' + c.intensity_basis, text: BASIS_SHORT[c.intensity_basis] }),
          F.el('td', { class: 'mono t-dim', text: fmt.share(c.w_cap, 2) }),
          F.el('td', { class: 'mono pf-w' }, [
            F.el('span', { text: fmt.share(c[b.wf], 2) }),
            c[b.wf] >= cap - 1e-9 ? F.el('span', { class: 'pf-capped', text: 'cap' }) : null,
            F.el('span', { class: 'pf-wbar-f', style: { width: (c[b.wf] / maxw * 100).toFixed(2) + '%' } })
          ]),
          F.el('td', { class: 'mono ' + (d < 0 ? 't-dim' : ''), text: fmt.signed(d * 1e4, 0) + ' bp' })
        ]));
      });
      body.classList.remove('is-swap');
    }, REDUCED ? 0 : 150);

    var held = D.companies.filter(function (c) { return c[b.wf] > 0; });
    var nMeasured = held.filter(function (c) { return c.measured; }).length;
    var wMeasured = held.reduce(function (a, c) { return a + (c.measured ? c[b.wf] : 0); }, 0);
    setHtml('pf-hold-note',
      'An EPA filing is a mandatory tonnage. Below the limit means the company sits under the ' +
      '25 000 tonne reporting floor, so its intensity is an upper bound. Our estimate is the ' +
      'sector median, which is the weakest input there is, a ' + F.g('PCAF data quality 5') +
      '. This book holds ' + fmt.int(nMeasured) + ' of the ' + fmt.int(D.universe.n_measured) +
      ' companies in the index whose emissions are measured at all, ' + fmt.share(wMeasured, 1) +
      ' of the money. It dropped ' + fmt.int(D.universe.n_measured - nMeasured) +
      ' of them. Everything else is imputed the same way inside the universe, so the ratio Article 11 ' +
      'asks for stays like for like.');
  }

  /* --- article 12 chips --- */

  function paintChips(b) {
    var chips = document.getElementById('pf-chips');
    var held = 0, heldW = 0;
    [].forEach.call(chips.children, function (el) {
      var c = F.index.portfolio[el.getAttribute('data-t')];
      var on = c && c[b.wf] > 0;
      if (on) { held++; heldW += c.w_cap; }
      el.classList.toggle('is-held', !!on);
    });
    setText('pf-chips-foot', held === 0
      ? 'This book holds none of them. Article 12 passes.'
      : 'This book still holds ' + fmt.int(held) + ' of them, ' + fmt.share(heldW, 2) +
        ' of index weight. Article 12 fails.');
    document.getElementById('pf-chips-foot').classList.toggle('is-fail', held > 0);

    Object.keys(D.exclusions.by_rule).forEach(function (id) {
      var n = D.exclusions.by_rule[id].names.filter(function (tk) {
        var c = F.index.portfolio[tk];
        return c && c[b.wf] > 0;
      }).length;
      var el = document.getElementById('pf-rule-held-' + id);
      if (!el) return;
      el.textContent = fmt.int(n);
      el.className = 'mono' + (n > 0 ? ' u-accent' : ' t-dim');
    });

    var pt = D.exclusions.power_test;
    setText('pf-power-note', fmt.int(pt.length) + ' companies were put through the 12(1)(g) test and ' +
      fmt.int(pt.filter(function (p) { return p.excluded; }).length) + ' failed it. ' +
      D.exclusions.untested_power.join(' and ') + ' owns generation we could not match to a CAMD plant, ' +
      'so it was never tested and is held anyway. That is a hole, not a pass.');
  }

  /* --- sector shift --- */

  function paintSectors(b) {
    var host = document.getElementById('pf-sectors');
    var agg = {};
    D.companies.forEach(function (c) {
      var a = agg[c.sector] || (agg[c.sector] = { cap: 0, sel: 0 });
      a.cap += c.w_cap; a.sel += c[b.wf];
    });
    var rows = Object.keys(agg).map(function (k) {
      return { s: k, d: agg[k].sel - agg[k].cap };
    }).sort(function (x, y) { return x.d - y.d; });
    var max = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.d); }));

    if (!host.children.length) {
      rows.forEach(function (r) {
        host.appendChild(F.el('div', { class: 'pf-sec', 'data-s': r.s }, [
          F.el('div', { class: 'pf-sec-k', text: SECTOR_SHORT[r.s] || r.s }),
          F.el('div', { class: 'pf-sec-track' }, [
            F.el('span', { class: 'pf-sec-zero' }),
            F.el('span', { class: 'pf-sec-bar' })
          ]),
          F.el('div', { class: 'pf-sec-v mono' })
        ]));
      });
    }

    var byS = {};
    [].forEach.call(host.children, function (el) { byS[el.getAttribute('data-s')] = el; });

    /* FLIP: measure, reorder, then slide each row from where it was. The
       reordering is the point, so it has to be watchable. */
    var before = {};
    rows.forEach(function (r) { before[r.s] = byS[r.s].offsetTop; });
    rows.forEach(function (r) { host.appendChild(byS[r.s]); });

    rows.forEach(function (r) {
      var el = byS[r.s];
      var bar = el.querySelector('.pf-sec-bar');
      var w = Math.abs(r.d) / max * 50;
      bar.style.width = w.toFixed(2) + '%';
      bar.style.left = r.d < 0 ? (50 - w).toFixed(2) + '%' : '50%';
      bar.classList.toggle('is-neg', r.d < 0);
      var v = el.querySelector('.pf-sec-v');
      v.textContent = fmt.signed(r.d * 100, 2) + 'pp';
      v.className = 'pf-sec-v mono' + (r.d < 0 ? ' u-accent' : '');

      if (REDUCED) return;
      var dy = before[r.s] - el.offsetTop;
      if (!dy) return;
      el.style.transition = 'none';
      el.style.transform = 'translateY(' + dy + 'px)';
      /* read back to commit the start position before the transition is armed */
      void el.offsetWidth;
      el.style.transition = 'transform 480ms cubic-bezier(.4,0,.2,1)';
      el.style.transform = '';
    });
  }

  /* --- who kept the improvement --- */

  function paintKeep(key) {
    var avail = P.pab_compliant.decomposition.improvement;
    setText('pf-avail', fmt.num(avail, 2));
    var body = document.getElementById('pf-keep-body');
    body.innerHTML = '';
    var rows = [{ key: CONTROL, name: 'The index, position cap only' }].concat(
      BOOKS.map(function (b) { return { key: b.key, name: b.name }; }));
    var max = Math.max.apply(null, rows.map(function (r) {
      return Math.abs(P[r.key].decomposition.improvement_held);
    }));
    rows.forEach(function (r) {
      var v = P[r.key].decomposition.improvement_held;
      body.appendChild(F.el('tr', { class: r.key === key ? 'is-on' : '' }, [
        F.el('td', { class: 't-name', text: r.name }),
        F.el('td', { class: 'mono', text: fmt.num(v, 2) }),
        F.el('td', { class: 'mono' }, [
          F.el('span', { class: 'pf-kbar' },
            F.el('span', {
              class: 'pf-kbar-f' + (r.key === key ? ' is-on' : ''),
              style: { width: (Math.abs(v) / max * 100).toFixed(1) + '%' }
            })),
          F.el('span', { text: fmt.share(v / avail, 0) })
        ])
      ]));
    });
    var pab = P.pab_compliant.decomposition.improvement_held;
    var idx = P[CONTROL].decomposition.improvement_held;
    setText('pf-keep-note',
      'Improvement is measured at base-year weights, so it is the same ' + fmt.num(avail, 2) +
      ' in every book. What separates them is improvement plus interaction: the cut companies ' +
      'delivered that is still in the ' +
      'book once the money has moved. The index, holding everything, keeps ' + fmt.num(idx, 2) +
      ', slightly more than the base-weighted figure because the position cap happens to push weight ' +
      'toward names that improved. The Paris-aligned book keeps ' + fmt.num(pab, 2) + ', which is ' +
      fmt.share(pab / idx, 0) + ' of what the index keeps. That is the finding in one line: the book ' +
      'that decarbonises on paper is the book that sold the companies doing the decarbonising.');
  }

  /* --- tracking error --- */

  function paintTe(key) {
    var host = document.getElementById('pf-te');
    var rows = [{ key: CONTROL, name: 'Position cap alone, no carbon rule' }].concat(
      BOOKS.map(function (b) { return { key: b.key, name: b.name }; }));
    var max = Math.max.apply(null, rows.map(function (r) { return P[r.key].tracking_error.te_p95; })) * 1.06;

    if (!host.children.length) {
      rows.forEach(function (r) {
        host.appendChild(F.el('div', { class: 'pf-te-row', 'data-k': r.key }, [
          F.el('div', { class: 'pf-te-k', text: r.name }),
          F.el('div', { class: 'pf-te-track' }, [
            F.el('span', { class: 'pf-te-ci' }),
            F.el('span', { class: 'pf-te-bar' })
          ]),
          F.el('div', { class: 'pf-te-v mono' })
        ]));
      });
    }
    [].forEach.call(host.children, function (el) {
      var k = el.getAttribute('data-k');
      var t = P[k].tracking_error;
      el.classList.toggle('is-on', k === key);
      el.classList.toggle('is-ctrl', k === CONTROL);
      el.querySelector('.pf-te-bar').style.width = (t.te / max * 100).toFixed(2) + '%';
      var ci = el.querySelector('.pf-te-ci');
      ci.style.left = (t.te_p05 / max * 100).toFixed(2) + '%';
      ci.style.width = ((t.te_p95 - t.te_p05) / max * 100).toFixed(2) + '%';
      el.querySelector('.pf-te-v').textContent = fmt.share(t.te, 2);
    });

    var ctrl = P[CONTROL].tracking_error.te;
    var sel = P[key].tracking_error.te;
    setText('pf-te-note',
      'The ' + fmt.share(D.meta.position_limits.max_absolute, 0) +
      ' position cap on its own, with no exclusion and no carbon rule anywhere in it, already costs ' +
      fmt.share(ctrl, 2) + '. This book costs ' + fmt.share(sel, 2) + '. The carbon constraint is worth ' +
      fmt.share(sel - ctrl, 2) + ' of that, and the capped index it is measured against is ' +
      fmt.share(Math.abs(P[CONTROL].cut_vs_universe), 1) + ' more carbon intense than the universe, ' +
      'because capping the five largest names pushes money into heavier ones.');
  }

  /* --- the four missing data rules --- */

  var SCHEME_LABEL = {
    imputed: 'Sector median, which is what we publish',
    threshold: 'Just under the reporting limit',
    available_case: 'Measured companies only',
    zerofill: 'Non-disclosers scored zero'
  };

  function paintSchemes(key) {
    var host = document.getElementById('pf-schemes');
    var cuts = P[key].cuts_by_scheme;
    var thr = D.thresholds.pab_baseline_reduction.min_reduction_vs_universe_pct / 100;
    var keys = ['imputed', 'threshold', 'available_case', 'zerofill'];
    var max = 0.8;

    if (!host.children.length) {
      keys.forEach(function (k) {
        host.appendChild(F.el('div', { class: 'pf-sch', 'data-k': k }, [
          F.el('div', { class: 'pf-sch-k', text: SCHEME_LABEL[k] }),
          F.el('div', { class: 'pf-sch-track' }, [
            F.el('span', { class: 'pf-sch-thr', style: { left: (thr / max * 100).toFixed(2) + '%' } }),
            F.el('span', { class: 'pf-sch-bar' })
          ]),
          F.el('div', { class: 'pf-sch-v mono' })
        ]));
      });
    }
    [].forEach.call(host.children, function (el) {
      var k = el.getAttribute('data-k');
      var v = cuts[k];
      var bar = el.querySelector('.pf-sch-bar');
      bar.style.width = (Math.max(0, v) / max * 100).toFixed(2) + '%';
      bar.classList.toggle('is-fail', v < thr);
      el.querySelector('.pf-sch-v').textContent = fmt.share(v, 1);
      el.querySelector('.pf-sch-v').className = 'pf-sch-v mono' + (v < thr ? ' u-accent' : '');
    });

    var vals = keys.map(function (k) { return cuts[k]; });
    var pass = vals.filter(function (v) { return v >= thr; }).length;
    setText('pf-scheme-note',
      'The headline uses the sector median. Under all four rules the cut lands between ' +
      fmt.share(Math.min.apply(null, vals), 1) + ' and ' + fmt.share(Math.max.apply(null, vals), 1) +
      ', and ' + (pass === 4 ? 'all four clear the 50% line, so the Article 11 verdict does not turn on the assumption.'
        : pass + ' of the four clear the 50% line, so the Article 11 verdict does turn on the assumption.') +
      ' The intensity level does turn on it: the universe reads ' +
      fmt.num(D.universe.waci.imputed, 2) + ' imputed and ' + fmt.num(D.universe.waci.available_case, 2) +
      ' if you look only at the names that file.');
  }

  /* --- the closing sentence under the waterfall --- */

  function paintSay(key, s) {
    var b = BOOKS.filter(function (x) { return x.key === key; })[0];

    setHtml('pf-verdict-txt',
      'of the intensity cut in <b>' + b.name + '</b> is reallocation between sectors. ' +
      'The money moved. The factories did not. Improvement, which is the same companies ' +
      'emitting less than they did in ' + D.meta.base_year + ', is <b class="u-cool">' +
      fmt.share(s.improvement / s.total, 1) + '</b> of it. The overlap between the two gives ' +
      fmt.share(Math.abs(s.interaction / s.total), 1) + ' of that straight back.');

    setText('pf-plot-note',
      'The dashed line is the universe re-measured in ' + D.meta.latest_year + ' at ' +
      fmt.num(D.universe.waci.imputed, 2) + '. Everything between it and ' +
      fmt.num(s.base, 2) + ' is the whole index\'s own five-year improvement, all ' +
      fmt.num(Math.abs(s.improvement), 2) + ' of it. Everything below it was bought by ' +
      'changing who you own.');

    var el = document.getElementById('pf-reveal-say');
    el.innerHTML = '';
    el.appendChild(F.el('p', {
      html: b.name + ' cuts intensity from <span class="mono">' + fmt.num(s.base, 2) +
        '</span> to <span class="mono">' + fmt.num(s.waci, 2) + '</span>, a <span class="mono">' +
        fmt.share(s.cut, 1) + '</span> cut against the investable universe, which is what ' +
        'Article 11 measures. Of that move, <b class="u-accent">' +
        fmt.share(s.reallocation / s.total, 1) + '</b> is money leaving utilities and oil for ' +
        'software and health care.'
    }));
    el.appendChild(F.el('p', {
      class: 'u-mt4',
      html: 'Interaction is positive because a Paris-aligned book sells the fastest ' +
        'decarbonisers. The companies cutting hardest are utilities and heavy industry, which ' +
        'are exactly the names Article 12 and the intensity constraint throw out, so the ' +
        'improvement they deliver leaves the book with them. Nothing here changes a single ' +
        'tonne. The <span class="mono">$1bn</span> is <span class="mono">' +
        fmt.share(D.meta.aum_share_of_index, 5) + '</span> of the index.'
    }));
  }

  /* ================= helpers ================= */

  function setText(id, t) { var e = document.getElementById(id); if (e) e.textContent = t; }
  function setHtml(id, h) { var e = document.getElementById(id); if (e) e.innerHTML = h; }
  function esc(s) {
    return String(s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }

  /* ================= css =================
     Scoped to #portfolio so it cannot touch another agent's section. Tokens
     that only this section needs are declared on #portfolio itself. */

  function injectCss() {
    if (document.getElementById('pf-css')) return;
    var css = [
      '#portfolio { --pf-anchor:#2f3742; --pf-anchor-2:#48535f; --pf-ok:var(--cool); }',
      '#portfolio-body > * + * { margin-top: var(--s5); }',
'#portfolio .panel-head > div:first-child { flex:1 1 auto; min-width:0; }',
'#portfolio .panel-n { flex:0 0 auto; }',

      /* mandate */
      '.pf-mandate { display:flex; gap:var(--s6); align-items:flex-start; border:1px solid var(--rule);',
      '  border-left:2px solid var(--accent); background:var(--bg-1); padding:var(--s4) var(--s5); }',
      '.pf-aum { flex:none; }',
      '.pf-aum-fig { font-size:34px; font-weight:600; letter-spacing:-0.02em; line-height:1.1; }',
      '.pf-aum-k { font-size:var(--fs-sm); color:var(--ink-3); margin-top:var(--s1); max-width:34ch; }',
      '.pf-mandate-kv { display:grid; grid-template-columns:repeat(3,1fr); gap:var(--s2) var(--s5); flex:1; }',
      '.pf-kv-k { font-size:13px; color:var(--ink-3); }',
      '.pf-kv-v { font-size:var(--fs-sm); color:var(--ink); }',

      /* picker */
      '.pf-pick { display:grid; grid-template-columns:repeat(3,1fr); gap:var(--s4); }',
      '.pf-card { text-align:left; font:inherit; color:inherit; cursor:pointer;',
      '  background:var(--bg-1); border:1px solid var(--rule); border-top:2px solid var(--rule-2);',
      '  padding:var(--s4); display:flex; flex-direction:column; gap:var(--s3); min-width:0; }',
      '.pf-card:hover { background:var(--bg-2); }',
      '.pf-card.is-on { border-top-color:var(--accent); background:var(--bg-2); border-color:var(--rule-2); }',
      '.pf-card-top { display:flex; align-items:baseline; gap:var(--s2); }',
      '.pf-card-name { font-size:var(--fs-h3); font-weight:600; }',
      '.pf-card.is-on .pf-card-name { color:var(--accent-2); }',
      '.pf-card-sub { font-size:var(--fs-sm); color:var(--ink-3); line-height:1.4; min-height:42px; }',
      '.pf-card-figs { display:grid; grid-template-columns:repeat(3,1fr); gap:var(--s2);',
      '  border-top:1px solid var(--rule); padding-top:var(--s3); }',
      '.pf-card-fig-v { font-size:22px; font-weight:600; letter-spacing:-0.02em; }',
      '.pf-card-fig-k { font-size:12px; color:var(--ink-3); }',
      '.pf-card-flags { display:flex; gap:var(--s2); flex-wrap:wrap; }',

      '.pf-pick-note { margin-top:var(--s4); }',

      /* verdict chip */
      '.pf-vchip { font-family:var(--font-mono); font-size:12px; letter-spacing:0.06em;',
      '  text-transform:uppercase; padding:2px 7px; border:1px solid currentColor; white-space:nowrap; }',
      '.pf-vchip.is-pass { color:var(--cool); }',
      '.pf-vchip.is-fail { color:var(--accent); background:var(--accent-dim); }',
      '.pf-vchip.is-open { color:var(--muted-ink); }',

      /* tiles */
      '.pf-tiles { display:grid; grid-template-columns:repeat(6,1fr); gap:var(--s4); }',
      '.pf-tile { border-top:2px solid var(--rule-2); padding-top:var(--s3); }',
      '.pf-tile.is-cool { border-top-color:var(--cool); }',
      '.pf-tile-v { font-size:38px; font-weight:600; letter-spacing:-0.03em; line-height:1; }',
      '.pf-tile.is-cool .pf-tile-v { color:var(--cool); }',
      '.pf-tile-k { font-size:var(--fs-sm); font-weight:600; margin-top:var(--s3); line-height:1.3; }',
      '.pf-tile-u { font-size:12px; color:var(--ink-3); margin-top:var(--s1); }',

      /* article table. app.css right-aligns and monospaces every .tbl td, so an
         override needs two classes to win on specificity. */
      '.pf-art { table-layout:fixed; }',
      '.pf-art td { vertical-align:top; padding-top:var(--s3); padding-bottom:var(--s3); }',
      '.pf-art td.pf-art-no { color:var(--ink-2); }',
      '.pf-art td.pf-art-test { text-align:left; font-family:var(--font-sans); line-height:1.4; }',
      '.pf-quote { color:var(--ink-3); font-size:var(--fs-sm); margin-top:var(--s2);',
      '  border-left:2px solid var(--rule-2); padding-left:var(--s3); line-height:1.4; }',
      '.pf-art td.pf-art-got { font-weight:600; }',
      '.pf-art tr.is-fail td.pf-art-got { color:var(--accent); }',

      /* holdings */
      '.pf-hold { table-layout:fixed; }',
      '.pf-hold tbody { transition:opacity 150ms linear, transform 150ms ease-out; }',
      '.pf-hold tbody.is-swap { opacity:0.06; transform:translateY(5px); }',
      '.pf-hold td { vertical-align:middle; }',
      '.pf-hold td.pf-l { text-align:left; }',
      '.pf-hold td.pf-tick { font-weight:600; }',
      '.pf-hold td.pf-basis-measured_mandatory { color:var(--tier-measured); }',
      '.pf-hold td.pf-basis-ghgrp_threshold_bound { color:var(--tier-reported); }',
      '.pf-hold td.pf-basis-sector_median_imputed { color:var(--muted-ink); }',
      '.pf-hold td.pf-w { position:relative; overflow:hidden; }',
      '.pf-wbar-f { position:absolute; right:0; top:0; bottom:0; display:block; z-index:0;',
      '  background:rgba(170,179,191,0.13); }',
      '.pf-hold td.pf-w > span:not(.pf-wbar-f) { position:relative; z-index:1; }',
      '.pf-capped { font-size:11px; letter-spacing:0.08em; text-transform:uppercase;',
      '  color:var(--accent); margin-left:6px; }',

      /* exclusions */
      '.pf-excl-grid { display:grid; grid-template-columns:1fr 400px; gap:var(--s5); align-items:stretch; }',
      '.pf-rules td { vertical-align:middle; }',
      '.pf-rules td.pf-rule-k { text-align:left; }',
      '.pf-rule-t { font-family:var(--font-sans); color:var(--ink); }',
      '.pf-chips-head { font-size:var(--fs-sm); color:var(--ink-3); margin-bottom:var(--s3); }',
      '.pf-chips { display:flex; flex-wrap:wrap; gap:5px; }',
      '.pf-x { font-size:12px; letter-spacing:0.04em; padding:3px 6px; border:1px solid var(--rule-2);',
      '  color:var(--ink-3); background:var(--bg-sunk); }',
      '.pf-x.is-held { color:var(--accent); border-color:var(--accent); background:var(--accent-dim); }',
      '.pf-chips-foot { font-size:var(--fs-sm); color:var(--ink-3); margin-top:var(--s3);',
      '  border-top:1px solid var(--rule); padding-top:var(--s3); }',
      '.pf-chips-foot.is-fail { color:var(--accent-2); }',

      /* reveal */
      '.pf-reveal { border-color:var(--rule-2); }',
      '.pf-verdict { display:flex; gap:var(--s5); align-items:center; margin-bottom:var(--s4); }',
      '.pf-verdict-fig { font-size:76px; font-weight:600; letter-spacing:-0.04em; line-height:1;',
      '  color:var(--accent); flex:none; }',
      '.pf-verdict-txt { font-size:17px; color:var(--ink-2); max-width:64ch; line-height:1.45; }',
      '.pf-verdict-txt b { color:var(--ink); font-weight:600; }',
      '.pf-plot { background:var(--bg-sunk); border:1px solid var(--rule); padding:var(--s3) var(--s4); }',
      '.pf-legend { margin-top:var(--s3); }',
      '.pf-plot-note { font-size:var(--fs-sm); color:var(--ink-3); margin-top:var(--s3);',
      '  line-height:1.45; max-width:92ch; }',
      '.pf-bar { shape-rendering:crispEdges; }',
      '.pf-conn { stroke:var(--rule-2); stroke-width:1; stroke-dasharray:3 3; shape-rendering:crispEdges; }',
      '.pf-bar-v { font-size:17px; font-weight:600; }',
      '.pf-bar-s { font-size:13px; }',
      '.pf-cat { font-family:var(--font-sans); font-size:var(--fs-sm); font-weight:600; }',
      '.pf-cat2 { font-family:var(--font-sans); font-size:13px; }',
      '.pf-ref-lab { font-size:13px; }',
      '.pf-reveal-say { margin-top:var(--s5); border-top:1px solid var(--rule); padding-top:var(--s4);',
      '  font-size:17px; color:var(--ink-2); line-height:1.5; max-width:92ch; }',
      '.pf-reveal-say b { font-weight:600; }',

      /* two up rows */
      '.pf-row2 { display:grid; grid-template-columns:1fr 1fr; gap:var(--s5); align-items:stretch; }',
      '.pf-row2 > .panel + .panel { margin-top:0; }',

      /* sector bars */
      '.pf-sec { display:grid; grid-template-columns:130px 1fr 74px; gap:var(--s3);',
      '  align-items:center; padding:3px 0; }',
      '.pf-sec-k { font-size:var(--fs-sm); color:var(--ink-2); }',
      '.pf-sec-track { position:relative; height:13px; background:var(--bg-sunk); border:1px solid var(--rule); }',
      '.pf-sec-zero { position:absolute; left:50%; top:0; bottom:0; width:1px; background:var(--rule-2); }',
      '.pf-sec-bar { position:absolute; top:1px; bottom:1px; background:var(--cool); }',
      '.pf-sec-bar.is-neg { background:var(--accent); }',
      '.pf-sec-v { font-size:var(--fs-sm); text-align:right; }',

      /* kept improvement */
      '.pf-keep td { vertical-align:middle; }',
      '.pf-keep td.t-name { text-align:left; }',
      '.pf-keep tr.is-on td { color:var(--ink); background:var(--bg-2); }',
      '.pf-kbar { display:inline-block; width:70px; height:7px; background:var(--bg-sunk);',
      '  border:1px solid var(--rule); margin-right:var(--s2); vertical-align:middle; }',
      '.pf-kbar-f { display:block; height:100%; background:var(--rule-2); }',
      '.pf-kbar-f.is-on { background:var(--cool); }',

      /* tracking error */
      '.pf-te-row { display:grid; grid-template-columns:170px 1fr 60px; gap:var(--s3);',
      '  align-items:center; padding:5px 0; }',
      '.pf-te-k { font-size:var(--fs-sm); color:var(--ink-3); line-height:1.3; }',
      '.pf-te-row.is-on .pf-te-k { color:var(--ink); }',
      '.pf-te-row.is-ctrl .pf-te-k { color:var(--ink-2); }',
      '.pf-te-track { position:relative; height:15px; background:var(--bg-sunk); border:1px solid var(--rule); }',
      '.pf-te-bar { position:absolute; left:0; top:3px; bottom:3px; background:var(--rule-2); }',
      '.pf-te-row.is-on .pf-te-bar { background:var(--ink-2); }',
      '.pf-te-row.is-ctrl .pf-te-bar { background:var(--muted); }',
      '.pf-te-ci { position:absolute; top:0; bottom:0; background:rgba(170,179,191,0.16);',
      '  border-left:1px solid var(--ink-3); border-right:1px solid var(--ink-3); }',
      '.pf-te-v { font-size:var(--fs-sm); text-align:right; color:var(--ink-2); }',
      '.pf-te-row.is-on .pf-te-v { color:var(--ink); }',

      /* missing data schemes */
      '.pf-sch { display:grid; grid-template-columns:210px 1fr 56px; gap:var(--s3);',
      '  align-items:center; padding:5px 0; }',
      '.pf-sch-k { font-size:var(--fs-sm); color:var(--ink-2); line-height:1.3; }',
      '.pf-sch-track { position:relative; height:15px; background:var(--bg-sunk); border:1px solid var(--rule); }',
      '.pf-sch-bar { position:absolute; left:0; top:3px; bottom:3px; background:var(--cool); }',
      '.pf-sch-bar.is-fail { background:var(--accent); }',
      '.pf-sch-thr { position:absolute; top:-2px; bottom:-2px; width:2px; background:var(--ink); }',
      '.pf-sch-v { font-size:var(--fs-sm); text-align:right; }',

      '.pf-attrib { font-size:13px; color:var(--ink-3); margin-top:var(--s4);',
      '  border-top:1px solid var(--rule); padding-top:var(--s3); }',

      '@media (prefers-reduced-motion: no-preference) {',
      '  .pf-wbar-f, .pf-sec-bar, .pf-te-bar, .pf-te-ci, .pf-sch-bar, .pf-kbar-f {',
      '    transition: width 480ms cubic-bezier(.4,0,.2,1), left 480ms cubic-bezier(.4,0,.2,1),',
      '                background-color 240ms linear; }',
      '  .pf-x { transition: color 320ms linear, border-color 320ms linear, background-color 320ms linear; }',
      '  .pf-card, .pf-vchip { transition: border-color 160ms linear, color 160ms linear,',
      '                                    background-color 160ms linear; }',
      '}'
    ].join('\n');
    document.head.appendChild(F.el('style', { id: 'pf-css', text: css }));
  }

}());
