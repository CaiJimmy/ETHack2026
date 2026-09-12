/* GreenRank — runs on web/data/master.json (real data). No build step. */
const $ = s => document.querySelector(s);
const logoUrl = d => `https://www.google.com/s2/favicons?domain=${d}&sz=64`;
const fmt = (v, d = 1) => v == null ? "—" : (+v).toLocaleString("en-US", { maximumFractionDigits: d });
const pct = v => v == null ? "—" : (v >= 0 ? "+" : "") + fmt(v, 1) + "%";

/* ---------- Sources (shown on every tab) ---------- */
const SRC = {
  epa:  { name: "US EPA Greenhouse Gas Reporting Program (GHGRP), direct emissions 2019–2023, matched to parent companies by ownership share", url: "https://www.epa.gov/ghgreporting/data-sets" },
  sust: { name: "Sustainalytics ESG Risk Ratings for the S&P 500, 2024 copy on Kaggle", url: "https://www.kaggle.com/datasets/pritish509/s-and-p-500-esg-risk-ratings" },
  yf:   { name: "Yahoo Finance company snapshot (EBITDA, employees), 2025, bundled in the open-source climate-credit-risk-analyzer", url: "https://huggingface.co/spaces/SubramaniMokkala/climate-credit-risk-analyzer" },
  world: { name: "World Sustainability Dataset (World Bank WDI and Our World in Data, via Kaggle), latest year per metric, up to 2018", url: "https://www.kaggle.com/datasets/truecue/worldsustainabilitydataset" },
  osm:  { name: "OpenStreetMap Nominatim, used once to find the latitude and longitude of each head-office city; country borders from Natural Earth", url: "https://nominatim.openstreetmap.org" },
  corp: { name: "Global Corporate ESG and Financial Dataset (Kaggle, mrbossjaysrb): Altman Z, Piotroski F, decarbonisation targets, controversy flags", url: "https://www.kaggle.com/datasets/mrbossjaysrb/global-corporate-esg-and-financial-dataset" },
  list: { name: "S&P 500 member list with market value, price and revenue: market screener screenshot, September 2026 (OCR)", url: null },
};
const srcLi = keys => keys.map(k => `<li><b>${SRC[k].name}</b>${SRC[k].url ? ` — <a href="${SRC[k].url}" target="_blank">${SRC[k].url}</a>` : ""}</li>`).join("");

/* ---------- Metric definitions ----------
   key, pillar, label, unit, higherIsBetter, source, formatter */
const METRICS = [
  { key: "ghg_intensity_t_per_musd", pillar: "E", label: "CO2 per $1M revenue (US sites)", unit: "t", good: "low", src: "epa", f: v => fmt(v, 0) + " t" },
  { key: "ghgrp_trend_5y_pct", pillar: "E", label: "Change in US site emissions 2019→2023", unit: "%", good: "low", src: "epa", f: pct },
  { key: "esg_risk_env", pillar: "E", label: "Environment risk score", unit: "", good: "low", src: "sust", f: v => fmt(v, 1) },
  { key: "temp_goal_c", pillar: "E", label: "Implied temperature of the emission plan", unit: "°C", good: "low", src: "corp", f: v => fmt(v, 1) + " °C" },
  { key: "decarb_target_year", pillar: "E", label: "Decarbonisation target year", unit: "", good: "low", src: "corp", f: v => String(v) },
  { key: "esg_risk_social", pillar: "S", label: "Social risk score", unit: "", good: "low", src: "sust", f: v => fmt(v, 1) },
  { key: "controversy_score", pillar: "S", label: "Controversy level (0 none – 5 severe)", unit: "", good: "low", src: "sust", f: v => fmt(v, 0) },
  { key: "controversy_flags", pillar: "S", label: "Controversy flags (0–6 topics)", unit: "", good: "low", src: "corp", f: v => fmt(v, 0) + " of 6" },
  { key: "esg_risk_gov", pillar: "G", label: "Governance risk score", unit: "", good: "low", src: "sust", f: v => fmt(v, 1) },
  { key: "altman_z", pillar: "F", label: "Altman Z-score (bankruptcy risk)", unit: "", good: "high", src: "corp", f: v => fmt(v, 2) },
  { key: "piotroski_f", pillar: "F", label: "Piotroski F-score (financial strength)", unit: "", good: "high", src: "corp", f: v => fmt(v, 0) + " of 9" },
];
const PILLARS = { E: "Environment", S: "Social", G: "Governance", F: "Financial resilience" };
const XSRC = { market_cap_b: "list", revenue_b: "list", ebitda_b: "yf", employees: "sust", ghgrp_scope1_mt: "epa", ghg_intensity_t_per_musd: "epa" };

let DATA = [];       // scored universe: one row per company, has sector
let ALL = [];        // all 500

/* Sector-relative percentile ranks. null stays null. */
function computeRanks() {
  const bySector = {};
  DATA.forEach(c => (bySector[c.sector] ||= []).push(c));
  for (const peers of Object.values(bySector)) for (const m of METRICS) {
    const vals = peers.map(c => c[m.key]).filter(v => v != null).sort((a, b) => a - b);
    for (const c of peers) {
      c.rank ||= {};
      const v = c[m.key];
      if (v == null || vals.length < 3) { c.rank[m.key] = null; continue; }
      const below = vals.filter(x => x < v).length, eq = vals.filter(x => x === v).length;
      const p = 100 * (below + eq / 2) / vals.length;
      c.rank[m.key] = m.good === "high" ? p : 100 - p;
    }
  }
}
function score(c, w) {
  const out = { n: 0, of: METRICS.length };
  let num = 0, den = 0;
  for (const p of Object.keys(PILLARS)) {
    const rs = METRICS.filter(m => m.pillar === p).map(m => c.rank[m.key]).filter(r => r != null);
    out.n += rs.length;
    out[p] = rs.length ? rs.reduce((a, b) => a + b) / rs.length : null;
    if (out[p] != null) { num += out[p] * w[p]; den += w[p]; }
  }
  out.total = den ? num / den : null;
  return out;
}
const weights = () => ({ E: +$("#wE").value, S: +$("#wS").value, G: +$("#wG").value, F: +$("#wF").value });

/* ================= EXPLORE ================= */
let selected = null;
const view = () => document.querySelector('input[name="view"]:checked').value;
function drawScatter() { view() === "treemap" ? drawTreemap() : drawScatterChart(); }

