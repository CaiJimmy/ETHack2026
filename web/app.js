/* GreenRank — vanilla JS, no build step. Sections: data+scoring, explore, fund, quiz. */
const $ = s => document.querySelector(s);
const logoUrl = d => `https://www.google.com/s2/favicons?domain=${d}&sz=64`;
const fmt = (v, d = 1) => v == null ? "—" : (+v).toLocaleString(undefined, { maximumFractionDigits: d });

/* ---------- Metric definitions: [group, key, label, unit, higherIsBetter] ---------- */
const METRICS = [
  ["env", "ghgIntensity", "GHG intensity", "tCO2e/$M", false],
  ["env", "renewableShare", "Renewable electricity", "%", true],
  ["env", "waterIntensity", "Water intensity", "m³/$M", false],
  ["env", "netZeroTarget", "Net-zero target year", "", false],
  ["env", "scope3Reported", "Scope 3 reported", "", true],
  ["social", "injuryRate", "Injury rate (TRIR)", "/100 FTE", false],
  ["social", "penaltiesM", "Fines & penalties", "$M", false],
  ["social", "genderPayGap", "Gender pay gap", "%", false],
  ["gov", "boardIndependence", "Board independence", "%", true],
  ["gov", "ceoPayRatio", "CEO pay ratio", "x", false],
  ["gov", "climateInProxy", "Climate risk in proxy", "", true],
];
const PILLAR = { env: "E", social: "S", gov: "G" };

let DATA = [];
const val = (c, m) => { const v = c[m[0]][m[1]]; return typeof v === "boolean" ? +v : v; };

/* Sector-relative percentile rank for each metric; null stays null. */
function computeRanks() {
  const bySector = {};
  DATA.forEach(c => (bySector[c.sector] ||= []).push(c));
  for (const peers of Object.values(bySector)) {
    for (const m of METRICS) {
      const vals = peers.map(c => val(c, m)).filter(v => v != null).sort((a, b) => a - b);
      peers.forEach(c => {
        c.rank ||= {};
        const v = val(c, m);
        if (v == null || vals.length < 2) { c.rank[m[1]] = null; return; }
        const below = vals.filter(x => x < v).length, eq = vals.filter(x => x === v).length;
        let p = 100 * (below + eq / 2) / vals.length;
        c.rank[m[1]] = m[4] ? p : 100 - p;
      });
    }
  }
}

/* Pillar + composite score under current weights and missing penalty. */
function score(c, w, pen) {
  const pillars = {};
  for (const g of Object.keys(PILLAR)) {
    const ms = METRICS.filter(m => m[0] === g);
    const rs = ms.map(m => c.rank[m[1]]).filter(r => r != null);
    const missing = ms.length - rs.length;
    pillars[g] = rs.length ? Math.max(0, rs.reduce((a, b) => a + b) / rs.length - pen * missing) : 0;
  }
  const tot = w.env + w.social + w.gov || 1;
  const composite = (pillars.env * w.env + pillars.social * w.social + pillars.gov * w.gov) / tot;
  return { ...pillars, composite };
}
const weights = () => ({ env: +$("#wE").value, social: +$("#wS").value, gov: +$("#wG").value });
const penalty = () => +$("#pen").value;

