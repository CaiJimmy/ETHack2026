/* Hero figures and the say-do scatter.
   Every number here is read out of the JSON. Nothing is typed into the markup. */
(function () {
  'use strict';

  var F = window.FILED;
  var fmt = F.fmt;

  /* how a target was sourced, short enough for the card's fixed width */
  var PROMISE_SRC_SHORT = {
    sbti_s12_absolute: 'SBTi scope 1+2 absolute',
    sbti_combined:     'SBTi combined',
    nzt_interim:       'Net Zero Tracker interim',
    netzero_inferred:  'implied by a net zero year',
    none:              'no target'
  };

  /* fit flags, in words */
  var FLAGS = {
    perimeter_drift: 'reporting boundary drifts across the window',
    stale:           'latest measured year is not recent',
    large_rate:      'fitted rate is large, read the fit with care'
  };

  F.onReady(function (D) {
    renderChrome(D);
    renderHero(D);
    renderSayDo(D);
  });

  /* ---------------- nav footer and build stamp ---------------- */

  function renderChrome(D) {
    var m = D.scores.meta;
    var day = String(m.built).slice(0, 10);
    document.getElementById('hero-build').textContent = 'build ' + day;
    document.getElementById('nav-foot').innerHTML =
      '<div class="mono">' + day + '</div>' +
      '<div style="margin-top:6px">' + fmt.int(m.n_draws) + ' draws over ' +
      Object.keys(m.trigger_factors).length + ' modelling choices</div>' +
      '<div style="margin-top:6px">EPA GHGRP &middot; SEC XBRL &middot; NGFS &middot; EU 2020/1818</div>';

    /* the file names, the seed and the build stamp: one place, once */
    F.drawer.add('build', 'The build, and where the numbers live',
      '<p class="mono">' + day + ' &middot; seed ' + m.seed + ' &middot; ' +
      fmt.int(m.n_draws) + ' draws</p>' +
      '<dl>' +
      '<dt>scores.json</dt><dd>the rank intervals, the variance decomposition, ' +
      'the coverage tiers. ' + fmt.int(m.n_draws) + ' draws over ' +
      Object.keys(m.trigger_factors).length + ' modelling choices.</dd>' +
      '<dt>say_do.json</dt><dd>the promise against the EPA-measured trend.</dd>' +
      '<dt>portfolio.json</dt><dd>the three books, the article tests and the ' +
      'decomposition of the carbon cut, built against EU 2020/1818.</dd>' +
      '<dt>ear.json</dt><dd>the carbon price path and earnings at risk.</dd>' +
      '<dt>bias.json</dt><dd>the disclosure regressions and the vendor comparison.</dd>' +
      '<dt>penalty.json</dt><dd>everything the control surface on screen one ' +
      'recomputes in the browser.</dd>' +
      '</dl><p>Every figure on the site is read out of those files. Nothing is ' +
      'typed into the markup, and the seed is fixed so the draws reproduce.</p>');
  }

  /* ---------------- hero ---------------- */

  function renderHero(D) {
    var h = D.scores.headline;
    var meta = D.scores.meta;
    var cov = D.scores.coverage.by_tier;
    var st = D.say_do.stats;
    var pab = D.portfolio.portfolios.pab_compliant;
    var dec = pab.decomposition;

    /* share of the portfolio's intensity cut that is reallocation between
       sectors rather than any company improving */
    var reallocShare = dec.reallocation / dec.total;
    var improveShare = dec.improvement / dec.total;

    set('stat-band', fmt.num(h.median_rank_band_width, 1) +
      '<span class="of"> / ' + meta.n_companies + '</span>');
    set('stat-band-sub',
      fmt.int(h.n_wider_than_100) + ' of ' + meta.n_companies +
      ' companies span more than 100 ranks. The honest output is an interval, not a rank.');
    set('stat-band-src', '5th to 95th percentile over ' + fmt.int(meta.n_draws) + ' draws');

    set('stat-saydo', fmt.int(st.missing) +
      '<span class="of"> / ' + fmt.int(st.n_plotted) + '</span>');
    set('stat-saydo-sub',
      'Of the companies carrying both a target and an EPA-measured trend, ' +
      fmt.int(st.missing) + ' emit more than they said they would. Median promised cut ' +
      fmt.num(st.median_promised_cut_pct_yr, 2) + '%/yr, delivered ' +
      fmt.num(st.median_delivered_cut_pct_yr, 2) + '%/yr.');
    set('stat-saydo-src', 'EPA-measured tonnes against the company&rsquo;s own target');

    set('stat-pab', fmt.share(reallocShare, 1));
    set('stat-pab-sub',
      'A $' + fmt.compact(D.portfolio.meta.aum_usd, 0) + ' Paris-aligned fund finances ' +
      fmt.share(pab.cut_vs_universe, 1) + ' fewer tonnes per dollar than the index. Selling the ' +
      'highest-emitting sectors does ' + fmt.share(reallocShare, 1) + ' of that. Companies cutting ' +
      'emissions do ' + fmt.share(improveShare, 1) + '.');
    set('stat-pab-src', 'built from EU 2020/1818, article by article');

    set('hero-data',
      '<b>' + D.say_do.meta.n_listings + ' listings, ' + meta.n_companies + ' companies.</b> ' +
      fmt.int(cov.measured) + ' measured by the EPA, ' +
      fmt.int(cov.reported) + ' self-reported only, ' +
      '<span class="u-muted">' + fmt.int(cov.unmeasurable) +
      ' with no mandatory number at all</span>. Financials from SEC filings throughout.');
  }

  function set(id, html) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = html;
  }

  /* ---------------- the scatter ---------------- */

  var state = { pinned: null, D: null, points: [] };

  function renderSayDo(D) {
    state.D = D;
    var spec = D.say_do.chart;
    var st = D.say_do.stats;
    var rows = D.say_do.companies;
    var plotted = rows.filter(function (c) { return c.state === 'plotted'; });

    document.getElementById('saydo-title').textContent =
      fmt.int(st.missing) + ' of ' + fmt.int(st.n_plotted) +
      ' companies emit more than they promised';

    document.getElementById('saydo-lede').textContent =
      'Promised on the horizontal, EPA-measured on the vertical.';

    drawChart(plotted, spec, D);
    showDefaultCard(D);
    renderStates(D, rows);
    renderCaveats(D);

    /* the plot is sized to its container, so a resize has to redraw it */
    var t = null;
    window.addEventListener('resize', function () {
      clearTimeout(t);
      t = setTimeout(function () { drawChart(plotted, spec, D); }, 180);
    });
  }

  /* frame from the data, not from a typed-in number: 2nd to 98th percentile
     with a pad, rounded out to a 2-point step. Points outside are pinned to
     the edge and counted under the chart. */
  function frameOf(values) {
    var a = values.slice().sort(function (p, q) { return p - q; });
    var lo = quantile(a, 0.02), hi = quantile(a, 0.98);
    var pad = (hi - lo) * 0.08;
    return [Math.floor((lo - pad) / 2) * 2, Math.ceil((hi + pad) / 2) * 2];
  }

  function quantile(sorted, p) {
    var i = (sorted.length - 1) * p, lo = Math.floor(i);
    return sorted[lo] + (sorted[Math.min(lo + 1, sorted.length - 1)] - sorted[lo]) * (i - lo);
  }

  function drawChart(plotted, spec, D) {
    var host = document.getElementById('saydo-chart');
    host.innerHTML = '';

    /* The floor used to be 420, which is wider than a phone, so the chart
       pushed the page sideways instead of redrawing into it. */
    var W = Math.max(280, host.clientWidth || 628);
    var narrow = W < 420;
    var H = narrow ? 330 : 424;
    var M = narrow ? { t: 14, r: 10, b: 56, l: 40 } : { t: 18, r: 16, b: 66, l: 58 };
    var px0 = M.l, px1 = W - M.r, py0 = H - M.b, py1 = M.t;

    var fx = frameOf(plotted.map(function (c) { return c.promised; }));
    var fy = frameOf(plotted.map(function (c) { return c.delivered; }));
    var x = F.scale(fx, [px0, px1]);
    var y = F.scale(fy, [py0, py1]);

    var svg = F.svg('svg', {
      width: W, height: H, role: 'img',
      'aria-label': 'Promised against delivered annual change in Scope 1 emissions, ' +
        plotted.length + ' companies'
    });

    /* plot ground */
    svg.appendChild(F.svg('rect', {
      x: px0, y: py1, width: px1 - px0, height: py0 - py1,
      fill: 'var(--bg-sunk)', stroke: 'none'
    }));

    /* the half plane above delivered = promised: every company in it is
       emitting more than it said it would */
    var clipLo = Math.max(fx[0], fy[0]), clipHi = Math.min(fx[1], fy[1]);
    var above = [[px0, py1], [px1, py1], [x(clipHi), y(clipHi)], [x(clipLo), y(clipLo)]];
    /* left of clipLo the whole column sits above the line, so close on the
       bottom-left corner rather than cutting a diagonal */
    if (clipLo > fx[0]) above.push([px0, py0]);
    svg.appendChild(F.svg('polygon', {
      points: above.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '),
      fill: 'var(--accent)', opacity: 0.06
    }));

    F.axisY(svg, y, {
      x: px0, ticks: 5, grid: [px0, px1],
      fmt: function (v) { return fmt.signed(v, 0); },
      label: spec.y_label.split(':')[0] + ' (%/yr)', labelX: 14
    });
    F.axisX(svg, x, {
      y: py0, ticks: 4,
      fmt: function (v) { return fmt.signed(v, 0); },
      label: spec.x_label.split(':')[0] + ' (%/yr)'
    });

    /* zero lines, so "still growing" is readable at a glance */
    if (fy[0] < 0 && fy[1] > 0) {
      svg.appendChild(F.svg('line', {
        x1: px0, x2: px1, y1: y(0).toFixed(1), y2: y(0).toFixed(1),
        stroke: 'var(--rule-2)', 'stroke-width': 1
      }));
    }

    /* delivered = promised */
    svg.appendChild(F.svg('line', {
      class: 'ref-line',
      x1: x(clipLo), y1: y(clipLo), x2: x(clipHi), y2: y(clipHi)
    }));
    /* the label rides the line itself, set down into the empty corner rather
       than across the cloud */
    var lt = 0.24;
    var lv = clipLo + (clipHi - clipLo) * lt;
    var ang = Math.atan2(y(clipHi) - y(clipLo), x(clipHi) - x(clipLo)) * 180 / Math.PI;
    svg.appendChild(F.svg('text', {
      transform: 'translate(' + x(lv).toFixed(1) + ',' + y(lv).toFixed(1) +
        ') rotate(' + ang.toFixed(2) + ') translate(0,16)',
      'text-anchor': 'middle', class: 'pt-label',
      style: 'fill:var(--ink-3)', text: 'delivered = promised'
    }));

    svg.appendChild(F.svg('text', {
      x: px0 + 12, y: py1 + 20, class: 'tick-label',
      text: spec.above_line.toUpperCase(),
      style: 'letter-spacing:0.1em;fill:var(--accent)'
    }));
    svg.appendChild(F.svg('text', {
      x: px1 - 8, y: py0 - 10, 'text-anchor': 'end', class: 'tick-label',
      text: spec.below_line.toUpperCase(),
      style: 'letter-spacing:0.1em;fill:var(--cool)'
    }));

    /* points. Radius is log tonnes: linear in tonnes would leave 90 of the
       108 as dots. The legend says so. */
    var tonnes = plotted.map(function (c) { return c.tonnes; });
    var lmin = Math.log(Math.min.apply(null, tonnes));
    var lmax = Math.log(Math.max.apply(null, tonnes));
    function radius(t) { return 3.2 + 10.8 * (Math.log(t) - lmin) / (lmax - lmin); }

    var gPts = F.svg('g', { class: 'pts' });
    svg.appendChild(gPts);

    var placed = [];
    state.points = [];
    var offFrame = [];

    /* biggest first, so the small ones stay clickable on top */
    plotted.slice().sort(function (a, b) { return b.tonnes - a.tonnes; })
      .forEach(function (c) {
        var cx = x(clampTo(c.promised, fx));
        var cy = y(clampTo(c.delivered, fy));
        var off = c.promised < fx[0] || c.promised > fx[1] ||
                  c.delivered < fy[0] || c.delivered > fy[1];
        if (off) offFrame.push(c);
        var r = radius(c.tonnes);
        var miss = c.gap > 0;
        var node;
        if (off) {
          /* a triangle at the edge: the value is real, the position is not */
          node = F.svg('path', {
            d: triangle(cx, cy, Math.max(5, r * 0.8), edgeAngle(c, fx, fy)),
            fill: miss ? 'var(--accent)' : 'var(--cool)',
            stroke: 'var(--bg-sunk)', 'stroke-width': 1, opacity: 0.9,
            'data-t': c.t
          });
        } else {
          node = F.svg('circle', {
            class: 'pt', cx: cx.toFixed(1), cy: cy.toFixed(1), r: r.toFixed(1),
            fill: miss ? 'var(--accent)' : 'var(--cool)',
            'fill-opacity': 0.72, stroke: 'var(--bg-sunk)',
            'data-t': c.t
          });
        }
        node.style.cursor = 'pointer';
        node.addEventListener('mouseenter', function () { hoverCompany(c); });
        node.addEventListener('mouseleave', function () { unhover(); });
        node.addEventListener('click', function (ev) { ev.stopPropagation(); pin(c); });
        gPts.appendChild(node);
        placed.push({ x: cx, y: cy, r: r });
        state.points.push({ c: c, node: node });
      });

    /* permanent labels, because a recording has no cursor to rest */
    var wanted = {};
    (spec.label_tickers || []).forEach(function (t) { wanted[t] = true; });
    var labelled = plotted.filter(function (c) { return wanted[c.t]; });
    var boxes = [];
    var gLead = F.svg('g', {});
    svg.appendChild(gLead);
    var DIRS = [
      [1, 0], [-1, 0], [0.72, -0.72], [0.72, 0.72], [-0.72, -0.72],
      [-0.72, 0.72], [0, -1], [0, 1]
    ];
    labelled.forEach(function (c) {
      var cx = x(clampTo(c.promised, fx)), cy = y(clampTo(c.delivered, fy));
      var r = radius(c.tonnes);
      var t = F.svg('text', { class: 'pt-label', text: c.t });
      svg.appendChild(t);
      var w = t.getComputedTextLength ? t.getComputedTextLength() : c.t.length * 8.4;

      /* try tight first, then step outward. A label that ends up far from its
         point gets a leader, so nothing is ambiguous. */
      var best = null, bestDist = 0;
      var rings = [r + 7, r + 20, r + 34, r + 50];
      for (var ri = 0; ri < rings.length && !best; ri++) {
        for (var di = 0; di < DIRS.length; di++) {
          var d = DIRS[di], dist = rings[ri];
          var lx = cx + d[0] * dist;
          var ly = cy + d[1] * dist + (d[1] === 0 ? 4 : d[1] < 0 ? -2 : 11);
          var anchor = d[0] > 0.3 ? 'start' : d[0] < -0.3 ? 'end' : 'middle';
          var cand = [lx, ly, anchor];
          var b = boxOf(cand, w);
          if (b.x0 < px0 + 2 || b.x1 > px1 - 2 || b.y0 < py1 + 2 || b.y1 > py0 - 2) continue;
          if (hits(b, boxes) || hitsPts(b, placed)) continue;
          best = cand; bestDist = dist;
          break;
        }
      }
      if (!best) { best = [cx + r + 7, cy + 4, 'start']; bestDist = r + 7; }

      var box = boxOf(best, w);
      boxes.push(box);
      t.setAttribute('x', best[0].toFixed(1));
      t.setAttribute('y', best[1].toFixed(1));
      t.setAttribute('text-anchor', best[2]);

      if (bestDist > r + 12) {
        var tx = Math.max(box.x0, Math.min(cx, box.x1));
        var ty = Math.max(box.y0, Math.min(cy, box.y1));
        var vx = tx - cx, vy = ty - cy;
        var len = Math.sqrt(vx * vx + vy * vy) || 1;
        gLead.appendChild(F.svg('line', {
          class: 'leader',
          x1: (cx + vx / len * (r + 1)).toFixed(1), y1: (cy + vy / len * (r + 1)).toFixed(1),
          x2: tx.toFixed(1), y2: ty.toFixed(1)
        }));
      }
    });

    /* a ring that follows the hover, so the card is never ambiguous */
    var ring = F.svg('circle', { class: 'hover-ring', r: 0, cx: 0, cy: 0, opacity: 0 });
    svg.appendChild(ring);
    state.ring = ring;
    state.ringAt = function (c) {
      if (!c) { ring.setAttribute('opacity', 0); return; }
      ring.setAttribute('cx', x(clampTo(c.promised, fx)).toFixed(1));
      ring.setAttribute('cy', y(clampTo(c.delivered, fy)).toFixed(1));
      ring.setAttribute('r', (radius(c.tonnes) + 4).toFixed(1));
      ring.setAttribute('opacity', 1);
    };

    host.appendChild(svg);
    renderLegend(D, plotted, offFrame);
  }

  function clampTo(v, f) { return Math.max(f[0], Math.min(f[1], v)); }

  function edgeAngle(c, fx, fy) {
    if (c.delivered < fy[0]) return 90;      /* points down */
    if (c.delivered > fy[1]) return -90;
    if (c.promised < fx[0]) return 180;
    return 0;
  }

  function triangle(cx, cy, r, deg) {
    var a = deg * Math.PI / 180;
    var pts = [[r, 0], [-r * 0.8, r * 0.8], [-r * 0.8, -r * 0.8]].map(function (p) {
      return [
        (cx + p[0] * Math.cos(a) - p[1] * Math.sin(a)).toFixed(1),
        (cy + p[0] * Math.sin(a) + p[1] * Math.cos(a)).toFixed(1)
      ].join(',');
    });
    return 'M' + pts.join('L') + 'Z';
  }

  function boxOf(cand, w) {
    var x = cand[0], y = cand[1], anchor = cand[2];
    var x0 = anchor === 'start' ? x : anchor === 'end' ? x - w : x - w / 2;
    return { x0: x0 - 2, x1: x0 + w + 2, y0: y - 12, y1: y + 3 };
  }

  function hits(b, boxes) {
    return boxes.some(function (o) {
      return !(b.x1 < o.x0 || b.x0 > o.x1 || b.y1 < o.y0 || b.y0 > o.y1);
    });
  }

  function hitsPts(b, pts) {
    return pts.some(function (p) {
      return p.x + p.r > b.x0 && p.x - p.r < b.x1 && p.y + p.r > b.y0 && p.y - p.r < b.y1;
    });
  }

  /* ---------------- legend ---------------- */

  function renderLegend(D, plotted, offFrame) {
    var st = D.say_do.stats;
    var lg = document.getElementById('saydo-legend');
    lg.innerHTML =
      item('var(--accent)', 'missing the promise (' + fmt.int(st.missing) + ')') +
      item('var(--cool)', 'beating it (' + fmt.int(st.beating) + ')');
    document.getElementById('saydo-sizekey').innerHTML =
      'Point size: ' + F.g('Scope 1') + ' tonnes, log scale. ' +
      'All ' + fmt.int(plotted.length) + ' plotted are companies the EPA measures directly. ' +
      (offFrame.length
        ? '<span class="u-dim">' + offFrame.length + ' sit outside the frame (' +
          offFrame.map(function (c) { return c.t; }).join(', ') +
          ') and are pinned to the edge as triangles.</span>'
        : '');
  }

  function item(color, label) {
    return '<span class="legend-item"><span class="swatch" style="background:' + color +
      '"></span>' + label + '</span>';
  }

  /* ---------------- the company card ---------------- */

  function hoverCompany(c) {
    if (state.pinned) return;
    if (state.ringAt) state.ringAt(c);
    fillCard(c);
  }
  function unhover() {
    if (state.pinned) return;
    if (state.ringAt) state.ringAt(null);
    showDefaultCard(state.D);
  }

  function pin(c) {
    var card = document.getElementById('saydo-card');
    if (state.pinned && state.pinned.t === c.t) {
      state.pinned = null;
      card.classList.remove('is-pinned');
      if (state.ringAt) state.ringAt(null);
      showDefaultCard(state.D);
      return;
    }
    state.pinned = c;
    if (state.ringAt) state.ringAt(c);
    card.classList.add('is-pinned');
    fillCard(c);
  }

  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && state.pinned) {
      state.pinned = null;
      document.getElementById('saydo-card').classList.remove('is-pinned');
      if (state.ringAt) state.ringAt(null);
      showDefaultCard(state.D);
    }
  });

  function showDefaultCard(D) {
    var st = D.say_do.stats;
    var card = document.getElementById('saydo-card');
    card.innerHTML =
      '<div class="card-head">' +
        '<div class="card-tick">THE MEDIAN COMPANY</div>' +
        '<div class="card-name">of the ' + fmt.int(st.n_plotted) + ' plotted here</div>' +
        '<div class="card-meta"><span class="chip chip--measured">measured</span>' +
          '<span class="card-sector">n = ' + fmt.int(st.n_plotted) + ' of ' +
          fmt.int(D.say_do.meta.n_listings) + ' listings</span></div>' +
      '</div>' +
      /* the stats file states the medians as CUTS. The chart, and every company
         card, states change rates. Negate so the two never disagree on a sign. */
      trio(-st.median_promised_cut_pct_yr, -st.median_delivered_cut_pct_yr,
           st.median_gap_pct_yr, ['promised', 'delivered', 'gap']) +
      '<div class="card-verdict is-miss">' + fmt.int(st.missing) + ' of ' + fmt.int(st.n_plotted) +
        ' emit more than their own target implies.</div>' +
      '<div class="card-rows">' +
        row('Beating their target', fmt.int(st.beating)) +
        row('Emitting more than they used to', fmt.int(st.rising_absolute)) +
      '</div>' +
      '<div class="card-hint">Hover any point for the company. Click to pin it.</div>';
  }

  function fillCard(c) {
    var D = state.D;
    var card = document.getElementById('saydo-card');
    var sc = F.index.scores[c.t] || null;
    var ea = F.index.ear[c.t] || null;
    var ear300 = ea && ea.ear_pct_by_price ? ea.ear_pct_by_price['300'] : null;
    var miss = c.gap > 0;
    var tier = F.tier(c.tier);

    var flags = (c.flags || '').split('|').filter(Boolean).map(function (f) {
      return FLAGS[f] || f;
    });

    var html =
      '<div class="card-head">' +
        '<div class="card-tick">' + c.t + '</div>' +
        '<div class="card-name">' + c.n + '</div>' +
        '<div class="card-meta">' +
          '<span class="chip chip--' + c.tier + '">' + tier.label + '</span>' +
          '<span class="card-sector">' + c.s + '</span>' +
        '</div>' +
      '</div>' +
      trio(c.promised, c.delivered, c.gap, ['promised', 'delivered', 'gap']) +
      '<div class="card-verdict ' + (miss ? 'is-miss' : 'is-beat') + '">' +
        (miss
          ? 'Emitting ' + fmt.num(Math.abs(c.gap), 2) + ' points a year more than the target implies.'
          : 'Cutting ' + fmt.num(Math.abs(c.gap), 2) + ' points a year faster than the target implies.') +
      '</div>' +
      '<div class="card-rows">' +
        row('Target', '<small>' + (PROMISE_SRC_SHORT[c.promised_src] || c.promised_src) + '</small>') +
        row('Trend fit', 'R&sup2; ' + fmt.num(c.r2, 2) + ' <small>&middot; ' + c.n_years +
            ' yrs ' + c.y0 + '&ndash;' + c.y1 + '</small>') +
        row('Scope 1', fmt.compact(c.tonnes, 1) + ' <small>tCO&#8322;e' +
            (ea && ea.emissions_year ? ' &middot; ' + ea.emissions_year : '') + '</small>') +
        row('Carbon cost at $300 a tonne',
            ear300 === null || ear300 === undefined
              ? '<span class="u-muted">not measurable</span>'
              : fmt.num(ear300, 1) + '% <small>of op income</small>') +
        (sc ? row('Rank band', fmt.int(sc.p05) + '&ndash;' + fmt.int(sc.p95) +
              ' <small>median ' + fmt.int(sc.med) + '</small>')
            : row('Rank band', '<span class="u-muted">not scored</span>')) +
      '</div>' +
      (sc ? bandSvg(sc, D.scores.meta.n_companies) : '') +
      (flags.length
        ? '<div class="card-hint">Fit flag: ' + flags.join('. ') + '.</div>'
        : '<div class="card-hint">No fit flags on this window.</div>');

    card.innerHTML = html;
  }

  function trio(p, d, g, keys) {
    var miss = g > 0;
    return '<div class="card-trio">' +
      cell(keys[0], fmt.num(p, 2), '%/yr', '') +
      cell(keys[1], fmt.num(d, 2), '%/yr', '') +
      cell(keys[2], fmt.signed(g, 2), '%/yr', miss ? 'ct-gap-miss' : 'ct-gap-beat') +
      '</div>';
  }

  function cell(k, v, u, cls) {
    return '<div><div class="ct-k">' + k + '</div>' +
      '<div class="ct-v ' + cls + '">' + v + '</div>' +
      '<div class="ct-u">' + u + '</div></div>';
  }

  function row(k, v) {
    return '<div class="card-row"><span class="k">' + k + '</span>' +
      '<span class="v">' + v + '</span></div>';
  }

  /* the rank interval as a bar, 1 best on the left */
  function bandSvg(sc, n) {
    var w = 264, h = 30, x0 = 2, x1 = w - 2;
    function px(r) { return x0 + (r - 1) / (n - 1) * (x1 - x0); }
    return '<div class="card-band"><svg width="' + w + '" height="' + h + '">' +
      '<line x1="' + x0 + '" x2="' + x1 + '" y1="10" y2="10" style="stroke:var(--rule-2)" stroke-width="1"/>' +
      '<rect x="' + px(sc.p05).toFixed(1) + '" y="4" width="' +
        Math.max(2, px(sc.p95) - px(sc.p05)).toFixed(1) +
        '" height="12" style="fill:var(--accent)" fill-opacity="0.30"/>' +
      '<line x1="' + px(sc.med).toFixed(1) + '" x2="' + px(sc.med).toFixed(1) +
        '" y1="2" y2="18" style="stroke:var(--accent)" stroke-width="2"/>' +
      '<text x="' + x0 + '" y="29" class="tick-label">1 best</text>' +
      '<text x="' + x1 + '" y="29" class="tick-label" text-anchor="end">' + n + '</text>' +
      '</svg></div>';
  }

  /* ---------------- declared states under the chart ---------------- */

  var STATE_COPY = {
    plotted:      ['Plotted above', 'a published target and an EPA-measured trend'],
    promise_only: ['Target, no measurement', 'promised a cut, files no mandatory tonnage we can fit'],
    trend_only:   ['Measured, no target', 'we can see the emissions, there is no promise to check'],
    neither:      ['Neither', 'no target and no mandatory tonnage']
  };
  var STATE_ORDER = ['plotted', 'promise_only', 'trend_only', 'neither'];

  function renderStates(D, rows) {
    var counts = {};
    STATE_ORDER.forEach(function (s) { counts[s] = 0; });
    rows.forEach(function (c) { counts[c.state] = (counts[c.state] || 0) + 1; });
    var total = rows.length;

    var host = document.getElementById('saydo-states');
    host.innerHTML = STATE_ORDER.map(function (s) {
      var copy = STATE_COPY[s];
      return '<div class="state-cell ' + (s === 'plotted' ? 'is-plotted' : 'is-muted') + '">' +
        '<div class="state-n">' + fmt.int(counts[s]) + '</div>' +
        '<div class="state-k">' + copy[0] + '</div>' +
        '<div class="state-d">' + copy[1] + '</div></div>';
    }).join('');

    document.getElementById('saydo-states-n').innerHTML =
      '<b>n = ' + fmt.int(total) + '</b> listings, ' + fmt.int(D.say_do.meta.n_companies) + ' companies';

    document.getElementById('saydo-bar').innerHTML = STATE_ORDER.map(function (s) {
      return '<span style="width:' + (counts[s] / total * 100).toFixed(2) + '%;background:' +
        (s === 'plotted' ? 'var(--accent)' : 'var(--muted)') + '" title="' +
        STATE_COPY[s][0] + ': ' + counts[s] + '"></span>';
    }).join('');
  }

  /* The five caveats are the honesty and they stay verbatim. They sit one click
     down, behind a bar that says how many there are, so the chart and the four
     declared states get the screen. */
  function renderCaveats(D) {
    var host = document.getElementById('saydo-caveat-slot');
    if (!host) return;
    var cav = D.say_do.meta.caveats || [];
    host.innerHTML =
      F.detailsHTML('What this chart cannot tell you', String(cav.length),
        '<ul class="note-list" id="saydo-caveats">' +
        cav.map(function (c) { return '<li>' + c + '</li>'; }).join('') + '</ul>') +
      F.detailsHTML('How the trend is measured', '',
        '<p class="note">Each company\u2019s delivered rate is a straight line fitted to the ' +
        'Scope 1 tonnes it filed with the EPA, year by year. The promise is its own published ' +
        'target, put on the same annual basis. A fit flag means the record moves under the ' +
        'line: ' + Object.keys(FLAGS).map(function (k) { return FLAGS[k]; }).join(', ') + '.</p>' +
        '<div class="kv u-mt4">' +
        '<span class="kv-k">Cleanest subset, no fit flags</span><span class="kv-v">' +
        fmt.int(st().n_plotted_clean) + ' companies, ' + fmt.int(st().missing_clean) +
        ' of them missing their promise</span>' +
        '<span class="kv-k">Median gap in that subset</span><span class="kv-v">' +
        fmt.signed(st().median_gap_pct_yr_clean, 2) + ' %/yr</span></div>');
    function st() { return D.say_do.stats; }
  }

}());