/* Squarified treemap: sector -> company. Box size = market value / revenue / CO2. Colour = score. */
function squarify(items, x, y, w, h) {
  const out = [], total = items.reduce((a, i) => a + i.v, 0); if (!total) return out;
  let rest = [...items].sort((a, b) => b.v - a.v), area = w * h / total;
  while (rest.length) {
    const vert = w >= h, side = vert ? h : w; let row = [], best = Infinity;
    for (const it of rest) {
      const cand = [...row, it], sum = cand.reduce((a, i) => a + i.v * area, 0), thick = sum / side;
      const worst = Math.max(...cand.map(i => Math.max(thick / (i.v * area / thick), (i.v * area / thick) / thick)));
      if (worst > best) break; row = cand; best = worst;
    }
    const sum = row.reduce((a, i) => a + i.v * area, 0), thick = sum / side; let off = 0;
    for (const it of row) { const len = it.v * area / thick; out.push(vert ? { it, x, y: y + off, w: thick, h: len } : { it, x: x + off, y, w: len, h: thick }); off += len; }
    rest = rest.slice(row.length);
    if (vert) { x += thick; w -= thick; } else { y += thick; h -= thick; }
  }
  return out;
}
function drawTreemap() {
  const svg = $("#scatter"), W = svg.clientWidth, H = svg.clientHeight, key = $("#sizeKey").value, sector = $("#sectorFilter").value, w = weights();
  const rows = DATA.filter(c => (!sector || c.sector === sector) && c[key] > 0).map(c => ({ c, v: c[key], s: score(c, w).total }));
  const secs = {}; rows.forEach(r => (secs[r.c.sector] ||= []).push(r));
  const sizeLabel = $("#sizeKey").selectedOptions[0].text;
  $("#charthead").textContent = `Box size = ${sizeLabel.toLowerCase()}. Colour = sustainability score (red 0 → green 100, grey = no score). Click a box for details.`;
  let g = "";
  const PAD = 3, TOP = 16;
  for (const sec of squarify(Object.entries(secs).map(([n, rs]) => ({ n, rs, v: rs.reduce((a, r) => a + r.v, 0) })), 0, 0, W, H)) {
    g += `<rect x="${sec.x}" y="${sec.y}" width="${sec.w}" height="${sec.h}" fill="#0f1115" stroke="#2a2f3a"/>`;
    if (sec.w > 60 && sec.h > 20) g += `<text x="${sec.x + sec.w / 2}" y="${sec.y + 12}" text-anchor="middle" fill="#9aa3b8" font-size="11">${sec.it.n}</text>`;
    for (const b of squarify(sec.it.rs, sec.x + PAD, sec.y + TOP, Math.max(0, sec.w - 2 * PAD), Math.max(0, sec.h - TOP - PAD))) {
      const c = b.it.c, col = b.it.s == null ? "#3a3f4a" : `hsl(${b.it.s * 1.2},60%,${28 + b.it.s * .12}%)`;
      g += `<g class="logo tm" data-t="${c.ticker}"><title>${c.name}: ${sizeLabel} ${fmt(b.it.v, 1)} · score ${fmt(b.it.s, 0)}</title>
        <rect x="${b.x}" y="${b.y}" width="${Math.max(0, b.w - 1)}" height="${Math.max(0, b.h - 1)}" fill="${col}" stroke="${selected === c.ticker ? "#fff" : "#0f1115"}"/>`;
      if (b.w > 34 && b.h > 14) g += `<text x="${b.x + b.w / 2}" y="${b.y + b.h / 2 + 4}" font-size="${Math.min(14, b.w / 4)}">${c.ticker}</text>`;
      if (b.w > 54 && b.h > 30) g += `<text x="${b.x + b.w / 2}" y="${b.y + b.h / 2 + 15}" font-size="9" fill="#ccc">${fmt(b.it.s, 0)}</text>`;
      g += `</g>`;
    }
  }
  svg.innerHTML = g;
  svg.querySelectorAll(".logo").forEach(el => el.onclick = () => showCard(DATA.find(c => c.ticker === el.dataset.t)));
  const scored = DATA.filter(c => score(c, w).total != null).length;
  $("#coverage").textContent = `${rows.length} companies on the map. ${scored} of ${ALL.length} S&P 500 companies have a score.`;
}
function drawScatterChart() {
  $("#charthead").textContent = "Sustainability score (0 = worst in sector, 100 = best in sector). Click a logo to see the details.";
  const svg = $("#scatter"), W = svg.clientWidth, H = svg.clientHeight, P = { l: 50, r: 20, t: 16, b: 44 };
  const xKey = $("#xAxis").value, sector = $("#sectorFilter").value, log = $("#logX").checked, w = weights();
  const rows = DATA.filter(c => !sector || c.sector === sector)
    .map(c => ({ c, x: c[xKey], y: score(c, w).total })).filter(r => r.x != null && r.y != null && (!log || r.x > 0));
  const xs = rows.map(r => r.x), xmin = Math.min(...xs), xmax = Math.max(...xs);
  const tx = v => log ? Math.log10(v) : v;
  const sx = v => P.l + (tx(v) - tx(xmin)) / ((tx(xmax) - tx(xmin)) || 1) * (W - P.l - P.r);
  const sy = v => H - P.b - v / 100 * (H - P.t - P.b);
  let g = `<g class="axis">`;
  for (let y = 0; y <= 100; y += 20) g += `<line x1="${P.l}" x2="${W - P.r}" y1="${sy(y)}" y2="${sy(y)}"/><text x="${P.l - 8}" y="${sy(y) + 4}" text-anchor="end">${y}</text>`;
  const ticks = log ? [...new Set(xs.map(v => Math.pow(10, Math.floor(Math.log10(v)))))].sort((a, b) => a - b) : [0, .25, .5, .75, 1].map(f => xmin + f * (xmax - xmin));
  for (const t of ticks) g += `<line y1="${P.t}" y2="${H - P.b}" x1="${sx(t)}" x2="${sx(t)}"/><text x="${sx(t)}" y="${H - P.b + 16}" text-anchor="middle">${fmt(t, 2)}</text>`;
  g += `<text x="${W / 2}" y="${H - 6}" text-anchor="middle">${$("#xAxis").selectedOptions[0].text} — source: ${SRC[XSRC[xKey]].name.split(",")[0]}</text>`;
  g += `<text transform="translate(14,${H / 2}) rotate(-90)" text-anchor="middle">Sustainability score</text></g>`;
  const showLabels = rows.length <= 90, r = rows.length <= 90 ? 13 : 9;
  for (const row of rows) {
    const x = sx(row.x), y = sy(row.y);
    g += `<g class="logo${selected === row.c.ticker ? " sel" : ""}" data-t="${row.c.ticker}"><title>${row.c.name} — score ${fmt(row.y, 0)}</title>
      <circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="hsl(${row.y * 1.2},70%,45%)" stroke-width="3"/>
      <image href="${logoUrl(row.c.domain)}" x="${x - r * .65}" y="${y - r * .65}" width="${r * 1.3}" height="${r * 1.3}"/>
      ${showLabels ? `<text x="${x}" y="${y + r + 11}">${row.c.ticker}</text>` : ""}</g>`;
  }
  svg.innerHTML = g;
  svg.querySelectorAll(".logo").forEach(el => el.onclick = () => showCard(DATA.find(c => c.ticker === el.dataset.t)));
  const scored = DATA.filter(c => score(c, w).total != null).length;
  $("#coverage").textContent = `${rows.length} companies on the chart. ${scored} of ${ALL.length} S&P 500 companies have a score; ${ALL.length - scored} have no rating data and are not shown.`;
}
function showCard(c) {
  selected = c.ticker;
  const s = score(c, weights());
  const peers = DATA.filter(x => x.sector === c.sector).map(x => ({ t: x.ticker, s: score(x, weights()).total })).filter(p => p.s != null).sort((a, b) => b.s - a.s);
  const pos = peers.findIndex(p => p.t === c.ticker) + 1;
  let h = `<h2><img src="${logoUrl(c.domain)}" width="20" style="vertical-align:middle"> ${c.name}</h2>
    <div class="hint">${c.sector} · ${c.industry || ""}</div>
    <div class="big">${fmt(s.total, 0)}</div>
    <div class="hint">Rank ${pos} of ${peers.length} in ${c.sector}. Data for ${s.n} of ${s.of} metrics.</div>`;
  for (const p of Object.keys(PILLARS)) h += `<div>${PILLARS[p]} ${s[p] == null ? "<span class='hint'>no data</span>" : fmt(s[p], 0)}<div class="bar"><i style="width:${s[p] || 0}%"></i></div></div>`;
  h += `<table>`;
  for (const m of METRICS) {
    const v = c[m.key], r = c.rank[m.key];
    h += `<tr><td>${m.label}<span class="src">${SRC[m.src].name.split(",")[0]}</span></td><td class="${v == null ? "na" : ""}">${v == null ? "no data" : m.f(v)}</td><td>${r == null ? "" : "p" + fmt(r, 0)}</td></tr>`;
  }
  h += `<tr><td>Market value<span class="src">${SRC.list.name.split(":")[0]}</span></td><td>$${fmt(c.market_cap_b, 0)} bn</td><td></td></tr>
        <tr><td>Revenue<span class="src">${SRC.list.name.split(":")[0]}</span></td><td>$${fmt(c.revenue_b, 1)} bn</td><td></td></tr>
        <tr><td>Direct CO2, US sites 2023<span class="src">EPA GHGRP</span></td><td class="${c.ghgrp_scope1_mt == null ? "na" : ""}">${c.ghgrp_scope1_mt == null ? "no site above 25 kt" : fmt(c.ghgrp_scope1_mt, 2) + " Mt"}</td><td></td></tr>
        <tr><td>Employees<span class="src">Sustainalytics / Yahoo</span></td><td>${fmt(c.employees, 0)}</td><td></td></tr></table>
    <p class="hint">"p85" = better than 85% of the sector on that metric.</p>`;
  $("#card").innerHTML = h;
  $("#scatter").querySelectorAll(".logo").forEach(el => el.classList.toggle("sel", el.dataset.t === c.ticker));
}