/* ================= EXPLORE ================= */
function drawScatter() {
  const svg = $("#scatter"), W = svg.clientWidth, H = svg.clientHeight, P = { l: 50, r: 20, t: 20, b: 40 };
  const xKey = $("#xAxis").value, sector = $("#sectorFilter").value, log = $("#logX").checked;
  const rows = DATA.filter(c => !sector || c.sector === sector)
    .map(c => ({ c, x: xKey === "ghgIntensity" ? c.env.ghgIntensity : c.financial[xKey], y: score(c, weights(), penalty()).composite }))
    .filter(r => r.x != null && (!log || r.x > 0));
  const xs = rows.map(r => r.x), xmin = Math.min(...xs), xmax = Math.max(...xs);
  const tx = v => log ? Math.log10(v) : v;
  const sx = v => P.l + (tx(v) - tx(xmin)) / ((tx(xmax) - tx(xmin)) || 1) * (W - P.l - P.r);
  const sy = v => H - P.b - v / 100 * (H - P.t - P.b);
  let g = `<g class="axis">`;
  for (let y = 0; y <= 100; y += 20) g += `<line x1="${P.l}" x2="${W - P.r}" y1="${sy(y)}" y2="${sy(y)}"/><text x="${P.l - 8}" y="${sy(y) + 4}" text-anchor="end">${y}</text>`;
  const ticks = log ? [...new Set(xs.map(v => Math.pow(10, Math.floor(Math.log10(v)))))].sort((a, b) => a - b) : [0, .25, .5, .75, 1].map(f => xmin + f * (xmax - xmin));
  for (const t of ticks) g += `<line y1="${P.t}" y2="${H - P.b}" x1="${sx(t)}" x2="${sx(t)}"/><text x="${sx(t)}" y="${H - P.b + 16}" text-anchor="middle">${fmt(t, 0)}</text>`;
  g += `<text x="${W / 2}" y="${H - 6}" text-anchor="middle">${$("#xAxis").selectedOptions[0].text}</text>`;
  g += `<text transform="translate(14,${H / 2}) rotate(-90)" text-anchor="middle">Sustainability score (sector-relative)</text></g>`;
  for (const r of rows) {
    const x = sx(r.x), y = sy(r.y);
    g += `<g class="logo" data-t="${r.c.ticker}"><title>${r.c.name}: ${fmt(r.y, 0)}</title>
      <circle cx="${x}" cy="${y}" r="14" fill="#fff" stroke="hsl(${r.y * 1.2},70%,50%)" stroke-width="3"/>
      <image href="${logoUrl(r.c.domain)}" x="${x - 9}" y="${y - 9}" width="18" height="18"/>
      <text x="${x}" y="${y + 26}">${r.c.ticker}</text></g>`;
  }
  svg.innerHTML = g;
  svg.querySelectorAll(".logo").forEach(el => el.onclick = () => showCard(DATA.find(c => c.ticker === el.dataset.t)));
}

function showCard(c) {
  const s = score(c, weights(), penalty());
  const peers = DATA.filter(x => x.sector === c.sector).map(x => ({ t: x.ticker, s: score(x, weights(), penalty()).composite })).sort((a, b) => b.s - a.s);
  const pos = peers.findIndex(p => p.t === c.ticker) + 1;
  let h = `<h2><img src="${logoUrl(c.domain)}" width="20" style="vertical-align:middle"> ${c.name}</h2>
    <div class="hint">${c.sector} · #${pos} of ${peers.length} in sector</div>
    <div class="big">${fmt(s.composite, 0)}</div>`;
  for (const g of Object.keys(PILLAR)) h += `<div>${PILLAR[g]} ${fmt(s[g], 0)}<div class="bar"><i style="width:${s[g]}%"></i></div></div>`;
  h += `<table>`;
  for (const m of METRICS) {
    const v = c[m[0]][m[1]], r = c.rank[m[1]];
    const shown = typeof v === "boolean" ? (v ? "yes" : "no") : m[1] === "netZeroTarget" ? String(v) : fmt(v);
    h += `<tr><td>${m[2]}</td><td class="${v == null ? "na" : ""}">${v == null ? "not reported" : shown + " " + m[3]}</td><td>${r == null ? "" : "p" + fmt(r, 0)}</td></tr>`;
  }
  h += `</table><p class="hint">Source: ${c.meta.source} · as of ${c.meta.asOf}</p>`;
  $("#card").innerHTML = h;
}

