// Migrated from web/app.js; values are a subset of web/data/master.json.
import companies from './quizData.json';
const fmt = (v, d = 1) => v.toLocaleString('en-US', { maximumFractionDigits: d });
const pct = v => (v >= 0 ? '+' : '') + fmt(v, 1) + '%';
const SRC = {
  epa:  { name: "US EPA Greenhouse Gas Reporting Program (GHGRP), direct emissions 2019-2023, matched to parent companies by ownership share", url: "https://www.epa.gov/ghgreporting/data-sets" },
  sust: { name: "Sustainalytics ESG Risk Ratings for the S&P 500, 2024 copy on Kaggle", url: "https://www.kaggle.com/datasets/pritish509/s-and-p-500-esg-risk-ratings" },
  yf:   { name: "Yahoo Finance company snapshot (EBITDA, employees), 2025, bundled in the open-source climate-credit-risk-analyzer", url: "https://huggingface.co/spaces/SubramaniMokkala/climate-credit-risk-analyzer" },
  world: { name: "World Sustainability Dataset (World Bank WDI and Our World in Data, via Kaggle), latest year per metric, up to 2018", url: "https://www.kaggle.com/datasets/truecue/worldsustainabilitydataset" },
  osm:  { name: "OpenStreetMap Nominatim, used once to find the latitude and longitude of each head-office city; country borders from Natural Earth", url: "https://nominatim.openstreetmap.org" },
  corp: { name: "Global Corporate ESG and Financial Dataset (Kaggle, mrbossjaysrb): Altman Z, Piotroski F, decarbonisation targets, controversy flags", url: "https://www.kaggle.com/datasets/mrbossjaysrb/global-corporate-esg-and-financial-dataset" },
  list: { name: "S&P 500 member list with market value, price and revenue: market screener screenshot, September 2026 (OCR)", url: null },
};
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

function shuffle(items) {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}
export function buildQuizRounds(data = companies) {
  return shuffle(Q.flatMap(t => {
    const pair = shuffle([data.find(c => c.ticker === t.a), data.find(c => c.ticker === t.b)]);
    if (pair.some(c => !c || !Number.isFinite(c[t.key])) || pair[0][t.key] === pair[1][t.key]) return [];
    const correct = (t.pick === 'high' ? pair[0][t.key] > pair[1][t.key] : pair[0][t.key] < pair[1][t.key]) ? 0 : 1;
    // Employee provenance follows master.json, which identifies the Yahoo snapshot.
    const source = SRC[t.key === 'employees' ? 'yf' : t.src];
    return [{ question: t.text, pair, correct, source,
      options: pair.map(c => c.name),
      values: pair.map(c => `${c.name}: ${t.f(c[t.key])}.`),
      explanation: t.why,
    }];
  }));
}