/* ================= FUND ================= */
function drawFund() {
  const cp = +$("#cp").value, capPct = +$("#cap").value, k = +$("#tilt").value, FUND = 1e9;
  const totCap = ALL.reduce((a, c) => a + c.market_cap_b, 0);
  const rows = ALL.map(c => {
    const wIdx = c.market_cap_b / totCap;
    const ebitda = c.ebitda_b != null ? c.ebitda_b : c.revenue_b * 0.15;
    const tonnes = (c.ghgrp_scope1_mt || 0) * 1e6;
    const hit = Math.min(1, cp * tonnes / Math.max(0.05e9, ebitda * 1e9));
    const excluded = $("#needTarget").checked && c.decarb_target_year === null;
    return { c, wIdx, hit, w: excluded ? 0 : wIdx * Math.exp(-k * hit * 5), inten: c.ghg_intensity_t_per_musd || 0, excluded };
  });
  const norm = () => { const s = rows.reduce((a, r) => a + r.w, 0); rows.forEach(r => r.w /= s); };
  const intensity = key => rows.reduce((a, r) => a + r[key] * r.inten, 0);
  norm();
  const idxInt = intensity("wIdx"), target = idxInt * (1 - capPct / 100);
  const dropped = [];
  for (let i = 0; i < 400 && intensity("w") > target; i++) {
    const worst = rows.filter(r => r.w > 0).sort((a, b) => b.inten - a.inten)[0];
    worst.w *= 0.5; if (worst.w < 1e-5) { worst.w = 0; dropped.push(worst.c); }
    norm();
  }
  const activeShare = rows.reduce((a, r) => a + Math.abs(r.w - r.wIdx), 0) / 2, excl = rows.filter(r => r.excluded).length;
  const held = rows.filter(r => r.w > 0).length;
  const risk = key => rows.reduce((a, r) => a + r[key] * r.hit, 0) * 100;
  $("#fundStats").innerHTML = [
    [fmt(idxInt, 0) + " t", "CO2 per $1M revenue in the index"], [fmt(intensity("w"), 0) + " t", "CO2 per $1M revenue in your fund"],
    [fmt(risk("wIdx"), 1) + "%", "Profit at risk, index"], [fmt(risk("w"), 1) + "%", "Profit at risk, your fund"],
    [fmt(activeShare * 100, 0) + "%", "Active share: how different from the index"], [`${held} / ${rows.length}`, excl ? `Companies held (${excl} have no decarbonisation target)` : "Companies held"],
  ].map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  const sec = {};
  rows.forEach(r => { const s = r.c.sector || "Unknown sector"; sec[s] ||= { i: 0, f: 0 }; sec[s].i += r.wIdx; sec[s].f += r.w; });
  $("#sectorTilt").innerHTML = Object.entries(sec).sort((a, b) => (b[1].f - b[1].i) - (a[1].f - a[1].i)).map(([s, v]) => {
    const d = (v.f - v.i) * 100, cls = d >= 0 ? "pos" : "neg";
    return `<div class="tiltrow"><span>${s}</span><div class="track"><i class="${cls}" style="left:${50 + (d < 0 ? d * 3 : 0)}%;width:${Math.min(50, Math.abs(d) * 3)}%"></i></div><span>${d >= 0 ? "+" : ""}${fmt(d, 1)} pts</span></div>`;
  }).join("");
  const top = [...rows].sort((a, b) => b.w - a.w).slice(0, 15);
  $("#fundTable tbody").innerHTML = top.map(r =>
    `<tr><td><img src="${logoUrl(r.c.domain)}" width="14">${r.c.name}</td><td>${fmt(r.wIdx * 100, 2)}%</td><td>${fmt(r.w * 100, 2)}%</td><td>${r.c.ghgrp_scope1_mt == null ? "<span class='hint'>no site data</span>" : fmt(r.hit * 100, 0) + "%"}</td></tr>`).join("");
  const cut = rows.filter(r => r.wIdx > 0 && r.w / r.wIdx <= 0.1 && !r.excluded).sort((a, b) => b.wIdx - a.wIdx);
  $("#dropped").innerHTML = cut.length ? `<span class="hint">${cut.length} companies. The largest: </span>` + cut.slice(0, 12).map(r => `${r.c.name} <span class="hint">(${fmt(r.hit * 100, 0)}% of profit at risk)</span>`).join(" · ") : `<span class="hint">None at these settings.</span>`;
  const gained = [...rows].sort((a, b) => (b.w - b.wIdx) - (a.w - a.wIdx)).slice(0, 3), lost = [...rows].sort((a, b) => (a.w - a.wIdx) - (b.w - b.wIdx)).slice(0, 3);
  $("#dollars").innerHTML = `Of $1,000,000,000: the largest position is ${top[0].c.name} with $${fmt(top[0].w * FUND / 1e6, 0)} million. ` +
    `Compared with the index, the most money moved into ${gained.map(r => r.c.name).join(", ")} and out of ${lost.map(r => r.c.name).join(", ")}.`;
}

