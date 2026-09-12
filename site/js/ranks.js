/* Rank intervals: the interval itself, the Sobol variance shares, the weight audit,
   the Pareto front and what would narrow the band.

   Every figure is read out of scores.json. Nothing numeric is typed into the
   markup. The section owns only #ranks-body and one scoped <style>, because
   four agents write into this page and app.css is shared. */
(function () {
  'use strict';

  var F = window.FILED;
  var fmt = F.fmt;

  /* Plain names for the seven modelling choices. The shares always come from
     the JSON; only the wording is ours. */
  var FACTOR_LABEL = {
    missing_data:     'the missing-data assumption',
    pillar_inclusion: 'which pillars are in',
    sector_relative:  'judged against its sector, or against everyone',
    normalisation:    'how scores are put on one scale',
    weights:          'the weights',
    aggregation:      'how the four pillars are combined',
    winsorisation:    'trimming the extremes'
  };

  /* the file's own setting names, in words. Only the wording is ours. */
  var SETTING_LABEL = {
    'Dirichlet(1,1,1,1) over the four pillars': 'every weighting, drawn at random'
  };
  var BAND_LABEL = {
    'all triggers live': 'nothing held fixed, which is what we publish',
    'available-case only': 'measured companies only',
    'NMAR-pessimistic only': 'pessimistic about the non-filers only',
    'copeland only': 'one way of combining the pillars, fixed',
    'linear only': 'the other way of combining them, fixed',
    'absolute lens only': 'judged against everyone, never the sector',
    'sector-relative only': 'judged against its own sector, always',
    'sector-median only': 'one missing-data rule, fixed',
    'global percentile only': 'one way of scaling the scores, fixed',
    'all four pillars kept': 'all four pillars, always',
    'absolute + sector-median + all four pillars': 'those three held together',
    'absolute + available-case + all four pillars': 'those three, on measured companies only'
  };
  function bandLabel(k) {
    return BAND_LABEL[k] || k.replace(/ only$/, ' held fixed');
  }

  var state = {
    D: null,
    rows: [],                 /* every company, sorted by median rank */
    visible: [],              /* the rows passing the current filters */
    pinned: null,
    sector: 'all',
    tiers: { measured: true, reported: true, unmeasurable: true },
    sobolTier: 'all',
    geom: null
  };

  F.onReady(function (D) {
    state.D = D;
    injectCss();
    document.getElementById('ranks-body').innerHTML = skeleton(D);
    buildRows(D);
    wireControls(D);
    drawBands();
    defaultCard(D);
    renderSobol(D);
    renderWeights(D);
    renderPareto(D);
    renderConditional(D);

    var t = null;
    window.addEventListener('resize', function () {
      clearTimeout(t);
      t = setTimeout(drawBands, 180);
    });
  });

  /* ---------------- scoped styles ----------------
     Scoped to #ranks so nothing here can reach another agent's section. */

  function injectCss() {
    var css = [
      '#ranks .rk-grid{display:grid;grid-template-columns:1fr 340px;gap:var(--s5);align-items:stretch}',
      '#ranks .rk-two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--s5);align-items:stretch}',
      '#ranks .rk-two > *{min-width:0}',
      '#ranks .rk-two > .panel + .panel{margin-top:0}',
            /* the tallest state the card ever takes, so hovering a row never moves
         the page under the pointer */
      '#ranks .card{min-height:725px}',

      /* controls */
      '#ranks .rk-ctl{display:flex;gap:var(--s2);align-items:center;flex-wrap:wrap;margin-bottom:var(--s2)}',
      '#ranks .rk-ctl .lab{font-size:13px;color:var(--ink-3);letter-spacing:.06em;text-transform:uppercase;font-family:var(--font-mono)}',
      '#ranks .rk-in,#ranks .rk-sel{background:var(--bg-sunk);border:1px solid var(--rule-2);color:var(--ink);' +
        'font-size:var(--fs-sm);padding:5px 8px;font-family:var(--font-mono)}',
      '#ranks .rk-in{width:118px}',
      '#ranks .rk-in::placeholder{color:var(--ink-3)}',
      '#ranks .rk-in:focus,#ranks .rk-sel:focus{outline:1px solid var(--accent);border-color:var(--accent)}',
      '#ranks .rk-sel{font-family:var(--font-sans);max-width:210px}',
      '#ranks .rk-tog{font-family:var(--font-mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase;' +
        'padding:3px 7px;border:1px solid currentColor;background:transparent;cursor:pointer}',
      '#ranks .rk-tog[data-on="0"]{color:var(--rule-2)}',
      '#ranks .rk-tog[data-tier="measured"][data-on="1"]{color:var(--tier-measured)}',
      '#ranks .rk-tog[data-tier="reported"][data-on="1"]{color:var(--tier-reported)}',
      '#ranks .rk-tog[data-tier="unmeasurable"][data-on="1"]{color:var(--muted-ink)}',
      '#ranks .rk-clear{font-family:var(--font-mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase;' +
        'padding:3px 7px;border:1px solid var(--rule-2);background:transparent;color:var(--ink-3);cursor:pointer}',
      '#ranks .rk-clear:hover{color:var(--ink)}',
      '#ranks .rk-hit{font-size:13px;color:var(--ink-3);font-family:var(--font-mono)}',
      '#ranks .rk-hit.is-miss{color:var(--accent)}',

      /* the band plot */
      '#ranks #rk-chart svg{cursor:crosshair}',
      '#ranks .rk-foot{display:flex;justify-content:space-between;gap:var(--s4);flex-wrap:wrap;' +
        'align-items:center;margin-top:var(--s2)}',
      '#ranks .rk-foot .rk-note{font-size:13px;color:var(--ink-3);max-width:44ch}',

      /* card extras */
      '#ranks .rk-big{font-family:var(--font-mono);font-size:46px;font-weight:600;letter-spacing:-.03em;line-height:1}',
      '#ranks .rk-big .of{font-size:24px;color:var(--ink-3)}',
      '#ranks .rk-biglab{font-size:var(--fs-sm);font-weight:600;margin-top:var(--s2)}',
      '#ranks .rk-sub{font-size:13px;color:var(--ink-3);line-height:1.45;margin-top:4px}',
      '#ranks .rk-finding{font-size:var(--fs-body);color:var(--ink);max-width:86ch;' +
        'border-left:2px solid var(--accent);padding-left:var(--s3)}',
      '#ranks .rk-pill{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:var(--s3)}',
      '#ranks .rk-pill div{border-top:1px solid var(--rule-2);padding-top:4px}',
      '#ranks .rk-pill .pk{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}',
      '#ranks .rk-pill .pv{font-family:var(--font-mono);font-size:17px}',

      /* sobol */
      '#ranks .rk-seg{display:flex;gap:0;margin-bottom:var(--s4);border:1px solid var(--rule-2);width:max-content}',
      '#ranks .rk-seg button{font-family:var(--font-mono);font-size:12px;letter-spacing:.05em;text-transform:uppercase;' +
        'background:transparent;border:0;border-right:1px solid var(--rule-2);color:var(--ink-3);padding:5px 9px;cursor:pointer}',
      '#ranks .rk-seg button:last-child{border-right:0}',
      '#ranks .rk-seg button[data-on="1"]{background:var(--bg-2);color:var(--ink)}',
      '#ranks .sob-row{display:grid;grid-template-columns:176px minmax(0,1fr) 58px;gap:var(--s3);' +
        'align-items:center;padding:5px 0;border-bottom:1px solid var(--rule)}',
      '#ranks .sob-row:last-child{border-bottom:0}',
      '#ranks .sob-k{font-size:var(--fs-sm);color:var(--ink-2);line-height:1.25}',
      '#ranks .sob-k .opt{display:block;font-size:12px;color:var(--ink-3);font-family:var(--font-mono)}',
      '#ranks .sob-track{height:14px;background:var(--bg-sunk);position:relative}',
      '#ranks .sob-bar{position:absolute;left:0;top:0;bottom:0;background:var(--rule-2)}',
      '#ranks .sob-v{font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-size:var(--fs-sm);text-align:right}',
      '#ranks .sob-row.is-key .sob-k{color:var(--accent-2)}',
      '#ranks .sob-row.is-key .sob-bar{background:var(--accent)}',
      '#ranks .sob-row.is-key .sob-v{color:var(--accent-2)}',
      '#ranks .sob-rest{display:grid;grid-template-columns:176px minmax(0,1fr) 58px;gap:var(--s3);' +
        'align-items:center;padding:8px 0 0 0;margin-top:var(--s2);border-top:1px solid var(--rule-2)}',
      '#ranks .sob-rest .sob-bar{background:var(--muted)}',
      '#ranks .sob-rest .sob-k,#ranks .sob-rest .sob-v{color:var(--muted-ink)}',

      /* weight audit */
      '#ranks #rk-weights{max-width:760px}',
      '#ranks .wa-row{display:grid;grid-template-columns:138px minmax(0,1fr) 56px;gap:var(--s3);' +
        'align-items:center;padding:7px 0}',
      '#ranks .wa-k{font-family:var(--font-mono);font-size:var(--fs-sm);color:var(--ink)}',
      '#ranks .wa-k span{display:block;font-family:var(--font-sans);font-size:12px;color:var(--ink-3);line-height:1.3}',
      '#ranks .wa-track{position:relative;height:20px;background:var(--bg-sunk)}',
      '#ranks .wa-seg{position:absolute;top:9px;height:2px;background:var(--rule-2)}',
      '#ranks .wa-seg.is-up{background:var(--cool)}',
      '#ranks .wa-seg.is-dn{background:var(--accent)}',
      '#ranks .wa-nom{position:absolute;top:2px;bottom:2px;width:1px;background:var(--ink-3)}',
      '#ranks .wa-eff{position:absolute;top:4px;width:12px;height:12px;margin-left:-6px;background:var(--ink)}',
      '#ranks .wa-eff.is-up{background:var(--cool)}',
      '#ranks .wa-eff.is-dn{background:var(--accent)}',
      '#ranks .wa-v{font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-size:var(--fs-sm);text-align:right}',
      '#ranks .wa-head{display:flex;justify-content:space-between;gap:var(--s3);font-size:12px;' +
        'color:var(--ink-3);font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase}',
      '#ranks .dm-list{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);' +
        'grid-template-rows:repeat(4,auto);grid-auto-flow:column;gap:2px var(--s5);margin-top:var(--s3)}',
      '#ranks .dm-list div{display:flex;justify-content:space-between;gap:var(--s3);font-size:13px;' +
        'color:var(--ink-3);border-bottom:1px solid var(--rule);padding:3px 0}',
      '#ranks .dm-list div.is-ours{color:var(--accent-2)}',
      '#ranks .dm-list b{font-family:var(--font-mono);font-weight:400;font-variant-numeric:tabular-nums}',

      /* pareto */
      '#ranks .rk-par{display:grid;grid-template-columns:1fr 512px;gap:var(--s5);align-items:stretch}',
      '#ranks .par-list{margin-top:var(--s3)}',
      '#ranks .par-row{display:flex;align-items:baseline;gap:var(--s3);padding:5px 0;border-bottom:1px solid var(--rule)}',
      '#ranks .par-row .pt-t{font-family:var(--font-mono);font-size:var(--fs-sm);width:56px;color:var(--ink)}',
      '#ranks .par-row .pt-n{font-size:13px;color:var(--ink-2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '#ranks .par-row .pt-r{font-family:var(--font-mono);font-size:13px;color:var(--ink-3);white-space:nowrap}',
      '#ranks .fronts{display:flex;gap:2px;margin-top:var(--s3)}',
      '#ranks .fronts span{display:block;height:10px}',
      '#ranks .par-stat{font-size:17px;color:var(--ink-2);line-height:1.35}',
      '#ranks .par-stat b{font-family:var(--font-mono);font-size:26px;color:var(--accent-2);' +
        'font-weight:600;letter-spacing:-.02em}',

      /* conditional bands */
      '#ranks .cb-row{display:grid;grid-template-columns:270px minmax(0,1fr) 64px 74px;gap:var(--s3);align-items:center;' +
        'padding:4px 0;border-bottom:1px solid var(--rule)}',
      '#ranks .cb-row:last-child{border-bottom:0}',
      '#ranks .cb-k{font-size:var(--fs-sm);color:var(--ink-2)}',
      '#ranks .cb-track{position:relative;height:13px;background:var(--bg-sunk);overflow:hidden}',
      '#ranks .cb-bar{position:absolute;left:0;top:0;bottom:0;background:var(--rule-2)}',
      '#ranks .cb-tick{position:absolute;top:0;bottom:0;width:3px;margin-left:-1.5px;background:var(--tier-measured)}',
      '#ranks .cb-v{font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-size:var(--fs-sm);text-align:right}',
      '#ranks .cb-n{color:var(--ink-3);font-size:12px}',
      '#ranks .cb-n{font-family:var(--font-mono);font-size:12px;color:var(--ink-3);text-align:right}',
      '#ranks .cb-row.is-live .cb-k,#ranks .cb-row.is-live .cb-v{color:var(--accent-2)}',
      '#ranks .cb-row.is-live .cb-bar{background:var(--accent)}',
      '#ranks .cb-head{display:grid;grid-template-columns:270px minmax(0,1fr) 64px 74px;gap:var(--s3);font-size:12px;' +
        'color:var(--ink-3);font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;' +
        'padding-bottom:4px;border-bottom:1px solid var(--rule-2)}',
      '#ranks .cb-head .r{text-align:right}',

      '@media (prefers-reduced-motion: no-preference){',
      '#ranks .sob-bar{transition:width 280ms ease}',
      '#ranks .rk-tog,#ranks .rk-seg button{transition:color 120ms linear,background 120ms linear}}'
    ].join('\n');
    document.head.appendChild(F.el('style', { text: css }));
  }

  /* ---------------- skeleton ---------------- */

  function skeleton(D) {
    var m = D.scores.meta;
    return '' +
      '<div class="rk-grid">' +
        '<div class="chart-wrap">' +
          '<div class="panel-head" style="margin-bottom:12px">' +
            '<div class="panel-title">Every company, ordered by median rank</div>' +
            '<div class="panel-n" id="rk-n"></div>' +
          '</div>' +
          '<div class="rk-ctl">' +
            '<input class="rk-in" id="rk-search" type="search" placeholder="ticker" ' +
              'aria-label="find a company">' +
            '<span class="rk-hit" id="rk-hit"></span>' +
            '<span style="flex:1"></span>' +
            '<select class="rk-sel" id="rk-sector" aria-label="filter by sector"></select>' +
            '<span id="rk-tiers"></span>' +
            '<button class="rk-clear" id="rk-clear" type="button">reset</button>' +
          '</div>' +
          '<div id="rk-chart"></div>' +
          '<div class="rk-foot">' +
            '<div class="legend" id="rk-legend"></div>' +
            '<div class="rk-note">One row per company, sorted by median rank, rank 1 is best. ' +
              'The bands are what ' + fmt.int(m.n_draws) + ' draws of the ' +
              'modelling choices do to the order. Filtering hides rows, it never re-ranks: the axis ' +
              'is always the rank inside all ' + fmt.int(m.n_companies) + '.</div>' +
          '</div>' +
        '</div>' +
        '<aside class="card" id="rk-card"></aside>' +
      '</div>' +
      '<div class="note u-mt4">' +
        m.what_this_is_not.replace('revenue_exclusions.parquet', 'a separate revenue table') +
        '</div>' +
      '<p class="rk-finding u-mt4">What we assume about the companies we cannot measure ' +
        'moves a company\u2019s rank further than the weights do. The weights are the thing ' +
        'everyone argues about.</p>' +

      F.detailsHTML('What moves a rank',
        Object.keys(m.trigger_factors).length + ' choices &times; <b>' +
          fmt.int(m.n_draws) + '</b> draws',
        '<div class="panel-sub">How much of a company\u2019s rank movement each choice ' +
          'explains on its own. <span class="panel-n" id="rk-sob-n"></span></div>' +
        '<div class="rk-seg u-mt4" id="rk-seg"></div>' +
        '<div id="rk-sobol"></div>' +
        '<div class="note u-mt4" id="rk-sobol-note"></div>') +

      F.detailsHTML('Stated weights against the weights that do the work', '4 pillars',
        '<div id="rk-weights"></div>') +

      '<div id="rk-pareto" class="u-mt5"></div>' +

      F.detailsHTML('What would narrow the band',
        Object.keys(D.scores.conditional_bands).length + ' slices, <b>n = ' +
          fmt.int(m.n_companies) + '</b>',
        '<div class="panel-sub">The same ' + fmt.int(m.n_draws) + ' draws, sliced by the ' +
          'choices held fixed. Fixing a choice buys precision only if the choice is ' +
          'defensible.</div>' +
        '<div class="u-mt4" id="rk-cond"></div>' +
        '<div class="note u-mt4" id="rk-cond-note"></div>');
  }

  /* ---------------- rows and filters ---------------- */

  function buildRows(D) {
    state.rows = D.scores.companies.slice().sort(function (a, b) {
      return a.med - b.med || (a.p95 - a.p05) - (b.p95 - b.p05) || (a.t < b.t ? -1 : 1);
    });
    state.rows.forEach(function (c, i) { c._i = i; });
  }

  function wireControls(D) {
    /* sector list with counts, straight off the data */
    var counts = {};
    state.rows.forEach(function (c) { counts[c.s] = (counts[c.s] || 0) + 1; });
    var sectors = Object.keys(counts).sort();
    var sel = document.getElementById('rk-sector');
    sel.innerHTML = '<option value="all">All sectors (' + state.rows.length + ')</option>' +
      sectors.map(function (s) {
        return '<option value="' + s + '">' + s + ' (' + counts[s] + ')</option>';
      }).join('');
    sel.addEventListener('change', function () {
      state.sector = sel.value;
      applyFilters();
    });

    var tierCounts = D.scores.coverage.by_tier;
    var host = document.getElementById('rk-tiers');
    host.innerHTML = F.tierOrder.map(function (t) {
      return '<button class="rk-tog" type="button" data-tier="' + t + '" data-on="1" ' +
        'title="' + F.tier(t).desc + '">' + F.tier(t).short + ' ' + fmt.int(tierCounts[t] || 0) +
        '</button>';
    }).join(' ');
    [].forEach.call(host.querySelectorAll('.rk-tog'), function (b) {
      b.addEventListener('click', function () {
        var t = b.getAttribute('data-tier');
        state.tiers[t] = !state.tiers[t];
        /* never leave every tier off: the chart would say nothing */
        if (!state.tiers.measured && !state.tiers.reported && !state.tiers.unmeasurable) {
          state.tiers[t] = true;
          return;
        }
        b.setAttribute('data-on', state.tiers[t] ? '1' : '0');
        applyFilters();
      });
    });

    var search = document.getElementById('rk-search');
    search.addEventListener('input', function () { runSearch(search.value); });

    document.getElementById('rk-clear').addEventListener('click', function () {
      state.sector = 'all';
      state.tiers = { measured: true, reported: true, unmeasurable: true };
      state.pinned = null;
      sel.value = 'all';
      search.value = '';
      document.getElementById('rk-hit').textContent = '';
      document.getElementById('rk-hit').className = 'rk-hit';
      [].forEach.call(host.querySelectorAll('.rk-tog'), function (b) {
        b.setAttribute('data-on', '1');
      });
      applyFilters();
      defaultCard(state.D);
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && state.pinned) { setPinned(null); }
    });
  }

  function runSearch(q) {
    var hit = document.getElementById('rk-hit');
    q = (q || '').trim();
    if (!q) {
      hit.textContent = '';
      hit.className = 'rk-hit';
      setPinned(null);
      return;
    }
    var up = q.toUpperCase(), low = q.toLowerCase();
    var exact = null, prefix = null, name = null;
    state.rows.forEach(function (c) {
      if (exact) return;
      if (c.t === up) { exact = c; return; }
      if (!prefix && c.t.indexOf(up) === 0) prefix = c;
      if (!name && c.n.toLowerCase().indexOf(low) >= 0) name = c;
    });
    var c = exact || prefix || name;
    if (!c) {
      hit.textContent = 'no match';
      hit.className = 'rk-hit is-miss';
      setPinned(null);
      return;
    }
    hit.textContent = c.n.length > 24 ? c.n.slice(0, 23) + '\u2026' : c.n;
    hit.className = 'rk-hit';
    /* a searched company is always shown, whatever the filters say */
    if (!passes(c)) {
      state.tiers[c.tier] = true;
      document.querySelector('#ranks .rk-tog[data-tier="' + c.tier + '"]').setAttribute('data-on', '1');
      if (state.sector !== 'all' && state.sector !== c.s) {
        state.sector = 'all';
        document.getElementById('rk-sector').value = 'all';
      }
      applyFilters();
    }
    setPinned(c);
  }

  function passes(c) {
    if (!state.tiers[c.tier]) return false;
    if (state.sector !== 'all' && c.s !== state.sector) return false;
    return true;
  }

  function applyFilters() {
    if (state.pinned && !passes(state.pinned)) state.pinned = null;
    drawBands();
    if (state.pinned) fillCard(state.pinned); else defaultCard(state.D);
  }

  function filtered() {
    return state.sector !== 'all' || !state.tiers.measured ||
      !state.tiers.reported || !state.tiers.unmeasurable;
  }

  function median(a) {
    if (!a.length) return 0;
    var v = a.slice().sort(function (p, q) { return p - q; });
    var i = (v.length - 1) / 2;
    return (v[Math.floor(i)] + v[Math.ceil(i)]) / 2;
  }

  function setPinned(c) {
    state.pinned = c;
    var card = document.getElementById('rk-card');
    if (c) { card.classList.add('is-pinned'); fillCard(c); }
    else { card.classList.remove('is-pinned'); defaultCard(state.D); }
    drawHighlight();
  }

  /* ---------------- the band plot ---------------- */

  function drawBands() {
    var D = state.D;
    var host = document.getElementById('rk-chart');
    if (!host) return;
    host.innerHTML = '';

    var N = state.rows.length;
    var W = Math.max(420, host.clientWidth || 598);
    /* One row must land on one whole pixel or the bands antialias into the
       plot ground and the wall reads as noise. 500 rows + the margins. */
    var M = { t: 30, r: 14, b: 44, l: 30 };
    var H = M.t + M.b + Math.max(350, N);
    var px0 = M.l, px1 = W - M.r, py0 = M.t, py1 = H - M.b;
    var plotH = py1 - py0;
    var rowStep = plotH / N;
    var x = F.scale([1, N], [px0, px1]);

    state.visible = [];
    state.rows.forEach(function (c) { if (passes(c)) state.visible.push(c); });
    var nv = state.visible.length;
    /* one row is a hairline when the whole index is shown, and grows as the
       filter narrows, so a 21-company sector is still visible in place */
    var barH = Math.max(rowStep, Math.min(7, plotH / Math.max(nv, 1) * 0.62));

    var svg = F.svg('svg', {
      width: W, height: H, role: 'img',
      'aria-label': 'Rank interval, 5th to 95th percentile, for ' + nv + ' companies'
    });

    svg.appendChild(F.svg('rect', {
      x: px0, y: py0, width: px1 - px0, height: plotH,
      fill: 'var(--bg-sunk)'
    }));

    F.axisX(svg, x, {
      y: py1, values: [1, 100, 200, 300, 400, N], grid: [py0, py1],
      fmt: function (v) { return fmt.int(v); },
      label: 'rank inside the S&P 500, 1 is best'
    });

    svg.appendChild(F.svg('text', {
      transform: 'translate(13,' + ((py0 + py1) / 2) + ') rotate(-90)',
      'text-anchor': 'middle', class: 'axis-label',
      text: fmt.int(N) + ' companies, ordered by median rank'
    }));

    /* the median band width, drawn at the same scale as the bands under it,
       so the headline figure is a length the eye can check */
    var mw = D.scores.rank_interval_summary.median_width;
    var ry = py0 - 7.5;
    svg.appendChild(F.svg('text', {
      x: px0, y: py0 - 17, class: 'tick-label',
      style: 'fill:var(--accent-2)',
      text: 'median band ' + fmt.num(mw, 1) + ' of ' + fmt.int(N) + ' ranks wide'
    }));
    svg.appendChild(F.svg('line', {
      x1: x(1), x2: x(1 + mw), y1: ry, y2: ry,
      style: 'stroke:var(--accent)', 'stroke-width': 2
    }));
    [1, 1 + mw].forEach(function (v) {
      svg.appendChild(F.svg('line', {
        x1: x(v), x2: x(v), y1: ry - 4, y2: ry + 4,
        style: 'stroke:var(--accent)', 'stroke-width': 2
      }));
    });

    var gBands = F.svg('g', {});
    svg.appendChild(gBands);

    state.visible.forEach(function (c) {
      var yc = py0 + (c._i + 0.5) * rowStep;
      var xa = x(c.p05), xb = x(c.p95);
      gBands.appendChild(F.svg('rect', {
        x: xa.toFixed(2), y: (yc - barH / 2).toFixed(2),
        width: Math.max(1.2, xb - xa).toFixed(2), height: barH.toFixed(2),
        class: 'tier-' + c.tier
      }));
    });

    /* the medians. Sorted by median, so with the whole index up they form one
       monotone spine: a clean ranking buried under its own uncertainty. */
    if (nv > 120) {
      var pts = state.visible.map(function (c) {
        return x(c.med).toFixed(1) + ',' + (py0 + (c._i + 0.5) * rowStep).toFixed(1);
      }).join(' ');
      svg.appendChild(F.svg('polyline', {
        points: pts, fill: 'none', style: 'stroke:var(--ink)',
        'stroke-width': 1.4, 'stroke-opacity': 0.9
      }));
    } else {
      var gMed = F.svg('g', {});
      svg.appendChild(gMed);
      state.visible.forEach(function (c) {
        var yc = py0 + (c._i + 0.5) * rowStep;
        gMed.appendChild(F.svg('rect', {
          x: (x(c.med) - 1).toFixed(2), y: (yc - barH / 2).toFixed(2),
          width: 2, height: barH.toFixed(2), style: 'fill:var(--ink)'
        }));
      });
    }

    var gHi = F.svg('g', {});
    svg.appendChild(gHi);

    /* one transparent rect takes every pointer event: 500 listeners would be
       500 listeners */
    var hit = F.svg('rect', {
      x: px0, y: py0, width: px1 - px0, height: plotH,
      fill: 'transparent'
    });
    hit.addEventListener('mousemove', function (ev) {
      var c = rowAt(ev);
      if (!c) return;
      if (!state.pinned) { fillCard(c); }
      drawHighlight(c);
    });
    hit.addEventListener('mouseleave', function () {
      if (!state.pinned) { defaultCard(state.D); drawHighlight(null); }
      else drawHighlight();
    });
    hit.addEventListener('click', function (ev) {
      var c = rowAt(ev);
      if (!c) return;
      if (state.pinned && state.pinned.t === c.t) setPinned(null);
      else {
        document.getElementById('rk-search').value = c.t;
        document.getElementById('rk-hit').textContent = c.t;
        document.getElementById('rk-hit').className = 'rk-hit';
        setPinned(c);
      }
    });
    svg.appendChild(hit);

    host.appendChild(svg);

    state.geom = { x: x, py0: py0, py1: py1, px0: px0, px1: px1, rowStep: rowStep, barH: barH, g: gHi };
    drawHighlight();
    renderLegend();
  }

  /* nearest visible row to the pointer */
  function rowAt(ev) {
    var g = state.geom;
    if (!g || !state.visible.length) return null;
    var rect = ev.currentTarget.ownerSVGElement.getBoundingClientRect();
    var py = ev.clientY - rect.top;
    var want = (py - g.py0) / g.rowStep - 0.5;
    var best = null, bd = Infinity;
    for (var i = 0; i < state.visible.length; i++) {
      var d = Math.abs(state.visible[i]._i - want);
      if (d < bd) { bd = d; best = state.visible[i]; }
      else if (state.visible[i]._i > want) break;
    }
    return best;
  }

  function drawHighlight(hoverRow) {
    var g = state.geom;
    if (!g) return;
    while (g.g.firstChild) g.g.removeChild(g.g.firstChild);
    var c = state.pinned || hoverRow;
    if (!c) return;
    var yc = g.py0 + (c._i + 0.5) * g.rowStep;
    var h = Math.max(3, g.barH);
    var xa = g.x(c.p05), xb = g.x(c.p95);
    g.g.appendChild(F.svg('rect', {
      x: (g.px0).toFixed(1), y: (yc - h / 2 - 1).toFixed(1),
      width: (g.px1 - g.px0).toFixed(1), height: (h + 2).toFixed(1),
      style: 'fill:var(--accent)', 'fill-opacity': 0.1
    }));
    g.g.appendChild(F.svg('rect', {
      x: xa.toFixed(1), y: (yc - h / 2).toFixed(1),
      width: Math.max(2, xb - xa).toFixed(1), height: h.toFixed(1),
      style: 'fill:var(--accent)'
    }));
    g.g.appendChild(F.svg('rect', {
      x: (g.x(c.med) - 1).toFixed(1), y: (yc - h / 2 - 3).toFixed(1),
      width: 2, height: (h + 6).toFixed(1), style: 'fill:var(--ink)'
    }));
    /* the ticker rides the end of the band, or the other end when there is no
       room, so the card is never ambiguous about which row is selected */
    var right = xb + 90 < g.px1;
    g.g.appendChild(F.svg('text', {
      x: (right ? xb + 7 : xa - 7).toFixed(1), y: (yc + 4).toFixed(1),
      'text-anchor': right ? 'start' : 'end', class: 'pt-label',
      text: c.t
    }));
  }

  function renderLegend() {
    var n = state.rows.length;
    var nv = state.visible.length;
    document.getElementById('rk-n').innerHTML = nv === n
      ? '<b>n = ' + fmt.int(n) + '</b> companies'
      : '<b>n = ' + fmt.int(nv) + '</b> shown of ' + fmt.int(n);

    var by = { measured: 0, reported: 0, unmeasurable: 0 };
    state.visible.forEach(function (c) { by[c.tier]++; });
    var html = F.tierOrder.map(function (t) {
      return '<span class="legend-item"><span class="swatch swatch--sq" style="background:' +
        F.tierColor(t) + ';opacity:.62"></span>' + F.tier(t).label + ' ' + fmt.int(by[t]) + '</span>';
    }).join('');
    html += '<span class="legend-item"><span class="swatch swatch--sq" ' +
      'style="background:var(--ink);width:2px;height:12px"></span>median</span>';
    document.getElementById('rk-legend').innerHTML = html;
  }

  /* ---------------- the card ---------------- */

  function defaultCard(D) {
    if (filtered()) { selectionCard(D); return; }
    var s = D.scores.rank_interval_summary;
    var m = D.scores.meta;
    var h = D.scores.headline;
    var card = document.getElementById('rk-card');
    card.innerHTML =
      '<div class="card-head">' +
        '<div class="card-tick">ALL ' + fmt.int(m.n_companies) + '</div>' +
        '<div class="card-name">Width of the 5th to 95th percentile rank band, across ' +
          fmt.int(m.n_draws) + ' draws of every modelling choice at once</div>' +
      '</div>' +
      '<div class="u-mt4"><div class="rk-big">' + fmt.num(s.median_width, 1) +
        '<span class="of"> / ' + fmt.int(m.n_companies) + '</span></div>' +
        '<div class="rk-biglab">median band width, in ranks</div>' +
        '<div class="rk-sub">' + fmt.int(h.n_wider_than_100) + ' of ' + fmt.int(m.n_companies) +
          ' companies could move more than 100 places. A published rank hides all of it.</div></div>' +
      '<div class="card-rows u-mt4">' +
        row('Mean width', fmt.num(s.mean_width, 1)) +
        row('Narrowest', fmt.int(s.min_width)) +
        row('Widest', fmt.int(s.max_width)) +
        row('Wider than 200 ranks', fmt.int(s.n_wider_than_200) + ' <small>companies</small>') +
        row('Wider than 300 ranks', fmt.int(s.n_wider_than_300) + ' <small>companies</small>') +
        row('Run it once, the average rank moves', fmt.num(h.average_shift_vs_naive, 1) + ' <small>places</small>') +
      '</div>' +
      '<table class="tbl u-mt4"><thead><tr><th>Tier</th><th>n</th>' +
        '<th>Band</th><th>Median</th></tr></thead><tbody>' +
        F.tierOrder.map(function (t) {
          var r = s.by_tier[t];
          if (!r) return '';
          return '<tr><td><span class="chip chip--' + t + '">' + F.tier(t).short + '</span></td>' +
            '<td>' + fmt.int(r.n) + '</td><td>' + fmt.num(r.median_width, 1) + '</td>' +
            '<td>' + fmt.int(r.median_rank) + '</td></tr>';
        }).join('') +
      '</tbody></table>' +
      '<div class="card-hint">Hover any row for the company. Click, or type a ticker, to pin it.</div>';
  }

  /* the same figures as the all-index card, over whatever is on screen */
  function selectionCard(D) {
    var m = D.scores.meta;
    var rows = state.visible;
    var widths = rows.map(function (c) { return c.p95 - c.p05; });
    var over = function (k) {
      return widths.filter(function (w) { return w > k; }).length;
    };
    var by = { measured: [], reported: [], unmeasurable: [] };
    rows.forEach(function (c) { by[c.tier].push(c); });
    var label = state.sector === 'all' ? 'SELECTION' : state.sector.toUpperCase();
    var card = document.getElementById('rk-card');
    card.innerHTML =
      '<div class="card-head">' +
        '<div class="card-tick">' + fmt.int(rows.length) + ' SHOWN</div>' +
        '<div class="card-name">' + label + ', computed over the rows now on the chart. ' +
          'Ranks stay the rank inside all ' + fmt.int(m.n_companies) + '.</div>' +
      '</div>' +
      '<div class="u-mt4"><div class="rk-big">' + fmt.num(median(widths), 1) +
        '<span class="of"> / ' + fmt.int(m.n_companies) + '</span></div>' +
        '<div class="rk-biglab">median band width, in ranks</div>' +
        '<div class="rk-sub">' + fmt.int(over(100)) + ' of ' + fmt.int(rows.length) +
          ' could move more than 100 places.</div></div>' +
      '<div class="card-rows u-mt4">' +
        row('Median rank', fmt.num(median(rows.map(function (c) { return c.med; })), 1)) +
        row('Narrowest', fmt.int(Math.min.apply(null, widths))) +
        row('Widest', fmt.int(Math.max.apply(null, widths))) +
        row('Wider than 200 ranks', fmt.int(over(200)) + ' <small>companies</small>') +
        row('Wider than 300 ranks', fmt.int(over(300)) + ' <small>companies</small>') +
      '</div>' +
      '<table class="tbl u-mt4"><thead><tr><th>Tier</th><th>n</th>' +
        '<th>Band</th><th>Median</th></tr></thead><tbody>' +
        F.tierOrder.map(function (t) {
          if (!by[t].length) return '';
          return '<tr><td><span class="chip chip--' + t + '">' + F.tier(t).short + '</span></td>' +
            '<td>' + fmt.int(by[t].length) + '</td><td>' +
            fmt.num(median(by[t].map(function (c) { return c.p95 - c.p05; })), 1) + '</td><td>' +
            fmt.num(median(by[t].map(function (c) { return c.med; })), 0) + '</td></tr>';
        }).join('') +
      '</tbody></table>' +
      '<div class="card-hint">Reset to put all ' + fmt.int(m.n_companies) + ' back.</div>';
  }

  function fillCard(c) {
    var D = state.D;
    var m = D.scores.meta;
    var card = document.getElementById('rk-card');
    var draws = c.hist.reduce(function (a, b) { return a + b; }, 0);
    var width = c.p95 - c.p05;
    var top100 = shareBelow(c, D, 100);
    var bot100 = 1 - shareBelow(c, D, m.n_companies - 100);
    var drivers = Object.keys(c.sobol).map(function (k) {
      return { k: k, v: c.sobol[k] };
    }).sort(function (a, b) { return b.v - a.v; }).slice(0, 3);

    card.innerHTML =
      '<div class="card-head">' +
        '<div class="card-tick">' + c.t + '</div>' +
        '<div class="card-name">' + c.n + '</div>' +
        '<div class="card-meta">' +
          '<span class="chip chip--' + c.tier + '">' + F.tier(c.tier).label + '</span>' +
          '<span class="card-sector">' + c.s + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="card-trio">' +
        cell('median rank', fmt.int(c.med), 'of ' + fmt.int(m.n_companies), '') +
        cell('band', fmt.int(c.p05) + '&ndash;' + fmt.int(c.p95), '5th to 95th', '') +
        cell('width', fmt.int(width), 'ranks', width > 100 ? 'ct-gap-miss' : '') +
      '</div>' +
      histSvg(c, D) +
      '<div class="card-rows u-mt4">' +
        row('Ranked in', fmt.int(draws) + ' <small>of ' + fmt.int(m.n_draws) + ' draws</small>') +
        row('Inside the top 100', fmt.share(top100, 1) + ' <small>of draws</small>') +
        row('Inside the bottom 100', fmt.share(bot100, 1) + ' <small>of draws</small>') +
        row('If we had picked one method and stopped', fmt.int(c.naive) + ' <small>' +
            (c.naive < c.med ? fmt.int(c.med - c.naive) + ' better than our median' :
             c.naive > c.med ? fmt.int(c.naive - c.med) + ' worse than our median' : 'same as our median') +
            '</small>') +
        row('Our percentile', fmt.num(c.pct, 1) + ' <small>100 is best</small>') +
        row('Vendor percentile', c.vendor === undefined || c.vendor === null
            ? '<span class="u-muted">no vendor score</span>'
            : fmt.num(c.vendor, 1) + ' <small>of ' + fmt.int(D.scores.vendor_comparison.n) + ' rated</small>') +
      '</div>' +
      '<div class="rk-pill">' +
        m.pillars.map(function (p) {
          var v = c.pillars[p.key];
          return '<div><div class="pk">' + p.key + '</div><div class="pv">' +
            (v === null || v === undefined ? '<span class="u-muted">&mdash;</span>' : fmt.num(v * 100, 0)) +
            '</div></div>';
        }).join('') +
      '</div>' +
      '<div class="rk-sub">Pillar scores, 100 is best. What moves this company: ' +
        drivers.map(function (d) {
          return (FACTOR_LABEL[d.k] || d.k) + ' ' + fmt.share(d.v, 1);
        }).join(', ') + '.</div>';
  }

  /* share of this company's draws that land at or above rank r */
  function shareBelow(c, D, r) {
    var edges = D.scores.rank_histogram.bin_edges;
    var total = 0, hit = 0;
    c.hist.forEach(function (v, i) {
      total += v;
      if (edges[i + 1] <= r + 0.5) hit += v;
    });
    return total ? hit / total : 0;
  }

  /* the company's own rank distribution over the draws */
  function histSvg(c, D) {
    var N = D.scores.meta.n_companies;
    var edges = D.scores.rank_histogram.bin_edges;
    var w = 300, h = 74, base = h - 16;
    var max = Math.max.apply(null, c.hist) || 1;
    function px(r) { return (r - 0.5) / N * w; }
    var bars = c.hist.map(function (v, i) {
      var x0 = px(edges[i]), x1 = px(edges[i + 1]);
      var bh = v / max * (base - 3);
      var inBand = edges[i + 1] > c.p05 && edges[i] < c.p95;
      return '<rect x="' + x0.toFixed(1) + '" y="' + (base - bh).toFixed(1) + '" width="' +
        Math.max(1, x1 - x0 - 1).toFixed(1) + '" height="' + bh.toFixed(1) +
        '" style="fill:var(--accent)" fill-opacity="' + (inBand ? 0.62 : 0.22) + '"/>';
    }).join('');
    return '<div class="card-band"><svg width="' + w + '" height="' + h + '" role="img" ' +
      'aria-label="rank distribution over the draws">' + bars +
      '<line x1="0" x2="' + w + '" y1="' + base + '" y2="' + base +
        '" style="stroke:var(--rule-2)" stroke-width="1"/>' +
      '<line x1="' + px(c.med).toFixed(1) + '" x2="' + px(c.med).toFixed(1) +
        '" y1="0" y2="' + (base + 4) + '" style="stroke:var(--ink)" stroke-width="1.5"/>' +
      '<text x="0" y="' + (h - 2) + '" class="tick-label">1</text>' +
      '<text x="' + w + '" y="' + (h - 2) + '" class="tick-label" text-anchor="end">' + N + '</text>' +
      (c.med > N * 0.18 && c.med < N * 0.82
        ? '<text x="' + px(c.med).toFixed(1) + '" y="' + (h - 2) + '" class="tick-label" ' +
          'text-anchor="middle" style="fill:var(--ink-2)">median</text>'
        : '') +
      '</svg></div>';
  }

  function row(k, v) {
    return '<div class="card-row"><span class="k">' + k + '</span><span class="v">' + v + '</span></div>';
  }

  function cell(k, v, u, cls) {
    return '<div><div class="ct-k">' + k + '</div><div class="ct-v ' + cls + '">' + v +
      '</div><div class="ct-u">' + u + '</div></div>';
  }

  /* ---------------- Sobol first-order shares ---------------- */

  function renderSobol(D) {
    var so = D.scores.sobol_first_order;
    var byTier = D.scores.sobol_by_tier;
    var cov = D.scores.coverage.by_tier;
    var order = Object.keys(so.mean_share).sort(function (a, b) {
      return so.mean_share[b] - so.mean_share[a];
    });

    /* one scale for every slice, so switching the tier is a comparison and
       not a redraw */
    var max = 0;
    [so.mean_share].concat(F.tierOrder.map(function (t) { return byTier[t]; }))
      .forEach(function (set) {
        if (!set) return;
        var sum = 0;
        order.forEach(function (k) {
          max = Math.max(max, set[k] || 0);
          sum += set[k] || 0;
        });
        /* the residual shares the scale with the factors, so no bar is clamped */
        max = Math.max(max, 1 - sum);
      });

    var seg = document.getElementById('rk-seg');
    var opts = [{ k: 'all', label: 'all ' + fmt.int(D.scores.meta.n_companies) }]
      .concat(F.tierOrder.map(function (t) {
        return { k: t, label: F.tier(t).short + ' ' + fmt.int(cov[t] || 0) };
      }));
    seg.innerHTML = opts.map(function (o) {
      return '<button type="button" data-k="' + o.k + '" data-on="' +
        (o.k === state.sobolTier ? '1' : '0') + '">' + o.label + '</button>';
    }).join('');
    [].forEach.call(seg.querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () {
        state.sobolTier = b.getAttribute('data-k');
        [].forEach.call(seg.querySelectorAll('button'), function (o) {
          o.setAttribute('data-on', o.getAttribute('data-k') === state.sobolTier ? '1' : '0');
        });
        paintSobol();
      });
    });

    var host = document.getElementById('rk-sobol');
    host.innerHTML = order.map(function (k) {
      var trig = D.scores.meta.trigger_factors[k];
      var n = Array.isArray(trig) ? trig.length + ' settings' : (SETTING_LABEL[trig] || trig);
      return '<div class="sob-row' + (k === 'weights' ? ' is-key' : '') + '" data-k="' + k + '">' +
        '<div class="sob-k">' + (FACTOR_LABEL[k] || k) + '<span class="opt">' + n + '</span></div>' +
        '<div class="sob-track"><span class="sob-bar" style="width:0%"></span></div>' +
        '<div class="sob-v"></div></div>';
    }).join('') +
      '<div class="sob-rest" data-k="_rest">' +
        '<div class="sob-k">choices acting together</div>' +
        '<div class="sob-track"><span class="sob-bar" style="width:0%"></span></div>' +
        '<div class="sob-v"></div></div>';

    state.sobolMax = max;
    state.sobolOrder = order;
    paintSobol();

    document.getElementById('rk-sobol-note').innerHTML =
      'Where the EPA does measure a company, the weights matter more, ' +
      fmt.share(byTier.measured.weights, 1) + ', and they are still not the largest factor. ' +
      F.detailsHTML('How this is measured', '',
        /* the page says "every weighting, drawn at random" where the data file
           says Dirichlet(1,1,1,1). Both are true; the parameterisation belongs
           here, one click down, rather than nowhere. */
        '<p>' + so.estimator + ' Weights enter as ' +
        so.weights_binning.replace('the Dirichlet draw',
          'a ' + D.scores.meta.trigger_factors.weights.replace(' over the four pillars', '') +
          ' draw, uniform over the four pillars,') + '.</p>');
  }

  function paintSobol() {
    var D = state.D;
    var set = state.sobolTier === 'all'
      ? D.scores.sobol_first_order.mean_share
      : D.scores.sobol_by_tier[state.sobolTier];
    var sum = 0;
    state.sobolOrder.forEach(function (k) { sum += set[k] || 0; });
    var host = document.getElementById('rk-sobol');
    state.sobolOrder.forEach(function (k) {
      var r = host.querySelector('.sob-row[data-k="' + k + '"]');
      var v = set[k] || 0;
      r.querySelector('.sob-bar').style.width = (v / state.sobolMax * 100).toFixed(2) + '%';
      r.querySelector('.sob-v').textContent = shareSmall(v);
    });
    var cov = D.scores.coverage.by_tier;
    document.getElementById('rk-sob-n').innerHTML = '<b>n = ' +
      fmt.int(state.sobolTier === 'all' ? D.scores.meta.n_companies : cov[state.sobolTier]) +
      '</b> ' + (state.sobolTier === 'all' ? 'companies' : F.tier(state.sobolTier).short) +
      ' &times; ' + fmt.int(D.scores.meta.n_draws) + ' draws';

    var rest = host.querySelector('.sob-rest');
    var rv = 1 - sum;
    rest.querySelector('.sob-bar').style.width = (rv / state.sobolMax * 100).toFixed(2) + '%';
    rest.querySelector('.sob-v').textContent = shareSmall(rv);
  }

  /* a share too small for one decimal still has to be legible as a number */
  function shareSmall(v) {
    return v * 100 < 0.1 ? fmt.num(v * 100, 3) + '%' : fmt.share(v, 1);
  }

  /* ---------------- weight audit ---------------- */

  function renderWeights(D) {
    var wa = D.scores.weight_audit;
    var pillars = D.scores.meta.pillars;
    var eff = wa.main_effect_normalised;
    var nom = wa.nominal;

    var maxv = 0;
    pillars.forEach(function (p) {
      maxv = Math.max(maxv, eff[p.key] || 0, nom[p.key] || 0);
    });
    var dom = Math.ceil(maxv / 0.05) * 0.05 + 0.05;   /* round out to a 0.05 step */
    function pc(v) { return (v / dom * 100).toFixed(2) + '%'; }

    var rows = pillars.slice().sort(function (a, b) {
      return eff[b.key] - eff[a.key];
    }).map(function (p) {
      var e = eff[p.key], n = nom[p.key];
      var up = e > n;
      var a = Math.min(e, n), b = Math.max(e, n);
      return '<div class="wa-row">' +
        '<div class="wa-k">' + p.key + '<span>' + p.label + '</span></div>' +
        '<div class="wa-track">' +
          '<span class="wa-seg ' + (up ? 'is-up' : 'is-dn') + '" style="left:' + pc(a) +
            ';width:' + pc(b - a) + '"></span>' +
          '<span class="wa-nom" style="left:' + pc(n) + '"></span>' +
          '<span class="wa-eff ' + (up ? 'is-up' : 'is-dn') + '" style="left:' + pc(e) + '"></span>' +
        '</div>' +
        '<div class="wa-v">' + fmt.num(e, 3) + '</div>' +
      '</div>';
    }).join('');

    var host = document.getElementById('rk-weights');
    host.innerHTML =
      '<div class="panel-sub">We say the four pillars are equal, ' +
        fmt.num(nom[pillars[0].key], 2) + ' each. The variance of the rank says one of them ' +
        'does a quarter more work than another.</div>' +
      '<div class="wa-head u-mt4"><div>stated ' + fmt.num(nom[pillars[0].key], 2) +
        ' marked, 0 to ' + fmt.num(dom, 2) + '</div><div>effective</div></div>' +
      rows +
      dmSvg(wa) +
      F.detailsHTML('How this is measured', '',
        '<p class="note">' + wa.definition + ' Reference specification: ' +
        wa.reference_specification + '. Bounds across the draw ' +
        fmt.num(wa.d_m_bounds[0], 3) + ' to ' + fmt.num(wa.d_m_bounds[1], 3) +
        '; measured companies only ' + fmt.num(wa.d_m_available_case, 3) + '.</p>' +
        '<p class="note u-mt4">The same figure for published composite indicators: ' +
        Object.keys(wa.benchmarks).sort(function (a, b) {
          return wa.benchmarks[b] - wa.benchmarks[a];
        }).map(function (k) {
          return k + ' ' + fmt.num(wa.benchmarks[k], 2);
        }).join(', ') + '.</p>');
  }

  /* the distance between stated and effective importance, on one line */
  function dmSvg(wa) {
    var w = 460, h = 74, y = 40, x0 = 6, x1 = w - 6;
    function px(v) { return x0 + v * (x1 - x0); }
    var ticks = [0, 0.25, 0.5, 0.75, 1];
    var parts = [
      '<line x1="' + x0 + '" x2="' + x1 + '" y1="' + y + '" y2="' + y +
        '" style="stroke:var(--rule-2)" stroke-width="1"/>'
    ];
    ticks.forEach(function (t) {
      parts.push('<line x1="' + px(t).toFixed(1) + '" x2="' + px(t).toFixed(1) + '" y1="' + y +
        '" y2="' + (y + 5) + '" style="stroke:var(--rule-2)"/>');
      parts.push('<text x="' + px(t).toFixed(1) + '" y="' + (y + 20) +
        '" class="tick-label" text-anchor="middle">' + fmt.num(t, 2) + '</text>');
    });
    parts.push('<line x1="' + px(wa.d_m).toFixed(1) + '" x2="' + px(wa.d_m).toFixed(1) +
      '" y1="' + (y - 16) + '" y2="' + (y + 6) + '" style="stroke:var(--accent)" stroke-width="2"/>');
    parts.push('<text x="' + px(wa.d_m).toFixed(1) + '" y="' + (y - 22) +
      '" class="pt-label" text-anchor="middle" style="fill:var(--accent-2)">FILED  ' +
      fmt.num(wa.d_m, 2) + '</text>');
    parts.push('<text x="' + x0 + '" y="' + (h - 2) + '" class="tick-label">stated equals effective</text>');
    parts.push('<text x="' + x1 + '" y="' + (h - 2) +
      '" class="tick-label" text-anchor="end">one pillar does all the work</text>');
    return '<div class="u-mt4"><div class="panel-sub" style="margin-bottom:4px">' +
      'The distance between the weights we state and the weights that move the rank' +
      '</div><svg width="' + w + '" height="' + h + '" role="img" ' +
      'aria-label="distance between stated and effective weights">' + parts.join('') +
      '</svg></div>';
  }

  /* ---------------- Pareto front and head to head ---------------- */

  function renderPareto(D) {
    var p = D.scores.pareto;
    if (!p || !p.front_1) { document.getElementById('rk-pareto').remove(); return; }
    var ix = F.index.scores;

    var fronts = {};
    D.scores.companies.forEach(function (c) {
      if (c.pareto) fronts[c.pareto] = (fronts[c.pareto] || 0) + 1;
    });
    var fkeys = Object.keys(fronts).map(Number).sort(function (a, b) { return a - b; });

    var list = p.front_1.slice().sort(function (a, b) {
      return ((ix[a.ticker] || {}).med || 0) - ((ix[b.ticker] || {}).med || 0);
    }).map(function (r) {
      var c = ix[r.ticker];
      return '<div class="par-row">' +
        '<span class="pt-t">' + r.ticker + '</span>' +
        '<span class="pt-n">' + r.company + '</span>' +
        '<span class="pt-r">' + (c ? fmt.int(c.med) + ' <span class="u-dim">[' +
          fmt.int(c.p05) + '&ndash;' + fmt.int(c.p95) + ']</span>' : '') + '</span>' +
      '</div>';
    }).join('');

    var dom = D.scores.pairwise_dominance_top20;
    var host = document.getElementById('rk-pareto');
    host.innerHTML = F.detailsHTML('Results that hold under any weighting',
      '<b>n = ' + fmt.int(p.n_scored) + '</b> with all four pillars',
      '<div class="panel-sub">A Pareto front carries no weights at all, and a head-to-head ' +
        'probability carries no aggregation rule. Neither depends on the argument everyone ' +
        'has about weights.</div>' +
      '<div class="rk-par u-mt4">' +
        '<div>' +
          '<div class="rk-big">' + fmt.int(p.front_1.length) + '<span class="of"> / ' +
            fmt.int(p.n_scored) + '</span></div>' +
          '<div class="rk-biglab">beaten by nobody on all four pillars at once</div>' +
          '<div class="rk-sub">No other scored company beats them on all four pillars at once. ' +
            fmt.int(p.n_fronts) + ' fronts in total.</div>' +
          '<div class="par-list">' + list + '</div>' +
          '<div class="fronts">' + fkeys.map(function (k) {
            return '<span style="width:' + (fronts[k] / p.n_scored * 100).toFixed(2) + '%;background:' +
              (k === 1 ? 'var(--accent)' : 'var(--rule-2)') + '" title="front ' + k + ': ' +
              fronts[k] + ' companies"></span>';
          }).join('') + '</div>' +
          '<div class="rk-sub">Front 1 to front ' + fkeys[fkeys.length - 1] + ', by share of the ' +
            fmt.int(p.n_scored) + ' scored.</div>' +
          '<div class="note u-mt4">' + p.note + '</div>' +
        '</div>' +
        '<div>' + (dom && dom.tickers ? dominance(D, dom) : '') + '</div>' +
      '</div>');
  }

  function dominance(D, dom) {
    var ix = F.index.scores;
    var n = dom.tickers.length;
    var m = dom.p_row_above_column;
    /* keep the file's own order but sort by median, so the grid reads as a
       ranking that does not hold up */
    var ord = dom.tickers.map(function (t, i) {
      return { t: t, i: i, med: (ix[t] || {}).med };
    }).sort(function (a, b) { return a.med - b.med; });

    var settled = 0, ties = 0, pairs = 0;
    for (var i = 0; i < n; i++) {
      for (var j = i + 1; j < n; j++) {
        pairs++;
        var pij = m[i][j], pji = m[j][i];
        if (pij >= 0.95 || pji >= 0.95) settled++;
        if (pij === 0 && pji === 0) ties++;
      }
    }

    var cell = 21, lab = 46, top = 54;
    var w = lab + n * cell, h = top + n * cell + 4;
    var parts = [];
    ord.forEach(function (o, ci) {
      var cx = lab + ci * cell + cell / 2;
      parts.push('<text transform="translate(' + cx + ',' + (top - 6) + ') rotate(-90)" ' +
        'class="tick-label" style="font-size:11px">' + o.t + '</text>');
    });
    ord.forEach(function (ro, ri) {
      var y = top + ri * cell;
      parts.push('<text x="' + (lab - 6) + '" y="' + (y + cell / 2 + 4) +
        '" class="tick-label" text-anchor="end" style="font-size:11px">' + ro.t + '</text>');
      ord.forEach(function (co, ci) {
        var x = lab + ci * cell;
        if (ri === ci) {
          parts.push('<rect x="' + x + '" y="' + y + '" width="' + (cell - 1) + '" height="' +
            (cell - 1) + '" style="fill:var(--bg-2)"/>');
          return;
        }
        var v = m[ro.i][co.i];
        var back = m[co.i][ro.i];
        var tie = v === 0 && back === 0;
        var fill, op;
        if (tie) { fill = 'var(--muted)'; op = 0.35; }
        else if (v >= 0.5) { fill = 'var(--cool)'; op = 0.1 + (v - 0.5) * 1.8; }
        else { fill = 'var(--accent)'; op = 0.1 + (0.5 - v) * 1.8; }
        parts.push('<rect x="' + x + '" y="' + y + '" width="' + (cell - 1) + '" height="' +
          (cell - 1) + '" style="fill:' + fill + '" fill-opacity="' + op.toFixed(2) +
          '"><title>' + ro.t + ' above ' + co.t + ' in ' + fmt.share(v, 1) +
          ' of draws</title></rect>');
      });
    });

    return '<div class="par-stat"><b>' + fmt.int(settled) + '</b> of ' + fmt.int(pairs) +
      ' head-to-head pairs among the best ' + n + ' companies ' +
      (settled === 1 ? 'is' : 'are') + ' settled in 95% of draws</div>' +
      '<div class="panel-sub" style="margin:4px 0 6px 0">' +
      'Probability that the row company ranks above the column company, top ' + n +
      ' by median rank</div>' +
      '<svg width="' + w + '" height="' + h + '" role="img" aria-label="head to head ' +
      'probabilities among the top ' + n + '">' + parts.join('') + '</svg>' +
      '<div class="legend u-mt4">' +
        '<span class="legend-item"><span class="swatch swatch--sq" style="background:var(--cool)"></span>row ranks above</span>' +
        '<span class="legend-item"><span class="swatch swatch--sq" style="background:var(--accent)"></span>column ranks above</span>' +
        '<span class="legend-item"><span class="swatch swatch--sq" style="background:var(--muted)"></span>identical in every draw</span>' +
      '</div>' +
      '<div class="rk-sub">' + fmt.int(ties) + ' of those pairs tie in every draw: the same ' +
      'observable record, so the same rank.</div>';
  }

  /* ---------------- conditional bands ---------------- */

  function renderConditional(D) {
    var cb = D.scores.conditional_bands;
    var keys = Object.keys(cb).sort(function (a, b) {
      return cb[b].median_width - cb[a].median_width;
    });
    var max = 0;
    keys.forEach(function (k) {
      max = Math.max(max, cb[k].median_width, cb[k].median_width_measured);
    });
    var narrow = keys[keys.length - 1];
    document.getElementById('rk-cond-note').innerHTML =
      'Our published band is the row with nothing held fixed, ' +
      fmt.num(cb['all triggers live'].median_width, 1) + ' ranks. Holding ' + bandLabel(narrow) +
      ' takes it to ' + fmt.num(cb[narrow].median_width, 1) + ', on ' +
      fmt.int(cb[narrow].n_draws) + ' of the ' + fmt.int(D.scores.meta.n_draws) +
      ' draws. We do not publish that number, because nothing makes those three settings ' +
      'more defensible than the ones they exclude.';

    var host = document.getElementById('rk-cond');
    host.innerHTML =
      '<div class="cb-head"><div>choices held fixed</div><div></div>' +
        '<div class="r">all ' + fmt.int(D.scores.meta.n_companies) + '</div>' +
        '<div class="r">draws</div></div>' +
      keys.map(function (k) {
        var r = cb[k];
        var live = r.n_draws === D.scores.meta.n_draws;
        return '<div class="cb-row' + (live ? ' is-live' : '') + '" title="' +
          fmt.int(r.n_draws) + ' of the ' + fmt.int(D.scores.meta.n_draws) + ' draws">' +
          '<div class="cb-k">' + bandLabel(k) + '</div>' +
          '<div class="cb-track">' +
            '<span class="cb-bar" style="width:' + (r.median_width / max * 100).toFixed(2) + '%"></span>' +
            '<span class="cb-tick" style="left:' + (r.median_width_measured / max * 100).toFixed(2) +
              '%" title="measured companies only"></span>' +
          '</div>' +
          '<div class="cb-v">' + fmt.num(r.median_width, 1) + '</div>' +
          '<div class="cb-v cb-n">' + fmt.int(r.n_draws) + '</div>' +
        '</div>';
      }).join('') +
      '<div class="legend u-mt4">' +
        '<span class="legend-item"><span class="swatch swatch--sq" style="background:var(--rule-2)"></span>median band width, all ' +
          fmt.int(D.scores.meta.n_companies) + '</span>' +
        '<span class="legend-item"><span class="swatch swatch--sq" style="background:var(--tier-measured);width:3px;height:12px"></span>' +
          'the same figure for the ' + fmt.int(D.scores.coverage.by_tier.measured) +
          ' EPA-measured companies</span>' +
      '</div>';
  }

}());
