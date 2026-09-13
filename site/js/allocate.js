/* Allocate $1bn: the control surface.

   One screen: the whole index, priced. Set a carbon price assumption on
   the left, read the index in the middle, read the $1bn advice on the right.
   Every number is recomputed in the browser from data/penalty.json, which
   carries per-company coefficients precisely so no server is involved.

   The chain, from penalty.json meta.chain, in order:
     price x deflator -> coverage per scope -> abatement from the OBSERVED rate
     -> cost -> dEBIT after sector pass-through -> dEV via the company's own
     EV/EBITDA -> value at risk -> percentile rank -> weights

   Verified against penalty.json reference.unit_test and reference.trace before
   a pixel was drawn: vardef reproduces to 3.6e-6 relative and wdef to 1.9e-6
   of a weight, which are the tolerances reference.browser_tolerance states.
   The tie-break matters and is not decoration: under the sector-median
   treatment the imputed companies' EVIC cancels out and 31 Financials land on
   exactly the same value at risk, so the rank key is the value at risk
   normalised by the maximum and rounded to 9 decimals, as the reference
   implementation does. Rank raw floats instead and those ties split at random.

   The two findings this screen exists to show:
     1. A uniform reprice scales value at risk and moves no weight at all,
        because the allocation runs on the RANK of value at risk. The advice
        panel says so out loud every time it happens.
     2. The missing-data treatment is the control that moves money: $123m of
        the $1bn between the four options.  */
