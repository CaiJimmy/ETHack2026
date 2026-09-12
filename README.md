# ETHack 2026

## Challenge

Build a data-driven framework to quantify and compare the sustainability of companies in the S&P 500.

Define what sustainability means, identify and justify the most relevant indicators, source the data, and develop a methodology to score, rank, or compare companies. Environmental, financial, operational, or other dimensions are all fair game.

Choose your own dataset, justify the choice, and show it is suitable for the challenge.

**Bonus:** Tomorrow, the world commits to reaching net-zero emissions as fast as possible. You manage a $1B fund. How do you allocate your portfolio under this scenario, and why?

## Judging Criteria

| Criterion | Question |
|---|---|
| Impact | What impact could the solution have on society, and who benefits? |
| Innovation | Original approach or fresh angle? Would a team get here without thinking hard? |
| Technical Execution | How much actually works? Build quality relative to two days. |
| Feasibility | Could it survive past the weekend? Realistic about cost, data, adoption, constraints. |
| Presentation | Clear problem framing, working demo, honest about limitations, finished on time. |

Each scored 0–5:

| Score | Meaning |
|---|---|
| 0 | Absent or not attempted |
| 1 | Barely there, mostly assertion |
| 2 | Attempted but weak or unclear |
| 3 | Solid, meets expectations |
| 4 | Strong, clearly above the field |
| 5 | Exceptional, best of the day |

## App (GreenRank)

Static site, no backend, no build step. It reads `web/data/master.json` (real data, see below).

```
data/sp500_ocr.csv    -> the 503-row S&P 500 list (spine)
data/build_master.py  -> joins tmp/ sources onto the spine, writes web/data/master.csv + master.json
web/index.html        -> four tabs: Explore, Net-Zero Fund, Quiz, Methods & Sources
web/app.js            -> scoring (sector percentiles, pillar weights), scatter, fund model, curated quiz
web/style.css
run.sh                -> rebuilds the master (if .venv exists) and serves on http://localhost:8000
```

Run: `./run.sh` then open http://localhost:8000

