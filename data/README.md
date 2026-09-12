# Data

Everything here is built by the scripts in `src/`. No file was edited by hand.

## What is committed and what is not

`data/interim/` is committed. It holds the derived tables, 38 MB, and it is what the scoring and site
code reads.

`data/raw/` is not committed. It is 2.4 GB of cached HTTP responses, and every fetch script is
idempotent, so a clone rebuilds it:

```bash
nix develop
uv venv && uv pip install --python .venv/bin/python -r requirements.txt
for s in src/fetch_*.py; do .venv/bin/python "$s"; done
.venv/bin/python src/match_parents.py
.venv/bin/python src/build_power_intensity.py
```

A full cold rebuild takes about two hours, most of it the SEC XBRL pull (1.9 GB) and the Violation
Tracker scrape (28 minutes of deliberately slow requests). A second run does no network I/O at all.

Two API keys are needed and both are free. Put them in `.env`, which is gitignored and which the
devshell sources automatically:

```
CAMD_API_KEY=...    # https://www.epa.gov/power-sector/cam-api-portal#/api-key-signup
EIA_API_KEY=...     # https://www.eia.gov/opendata/register.php
```

Without them the CAMD lane falls back to bulk files and the EIA lane will not run.

## Conventions

The join key is `ticker`, uppercase, dots not dashes, so `BRK.B` and not `BRK-B`. SEC writes them with
dashes; `ticker_aliases.json` maps every spelling we might meet, 511 aliases over 808 normalised name
keys, to the canonical one.

`universe.parquet` is **503 rows, one per listing, not 500 companies**. GOOGL/GOOG, FOXA/FOX and
NWSA/NWS each share a CIK. Filter `is_primary_listing == True` for the 500-company view. Anything that
sums emissions, revenue or portfolio weight has to dedupe first or Alphabet counts twice.

Missing values are null and counted. Nothing is imputed silently. Where a number is estimated rather
than reported it carries a `dq` column scored 1 to 5 on the PCAF convention: 1 is verified reported,
3 is a physical-activity estimate, 5 is a sector factor times revenue.

Every source has a provenance record in `data/interim/provenance/` listing each URL fetched with its
retrieval time, HTTP status, byte count, SHA-256, licence and a plain sentence on redistribution. API
keys are masked to `<api_key>` before anything is written, and the repo has been scanned to confirm
neither key appears in any tracked file.

## Files

### Universe and identity

| file | rows | what it is |
|---|---|---|
| `universe.parquet` | 503 | S&P 500 constituents with CIK, GICS sector and sub-industry, SEC entity and former names |
| `cik_ticker.parquet` | 10,426 | every SEC registrant with a ticker, over 8,020 CIKs |
| `ticker_aliases.json` | 511 aliases | ticker spellings, normalised name keys, CIK co-filer map |
| `universe_turnover.json` | 4 windows | index churn at 1, 3, 5 and 10 years, with the full departed and joined lists |

All 503 listings agree with SEC's own `company_tickers.json` on CIK. Zero disagreements. Without the
dot-to-dash fix it would be 501 of 503.

### Emissions

| file | rows | years | what it is |
|---|---|---|---|
| `ghgrp_facilities.parquet` | 148,833 | 2010-2023 | EPA GHGRP facilities, parent-company strings with ownership share, lat/lon, NAICS |
| `ghgrp_parent_year.parquet` | 50,906 | 2010-2023 | direct Scope 1 rolled to parent company |
| `camd_unit_year.parquet` | 74,896 | 2010-2026 | Part 75 stack-monitor CO2 per unit, instrument-measured |
| `camd_unit_quarter.parquet` | 38,932 | 2024-2026 | the same at quarterly resolution |
| `oris_ghgrp_crosswalk.parquet` | 2,089 | | ORIS code to GHGRP facility id, covers 98.4% of 2025 CAMD CO2 |
| `emissions_by_ticker.parquet` | 8,551 | 2010-2026 | the joined result, 503 tickers x 17 years, absence recorded rather than dropped |
| `parent_ticker_map.parquet` | 8,778 | | every distinct parent string, matched or not, tagged with the method that matched it |
| `unmatched_top_emitters.csv` | 6,867 | | the emitters we could not attribute, largest first |

### Power sector

| file | rows | years | what it is |
|---|---|---|---|
| `eia_plant_generation.parquet` | 399,709 | 2015-2025 | EIA net generation by plant, fuel and prime mover |
| `eia_plant_totals.parquet` | 105,710 | 2015-2025 | one row per plant-year, the intensity denominator |
| `egrid_plant.parquet` | 71,475 | 2018-2023 | eGRID plant attributes, emission rates, subregion |
| `egrid_subregion.parquet` | 161 | 2018-2023 | the 27 grid subregion emission factors |
| `plant_intensity.parquet` | 114,078 | 2015-2025 | gCO2e/kWh per plant-year, with the PAB Article 12(1)(g) flag |

### Financial, targets, conduct, scenarios

