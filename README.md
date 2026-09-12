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

Static site, no backend, no build step. All metric values are **synthetic** (seeded, sector-calibrated); company names, tickers and logos are real.

```
data/generate.py      -> writes web/data/companies.json  (swap this for the real EDGAR/EPA pipeline; keep the schema)
web/index.html        -> four tabs: Explore, Net-Zero Fund, Quiz, Methods
web/app.js            -> scoring engine (sector percentile ranks, pillar weights, missing-data penalty) + all panels
web/style.css
run.sh                -> regenerates data and serves on http://localhost:8000
```

Run: `./run.sh` then open http://localhost:8000

| Tab | What it shows |
|---|---|
| Explore | Scatter of sustainability score vs market cap / return / P/E / GHG intensity, logos as points, live E/S/G weight sliders, sector filter, click for a score card with per-metric rank, source and missing-data flags |
| Net-Zero Fund | $1B allocation under a shadow carbon price: EBIT hit per company, tilt away from it, trim until portfolio intensity cap holds; sector tilts, active share, names dropped first |
| Quiz | "Which company has the lower X?" between sector peers; reveals values and source; accumulates a perception-gap table in localStorage |
| Methods | Definition, indicator table with intended real sources, scoring steps, limitations |