| Tab | What it shows |
|---|---|
| Explore | Two views. Scatter: sustainability score (sector-relative, 0–100) against market value, revenue, EBITDA, employees or emissions, logos as points. Treemap: the whole index as boxes sized by market value, revenue or CO2 and coloured by score (like a stock heatmap). Four weight sliders (E, S, G, Financial resilience), sector filter, search box. Click a logo or box for a score card: each metric, its value, its sector percentile and its source. |
| Net-Zero Fund | $1B allocation under a carbon price. Four plain-language steps, three sliders each with a one-sentence explanation, results as labelled tiles, sector tilts, top positions, companies cut. A "what the model does not know" list and a glossary sit at the bottom. |
| Quiz | Ten fixed questions about well-known companies with surprising answers (Duke Energy out-emits ExxonMobil on US sites, Berkshire out-emits Chevron, Starbucks has 13x Nvidia's staff, CVS out-sells Nvidia). Each answer shows both real values, a one-line explanation, and the source. Questions are skipped if the data is missing. |
| World Map | Interactive globe (globe.gl, bundled in `web/lib/`). Countries coloured by CO2 per person, CO2 total, renewable electricity, electricity access, GDP per person, or life expectancy. Company logos at head-office cities (top N by market value). Click a country for its numbers and the S&P 500 companies based there. Needs WebGL; if the browser has none (VS Code's built-in browser, some remote desktops), the tab falls back to a flat SVG map with the same colours, clicks and logos. A 3D/2D toggle is in the panel. |
| Methods & Sources | Definition, metric table with source and coverage count, scoring steps, why each source was chosen, limits, and a list of every source with links. |

Text follows ASD-STE100 style where practical: short sentences, active voice, one idea per sentence. Every tab ends with its sources and a glossary of the finance words used on that tab.

## Master dataset (real data)

`tmp/` (gitignored) holds the raw downloads. `data/build_master.py` joins the company-level ones onto the OCR'd S&P 500 list and writes `web/data/master.csv` and `master.json` (503 rows, 500 after dual-class duplicates).

```
python3 -m venv .venv && .venv/bin/pip install openpyxl
.venv/bin/python data/build_master.py
```

| Column group | Source file in tmp/ | Join key | Coverage |
|---|---|---|---|
| ticker, name, market_cap_b, price, revenue_b | `data/sp500_ocr.csv` (OCR of a Sep-2026 screener; has OCR errors, e.g. HONA, VMRK, FDXF) | spine | 500 |
| sector, industry, employees, esg_risk_* , controversy_* | `SP 500 ESG Risk Ratings.csv` (Sustainalytics via Kaggle, 2024) | ticker | 395 with scores |
| ebitda_b, revenue_growth, ntc_climate_credit_score | `climate-credit-risk-analyzer-main/climate_credit_risk_data.csv` (yfinance snapshot) | ticker | 393 |
| ghgrp_scope1_mt, ghgrp_scope1_2019_mt, ghgrp_trend_5y_pct, ghg_intensity_t_per_musd, ghgrp_facilities | `2023_data_summary_spreadsheets/ghgp_data_by_year_2023.xlsx` (EPA GHGRP direct emissions, all direct-emitter sheets) + `ghgp_data_parent_company(2023).csv` (ownership %) | parent-company name, normalised + alias table | 127 |
| logo_domain, altman_z, piotroski_f, decarb_target_year, decarb_ambition_pa_pct, decarb_coverage_pct, temp_goal_c, controversy_flags, controversy_worst, sdg_aligned_count | `Global Corporate ESG and Financial Dataset.csv` (Kaggle mrbossjaysrb, semicolon-separated; Yahoo Finance / Sustainalytics fields) | ticker | 421 (300–390 per column) |
| report_year, report_e/s/g/total_score, report_count | `preprocessed_content.csv` (NLP keyword scores of sustainability-report PDFs, Kaggle) | ticker, latest year | 239 |

Notes on the EPA join:
- Only **direct** (Scope 1) emissions are used. `ghg.csv` (the single-file export) mixes in supplier subparts MM/NN/PP, which count fuel sold downstream and inflated refiners 10x; it is not used.
- GHGRP covers US facilities above 25 kt CO2e only. A null means "no reporting US facility matched", not zero. Banks, software and pharma are legitimately null.
- Matching: normalised name equality, an alias table for renames and mergers (Calpine to Constellation, Chesapeake to Expand, WestRock to Smurfit Westrock), then a two-token prefix rule. `data/ghgrp_matches.csv` lists every parent-to-ticker pair; `data/ghgrp_unmatched_parents.csv` lists the largest unmatched parents (none are S&P 500 members).

Company logos are bundled in `web/icons/` (492 of 500) by `data/build_icons.py`, so the site needs no icon service at demo time. Every icon was checked by eye on a contact sheet. The Kaggle dataset's `domain` column was wrong for about 1 in 4 companies (Procter & Gamble pointed at pc-people.com), so the curated `DOMAINS` map in `web/app.js` takes priority and implausible dataset domains are dropped at build time. Sources per icon: Google's favicon service first (its blue-globe placeholder is rejected by hash), then icon.horse, with hand-checked alternative domains for a few. Eight companies have no usable icon anywhere (Allstate, Targa, Devon, Diamondback, Atmos, Alexandria RE, Berkshire, Roper) and show a ticker circle instead.

Also written by other scripts: `data/build_hq.py` geocodes each head-office city once through OpenStreetMap Nominatim (cache in `data/hq_geocode.json`) and writes `web/data/hq.json`; `web/data/countries.json` holds the latest value per country per metric from `archive (3)/WorldSustainabilityDataset.csv`; `web/data/countries.geojson` is Natural Earth 110m via the globe.gl examples.

The "involvement" screens in the Global Corporate dataset (thermal coal, weapons, tobacco) are filled for only 34 of 421 S&P companies, so they are not used.

Not joinable to companies (country-level, kept for context or quiz questions only): World Development Indicators extract, WorldSustainabilityDataset, global-data-on-sustainable-energy, energy_data_II. `company_esg_financial_dataset.csv` is anonymised (Company_1 ...) and cannot be joined. `SP500.csv`, `data.csv`, `s-and-p-500-main` are index price history.

Caveat: the `report_*` scores track the Sustainalytics `esg_risk_*` columns almost exactly (Apple 17.22 vs 17.2, JPMorgan 29.08 vs 29.3), so the Kaggle report dataset appears to have copied those ratings rather than derived them from the PDFs. Treat them as a second copy of Sustainalytics, not as independent evidence.