/* ================= FUND ================= */
function drawFund() {
  const cp = +$("#cp").value, capPct = +$("#cap").value, k = +$("#tilt").value;
  const totCap = DATA.reduce((a, c) => a + c.financial.marketCapB, 0);
  const rows = DATA.map(c => {
    const wIdx = c.financial.marketCapB / totCap;
    const hit = Math.min(1, cp * c.env.scope12Mt * 1e6 / 1e9 / Math.max(0.05, c.financial.ebitB)); // share of EBIT lost
    return { c, wIdx, hit, w: wIdx * Math.exp(-k * hit * 5) };
  });
  const norm = () => { const s = rows.reduce((a, r) => a + r.w, 0); rows.forEach(r => r.w /= s); };
  const intensity = key => rows.reduce((a, r) => a + r[key] * r.c.env.ghgIntensity, 0);
  norm();
  const idxInt = intensity("wIdx"), target = idxInt * (1 - capPct / 100);
  const dropped = [];
  for (let i = 0; i < 200 && intensity("w") > target; i++) {          // trim the dirtiest held name
    const worst = rows.filter(r => r.w > 0).sort((a, b) => b.c.env.ghgIntensity - a.c.env.ghgIntensity)[0];
    worst.w *= 0.5; if (worst.w < 1e-4) { worst.w = 0; dropped.push(worst.c); }
    norm();
  }
  const activeShare = rows.reduce((a, r) => a + Math.abs(r.w - r.wIdx), 0) / 2;
  const held = rows.filter(r => r.w > 0).length;
  $("#fundStats").innerHTML = [
    ["Index intensity", fmt(idxInt, 0) + " t/$M"], ["Fund intensity", fmt(intensity("w"), 0) + " t/$M"],
    ["Active share", fmt(activeShare * 100, 0) + "%"], ["Names held", `${held} / ${rows.length}`],
    ["Index EBIT at risk", fmt(rows.reduce((a, r) => a + r.wIdx * r.hit, 0) * 100, 1) + "%"],
    ["Fund EBIT at risk", fmt(rows.reduce((a, r) => a + r.w * r.hit, 0) * 100, 1) + "%"],
  ].map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("");
  // sector tilt
  const sec = {};
  rows.forEach(r => { sec[r.c.sector] ||= { i: 0, f: 0 }; sec[r.c.sector].i += r.wIdx; sec[r.c.sector].f += r.w; });
  $("#sectorTilt").innerHTML = Object.entries(sec).sort((a, b) => (b[1].f - b[1].i) - (a[1].f - a[1].i)).map(([s, v]) => {
    const d = (v.f - v.i) * 100, cls = d >= 0 ? "pos" : "neg";
    return `<div class="tiltrow"><span>${s}</span><div class="track"><i class="${cls}" style="left:${50 + (d < 0 ? d * 2 : 0)}%;width:${Math.abs(d) * 2}%"></i></div><span>${d >= 0 ? "+" : ""}${fmt(d, 1)}pp</span></div>`;
  }).join("");
  $("#fundTable tbody").innerHTML = rows.sort((a, b) => b.w - a.w).slice(0, 15).map(r =>
    `<tr><td><img src="${logoUrl(r.c.domain)}" width="14"> ${r.c.name}</td><td>${fmt(r.wIdx * 100, 2)}%</td><td>${fmt(r.w * 100, 2)}%</td><td>${fmt(r.hit * 100, 0)}%</td></tr>`).join("");
  $("#dropped").innerHTML = dropped.length ? dropped.map(c => `<span class="hint">${c.name} (${fmt(c.env.ghgIntensity, 0)} t/$M)</span>`).join(" · ") : `<span class="hint">none — cap satisfied by tilt alone</span>`;
}