| file | rows | years | what it is |
|---|---|---|---|
| `financials.parquet` | 5,379 | 2015-2025 | SEC XBRL revenue, operating income, assets, equity, capex, R&D, debt, shares, each with the tag it came from |
| `market_cap.parquet` | 503 | | price, shares outstanding, market cap, public float |
| `targets.parquet` | 1,352 | | one row per climate target, from Net Zero Tracker and SBTi |
| `targets_company.parquet` | 503 | | one row per company, including the implied annual reduction rate |
| `violations.parquet` | 12,846 | 2000-2026 | regulatory penalties by year and offence group |
| `violations_by_agency.parquet` | 6,778 | | the same split by enforcing agency |
| `violations_summary.parquet` | 503 | | per-company totals, environment subtotal separated |
| `ngfs_scenarios.parquet` | 61,469 | 2020-2100 | NGFS Phase 5 carbon price and pathway variables, 7 scenarios |
| `pab_rules.json` | 24 rules | | EU Regulation 2020/1818 encoded, each rule carrying its article and the sentence it was parsed from |

## Coverage, stated honestly

| layer | S&P 500 covered | note |
|---|---|---|
| Universe, financials | 503 / 503 | operating income 501/503; the gaps are HONA and PSKY, both 2026 corporate actions |
| Climate targets | 461 / 503 (91.7%) | 341 carry a numeric annual reduction rate |
| Regulatory penalties | 468 / 503 measured non-zero | the other 35 were checked and have no records, so they are measured zero, not missing |
| Measured Scope 1 (GHGRP) | 142 matched, 128 with non-zero | these carry 44.8% of all US regulated direct emissions |
| Measured power CO2 (CAMD) | 49 tickers | 54.0% of US measured power CO2 in 2025 |

The emissions gap is structural, not a join failure. Most of the S&P 500 operates no US facility above
the 25,000 tCO2e reporting threshold. Of 30 sampled uncovered tickers, 25 genuinely have no qualifying
facility, 3 are 2025-26 spinoffs with no reporting history, and 2 are deliberate fund-holding
exclusions.

## Known problems

**Survivorship bias, measured.** Today's membership applied to historical emissions. Of the 503 tickers
in the index on 2023-08-30, 62 are gone today and 37 of those are still SEC registrants that still
emit. Over ten years it is 168. The departed set is energy-heavy (HES, MRO, PXD, CTRA), which skews any
backward-looking trend.

**Cogeneration breaks the naive intensity calculation.** A CAMD stack monitor meters the whole flue,
including the CO2 that made process steam for a neighbouring plant, while eGRID allocates the steam
host's share away from the kWh. Dividing measured CO2 by electric generation overstates CHP intensity
by 16% at the median and by 3x at Sweeny Cogeneration. `plant_intensity.parquet` uses eGRID's allocated
rate for CHP and the measured ratio elsewhere.

**eGRID publishes a rate of 0.00 gCO2e/kWh for 914 plant-years that did emit.** One is a coal plant
with negative net generation that reads as Paris-aligned at face value. Those are voided and counted.

**The three-way reconciliation is partly circular.** eGRID republishes EIA-923 generation and uses the
same Part 75 monitors as CAMD, so 88% of overlapping rows agree to the last decimal place. What the
reconciliation validates is the ORIS join, which it does convincingly. It does not demonstrate three
independent sources agreeing, and the write-up should not claim it does.

**EIA returns the same generation at three nesting levels**, so summing without filtering triples the
national total. Use `eia_plant_totals.parquet`, or `row_level == 'plant_total'`. Plant code 99999 is
not a plant; it is EIA's imputed state-level residual and must never be joined to CAMD.

**GHGRP mixes direct emitters with fuel suppliers.** Summing the emissions table without filtering
`sector_type == 'E'` gives 7,364 MMT for 2023, roughly three times actual US emissions. The correct
figure is 2,697 MMT and the fetch script asserts it.

**GHGRP has no 2024 or 2025 data.** Reporting year 2025 is due 30 October 2026. CAMD is the only
current feed.

**Fuzzy name matching is close to worthless on this data.** At `token_set_ratio >= 80` the top 36
candidates by tonnes are 36 false positives and zero true positives, because every US utility name is a
token subset of another one. CPS ENERGY matches CMS at 90, PORTLAND GENERAL ELECTRIC matches GENERAL
ELECTRIC at 100. The map is built from exact keys, a 28-entry hand-verified override table and a
9-entry blocklist instead.

## Entity resolution

`docs/entity_resolution_audit.md` has the full audit. Precision on a seeded, tonnes-stratified random
sample of 50 matched pairs is 49/50, or 98.0%, with a 95% Wilson interval of 89.5% to 99.6%. Sampling
30 uncovered tickers found no recall misses. Three false positives were found and fixed, including
ENERGY HARBOR CORP mapped to Vistra, which had overstated Vistra's 2022 emissions by 13% because the
coal fleet was explicitly excluded from that acquisition.