/* ================= QUIZ (fixed, well-known companies, surprising answers) =================
   Each question names two tickers. The value is read from the data at run time, so the
   answer always matches the dataset. If a value is missing the question is skipped. */
const Q = [
  { a: "NVDA", b: "SBUX", key: "employees", pick: "high", src: "sust", text: "Which company has more employees?", f: v => fmt(v, 0) + " employees",
    why: "Nvidia is worth about 40 times more than Starbucks on the stock market, but a chip designer needs far fewer people than a coffee chain." },
  { a: "AMZN", b: "WMT", key: "employees", pick: "high", src: "sust", text: "Which company has more employees?", f: v => fmt(v, 0) + " employees",
    why: "Walmart is still the largest private employer in the world." },
  { a: "XOM", b: "DUK", key: "ghgrp_scope1_mt", pick: "high", src: "epa", text: "Which company released more CO2 from its own US sites in 2023?", f: v => fmt(v, 1) + " million tonnes CO2e",
    why: "Power plants that burn coal and gas release more CO2 than refineries. Most of the CO2 from oil is released later, when customers burn the fuel. That part is not counted here." },
  { a: "BRK.B", b: "CVX", key: "ghgrp_scope1_mt", pick: "high", src: "epa", text: "Which company released more CO2 from its own US sites in 2023?", f: v => fmt(v, 1) + " million tonnes CO2e",
    why: "Berkshire Hathaway is not only an investment company. It owns power utilities, gas pipelines and a railroad, and they all report to the EPA." },
  { a: "GOOGL", b: "PEP", key: "ghgrp_scope1_mt", pick: "high", src: "epa", text: "Which company released more CO2 from its own US sites in 2023?", f: v => fmt(v, 2) + " million tonnes CO2e",
    why: "Data centres use a lot of electricity, but that CO2 is released at the power plant, not at Google's site. PepsiCo runs bottling plants and snack factories that burn gas on site." },
  { a: "TSLA", b: "F", key: "ghgrp_trend_5y_pct", pick: "high", src: "epa", text: "Which company's US site emissions went UP between 2019 and 2023?", f: v => pct(v) + " since 2019",
    why: "Tesla built new factories in Texas and Nevada. Ford closed and cleaned up old ones. Making electric cars still needs energy." },
  { a: "META", b: "MCD", key: "esg_risk_total", pick: "high", src: "sust", text: "Which company has the higher ESG risk score? (higher = more risk that is not managed)", f: v => fmt(v, 1) + " risk points",
    why: "Meta's risk is social, not environmental: data privacy, content moderation and legal cases. McDonald's has a lower total score even with its supply chain." },
  { a: "MMM", b: "CVX", key: "controversy_score", pick: "high", src: "sust", text: "Which company has the higher controversy level? (0 = none, 5 = severe)", f: v => "level " + fmt(v, 0),
    why: "3M makes 'forever chemicals' (PFAS) and faces one of the largest legal settlements in US history. Sustainalytics rates that as the most severe level." },
  { a: "NEE", b: "CVX", key: "ghg_intensity_t_per_musd", pick: "high", src: "epa", text: "Which company releases more CO2 for each dollar of revenue from its US sites?", f: v => fmt(v, 0) + " tonnes per $1M revenue",
    why: "NextEra is the world's largest producer of wind and solar power, but it also owns gas plants in Florida. Per dollar of sales, a power company releases far more CO2 than an oil company." },
  { a: "CVS", b: "NVDA", key: "revenue_b", pick: "high", src: "list", text: "Which company has more revenue (sales in one year)?", f: v => "$" + fmt(v, 0) + " billion",
    why: "Nvidia is worth about 50 times more than CVS on the stock market. But CVS sells more: pharmacies, health insurance and drug distribution have huge sales with thin profit." },
];
let order = [], qi = 0, qScore = 0, q = null;
const byT = t => ALL.find(c => c.ticker === t);
function newRound() {
  order = Q.filter(t => byT(t.a) && byT(t.b) && byT(t.a)[t.key] != null && byT(t.b)[t.key] != null).sort(() => Math.random() - .5);
  qi = 0; qScore = 0; askQuestion();
}
function askQuestion() {
  if (qi >= order.length) {
    $("#qText").textContent = ""; $(".choices").classList.add("hidden");
    $("#reveal").classList.add("hidden"); $("#next").classList.add("hidden"); $("#finish").classList.remove("hidden");
    $("#qProgress").textContent = "Round finished";
    $("#finalText").textContent = `You got ${qScore} of ${order.length} right.`;
    return;
  }
  const t = order[qi]; q = { t, pair: Math.random() < .5 ? [byT(t.a), byT(t.b)] : [byT(t.b), byT(t.a)] };
  $("#finish").classList.add("hidden"); $(".choices").classList.remove("hidden");
  $("#qProgress").textContent = `Question ${qi + 1} of ${order.length} · score ${qScore}`;
  $("#qText").textContent = t.text;
  q.pair.forEach((c, i) => { const el = $("#c" + i); el.className = "choice"; el.disabled = false; el.innerHTML = `<img src="${logoUrl(c.domain)}">${c.name}<small>${c.sector || ""}</small>`; });
  $("#reveal").classList.add("hidden"); $("#next").classList.add("hidden");
}
function answer(i) {
  const { t, pair: [a, b] } = q, va = a[t.key], vb = b[t.key];
  const better = (t.pick === "high" ? va > vb : va < vb) ? 0 : 1, ok = i === better;
  $("#c" + i).classList.add(ok ? "right" : "wrong"); $("#c" + better).classList.add("right");
  [0, 1].forEach(j => $("#c" + j).disabled = true);
  if (ok) qScore++;
  $("#reveal").innerHTML = `<b>${ok ? "Correct." : "Not this one."}</b> ${a.name}: <b>${t.f(va)}</b>. ${b.name}: <b>${t.f(vb)}</b>.<span class="why">${t.why}</span><span class="src">Source: ${SRC[t.src].name}</span>`;
  $("#reveal").classList.remove("hidden"); $("#next").classList.remove("hidden");
  $("#qProgress").textContent = `Question ${qi + 1} of ${order.length} · score ${qScore}`;
}