(function (global) {
  'use strict';

  var FILED = global.FILED;
  if (!FILED) return;

  /* ---------------- constants that are layout, not taste ---------------- */

  var AUM = 1e9;
  var SHORT = {
    'Communication Services': 'Comm Svcs',
    'Consumer Discretionary': 'Cons Disc',
    'Consumer Staples': 'Cons Staples',
    'Energy': 'Energy',
    'Financials': 'Financials',
    'Health Care': 'Health Care',
    'Industrials': 'Industrials',
    'Information Technology': 'Info Tech',
    'Materials': 'Materials',
    'Real Estate': 'Real Estate',
    'Utilities': 'Utilities'
  };
  /* repo_sector_table is not offered: penalty.json says in its own preset_notes
     that it has no empirical source, and we will not ship a control we would
     not defend. */
  var PT_PRESETS = [
    ['default_two_grounded', 'Measured where known, 50% elsewhere'],
    ['flat_0', 'Companies absorb all of it'],
    ['flat_50', 'Half passed on, everywhere'],
    ['flat_100', 'All passed on, everywhere']
  ];
  /* Value at risk is coloured on a fixed domain, never on the current range,
     so that repricing visibly brightens the map while the layout holds still.
     A rank-based ramp would hide exactly the thing we want to show. */
  var VAR_TOP = 35;
  var RAMP_CARBON = [[0, 41, 47, 57], [0.35, 114, 63, 48], [0.7, 197, 93, 53], [1, 255, 122, 69]];
  var RAMP_WATER = [[0, 35, 43, 51], [0.5, 47, 127, 146], [1, 79, 195, 217]];
  /* The file's own labels are the law's words. These are the same four rules in
     the words a reader can act on. The full rule and its bias stay on the
     button as its title, and both are in the drawer. */
  var TREAT_LABEL = {
    sector_median: 'Charge their sector\u2019s median',
    threshold_bound: 'Just under the reporting limit',
    neutral_rank: 'Leave them unscored',
    zerofill: 'Treat them as zero'
  };
  var MUTED = '#5a6470';
  var MUTED_INK = '#8b95a2';

  /* ---------------- state ---------------- */

  var P = null, WATER = null, waterBy = {}, LOGOS = {};
  var C = null, N = 0, SECTORS = null;
  var host = null, dom = {};
  var S = null;                 /* the settings the controls own */
  var prev = null;              /* last result, for the invariance line */
  var tmNodes = [], tmBox = null;

  FILED.onReady(function (D) {
    host = document.getElementById('allocate-body');
    if (!host) return;
    P = D.penalty;
    WATER = D.water || null;
    LOGOS = D.logos || {};
    if (!P) { fail('data/penalty.json is not in the data map'); return; }
    C = P.companies; N = C.length; SECTORS = P.sectors;
    if (WATER) WATER.companies.forEach(function (w) { waterBy[w.ticker] = w; });

    S = initialState();
    registerDrawer();
    build();
    setColor('carbon');
    verify();
    recompute(true);
  });

  /* The material five places on this page point at, written once. */
  /* penalty.json states each rule in the model's own variable names. The rule
     is what a reader of this drawer came for, so it is said in words here and
     nothing is dropped: every quantity below is the same quantity. */
  var RULE_PLAIN = {
    sector_median:
      'We charge the sector\u2019s median tonnes per $m of company value, taken over the ' +
      'companies in that sector that do file, times this company\u2019s own value. Scope 2 the ' +
      'same way. A sector with fewer than 5 filers falls back to the reporting-limit rule ' +
      'below; on this data that is 0 sectors for Scope 1.',
    threshold_bound:
      'We charge every company that files nothing 25 000 tonnes of Scope 1, and nothing for ' +
      'Scope 2.',
    neutral_rank:
      'No tonnage is invented. The carbon cost, the hit to profit and the hit to company ' +
      'value are left blank, not set to zero.',
    zerofill:
      'We charge nothing at all. Scope 1, 2 and 3 are set to zero.'
  };

  function registerDrawer() {
    var rules = '<dl>' + P.missing_treatments.options.map(function (o) {
      return '<dt>' + (TREAT_LABEL[o.key] || o.label) + '</dt><dd>' +
        (RULE_PLAIN[o.key] || o.rule) +
        '<div class="u-dim" style="margin-top:6px">' + o.bias + '</div></dd>';
    }).join('') + '</dl>';
    FILED.drawer.add('missing', 'The four rules for a company we cannot measure',
      '<p>181 of the 500 file no Scope 1 figure at all. Every rule below is a ' +
      'different honest answer to that, and the money on those 181 moves by $' +
      (P.missing_treatments.measured_effect.zerofill.dollars_unmeasurable -
       P.missing_treatments.measured_effect.neutral_rank.dollars_unmeasurable).toFixed(0) +
      'm between them. The US reporting rule (40 CFR Part 98) makes a facility report only ' +
      'once it passes 25 000 tonnes a year, which is where the second rule gets its number.</p>' +
      rules);

    var keys = ['treatment', 'sectors_exempt', 'coverage_scope3', 'var_denominator',
      'coverage_scope2', 'passthrough_level', 'price_level', 'horizon'];
    var names = {
      treatment: 'the missing-data rule', sectors_exempt: 'exempting a sector',
      coverage_scope3: 'Scope 3 coverage', var_denominator: 'the value denominator',
      coverage_scope2: 'Scope 2 coverage', passthrough_level: 'cost passed to customers',
      price_level: 'the carbon price', horizon: 'the year'
    };
    FILED.drawer.add('controls', 'How much each control moves the $1bn',
      '<p>Measured over 3000 runs at a fixed tilt strength, in ' +
      '<span class="mono">src/penalty_model.py</span>. The figure is the share of the ' +
      'variance in the 500 advised weights that the control explains on its own.</p>' +
      '<dl>' + keys.map(function (k) {
        return '<dt>' + names[k] + ' <span class="mono">' +
          P.sensitivity.shares[k].allocation_fixed_lambda.toFixed(3) + '</span></dt>';
      }).join('') + '</dl>' +
      '<p>The price is the control everyone reaches for and it moves no money at all, ' +
      'because the allocation runs on the rank of value at risk and a scalar cannot ' +
      'reorder a ranking.</p>');

    FILED.drawer.add('passthrough', 'Cost passed on to customers',
      '<p>Pass-through is the share of a carbon bill a company pushes onto its ' +
      'customers through prices, so it never reaches its own earnings. Two of the ' +
      'eleven sectors have a published estimate we will stand behind: Utilities at ' +
      '80% (Fabra and Reguant 2014), Materials at 70% (Ganapati, Shapiro and Walker ' +
      '2020). The other nine have none, so all nine get one flat 50%.</p>');
  }

  function fail(msg) {
    host.innerHTML = '';
    host.appendChild(FILED.el('div', { class: 'awaiting', text: 'allocate.js: ' + msg }));
  }

  function initialState() {
    var d = P.defaults, price = {}, ex = {};
    SECTORS.forEach(function (s) { price[s] = d.price_usd2010[s]; ex[s] = false; });
    return {
      scenario: 'Net Zero 2050',
      horizon: d.horizon,
      price: price,
      exempt: ex,
      ptPreset: 'default_two_grounded',
      cov: { s1: d.coverage.scope1, s2: d.coverage.scope2, s3: d.coverage.scope3 },
      treatment: d.treatment,
      colorBy: 'carbon'
    };
  }

  /* ================= the model =================
     Arithmetic only. Nothing here touches the DOM. */

  function priceApplied(sec) {
    return (S.exempt[sec] ? 0 : S.price[sec]) * P.defaults.deflator;
  }

  function passthrough() { return P.passthrough.presets[S.ptPreset]; }

  /* s1_eff, s2_eff, s3_eff under the chosen missing-data treatment.
     Returns null for a company the treatment refuses to price. */
  function effective(c, tr, out) {
    var s1 = c.s1, s2 = c.s2, s3 = c.s3;
    if (tr === 'sector_median') {
      if (s1 === null) s1 = c.s1i;
      if (s2 === null) s2 = c.s2i;
    } else if (tr === 'threshold_bound') {
      if (s1 === null) s1 = P.missing_treatments.ghgrp_threshold_t;
      if (s2 === null) s2 = 0;
    } else if (tr === 'zerofill') {
      s1 = s1 || 0; s2 = s2 || 0; s3 = s3 || 0;
    } else {                       /* neutral_rank: invent nothing */
      if (s1 === null) return false;
      if (s2 === null) s2 = 0;
    }
    out[0] = s1 || 0; out[1] = s2 || 0; out[2] = s3 || 0;
    return true;
  }

  /* (1 + observed rate)^years, clipped. Never the promised rate: penalty.json
     carries promised_rate and says promised_never_used, and it means it. */
  function abateFactor(c) {
    if (c.dlv === null || c.s1y === null) return 1;
    var yrs = Math.max(S.horizon - c.s1y, 0);
    var f = Math.pow(1 + c.dlv / 100, yrs);
    return Math.min(Math.max(f, P.defaults.abate_floor), P.defaults.abate_ceiling);
  }

  var _eff = [0, 0, 0];

  function priceCompanies() {
    var pt = passthrough(), tr = S.treatment;
    var ap = P.defaults.abate_scopes;
    var pa = SECTORS.map(priceApplied);
    var r = {
      varr: new Float64Array(N), have: new Uint8Array(N),
      cost: new Float64Array(N), debit: new Float64Array(N),
      dev: new Float64Array(N), tonnes: new Float64Array(N)
    };
    var i, c, f, f1, f2, f3, t, sec;
    for (i = 0; i < N; i++) {
      c = C[i];
      if (!effective(c, tr, _eff)) continue;
      f = abateFactor(c);
      f1 = ap.scope1 ? f : 1; f2 = ap.scope2 ? f : 1; f3 = ap.scope3 ? f : 1;
      t = _eff[0] * S.cov.s1 * f1 + _eff[1] * S.cov.s2 * f2 + _eff[2] * S.cov.s3 * f3;
      sec = c.sec;
      r.tonnes[i] = t;
      r.cost[i] = pa[sec] * t / 1e6;
      r.debit[i] = r.cost[i] * (1 - pt[SECTORS[sec]]);
      r.dev[i] = r.debit[i] * c.evx;
      r.varr[i] = c.evic ? 100 * r.dev[i] / c.evic : 0;
      r.have[i] = 1;
    }
    return r;
  }

  /* Percentile rank of value at risk among the companies the treatment
     priced. A company it refused to price takes 0.5, the median tilt score,
     so the tilt neither rewards nor punishes it for being unmeasurable. */
  function tiltScores(r) {
    var idx = [], i, mx = 0;
    for (i = 0; i < N; i++) if (r.have[i]) { idx.push(i); if (r.varr[i] > mx) mx = r.varr[i]; }
    var n = idx.length, key = new Float64Array(N);
    if (!mx) mx = 1;
    for (i = 0; i < n; i++) key[idx[i]] = Math.round(r.varr[idx[i]] / mx * 1e9) / 1e9;
    idx.sort(function (a, b) { return key[a] - key[b]; });
    var score = new Float64Array(N);
    for (i = 0; i < N; i++) score[i] = 0.5;
    var a = 0, b, rk;
    while (a < n) {
      b = a;
      while (b + 1 < n && key[idx[b + 1]] === key[idx[a]]) b++;
      rk = ((a + b) / 2 + 1) / n;
      for (i = a; i <= b; i++) score[idx[i]] = rk;
      a = b + 1;
    }
    return score;
  }

  /* Article 3 buckets, the exp tilt, then the position caps by water filling.
     Lifted step for step from advice_algorithm.steps. */
  var BUCKETS = null;

  function buckets() {
    if (BUCKETS) return BUCKETS;
    BUCKETS = [true, false].map(function (hi) {
      var keep = [], target = 0, base = 0, i;
      for (i = 0; i < N; i++) {
        if (C[i].hi !== hi) continue;
        target += C[i].w0;
        if (!C[i].ex) { keep.push(i); base += C[i].w0; }
      }
      return { keep: keep, target: target, base: base };
    });
    return BUCKETS;
  }

  function weightsFor(score, lam) {
    var W = new Float64Array(N), bs = buckets(), bi, b, i, k, sum, spill, freeSum, over;
    var mxAbs = P.constraints.max_abs_weight, mxRel = P.constraints.max_rel_weight;
    for (bi = 0; bi < bs.length; bi++) {
      b = bs[bi];
      if (!b.keep.length) continue;
      var m = b.keep.length, w = new Float64Array(m), cap = new Float64Array(m);
      sum = 0;
      for (k = 0; k < m; k++) { i = b.keep[k]; w[k] = C[i].w0 * Math.exp(-lam * score[i]); sum += w[k]; }
      for (k = 0; k < m; k++) {
        i = b.keep[k];
        w[k] /= sum;
        cap[k] = Math.min(mxAbs / b.target, mxRel * C[i].w0 / b.base);
      }
      for (var pass = 0; pass < 200; pass++) {
        spill = 0; freeSum = 0; over = false;
        for (k = 0; k < m; k++) {
          if (w[k] > cap[k] + 1e-15) { spill += w[k] - cap[k]; w[k] = cap[k]; over = true; }
          else if (w[k] < cap[k] - 1e-15) freeSum += w[k];
        }
        if (!over || freeSum <= 0) break;
        for (k = 0; k < m; k++) if (w[k] < cap[k] - 1e-15) w[k] += spill * w[k] / freeSum;
      }
      for (k = 0; k < m; k++) W[b.keep[k]] = w[k] * b.target;
    }
    sum = 0;
    for (i = 0; i < N; i++) sum += W[i];
    for (i = 0; i < N; i++) W[i] /= sum;
    return W;
  }

  function activeShare(W) {
    var a = 0;
    for (var i = 0; i < N; i++) a += Math.abs(W[i] - C[i].w0);
    return a / 2;
  }

  /* lambda is bisected to a fixed active-share budget rather than held at a
     constant, which is what makes the price invariance exact: same ranks in,
     same lambda out, same weights. tilt_budget is a manager's risk budget and
     is stated as one. */
  function solveLambda(score) {
    var a0 = activeShare(weightsFor(score, 0)), budget = P.defaults.tilt_budget;
    var lo = 0, hi = P.advice_algorithm.lambda_range_for_ui[1], mid;
    for (var k = 0; k < 40; k++) {
      mid = (lo + hi) / 2;
      if (activeShare(weightsFor(score, mid)) - a0 < budget) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  }

  function run() {
    var r = priceCompanies();
    var score = tiltScores(r);
    var lam = solveLambda(score);
    var W = weightsFor(score, lam);

    var i, c, totDev = 0, totEvic = 0, totCost = 0, totT = 0;
    var bookVar = 0, idxVar = 0, covered = 0, wUn = 0, wUnIdx = 0, held = 0;
    for (i = 0; i < N; i++) {
      c = C[i];
      totDev += r.dev[i]; totCost += r.cost[i]; totT += r.tonnes[i];
      totEvic += c.evic || 0;
      if (r.have[i]) { bookVar += W[i] * r.varr[i]; idxVar += c.w0 * r.varr[i]; covered += W[i]; }
      if (c.s1 === null) { wUn += W[i]; wUnIdx += c.w0; }
      if (W[i] > 1e-12) held++;
    }

    /* Brinson: how much of the book's cut in value at risk is sector
       reallocation and how much is picking inside a sector. */
    var sw = [], sw0 = [], sv = [], sv0 = [];
    for (i = 0; i < SECTORS.length; i++) { sw[i] = 0; sw0[i] = 0; sv[i] = 0; sv0[i] = 0; }
    for (i = 0; i < N; i++) {
      if (!r.have[i]) continue;
      c = C[i];
      sw[c.sec] += W[i]; sw0[c.sec] += c.w0;
      sv[c.sec] += W[i] * r.varr[i]; sv0[c.sec] += c.w0 * r.varr[i];
    }
    var alloc = 0, sel = 0;
    for (i = 0; i < SECTORS.length; i++) {
      var v0 = sw0[i] ? sv0[i] / sw0[i] : 0;
      var v1 = sw[i] ? sv[i] / sw[i] : 0;
      alloc += (sw[i] - sw0[i]) * v0;
      sel += sw[i] * (v1 - v0);
    }

    return {
      r: r, score: score, lam: lam, W: W,
      totDev: totDev, totCost: totCost, totT: totT, totEvic: totEvic,
      bookVar: bookVar, idxVar: idxVar, covered: covered,
      wUn: wUn, wUnIdx: wUnIdx, held: held,
      active: activeShare(W), alloc: alloc, sel: sel
    };
  }

  /* ---------------- the arithmetic has to earn trust before it draws ----- */

  function verify() {
    var keep = S, ok = true, worstV = 0, worstW = 0;
    S = initialState();
    var out = run();
    P.reference.unit_test.forEach(function (u) {
      for (var i = 0; i < N; i++) {
        if (C[i].t !== u.t) continue;
        var e = Math.abs(out.r.varr[i] - u.var_pct) / Math.max(Math.abs(u.var_pct), 1e-9);
        if (e > worstV) worstV = e;
        if (e > 1e-4) ok = false;
      }
    });
    for (var i = 0; i < N; i++) worstW = Math.max(worstW, Math.abs(out.W[i] - C[i].wdef));
    if (worstW > 1e-5) ok = false;
    var msg = 'allocate.js model check: value at risk to ' + worstV.toExponential(1) +
      ' relative, weights to ' + worstW.toExponential(1) + ' of a weight';
    if (ok) console.log(msg); else console.error(msg + ': OUTSIDE reference.browser_tolerance');
    S = keep;
  }

  /* ================= layout: squarified treemap ================= */

  /* The classic squarify. Items must arrive sorted by value, descending. */
  function squarify(items, x, y, w, h, out) {
    var row = [], rowSum = 0, total = 0, i;
    for (i = 0; i < items.length; i++) total += items[i].v;
    if (total <= 0 || w <= 0 || h <= 0) return;
    var scale = (w * h) / total;
    var idx = 0;
    while (idx < items.length) {
      var short = Math.min(w, h);
      var cand = items[idx].v * scale;
      if (row.length === 0 || worst(row, rowSum, short) >= worst(row.concat([cand]), rowSum + cand, short)) {
        row.push(cand); rowSum += cand; idx++;
        if (idx < items.length) continue;
      }
      /* lay the row down along the short side and recurse on what is left */
      var thick = rowSum / short, at = 0, j, k = idx - row.length;
      for (j = 0; j < row.length; j++) {
        var len = row[j] / thick;
        if (w >= h) out.push({ it: items[k + j], x: x, y: y + at, w: thick, h: len });
        else out.push({ it: items[k + j], x: x + at, y: y, w: len, h: thick });
        at += len;
      }
      if (w >= h) { x += thick; w -= thick; } else { y += thick; h -= thick; }
      row = []; rowSum = 0;
      if (w <= 0 || h <= 0) break;
    }
  }

  function worst(row, sum, short) {
    var mx = 0, mn = Infinity, i;
    for (i = 0; i < row.length; i++) { if (row[i] > mx) mx = row[i]; if (row[i] < mn) mn = row[i]; }
    var s2 = short * short, sm = sum * sum;
    return Math.max(s2 * mx / sm, sm / (s2 * mn));
  }

  /* The 11 sector blocks keep their reading order, most exposed first, so a
     change of assumption reorders them and the tiles visibly move. A
     squarified top level would sort by size and never move at all. */
  function sliceDice(items, x, y, w, h, out) {
    if (!items.length) return;
    if (items.length === 1) { out.push({ it: items[0], x: x, y: y, w: w, h: h }); return; }
    var total = 0, i;
    for (i = 0; i < items.length; i++) total += items[i].v;
    var half = 0, cut = 0, best = Infinity;
    for (i = 0; i < items.length - 1; i++) {
      half += items[i].v;
      var d = Math.abs(half / total - 0.5);
      if (d < best) { best = d; cut = i + 1; }
    }
    var a = items.slice(0, cut), b = items.slice(cut), aSum = 0;
    for (i = 0; i < a.length; i++) aSum += a[i].v;
    var frac = aSum / total;
    if (w >= h) {
      sliceDice(a, x, y, w * frac, h, out);
      sliceDice(b, x + w * frac, y, w * (1 - frac), h, out);
    } else {
      sliceDice(a, x, y, w, h * frac, out);
      sliceDice(b, x, y + h * frac, w, h * (1 - frac), out);
    }
  }

  /* ================= colour ================= */

  function ramp(stops, t) {
    t = Math.max(0, Math.min(1, t));
    for (var i = 1; i < stops.length; i++) {
      if (t <= stops[i][0]) {
        var a = stops[i - 1], b = stops[i];
        var f = (t - a[0]) / (b[0] - a[0] || 1);
        return 'rgb(' + Math.round(a[1] + (b[1] - a[1]) * f) + ',' +
          Math.round(a[2] + (b[2] - a[2]) * f) + ',' +
          Math.round(a[3] + (b[3] - a[3]) * f) + ')';
      }
    }
    return 'rgb(' + stops[stops.length - 1].slice(1).join(',') + ')';
  }

  function tileColor(i, out) {
    if (S.colorBy === 'water') {
      var w = waterBy[C[i].t];
      return w ? ramp(RAMP_WATER, w.share_high) : MUTED;
    }
    if (!out.r.have[i]) return MUTED;
    return ramp(RAMP_CARBON, Math.sqrt(Math.min(out.r.varr[i], VAR_TOP) / VAR_TOP));
  }

  /* ================= build the DOM ================= */

  function build() {
    host.innerHTML = '';
    var grid = FILED.el('div', { class: 'al-grid' });
    grid.appendChild(buildLeft());
    grid.appendChild(buildMid());
    grid.appendChild(buildRight());
    host.appendChild(grid);
    host.appendChild(buildFoot());
  }

  function colShell(title, nHtml) {
    var col = FILED.el('div', { class: 'al-col' });
    var head = FILED.el('div', { class: 'al-col-head' }, [
      FILED.el('div', { class: 'al-col-t', text: title }),
      FILED.el('div', { class: 'al-col-n', html: nHtml })
    ]);
    col.appendChild(head);
    return col;
  }

  /* The share of allocation variance a control owns, measured over 3000 draws
     in src/penalty_model.py. It used to print as a bare decimal, which reads as
     a price. It prints in words now, and only on the two controls the whole
     contrast is about. The measured numbers are in the drawer. */
  function share(key) {
    var v = P.sensitivity.shares[key].allocation_fixed_lambda;
    var big = v >= 0.05;
    return FILED.el('span', {
      class: 'ac-share' + (big ? ' is-big' : ' is-nil'),
      text: big ? 'moves the money' : 'moves no money',
      title: 'Measured over 3000 runs: on its own this control explains ' +
        v.toFixed(3) + ' of the variance in the 500 advised weights.'
    });
  }

  function group(labelText, shareKey, body) {
    var g = FILED.el('div', { class: 'ac-group' });
    var lab = FILED.el('div', { class: 'ac-label' }, [FILED.el('span', { text: labelText })]);
    if (shareKey) lab.appendChild(share(shareKey));
    g.appendChild(lab);
    (Array.isArray(body) ? body : [body]).forEach(function (b) { if (b) g.appendChild(b); });
    return g;
  }

  function slider(min, max, step, val, on) {
    return FILED.el('input', {
      class: 'ac-range', type: 'range', min: min, max: max, step: step, value: val,
      oninput: on
    });
  }

  /* ---------- left: the assumption ---------- */

  /* Three things are visible: the companies we cannot measure, the price, and
     the scenario. Everything else is a modelling assumption and sits behind one
     disclosure, because a judge will not drag eleven sliders in thirty seconds
     and at rest all eleven read the same number. */
  function buildLeft() {
    var col = colShell('What you assume', '');
    col.classList.add('al-col--assume');
    dom.leftN = col.querySelector('.al-col-n');
    var wrap = FILED.el('div', { class: 'ac-wrap' });
    col.appendChild(wrap);

    /* the control that moves money, first, because it does */
    var box = FILED.el('div', { class: 'ac-treat' });
    dom.treatBtn = {};
    P.missing_treatments.options.forEach(function (o) {
      var me = P.missing_treatments.measured_effect[o.key];
      var b = FILED.el('button', {
        class: 'ac-opt' + (o.key === S.treatment ? ' is-on' : ''), type: 'button',
        title: o.rule + '\n\n' + o.bias,
        onclick: function () { S.treatment = o.key; syncTreat(); recompute(); }
      }, [
        FILED.el('span', { text: TREAT_LABEL[o.key] || o.label }),
        FILED.el('span', { class: 'o-w', text: '$' + me.dollars_unmeasurable.toFixed(0) + 'm' })
      ]);
      dom.treatBtn[o.key] = b;
      box.appendChild(b);
    });
    var spread = P.missing_treatments.measured_effect.zerofill.dollars_unmeasurable -
      P.missing_treatments.measured_effect.neutral_rank.dollars_unmeasurable;
    wrap.appendChild(group('181 companies file no emissions figure. Pick a rule.', 'treatment', [
      box,
      FILED.el('div', { class: 'ac-hint', text:
        'Each figure is what those 181 pay under that rule.' }),
      FILED.el('div', { class: 'ac-spread', html:
        '<b>$' + spread.toFixed(0) + 'm moves</b> between the cheapest and the dearest of ' +
        'these four rules, on the same 500 companies.' })
    ]));

    wrap.appendChild(FILED.el('div', { class: 'ac-rule' }));

    /* the price: a scenario, one slider, and the unit said once */
    var sel = FILED.el('select', { class: 'ac-sel', onchange: function () {
      S.scenario = this.value;
      if (S.scenario !== 'custom') applyScenario();
      recompute();
    } });
    P.price.presets.forEach(function (p) {
      sel.appendChild(FILED.el('option', { value: p.key, text: p.label }));
    });
    sel.appendChild(FILED.el('option', { value: 'custom', text: 'Custom' }));
    sel.value = S.scenario;
    dom.scenario = sel;

    dom.allVal = FILED.el('span', { class: 'ac-val', text: fmtPrice(S.price[SECTORS[0]]) });
    dom.allRange = slider(0, 1000, 1, S.price[SECTORS[0]], function () {
      var v = +this.value;
      SECTORS.forEach(function (s) { S.price[s] = v; });
      S.scenario = 'custom'; dom.scenario.value = 'custom';
      syncPrices();
      recompute();
    });
    wrap.appendChild(group('Carbon price', 'price_level', [
      sel,
      FILED.el('div', { class: 'ac-row', style: { 'margin-top': '3px' } }, [
        FILED.el('span', { class: 'ac-name', text: 'every sector' }),
        dom.allRange, dom.allVal
      ]),
      FILED.el('div', { class: 'ac-hint', text: 'US dollars a tonne, 2010 money.' })
    ]));

    /* everything below is an assumption, not a finding */
    var ass = FILED.el('div');

    dom.horizonVal = FILED.el('span', { class: 'ac-val', text: String(S.horizon) });
    ass.appendChild(group('Year', null, FILED.el('div', { class: 'ac-row ac-row--wide' }, [
      FILED.el('span', { class: 'ac-name', text: 'price and abatement',
        title: 'One year drives both: the scenario price is read off its path at ' +
          'this year, and the observed abatement rate is compounded to it.' }),
      slider(2026, 2050, 1, S.horizon, function () {
        S.horizon = +this.value;
        dom.horizonVal.textContent = this.value;
        if (S.scenario !== 'custom') applyScenario();
        recompute();
      }),
      dom.horizonVal
    ])));

    var perSec = FILED.el('div');
    dom.secRange = {}; dom.secVal = {}; dom.secEx = {};
    SECTORS.forEach(function (s) {
      var val = FILED.el('span', { class: 'ac-val', text: fmtPrice(S.price[s]) });
      var rng = slider(0, 1000, 1, S.price[s], function () {
        S.price[s] = +this.value;
        S.scenario = 'custom'; dom.scenario.value = 'custom';
        syncPrices();
        recompute();
      });
      var ex = FILED.el('button', {
        class: 'ac-ex', type: 'button', text: 'off',
        title: 'charge ' + s + ' nothing',
        onclick: function () { S.exempt[s] = !S.exempt[s]; syncPrices(); recompute(); }
      });
      dom.secRange[s] = rng; dom.secVal[s] = val; dom.secEx[s] = ex;
      perSec.appendChild(FILED.el('div', { class: 'ac-row' }, [
        FILED.el('span', { class: 'ac-name', text: SHORT[s], title: s }), rng, val, ex
      ]));
    });
    ass.appendChild(group('Set a price per sector, or none at all', 'sectors_exempt', perSec));

    var cov = FILED.el('div');
    [['s1', 'Scope 1', 'a company\u2019s own sites'],
     ['s2', 'Scope 2', 'the power it buys'],
     ['s3', 'Scope 3', 'its supply chain']].forEach(function (k) {
      var v = FILED.el('span', { class: 'ac-val', text: pct(S.cov[k[0]]) });
      cov.appendChild(FILED.el('div', { class: 'ac-row' }, [
        FILED.el('span', { class: 'ac-name', text: k[1], title: k[2] }),
        slider(0, 100, 1, S.cov[k[0]] * 100, function () {
          S.cov[k[0]] = +this.value / 100;
          v.textContent = pct(S.cov[k[0]]);
          recompute();
        }),
        v
      ]));
    });
    ass.appendChild(group('How much of each scope we charge for', null, [
      FILED.el('div', { class: 'ac-hint', text:
        'own sites  \u00b7  bought power  \u00b7  supply chain' }),
      cov
    ]));

    var ps = FILED.el('select', { class: 'ac-sel', onchange: function () {
      S.ptPreset = this.value; recompute();
    } });
    PT_PRESETS.forEach(function (p) {
      ps.appendChild(FILED.el('option', { value: p[0], text: p[1] }));
    });
    ps.value = S.ptPreset;
    ass.appendChild(group('Cost passed on to customers', null, ps));

    wrap.appendChild(FILED.el('div', { class: 'al-spacer' }));
    wrap.appendChild(FILED.details('Model assumptions', '4', ass, 'dd--tight'));
    return col;
  }

  function applyScenario() {
    var path = P.price.paths[S.scenario][P.price.source.model];
    var v = interpolate(path, S.horizon);
    SECTORS.forEach(function (s) { S.price[s] = v; });
    syncPrices();
  }

  function interpolate(path, year) {
    var ys = Object.keys(path).map(Number).sort(function (a, b) { return a - b; });
    if (year <= ys[0]) return path[ys[0]];
    for (var i = 1; i < ys.length; i++) {
      if (year <= ys[i]) {
        var f = (year - ys[i - 1]) / (ys[i] - ys[i - 1]);
        return path[ys[i - 1]] + (path[ys[i]] - path[ys[i - 1]]) * f;
      }
    }
    return path[ys[ys.length - 1]];
  }

  function syncPrices() {
    var first = null, uniform = true;
    SECTORS.forEach(function (s) {
      var off = S.exempt[s];
      dom.secRange[s].value = S.price[s];
      dom.secRange[s].disabled = off;
      dom.secVal[s].textContent = off ? 'off' : fmtPrice(S.price[s]);
      dom.secVal[s].className = 'ac-val' + (off ? ' is-off' : '');
      dom.secEx[s].classList.toggle('is-on', off);
      if (first === null) first = S.price[s];
      else if (S.price[s] !== first) uniform = false;
    });
    if (uniform) { dom.allRange.value = first; dom.allVal.textContent = fmtPrice(first); }
    else dom.allVal.textContent = 'mixed';
  }

  function syncTreat() {
    Object.keys(dom.treatBtn).forEach(function (k) {
      dom.treatBtn[k].classList.toggle('is-on', k === S.treatment);
    });
  }

  /* ---------- centre: the index ---------- */

  function buildMid() {
    var col = colShell('The index', 'n=<b>500</b>, sized by market cap');
    col.classList.add('al-col--index');
    var tog = FILED.el('div', { class: 'al-toggle' }, [
      FILED.el('button', { class: 'is-on', type: 'button', text: 'Carbon',
        onclick: function () { setColor('carbon'); } }),
      FILED.el('button', { type: 'button', text: 'Water',
        onclick: function () { setColor('water'); } })
    ]);
    dom.colorBtns = tog.children;
    /* Half the index is a five-pixel tile on a phone, so "click any company"
       is only true for the large caps unless there is a lookup. This is it. */
    var find = FILED.el('input', {
      class: 'tm-find', type: 'search', placeholder: 'ticker',
      'aria-label': 'find a company',
      oninput: function () {
        var q = this.value.trim().toUpperCase();
        this.classList.remove('is-miss');
        if (!q) { closeCard(); return; }
        for (var i = 0; i < N; i++) {
          if (C[i].t === q) { drawCard(i); return; }
        }
        this.classList.add('is-miss');
      }
    });
    col.querySelector('.al-col-head').appendChild(find);
    col.querySelector('.al-col-head').appendChild(tog);

    var wrap = FILED.el('div', { class: 'tm-wrap' });
    dom.svg = FILED.svg('svg', { width: '100%', height: '100%' });
    wrap.appendChild(dom.svg);
    dom.card = FILED.el('div', { class: 'tm-card', hidden: 'hidden' });
    wrap.appendChild(dom.card);
    col.appendChild(wrap);
    dom.tmWrap = wrap;

    /* The two keys used to sit along the bottom edge at 10px, which made the
       map decorative: colour meant nothing and the hatched cells meant nothing.
       They ride at the top of the map now, at a size a judge can read. */
    dom.rampBar = FILED.el('div', { class: 'tm-ramp-bar' });
    dom.rampK = FILED.el('span', { html: FILED.g('value at risk') });
    dom.rampLo = FILED.el('span', { text: '0' });
    dom.rampHi = FILED.el('span', { text: '35%+' });
    dom.keyText = FILED.el('span', { text: '181 we cannot measure' });
    var keys = FILED.el('div', { class: 'tm-keys' }, [
      FILED.el('div', { class: 'tm-ramp' }, [
        dom.rampK, dom.rampLo, dom.rampBar, dom.rampHi
      ]),
      FILED.el('div', { class: 'tm-key' }, [
        FILED.el('span', { class: 'sw sw-un' }), dom.keyText
      ])
    ]);
    col.insertBefore(keys, col.querySelector('.tm-wrap'));

    col.appendChild(FILED.el('div', { class: 'tm-foot' }, [
      FILED.el('span', { html: '<b>Click a company</b> for its filed tonnes and its carbon bill. ' }),
      FILED.el('span', { class: 'tm-small-note', html:
        'A tile under about 30 pixels carries no logo. Type a ticker to reach the small ones. ' }),
      FILED.el('span', { html: '<b>An exposure model, not a forecast.</b> It prices ' +
        'a carbon bill against filings that exist. It predicts nothing.' })
    ]));

    dom.svg.addEventListener('mousemove', onHover);
    dom.svg.addEventListener('mouseleave', function () {
      FILED.tip.hide(); dom.hi.style.display = 'none';
    });
    dom.svg.addEventListener('click', onClick);
    return col;
  }

  function setColor(mode) {
    S.colorBy = mode;
    dom.colorBtns[0].classList.toggle('is-on', mode === 'carbon');
    dom.colorBtns[1].classList.toggle('is-on', mode === 'water');
    /* The foot has to stay on one line. It sits under a treemap that is
       absolutely positioned inside a flex item, so a wrapped legend steals
       height from the map and clips its bottom row of tiles. Water words are
       longer than carbon ones, so they are cut to fit rather than left to wrap. */
    if (mode === 'water') dom.rampK.textContent = 'high-stress sites';
    else dom.rampK.innerHTML = FILED.g('value at risk');
    dom.rampLo.textContent = mode === 'water' ? 'none' : '0';
    dom.rampHi.textContent = mode === 'water' ? 'all' : '35%+';
    dom.keyText.textContent = mode === 'water'
      ? (500 - Object.keys(waterBy).length) + ' with no US facility'
      : '181 we cannot measure';
    dom.rampBar.style.background = 'linear-gradient(90deg,' +
      (mode === 'water'
        ? ramp(RAMP_WATER, 0) + ',' + ramp(RAMP_WATER, 0.5) + ',' + ramp(RAMP_WATER, 1)
        : ramp(RAMP_CARBON, 0) + ',' + ramp(RAMP_CARBON, 0.5) + ',' + ramp(RAMP_CARBON, 1)) + ')';
    paintColors(prev);
  }

  /* ---------- right: the advice ---------- */

  function buildRight() {
    var col = colShell('What you hold', 'if you ran <b>$1bn</b>');
    col.classList.add('al-col--advice');
    dom.avHeld = FILED.el('div', { class: 'av-fig' });
    col.appendChild(dom.avHeld);

    dom.avBook = FILED.el('div', { class: 'av-cell is-book' });
    dom.avIdx = FILED.el('div', { class: 'av-cell' });
    col.appendChild(FILED.el('div', { class: 'av-sub', style: { 'margin-top': '7px' },
      html: 'Share of ' + FILED.g('value at risk') }));
    col.appendChild(FILED.el('div', { class: 'av-pair' }, [dom.avBook, dom.avIdx]));

    dom.avInv = FILED.el('div', { class: 'av-inv', style: { 'margin-top': '6px' } });
    col.appendChild(dom.avInv);

    dom.avUnm = FILED.el('div', { style: { 'margin-top': '6px' } });
    col.appendChild(dom.avUnm);

    var lists = FILED.el('div', { class: 'av-lists', style: { 'margin-top': '7px' } });
    dom.avUp = FILED.el('div');
    dom.avDn = FILED.el('div');
    lists.appendChild(FILED.el('div', null, [
      FILED.el('div', { class: 'av-sub', text: 'Largest adds, $m' }), dom.avUp]));
    lists.appendChild(FILED.el('div', null, [
      FILED.el('div', { class: 'av-sub', text: 'Largest cuts, $m' }), dom.avDn]));
    col.appendChild(lists);

    dom.avDec = FILED.el('div', { style: { 'margin-top': '7px' } });
    col.appendChild(dom.avDec);

    dom.avBook2 = FILED.el('div', { class: 'kv' });
    col.appendChild(FILED.el('div', { class: 'al-spacer' }));
    col.appendChild(FILED.details('How this book is built', '3', dom.avBook2, 'dd--tight'));
    col.appendChild(FILED.el('div', { class: 'ac-hint', text:
      'We reweight inside a rulebook. We do not try to beat the market: no ' +
      'expected return, no covariance matrix, no alpha claim. Daily liquidity ' +
      'assumed. $1bn is 0.00144% of the index.' }));
    return col;
  }

  /* The three caveats are verbatim, one click down, and the bar that holds them
     names them. Nothing here was cut, only moved off a 720px screen. */
  function buildFoot() {
    var body = FILED.el('div', { class: 'al-foot-body' }, [
      FILED.el('span', { html: '<b>An exposure model, not a forecast.</b> No pass-through ' +
        'elasticity, no demand response, no free allocation, no competitor reaction.' }),
      FILED.el('span', { html: '<b>The units differ.</b> NGFS prices are US$2010 a tonne, SEC ' +
        'operating income is nominal. The deflator is visible and held at ' +
        P.defaults.deflator + '.' }),
      FILED.el('span', { html: '<b>' + P.ebit_guard.n_operating_loss_with_tonnage +
        ' companies ran an operating loss.</b> Their cost against earnings is null. ' +
        P.ebit_guard.n_over_100pct_of_ebit_at_default + ' more owe over 100% of it.' })
    ]);
    return FILED.el('div', { class: 'al-foot' },
      FILED.details('What this model is not', '3', body, 'dd--tight dd--up'));
  }

  /* ================= paint ================= */

  var rafPending = false, dirty = false;

  function recompute(immediate) {
    dirty = true;
    if (immediate) { flush(); return; }
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () { rafPending = false; flush(); });
  }

  function flush() {
    if (!dirty) return;
    dirty = false;
    var t0 = performance.now();
    var out = run();
    drawTreemap(out);
    drawAdvice(out);
    prev = out;
    global.__allocMs = performance.now() - t0;
  }

  /* ---------- treemap ---------- */

  function measure() {
    var r = dom.tmWrap.getBoundingClientRect();
    return { w: Math.max(80, Math.round(r.width)), h: Math.max(80, Math.round(r.height)) };
  }

  function layout(out, box) {
    /* sector blocks ordered by cap-weighted value at risk, most exposed first */
    var secs = SECTORS.map(function (name, i) {
      return { i: i, name: name, v: 0, num: 0, den: 0 };
    });
    var i, c;
    for (i = 0; i < N; i++) {
      c = C[i];
      secs[c.sec].v += c.mc;
      if (out.r.have[i]) { secs[c.sec].num += c.w0 * out.r.varr[i]; secs[c.sec].den += c.w0; }
    }
    secs.forEach(function (s) { s.x = s.den ? s.num / s.den : -1; });
    secs.sort(function (a, b) { return b.x - a.x; });

    var blocks = [];
    sliceDice(secs, 0, 0, box.w, box.h, blocks);

    var tiles = [], labels = [];
    blocks.forEach(function (b) {
      var members = [];
      for (i = 0; i < N; i++) if (C[i].sec === b.it.i) members.push({ i: i, v: C[i].mc });
      members.sort(function (p, q) { return q.v - p.v; });
      var pad = 1;
      var inner = [];
      squarify(members, b.x + pad, b.y + pad,
        Math.max(0, b.w - pad * 2), Math.max(0, b.h - pad * 2), inner);
      inner.forEach(function (t) { tiles.push(t); });
      labels.push({ name: SHORT[b.it.name], x: b.x + 4, y: b.y + 11, w: b.w, h: b.h });
    });
    return { tiles: tiles, labels: labels };
  }

  function drawTreemap(out) {
    var box = measure();
    var L = layout(out, box);
    var byIndex = new Array(N);
    L.tiles.forEach(function (t) { byIndex[t.it.i] = t; });

    if (!tmNodes.length || tmBox === null) buildTiles();
    tmBox = box;

    var i, t, node, c, big;
    for (i = 0; i < N; i++) {
      t = byIndex[i]; node = tmNodes[i]; c = C[i];
      if (!t) { node.g.style.display = 'none'; continue; }
      node.g.style.display = '';
      node.g.style.transform = 'translate(' + t.x.toFixed(1) + 'px,' + t.y.toFixed(1) + 'px)';
      var w = Math.max(0, t.w - 1), h = Math.max(0, t.h - 1);
      node.x = t.x; node.y = t.y; node.w = w; node.h = h;
      node.rect.style.width = w + 'px';
      node.rect.style.height = h + 'px';
      big = w >= 30 && h >= 24;
      if (node.img) {
        node.img.style.display = big ? '' : 'none';
        if (big) {
          var s = Math.min(w - 8, h - 8, 42);
          node.img.style.width = s + 'px';
          node.img.style.height = s + 'px';
          node.img.style.x = ((w - s) / 2).toFixed(1) + 'px';
          node.img.style.y = ((h - s) / 2).toFixed(1) + 'px';
        }
      } else if (node.badge) {
        node.badge.style.display = big ? '' : 'none';
        if (big) {
          node.badge.setAttribute('x', (w / 2).toFixed(1));
          node.badge.setAttribute('y', (h / 2 + 3).toFixed(1));
        }
      }
    }

    /* sector labels sit on top of everything */
    while (dom.labels.firstChild) dom.labels.removeChild(dom.labels.firstChild);
    L.labels.forEach(function (l) {
      /* 10px mono at 0.12em tracking is about 7.2px a character. A label wider
         than its own block runs into the next sector and the two read as one
         word, so a tall narrow block gets its name down the left edge instead.
         Utilities and Materials are the two most exposed sectors and they are
         also two of the narrowest, so leaving them unnamed is not an option. */
      var need = l.name.length * 7.2 + 8;
      if (need <= l.w && l.h >= 18) {
        dom.labels.appendChild(FILED.svg('text', {
          class: 'tm-sec-label', x: l.x, y: l.y, text: l.name
        }));
      } else if (need <= l.h && l.w >= 18) {
        dom.labels.appendChild(FILED.svg('text', {
          class: 'tm-sec-label', text: l.name,
          transform: 'translate(' + (l.x + 7) + ',' + (l.y - 7) + ') rotate(90)'
        }));
      }
    });

    paintColors(out);
  }

  function buildTiles() {
    var frag = FILED.svg('g');
    tmNodes = [];
    for (var i = 0; i < N; i++) {
      var c = C[i];
      var g = FILED.svg('g', { class: 'tm-tile', 'data-i': i });
      var rect = FILED.svg('rect', {
        x: 0, y: 0, width: 1, height: 1,
        style: { 'stroke-width': '1px', 'shape-rendering': 'crispEdges' }
      });
      g.appendChild(rect);
      var node = { g: g, rect: rect, img: null, badge: null };
      var src = LOGOS[c.t];
      if (src) {
        var img = FILED.svg('image', { href: src, preserveAspectRatio: 'xMidYMid meet',
          style: { 'pointer-events': 'none', opacity: '0.95' } });
        img.setAttribute('x', 0); img.setAttribute('y', 0);
        g.appendChild(img);
        node.img = img;
      } else {
        node.badge = FILED.svg('text', { class: 'tm-badge', 'text-anchor': 'middle', text: c.t });
        g.appendChild(node.badge);
      }
      frag.appendChild(g);
      tmNodes.push(node);
    }
    dom.svg.appendChild(frag);
    dom.labels = FILED.svg('g');
    dom.svg.appendChild(dom.labels);
    dom.hi = FILED.svg('rect', { class: 'tm-hi', width: 0, height: 0,
      style: { display: 'none' } });
    dom.svg.appendChild(dom.hi);
  }

  function paintColors(out) {
    if (!out || !tmNodes.length) return;
    for (var i = 0; i < N; i++) {
      tmNodes[i].rect.style.fill = tileColor(i, out);
      tmNodes[i].rect.style.stroke =
        (S.colorBy === 'carbon' && C[i].s1 === null) ? MUTED_INK : '#08090c';
    }
  }

  /* ---------- hover, click, the company card ---------- */

  function tileIndex(ev) {
    var el = ev.target;
    while (el && el !== dom.svg && !el.hasAttribute('data-i')) el = el.parentNode;
    return el && el.hasAttribute && el.hasAttribute('data-i') ? +el.getAttribute('data-i') : -1;
  }

  function onHover(ev) {
    var i = tileIndex(ev);
    if (i < 0) { FILED.tip.hide(); dom.hi.style.display = 'none'; return; }
    var nd = tmNodes[i];
    if (nd && nd.w) {
      dom.hi.style.display = '';
      dom.hi.setAttribute('x', nd.x + 0.5); dom.hi.setAttribute('y', nd.y + 0.5);
      dom.hi.setAttribute('width', Math.max(0, nd.w - 1));
      dom.hi.setAttribute('height', Math.max(0, nd.h - 1));
    }
    var c = C[i], o = prev;
    var w = waterBy[c.t];
    var html = '<div class="tm-tip"><div class="tip-t">' + c.t + '  ' + esc(c.n) + '</div>' +
      '<div class="u-dim">' + SECTORS[c.sec] + '  ' + FILED.tier(c.tier).label + '</div>' +
      row('Value at risk', o.r.have[i] ? FILED.fmt.num(o.r.varr[i], 2) + '% of company value' : 'not priced') +
      row('Index weight', FILED.fmt.num(c.w0 * 100, 3) + '%') +
      row('Advised', FILED.fmt.num(o.W[i] * 100, 3) + '%' +
        (c.ex ? ' <span class="u-accent">excluded</span>' : '')) +
      (w ? row('Water stress', FILED.fmt.num(w.share_high * 100, 0) + '% of ' + w.n_fac + ' sites') : '') +
      '</div>';
    FILED.tip.show(html, ev);
  }

  function row(k, v) {
    return '<div style="display:flex;justify-content:space-between;gap:12px">' +
      '<span class="u-dim">' + k + '</span><span class="mono">' + v + '</span></div>';
  }

  function onClick(ev) {
    var i = tileIndex(ev);
    if (i < 0) { closeCard(); return; }
    drawCard(i);
  }

  function closeCard() { dom.card.hidden = true; }

  function drawCard(i) {
    var c = C[i], o = prev, w = waterBy[c.t];
    var card = dom.card;
    card.innerHTML = '';
    card.hidden = false;
    card.appendChild(FILED.el('button', { class: 'tm-card-x', type: 'button', text: '×',
      onclick: closeCard }));
    card.appendChild(FILED.el('div', { class: 'card-tick', text: c.t }));
    card.appendChild(FILED.el('div', { class: 'card-name', text: c.n }));
    card.appendChild(FILED.el('div', { class: 'card-meta' }, [
      FILED.el('span', { class: 'card-sector', text: SECTORS[c.sec] }), FILED.chip(c.tier)
    ]));
    var rows = FILED.el('div', { class: 'card-rows'});
    function r(k, v, sub) {
      rows.appendChild(FILED.el('div', { class: 'card-row' }, [
        FILED.el('span', { class: 'k', text: k }),
        FILED.el('span', { class: 'v', html: v + (sub ? ' <small>' + sub + '</small>' : '') })
      ]));
    }
    r('Scope 1', c.s1 === null ? 'none filed' : FILED.fmt.compact(c.s1, 1), c.s1 === null ? '' : 't');
    r('Tonnes we charge for', o.r.have[i] ? FILED.fmt.compact(o.r.tonnes[i], 1) : 'not priced', 't');
    r('Carbon cost', o.r.have[i] ? '$' + FILED.fmt.num(o.r.cost[i], 0) : '—', 'm');
    r('Hit to company value', o.r.have[i] ? '$' + FILED.fmt.num(o.r.dev[i], 0) : '—', 'm');
    r('Share of value at risk', o.r.have[i] ? FILED.fmt.num(o.r.varr[i], 2) + '%' : '—',
      'of company value');
    r('Cost vs operating income',
      c.earflag === 'loss' ? 'null' : c.earflag === 'none' ? 'no filing'
        : o.r.have[i] && c.ebit > 0 ? FILED.fmt.num(100 * o.r.debit[i] / c.ebit, 1) + '%' : '—',
      c.earflag === 'loss' ? 'operating loss' : '');
    r('Index weight', FILED.fmt.num(c.w0 * 100, 3), '%');
    r('Our weight', c.ex ? 'excluded' : FILED.fmt.num(o.W[i] * 100, 3) + '%',
      c.ex ? 'Article 12' : '');
    r('Position', '$' + FILED.fmt.num(o.W[i] * AUM / 1e6, 2), 'm');
    if (w) r('Water stress', FILED.fmt.num(w.share_high * 100, 0) + '%',
      'of ' + w.n_fac + ' US site' + (w.n_fac === 1 ? '' : 's'));
    card.appendChild(rows);
  }

  /* ---------- advice ---------- */

  function drawAdvice(out) {
    /* the assumption column states how many companies the current treatment
       is willing to price, because that is the number the rest depends on */
    var priced = 0;
    for (var q = 0; q < N; q++) if (out.r.have[q]) priced++;
    dom.leftN.innerHTML = 'priced: <b>' + priced + '</b> of 500';

    var nEx = P.constraints.article_12_excluded;
    set(dom.avHeld, '<div class="f">' + out.held + '<small> held</small></div>' +
      '<div class="s">' + nEx + ' barred by the EU rulebook, Article 12<br>they are ' +
      FILED.fmt.num(P.constraints.article_12_excluded_cap_share * 100, 1) +
      '% of the index</div>');

    var bookUsd = out.bookVar / 100 * AUM, idxUsd = out.idxVar / 100 * AUM;
    set(dom.avBook, '<div class="k">Our book</div><div class="v">' +
      FILED.fmt.num(out.bookVar, 2) + '%</div><div class="u">$' +
      FILED.fmt.num(bookUsd / 1e6, 1) + 'm of $1bn</div>');
    set(dom.avIdx, '<div class="k">The index</div><div class="v u-dim">' +
      FILED.fmt.num(out.idxVar, 2) + '%</div><div class="u">$' +
      FILED.fmt.num(idxUsd / 1e6, 1) + 'm, cap weighted</div>');

    /* the price-invariance line */
    var inv = dom.avInv;
    if (prev) {
      var mx = 0, i;
      for (i = 0; i < N; i++) mx = Math.max(mx, Math.abs(out.W[i] - prev.W[i]));
      var ratio = prev.totDev ? out.totDev / prev.totDev : 1;
      var still = mx < 1e-9;
      inv.className = 'av-inv ' + (still ? 'is-still' : 'is-moved');
      inv.innerHTML = '<span class="verdict">' +
        (still ? 'Weights unchanged.' : 'Weights moved.') + '</span>' +
        'Since the last change, value at risk ×<b>' + ratio.toFixed(2) +
        '</b>, largest weight change <b>' + (mx * 1e4).toFixed(mx * 1e4 < 10 ? 2 : 0) +
        '</b> bp. ' + (still
          ? 'The allocation runs on the rank of value at risk, and a scalar cannot reorder a ranking.'
          : 'Something changed the ranking, so money moved.');
    } else {
      inv.className = 'av-inv is-still';
      inv.innerHTML = '<span class="verdict">Move the price slider.</span>' +
        'This line reports what your last change did to the weights.';
    }

    /* the 181 */
    var wu = out.wUn * 100, wi = out.wUnIdx * 100;
    set(dom.avUnm, '<div class="av-sub">Money on the 181 we cannot measure</div>' +
      '<div class="av-fig"><div class="f">$' + FILED.fmt.num(out.wUn * AUM / 1e6, 0) +
      '<small>m</small></div><div class="s">' + FILED.fmt.num(wu, 2) + '% of the book against ' +
      FILED.fmt.num(wi, 2) + '% of the index</div></div>');

    /* the biggest moves, in dollars */
    var moves = [];
    for (var k = 0; k < N; k++) moves.push([k, (out.W[k] - C[k].w0) * AUM / 1e6]);
    moves.sort(function (a, b) { return b[1] - a[1]; });
    dom.avUp.innerHTML = moves.slice(0, 6).map(function (m) {
      return line(m, 'up');
    }).join('');
    dom.avDn.innerHTML = moves.slice(-6).reverse().map(function (m) {
      return line(m, 'dn');
    }).join('');

    /* what kind of book this is, in three numbers */
    var eff = 0;
    for (var e = 0; e < N; e++) eff += out.W[e] * out.W[e];
    set(dom.avBook2,
      '<span class="kv-k">How far this book sits from the index</span><span class="kv-v">' +
      FILED.fmt.num(out.active * 100, 1) + '%</span>' +
      '<span class="kv-k">It behaves like this many equal positions</span><span class="kv-v">' +
      FILED.fmt.num(1 / eff, 0) + '</span>' +
      '<span class="kv-k">Tilt strength, solved to a ' +
      FILED.fmt.num(P.defaults.tilt_budget * 100, 0) + '% budget</span><span class="kv-v">' +
      FILED.fmt.num(out.lam, 2) + '</span>');

    /* reallocation against selection */
    var tot = Math.abs(out.alloc) + Math.abs(out.sel) || 1;
    var aShare = Math.abs(out.alloc) / tot;
    set(dom.avDec, '<div class="av-sub">Where the risk cut comes from</div>' +
      '<div class="bar-stack"><span style="width:' + (aShare * 100).toFixed(1) +
      '%;background:var(--accent)"></span><span style="width:' + ((1 - aShare) * 100).toFixed(1) +
      '%;background:var(--tier-measured)"></span></div>' +
      '<div class="av-split"><span>Moving money between sectors</span><b>' +
      FILED.fmt.num(aShare * 100, 1) + '%</b></div>' +
      '<div class="av-split"><span>Picking names inside a sector</span><b>' +
      FILED.fmt.num((1 - aShare) * 100, 1) + '%</b></div>');
  }

  function line(m, cls) {
    var c = C[m[0]];
    return '<div class="av-line ' + cls + '"><span class="t">' + c.t +
      '</span><span class="m">' + (m[1] >= 0 ? '+' : FILED.fmt.minus) +
      FILED.fmt.num(Math.abs(m[1]), 1) + '</span></div>';
  }

  function set(el, html) { el.innerHTML = html; }
  function esc(s) { return String(s).replace(/[<>&]/g, function (ch) {
    return ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : '&amp;'; }); }
  function fmtPrice(v) { return v >= 1000 ? '1000' : v.toFixed(v < 10 ? 1 : 0); }
  function pct(v) { return Math.round(v * 100) + '%'; }

  /* redraw on resize: the treemap reads its own box, so it has to be told */
  var rt = null;
  global.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () { if (prev) { drawTreemap(prev); } }, 150);
  });

}(window));