/* ================= QUIZ ================= */
const QMETRICS = METRICS.filter(m => !["scope3Reported", "climateInProxy", "netZeroTarget"].includes(m[1]));
let q = null;
const gapStore = JSON.parse(localStorage.getItem("gap") || "{}"); // ticker -> {picks, actualGreen}
function newQuestion() {
  for (let tries = 0; tries < 50; tries++) {
    const m = QMETRICS[Math.floor(Math.random() * QMETRICS.length)];
    const pool = DATA.filter(c => val(c, m) != null);
    const a = pool[Math.floor(Math.random() * pool.length)];
    const peers = pool.filter(c => c.sector === a.sector && c !== a && val(c, m) !== val(a, m));
    if (!peers.length) continue;
    const b = peers[Math.floor(Math.random() * peers.length)];
    q = { m, pair: Math.random() < .5 ? [a, b] : [b, a] };
    break;
  }
  const [a, b] = q.pair, m = q.m;
  $("#qText").textContent = `Which ${a.sector} company has the ${m[4] ? "HIGHER" : "LOWER"} ${m[2].toLowerCase()}?`;
  [a, b].forEach((c, i) => { const el = $("#c" + i); el.className = "choice"; el.disabled = false; el.innerHTML = `<img src="${logoUrl(c.domain)}">${c.name}`; });
  $("#reveal").classList.add("hidden"); $("#next").classList.add("hidden");
}
function answer(i) {
  const [a, b] = q.pair, m = q.m, va = val(a, m), vb = val(b, m);
  const better = (m[4] ? va > vb : va < vb) ? 0 : 1;
  const ok = i === better;
  $("#c" + i).classList.add(ok ? "right" : "wrong"); $("#c" + better).classList.add("right");
  [0, 1].forEach(j => $("#c" + j).disabled = true);
  $("#qTotal").textContent = +$("#qTotal").textContent + 1;
  if (ok) $("#qScore").textContent = +$("#qScore").textContent + 1;
  // perception gap: the company that was picked as "greener"
  const picked = q.pair[i].ticker; gapStore[picked] ||= { picks: 0, right: 0 };
  gapStore[picked].picks++; if (ok) gapStore[picked].right++;
  localStorage.setItem("gap", JSON.stringify(gapStore));
  $("#reveal").innerHTML = `<b>${ok ? "Correct" : "Nope"}.</b> ${a.name}: <b>${fmt(va)} ${m[3]}</b> · ${b.name}: <b>${fmt(vb)} ${m[3]}</b><br>
    <span class="hint">Source: ${a.meta.source} · as of ${a.meta.asOf}</span>`;
  $("#reveal").classList.remove("hidden"); $("#next").classList.remove("hidden");
  drawGap();
}
function drawGap() {
  const rows = Object.entries(gapStore).filter(([, v]) => v.picks >= 2).map(([t, v]) => ({ t, gap: 1 - v.right / v.picks, n: v.picks })).sort((a, b) => b.gap - a.gap).slice(0, 8);
  $("#gap").innerHTML = rows.length ? rows.map(r => `<div>${r.t} <span class="hint">${fmt(r.gap * 100, 0)}% wrong when picked (n=${r.n})</span><div class="bar"><i style="width:${r.gap * 100}%;background:var(--bad)"></i></div></div>`).join("") : `<span class="hint">Play a few rounds.</span>`;
}

/* ================= WIRING ================= */
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button,.tab").forEach(e => e.classList.remove("active"));
  b.classList.add("active"); $("#" + b.dataset.tab).classList.add("active");
  if (b.dataset.tab === "explore") drawScatter();
  if (b.dataset.tab === "fund") drawFund();
  if (b.dataset.tab === "quiz" && !q) newQuestion();
});
["wE", "wS", "wG", "pen"].forEach(id => $("#" + id).oninput = e => { $("#" + id + "v").textContent = e.target.value; drawScatter(); if ($("#card h2")) showCard(DATA.find(c => c.name === $("#card h2").textContent.trim())); });
["xAxis", "sectorFilter", "logX"].forEach(id => $("#" + id).onchange = drawScatter);
[["cp", "cpv"], ["cap", "capv"], ["tilt", "tiltv"]].forEach(([a, b]) => $("#" + a).oninput = e => { $("#" + b).textContent = e.target.value; drawFund(); });
$("#c0").onclick = () => answer(0); $("#c1").onclick = () => answer(1); $("#next").onclick = newQuestion;
window.onresize = () => $("#explore").classList.contains("active") && drawScatter();

fetch("data/companies.json").then(r => r.json()).then(j => {
  DATA = j.companies; computeRanks();
  [...new Set(DATA.map(c => c.sector))].sort().forEach(s => $("#sectorFilter").insertAdjacentHTML("beforeend", `<option>${s}</option>`));
  drawScatter(); drawGap();
});