/* ================= GLOBE ================= */
let G = null, COUNTRIES = null, GEO = null, HQ = null;
const ISO_ALIAS = { "United States": "USA", "Ireland": "IRL", "Switzerland": "CHE", "United Kingdom": "GBR", "Netherlands": "NLD", "Canada": "CAN", "Singapore": "SGP", "Bermuda": "BMU", "Jersey": "JEY", "Israel": "ISR", "Panama": "PAN", "Luxembourg": "LUX" };
const isoOf = f => f.properties.ISO_A3 !== "-99" ? f.properties.ISO_A3 : f.properties.ADM0_A3;
const METRIC_FMT = { co2_per_capita_t: v => fmt(v, 1) + " t per person", co2_mt: v => fmt(v, 0) + " Mt", renew_elec_pct: v => fmt(v, 0) + "%", elec_access_pct: v => fmt(v, 0) + "%", gdp_pc: v => "$" + fmt(v, 0), life_exp: v => fmt(v, 1) + " years" };
function colorScale(key) {
  const vals = Object.values(COUNTRIES).map(c => c[key]).filter(v => v != null).sort((a, b) => a - b);
  const lo = vals[Math.floor(vals.length * .05)], hi = vals[Math.floor(vals.length * .95)];
  const log = key === "co2_mt" || key === "gdp_pc" || key === "co2_per_capita_t";
  const t = v => { const f = log ? (Math.log10(Math.max(v, .01)) - Math.log10(Math.max(lo, .01))) / (Math.log10(hi) - Math.log10(Math.max(lo, .01))) : (v - lo) / (hi - lo); return Math.min(1, Math.max(0, f)); };
  const good = key === "renew_elec_pct" || key === "elec_access_pct" || key === "gdp_pc" || key === "life_exp";
  return { lo, hi, color: v => { if (v == null) return "rgba(60,60,70,.6)"; const x = good ? 1 - t(v) : t(v); return `hsl(${120 - 120 * x},70%,${35 + 15 * x}%)`; } };
}
async function initGlobe() {
  if (G) { G.width($("#globeDiv").clientWidth).height($("#globeDiv").clientHeight); return; }
  [COUNTRIES, GEO, HQ] = await Promise.all([fetch("data/countries.json").then(r => r.json()).then(j => j.countries), fetch("data/countries.geojson").then(r => r.json()), fetch("data/hq.json").then(r => r.json()).catch(() => ({}))]);
  ALL.forEach(c => { c.hq = HQ[c.ticker] || null; });
  const withHq = ALL.filter(c => c.hq).length;
  $("#globeNote").textContent = `${withHq} of ${ALL.length} companies have a known head-office location.`;
  G = Globe()($("#globeDiv"))
    .width($("#globeDiv").clientWidth).height($("#globeDiv").clientHeight)
    .globeImageUrl("lib/earth-dark.jpg").backgroundImageUrl("lib/night-sky.png")
    .polygonsData(GEO.features.filter(f => f.properties.ISO_A2 !== "AQ"))
    .polygonAltitude(0.006).polygonSideColor(() => "rgba(0,0,0,0.15)").polygonStrokeColor(() => "#111")
    .polygonLabel(f => { const c = COUNTRIES[isoOf(f)], k = $("#globeMetric").value; return `<div style="background:#181b22;padding:6px 8px;border-radius:6px;font-size:12px"><b>${f.properties.ADMIN}</b><br>${c && c[k] != null ? METRIC_FMT[k](c[k]) + " (" + (c[k + "_yr"] || c.co2_mt_yr) + ")" : "no data"}</div>`; })
    .onPolygonClick(f => showCountry(f))
    .htmlElement(c => { const el = document.createElement("img"); el.src = logoUrl(c.domain); el.className = "glogo"; el.title = `${c.name} — ${c.hq.city.split(",")[0]}`; el.onclick = () => { openExplore(c); }; return el; })
    .htmlLat(c => c.hq.lat).htmlLng(c => c.hq.lon).htmlAltitude(0.01);
  G.pointOfView({ lat: 35, lng: -60, altitude: 1.9 });
  G.controls().autoRotate = true; G.controls().autoRotateSpeed = 0.4;
  $("#globeDiv").addEventListener("pointerdown", () => G.controls().autoRotate = false);
  paintGlobe(); placeLogos();
}
function paintGlobe() {
  const k = $("#globeMetric").value, sc = colorScale(k);
  G.polygonCapColor(f => sc.color(COUNTRIES[isoOf(f)]?.[k]));
  $("#globeLegend").innerHTML = `<span>${METRIC_FMT[k](sc.lo)}</span><i></i><span>${METRIC_FMT[k](sc.hi)}</span>`;
}
function placeLogos() {
  const n = +$("#topN").value; $("#topNv").textContent = n;
  G.htmlElementsData(ALL.filter(c => c.hq).sort((a, b) => b.market_cap_b - a.market_cap_b).slice(0, n));
}
function showCountry(f) {
  const iso = isoOf(f), c = COUNTRIES[iso] || {}, name = f.properties.ADMIN;
  const here = ALL.filter(x => x.hq && (ISO_ALIAS[x.hq.country] || "") === iso).sort((a, b) => b.market_cap_b - a.market_cap_b);
  const row = (l, k, f2) => `<tr><td>${l}</td><td class="${c[k] == null ? "na" : ""}">${c[k] == null ? "no data" : f2(c[k]) + ` <span class="src">${c[k + "_yr"] || c.co2_mt_yr}</span>`}</td></tr>`;
  let h = `<h2>${name}</h2><div class="hint">${c.continent || f.properties.CONTINENT} · ${c.income || ""}</div><table>` +
    row("CO2 per person", "co2_per_capita_t", METRIC_FMT.co2_per_capita_t) + row("CO2 total", "co2_mt", METRIC_FMT.co2_mt) +
    row("Renewable electricity", "renew_elec_pct", METRIC_FMT.renew_elec_pct) + row("Access to electricity", "elec_access_pct", METRIC_FMT.elec_access_pct) +
    row("GDP per person", "gdp_pc", METRIC_FMT.gdp_pc) + row("Life expectancy", "life_exp", METRIC_FMT.life_exp) + row("Population", "pop", v => fmt(v / 1e6, 1) + " million") + `</table>`;
  h += `<h3>S&P 500 head offices here: ${here.length}</h3>`;
  if (here.length) {
    const mc = here.reduce((a, x) => a + x.market_cap_b, 0), em = here.reduce((a, x) => a + (x.ghgrp_scope1_mt || 0), 0);
    h += `<p class="hint">Together worth $${fmt(mc / 1000, 1)} trillion. Their reported US site emissions: ${fmt(em, 0)} Mt.</p><ul class="clist">` +
      here.slice(0, 40).map(x => `<li data-t="${x.ticker}"><img src="${logoUrl(x.domain)}">${x.name}<span class="hint" style="margin-left:auto">${x.hq.city.split(",")[0]}</span></li>`).join("") + (here.length > 40 ? `<li class="hint">… and ${here.length - 40} more</li>` : "") + "</ul>";
  } else h += `<p class="hint">No S&P 500 company has its head office here. Many still sell, make, or emit here; that is not in this dataset.</p>`;
  h += `<p class="hint">Source: ${SRC.world.name}</p>`;
  $("#countryCard").innerHTML = h;
  $("#countryCard").querySelectorAll("li[data-t]").forEach(li => li.onclick = () => openExplore(byT(li.dataset.t)));
  const [lng, lat] = centroid(f);
  G.pointOfView({ lat, lng, altitude: 1.6 }, 800);
}
function centroid(f) {           // vertex average of the largest ring; good enough to aim the camera
  const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
  const ring = polys.map(p => p[0]).sort((a, b) => b.length - a.length)[0];
  const n = ring.length; return [ring.reduce((a, p) => a + p[0], 0) / n, ring.reduce((a, p) => a + p[1], 0) / n];
}
function openExplore(c) {
  document.querySelector('nav button[data-tab="explore"]').click();
  if (DATA.includes(c)) { $("#sectorFilter").value = ""; drawScatter(); showCard(c); }
}
$("#globeMetric").onchange = () => G && paintGlobe();
$("#topN").oninput = () => G && placeLogos();

