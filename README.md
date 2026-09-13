# ETHack 2026

## Challenge

Build a data-driven framework to quantify and compare the sustainability of companies in the S&P 500.

Define what sustainability means, identify and justify the most relevant indicators, source the data, and develop a methodology to score, rank, or compare companies. Environmental, financial, operational, or other dimensions are all fair game.

Choose your own dataset, justify the choice, and show it is suitable for the challenge.

**Bonus:** Tomorrow, the world commits to reaching net-zero emissions as fast as possible. You manage a $1B fund. How do you allocate your portfolio under this scenario, and why?

## Judging criteria

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

## Repo layout

```
src/            fetch and build scripts, one per source
data/interim/   derived tables, committed, 38 MB  -> see data/README.md
data/raw/       cached HTTP responses, not committed, rebuildable
docs/           audits and methodology notes
flake.nix       nix devshell: python312 + uv + duckdb + node + ffmpeg
```

## Data

Every number comes from a source companies are legally compelled to file, or from a public regulator or
standards body. Nothing is bought, nothing is scraped from a vendor's proprietary feed, and everything is
reproducible by anyone with the two free API keys listed in `data/README.md`.

| source | what it gives | S&P 500 covered |
|---|---|---|
| EPA GHGRP | facility-level Scope 1, mandatory, with parent company and lat/lon, 2010-2023 | 142 matched, carrying 44.8% of all US regulated direct emissions |
| EPA CAMD | Part 75 stack-monitor CO2, instrument-measured, through 2026 | 48 tickers, 40 of them in 2025, carrying 54.0% of 2025 US measured power CO2 |
| EIA + EPA eGRID | net generation and grid emission factors, for gCO2e/kWh | 15,757 plants |
| SEC XBRL | revenue, operating income, assets, capex, shares | 503 / 503 |
| Net Zero Tracker + SBTi | climate targets, years, baselines, validation status | 461 / 503 |
| Good Jobs First | regulatory penalties by offence group, 2000-2026 | 468 measured non-zero, 35 measured zero |
| NGFS Phase 5 | carbon price paths to 2050 under 7 scenarios | scenario layer |
| EU 2020/1818 | the Paris-Aligned Benchmark rulebook, encoded with article citations | 24 rules |

Coverage, limitations and the traps in each source are written up in `data/README.md`. The entity
resolution behind the emissions join is audited in `docs/entity_resolution_audit.md`: 98% precision on a
seeded random sample, with the three false positives we found and fixed.

## Setup

```bash
nix develop
uv venv && uv pip install --python .venv/bin/python -r requirements.txt
```