/* ================= METHODS tables ================= */
function fillMethods() {
  const cnt = k => ALL.filter(c => c[k] != null).length;
  $("#metricTable tbody").innerHTML = METRICS.map(m => `<tr><td>${PILLARS[m.pillar]}</td><td>${m.label}</td><td>${m.good}</td><td>${SRC[m.src].name}</td><td>${cnt(m.key)} / ${ALL.length}</td></tr>`).join("") +
    `<tr><td>Financial</td><td>Market value, revenue</td><td>—</td><td>${SRC.list.name}</td><td>${cnt("market_cap_b")} / ${ALL.length}</td></tr>
     <tr><td>Financial</td><td>EBITDA</td><td>—</td><td>${SRC.yf.name}</td><td>${cnt("ebitda_b")} / ${ALL.length}</td></tr>
     <tr><td>Financial</td><td>Direct CO2 from US sites (tonnes), used by the fund</td><td>low</td><td>${SRC.epa.name}</td><td>${cnt("ghgrp_scope1_mt")} / ${ALL.length}</td></tr>`;
  $("#allSources").innerHTML = srcLi(Object.keys(SRC));
  $("#exploreSources").innerHTML = srcLi(["epa", "sust", "corp", "list", "yf"]);
  $("#fundSources").innerHTML = srcLi(["list", "epa", "yf", "corp"]);
  $("#quizSources").innerHTML = srcLi(["epa", "sust", "list"]);
  $("#qList").innerHTML = Q.map(t => `<li>${t.text.replace(/\(.*\)/, "")} <b>${byT(t.a)?.name || t.a}</b> or <b>${byT(t.b)?.name || t.b}</b></li>`).join("");
  $("#globeSources").innerHTML = srcLi(["world", "osm", "yf", "sust", "list", "epa"]);
}

/* ================= WIRING ================= */
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button,.tab").forEach(e => e.classList.remove("active"));
  b.classList.add("active"); $("#" + b.dataset.tab).classList.add("active");
  if (b.dataset.tab === "explore") drawScatter();
  if (b.dataset.tab === "fund") drawFund();
  if (b.dataset.tab === "quiz" && !q) newRound();
  if (b.dataset.tab === "globe") initGlobe();
});
["wE", "wS", "wG", "wF"].forEach(id => $("#" + id).oninput = e => { $("#" + id + "v").textContent = e.target.value; drawScatter(); if (selected) showCard(DATA.find(c => c.ticker === selected)); });
["xAxis", "sectorFilter", "logX"].forEach(id => $("#" + id).onchange = drawScatter);
$("#search").onchange = e => { const v = e.target.value.toUpperCase(); const c = DATA.find(c => c.ticker === v || c.name.toUpperCase() === v || v.startsWith(c.ticker + " ")); if (c) { $("#sectorFilter").value = ""; drawScatter(); showCard(c); } };
[["cp", "cpv"], ["cap", "capv"], ["tilt", "tiltv"]].forEach(([a, b]) => $("#" + a).oninput = e => { $("#" + b).textContent = e.target.value; drawFund(); });
$("#needTarget").onchange = drawFund;
document.querySelectorAll('input[name="view"]').forEach(r => r.onchange = () => { $("#sizeWrap").classList.toggle("hidden", view() !== "treemap"); drawScatter(); });
$("#sizeKey").onchange = drawScatter;
$("#c0").onclick = () => answer(0); $("#c1").onclick = () => answer(1);
$("#next").onclick = () => { qi++; askQuestion(); };
$("#restart").onclick = newRound;
window.onresize = () => $("#explore").classList.contains("active") && drawScatter();

fetch("data/master.json").then(r => r.json()).then(j => {
  ALL = j.companies.filter(c => !c.dual_class_duplicate && c.market_cap_b);
  ALL.forEach(c => c.domain = c.logo_domain || DOMAINS[c.ticker] || (c.name.toLowerCase().replace(/^the /, "").replace(/[,.]?\s*(inc|corp|corporation|company|co|plc|ltd|group|holdings|incorporated|limited)\b.*$/, "").replace(/[^a-z0-9]/g, "") + ".com"));
  DATA = ALL.filter(c => c.sector);
  computeRanks();
  [...new Set(DATA.map(c => c.sector))].sort().forEach(s => $("#sectorFilter").insertAdjacentHTML("beforeend", `<option>${s}</option>`));
  $("#tickers").innerHTML = DATA.map(c => `<option value="${c.ticker} — ${c.name}">`).join("");
  $("#dataBadge").textContent = `${ALL.length} companies · EPA 2023 · Sustainalytics 2024 · prices Sep 2026`;
  fillMethods(); drawScatter();
});

/* Logo domains for names that do not map cleanly to a .com */
const DOMAINS = { AAPL: "apple.com", GOOGL: "google.com", META: "meta.com", "BRK.B": "berkshirehathaway.com", XOM: "exxonmobil.com", JPM: "jpmorganchase.com",
  UNH: "unitedhealthgroup.com", PG: "pg.com", KO: "coca-colacompany.com", HD: "homedepot.com", BAC: "bankofamerica.com", GS: "goldmansachs.com",
  T: "att.com", VZ: "verizon.com", DIS: "disney.com", UNP: "up.com", MMM: "3m.com", CAT: "caterpillar.com", DE: "deere.com", GE: "geaerospace.com",
  GEV: "gevernova.com", NEE: "nexteraenergy.com", DUK: "duke-energy.com", SO: "southerncompany.com", AEP: "aep.com", EXC: "exeloncorp.com",
  XEL: "xcelenergy.com", D: "dominionenergy.com", PSX: "phillips66.com", MPC: "marathonpetroleum.com", VLO: "valero.com", COP: "conocophillips.com",
  EOG: "eogresources.com", OXY: "oxy.com", SLB: "slb.com", LIN: "linde.com", FCX: "fcx.com", NEM: "newmont.com", DOW: "dow.com", NUE: "nucor.com",
  WM: "wm.com", RSG: "republicservices.com", BA: "boeing.com", LMT: "lockheedmartin.com", RTX: "rtx.com", NOC: "northropgrumman.com",
  MSFT: "microsoft.com", NVDA: "nvidia.com", AMZN: "amazon.com", TSLA: "tesla.com", INTC: "intel.com", CSCO: "cisco.com", ORCL: "oracle.com",
  IBM: "ibm.com", CRM: "salesforce.com", ADBE: "adobe.com", NFLX: "netflix.com", PEP: "pepsico.com", WMT: "walmart.com", COST: "costco.com",
  MCD: "mcdonalds.com", SBUX: "starbucks.com", NKE: "nike.com", LOW: "lowes.com", TGT: "target.com", F: "ford.com", GM: "gm.com",
  JNJ: "jnj.com", PFE: "pfizer.com", MRK: "merck.com", LLY: "lilly.com", ABBV: "abbvie.com", ABT: "abbott.com", TMO: "thermofisher.com",
  V: "visa.com", MA: "mastercard.com", AXP: "americanexpress.com", WFC: "wellsfargo.com", C: "citi.com", MS: "morganstanley.com", BLK: "blackrock.com",
  SPGI: "spglobal.com", CME: "cmegroup.com", ICE: "ice.com", PLD: "prologis.com", AMT: "americantower.com", EQIX: "equinix.com", SPG: "simon.com",
  O: "realtyincome.com", WELL: "welltower.com", VST: "vistra.com", CEG: "constellationenergy.com", ETR: "entergy.com", PPL: "pplweb.com",
  DTE: "dteenergy.com", AEE: "ameren.com", CMS: "cmsenergy.com", FE: "firstenergycorp.com", PCG: "pge.com", EIX: "edison.com", SRE: "sempra.com",
  PNW: "pinnaclewest.com", LNT: "alliantenergy.com", NI: "nisource.com", ATO: "atmosenergy.com", TRGP: "targaresources.com", OKE: "oneok.com",
  KMI: "kindermorgan.com", WMB: "williams.com", LYB: "lyondellbasell.com", IP: "internationalpaper.com", PKG: "packagingcorp.com", CVX: "chevron.com",
  HON: "honeywell.com", EMR: "emerson.com", ETN: "eaton.com", ITW: "itw.com", PH: "parker.com", CMI: "cummins.com", PCAR: "paccar.com",
  UPS: "ups.com", FDX: "fedex.com", DAL: "delta.com", UAL: "united.com", LUV: "southwest.com", CSX: "csx.com", NSC: "nscorp.com",
  ADM: "adm.com", TSN: "tysonfoods.com", GIS: "generalmills.com", KHC: "kraftheinzcompany.com", MDLZ: "mondelezinternational.com", CL: "colgatepalmolive.com",
  KMB: "kimberly-clark.com", MO: "altria.com", PM: "pmi.com", CVS: "cvshealth.com", CI: "cigna.com", ELV: "elevancehealth.com", HUM: "humana.com",
  MCK: "mckesson.com", COR: "cencora.com", CAH: "cardinalhealth.com", HCA: "hcahealthcare.com", AMGN: "amgen.com", GILD: "gilead.com",
  BMY: "bms.com", MDT: "medtronic.com", SYK: "stryker.com", BSX: "bostonscientific.com", ISRG: "intuitive.com", DHR: "danaher.com",
  AVGO: "broadcom.com", AMD: "amd.com", QCOM: "qualcomm.com", TXN: "ti.com", MU: "micron.com", AMAT: "appliedmaterials.com", LRCX: "lrcx.com",
  KLAC: "kla.com", ADI: "analog.com", NOW: "servicenow.com", INTU: "intuit.com", PANW: "paloaltonetworks.com", CRWD: "crowdstrike.com",
  ACN: "accenture.com", DELL: "dell.com", HPQ: "hp.com", HPE: "hpe.com", CMCSA: "corporate.comcast.com", CHTR: "charter.com", TMUS: "t-mobile.com",
  BKNG: "booking.com", ABNB: "airbnb.com", UBER: "uber.com", MAR: "marriott.com", HLT: "hilton.com", RCL: "royalcaribbean.com", CCL: "carnival.com",
  DHI: "drhorton.com", LEN: "lennar.com", PHM: "pultegroup.com", NVR: "nvrinc.com", TJX: "tjx.com", ROST: "rossstores.com", ORLY: "oreillyauto.com",
  AZO: "autozone.com", CMG: "chipotle.com", YUM: "yum.com", EL: "elcompanies.com", KR: "kroger.com", SYY: "sysco.com", DG: "dollargeneral.com",
  DLTR: "dollartree.com", BRO: "bbinsurance.com", ALL: "allstate.com", PGR: "progressive.com", TRV: "travelers.com", CB: "chubb.com", AIG: "aig.com",
  MET: "metlife.com", PRU: "prudential.com", AFL: "aflac.com", USB: "usbank.com", PNC: "pnc.com", TFC: "truist.com", COF: "capitalone.com",
  SCHW: "schwab.com", BX: "blackstone.com", KKR: "kkr.com", APO: "apollo.com", BK: "bny.com", BNY: "bny.com", STT: "statestreet.com",
  MCO: "moodys.com", MSCI: "msci.com", NDAQ: "nasdaq.com", CBOE: "cboe.com", PYPL: "paypal.com", XYZ: "block.xyz", COIN: "coinbase.com",
  HOOD: "robinhood.com", PLTR: "palantir.com", APP: "applovin.com", ANET: "arista.com", SNPS: "synopsys.com", CDNS: "cadence.com", WDAY: "workday.com",
  ADSK: "autodesk.com", FTNT: "fortinet.com", DDOG: "datadoghq.com", TTD: "thetradedesk.com", RDDT: "reddit.com", EA: "ea.com", TTWO: "take2games.com",
  WBD: "wbd.com", FOXA: "foxcorporation.com", FOX: "foxcorporation.com", NWSA: "newscorp.com", NWS: "newscorp.com", OMC: "omnicomgroup.com",
  LYV: "livenationentertainment.com", TKO: "tkogrp.com", AWK: "amwater.com", AES: "aes.com", NRG: "nrg.com", EQT: "eqt.com", DVN: "devonenergy.com",
  FANG: "diamondbackenergy.com", APA: "apacorp.com", HAL: "halliburton.com", BKR: "bakerhughes.com", EXE: "expandenergy.com", TPL: "texaspacific.com",
  CTVA: "corteva.com", CF: "cfindustries.com", MOS: "mosaicco.com", ALB: "albemarle.com", ECL: "ecolab.com", SHW: "sherwin-williams.com",
  PPG: "ppg.com", APD: "airproducts.com", DD: "dupont.com", IFF: "iff.com", MLM: "martinmarietta.com", VMC: "vulcanmaterials.com",
  STLD: "steeldynamics.com", CRH: "crh.com", BALL: "ball.com", AMCR: "amcor.com", SW: "smurfitwestrock.com", AVY: "averydennison.com",
  WY: "weyerhaeuser.com", BRK: "berkshirehathaway.com", "BF.B": "brown-forman.com", TAP: "molsoncoors.com", STZ: "cbrands.com", MNST: "monsterbevcorp.com",
  KDP: "keurigdrpepper.com", HSY: "thehersheycompany.com", SJM: "jmsmucker.com", MKC: "mccormick.com", HRL: "hormelfoods.com", CLX: "thecloroxcompany.com",
  CHD: "churchdwight.com", KVUE: "kenvue.com", CPB: "thecampbellscompany.com", CAG: "conagrabrands.com", K: "kellanova.com", BG: "bunge.com",
  GWW: "grainger.com", FAST: "fastenal.com", URI: "unitedrentals.com", CTAS: "cintas.com", PWR: "quantaservices.com", EME: "emcorgroup.com",
  JCI: "johnsoncontrols.com", TT: "tranetechnologies.com", CARR: "carrier.com", OTIS: "otis.com", LII: "lennox.com", AOS: "aosmith.com",
  GD: "gd.com", LHX: "l3harris.com", HII: "hii.com", TDG: "transdigm.com", HWM: "howmet.com", TXT: "textron.com", LDOS: "leidos.com",
  WAB: "wabteccorp.com", ODFL: "odfl.com", JBHT: "jbhunt.com", CHRW: "chrobinson.com", EXPD: "expeditors.com", ROK: "rockwellautomation.com",
  AME: "ametek.com", DOV: "dovercorporation.com", IR: "irco.com", XYL: "xylem.com", PNR: "pentair.com", SWK: "stanleyblackanddecker.com", MAS: "masco.com",
  SNA: "snapon.com", IEX: "idexcorp.com", NDSN: "nordson.com", GNRC: "generac.com", ROL: "rollins.com", J: "jacobs.com", FTV: "fortive.com",
  VLTO: "veralto.com", TDY: "teledyne.com", KEYS: "keysight.com", TRMB: "trimble.com", ZBRA: "zebra.com", GLW: "corning.com", APH: "amphenol.com",
  TEL: "te.com", JBL: "jabil.com", FLEX: "flex.com", STX: "seagate.com", WDC: "westerndigital.com", NTAP: "netapp.com", SMCI: "supermicro.com",
  MRVL: "marvell.com", MCHP: "microchip.com", ON: "onsemi.com", NXPI: "nxp.com", NXP: "nxp.com", SWKS: "skyworksinc.com", MPWR: "monolithicpower.com",
  TER: "teradyne.com", FSLR: "firstsolar.com", ENPH: "enphase.com", VRT: "vertiv.com", HUBB: "hubbell.com", CSGP: "costargroup.com",
  CBRE: "cbre.com", DLR: "digitalrealty.com", CCI: "crowncastle.com", SBAC: "sbasite.com", PSA: "publicstorage.com", EXR: "extraspace.com",
  VTR: "ventasreit.com", ARE: "are.com", AVB: "avalonbay.com", EQR: "equityapartments.com", ESS: "essexapartmenthomes.com", MAA: "maac.com",
  UDR: "udr.com", CPT: "camdenliving.com", INVH: "invh.com", KIM: "kimcorealty.com", REG: "regencycenters.com", FRT: "federalrealty.com",
  HST: "hosthotels.com", VICI: "viciproperties.com", IRM: "ironmountain.com", DOC: "healthpeak.com", BXP: "bxp.com", WSM: "williams-sonoma.com",
  ULTA: "ulta.com", BBY: "bestbuy.com", TSCO: "tractorsupply.com", GPC: "genpt.com", LULU: "lululemon.com", RL: "ralphlauren.com", TPR: "tapestry.com",
  DECK: "deckers.com", HAS: "hasbro.com", DPZ: "dominos.com", DRI: "darden.com", MGM: "mgmresorts.com", LVS: "sands.com", WYNN: "wynnresorts.com",
  NCLH: "nclhltd.com", EXPE: "expediagroup.com", CVNA: "carvana.com", EBAY: "ebay.com", DASH: "doordash.com", GRMN: "garmin.com", APTV: "aptiv.com",
  BLDR: "bldr.com", CPRT: "copart.com", ROP: "ropertech.com", CDW: "cdw.com", IT: "gartner.com", CTSH: "cognizant.com", ACGL: "archgroup.com",
  WTW: "wtwco.com", AON: "aon.com", MMC: "marsh.com", AJG: "ajg.com", CINF: "cinfin.com", WRB: "berkley.com", HIG: "thehartford.com", L: "loews.com",
  GL: "globelifeinsurance.com", AIZ: "assurant.com", EG: "everestglobal.com", ERIE: "erieinsurance.com", PFG: "principal.com", AMP: "ameriprise.com",
  RJF: "raymondjames.com", IBKR: "interactivebrokers.com", TROW: "troweprice.com", BEN: "franklintempleton.com", IVZ: "invesco.com", NTRS: "northerntrust.com",
  FITB: "53.com", HBAN: "huntington.com", RF: "regions.com", CFG: "citizensbank.com", KEY: "key.com", MTB: "mtb.com", SYF: "synchrony.com",
  FIS: "fisglobal.com", FISV: "fiserv.com", GPN: "globalpayments.com", CPAY: "corpay.com", JKHY: "jackhenry.com", BR: "broadridge.com", PAYX: "paychex.com",
  ADP: "adp.com", VRSK: "verisk.com", EFX: "equifax.com", FICO: "fico.com", FDS: "factset.com", TYL: "tylertech.com", PTC: "ptc.com", GEN: "gendigital.com",
  FFIV: "f5.com", AKAM: "akamai.com", VRSN: "verisign.com", GDDY: "godaddy.com", CIEN: "ciena.com", COHR: "coherent.com", LITE: "lumentum.com",
  MSI: "motorolasolutions.com", AXON: "axon.com", VEEV: "veeva.com", IQV: "iqvia.com", A: "agilent.com", WAT: "waters.com", MTD: "mt.com",
  IDXX: "idexx.com", RMD: "resmed.com", DXCM: "dexcom.com", PODD: "insulet.com", ALGN: "aligntech.com", EW: "edwards.com", ZBH: "zimmerbiomet.com",
  BDX: "bd.com", BAX: "baxter.com", STE: "steris.com", COO: "coopercos.com", HOLX: "hologic.com", TECH: "bio-techne.com", CRL: "criver.com",
  WST: "westpharma.com", RVTY: "revvity.com", SOLV: "solventum.com", GEHC: "gehealthcare.com", LH: "labcorp.com", DGX: "questdiagnostics.com",
  DVA: "davita.com", UHS: "uhs.com", CNC: "centene.com", MRNA: "modernatx.com", REGN: "regeneron.com", VRTX: "vrtx.com", BIIB: "biogen.com",
  INCY: "incyte.com", ZTS: "zoetis.com", VTRS: "viatris.com", HSIC: "henryschein.com", ES: "eversource.com", ED: "conedison.com", PEG: "pseg.com",
  WEC: "wecenergygroup.com", EVRG: "evergy.com", CNP: "centerpointenergy.com", NCL: "nclhltd.com" };
