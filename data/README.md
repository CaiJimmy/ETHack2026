# Data

Everything here is built by the scripts in `src/`. No file was edited by hand.

## What the repo holds and what it rebuilds

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
.venv/bin/python src/validate_coverage.py
.venv/bin/python src/verify_camd_share.py
```

`validate_coverage.py` touches no network, reads only the tables above and writes the validation
tables plus every number quoted in `docs/coverage_and_validation.md`. `verify_camd_share.py` runs
last and makes two EPA calls, to check our CAMD national total against EPA's own aggregation of
the same feed.

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
| `scope23.parquet` | 3,969 | 2013-2022 | voluntary Scope 1, 2 and 3 from company reports, plus the eGRID grid factor for every HQ region |
| `climatetrace_company.parquet` | 1,578 | 2021-2026 | Climate TRACE asset emissions rolled to ticker by sector, subsector and country, gross and equity share |
| `climatetrace_nonus_share.parquet` | 438 | 2021-2026 | the non-US share per company-year, with the EPA comparison columns |

`scope23.parquet` is voluntary and modelled, never mandatory. 3,018 of its rows carry no tonnage at
all: they are the eGRID factor for a company's HQ subregion, waiting for a kWh figure that does not
exist for free. Filter `tonnes_co2e.notna()` before counting anything.

`climatetrace_company.parquet` carries both `emissions_tonnes_co2e` (gross) and
`equity_share_tonnes_co2e`. Use the equity column. Gross double counts joint ventures and sums to
2,379 MMT against 1,508 MMT on equity across the same 73 tickers.

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

### Exclusions and vendor benchmarks

| file | rows | what it is |
|---|---|---|
| `revenue_exclusions.parquet` | 3,018 | 503 listings x 6 Article 12 rules, with a flag from each of four independent screens and a decided `flag_best` |
| `vendor_scores.parquet` | 9,154 | six free ESG datasets in long form, one row per ticker, metric and source |
| `esg_vendor_consensus.parquet` | 489 | per-source percentile and a consensus percentile per company |

Everything in `vendor_scores.parquet` and `esg_vendor_consensus.parquet` carries
`provenance_class = 'vendor'`. Nothing tagged `vendor` is an input to the score. These tables exist to
benchmark our score and to validate proxies we built ourselves, and the schema is the enforcement.

`revenue_exclusions.parquet` keeps the four screens in separate columns on purpose: `flag_gics` (sector
proxy), `flag_sec` (measured segment revenue from the SEC DERA statement sets), `flag_vendor`
(`provenance_class = 'vendor'`), `flag_nbim` (Norges Bank's published exclusion list, `voluntary`).
`flag_best` is the decided answer and `flag_basis` says which screen decided it. `flag_dq` is 1 when a
measured revenue share was tested against the article's own threshold, 3 or 4 for the sector proxy, 5
when nobody spoke.

### Validation

| file | rows | what it is |
|---|---|---|
| `vendor_rank_correlation.parquet` | 25 | pairwise Spearman rho between every vendor source, with n and lineage, for `esg_total` and `esg_e` |
| `gics_proxy_validation.parquet` | 18 | per Article 12 rule, the GICS proxy against each comparator: confusion counts, precision, recall, kappa and the names of every disagreement |
| `coverage_summary.parquet` | 26 | one row per data layer with coverage out of 503 and what it can and cannot support |
| `validation_summary.json` | | every number quoted in `docs/coverage_and_validation.md` |
| `camd_share_verification.json` | | the 2025 CAMD national total against EPA's own aggregation, the stack test, and the S&P 500 share |

## Coverage

Every count below is printed by `src/validate_coverage.py`, and the full table with one row per
layer is in `coverage_summary.parquet`. Counts are listings out of 503.

| layer | covered | note |
|---|---|---|
| Universe, revenue | 503 / 503 | operating income 502/503, the gap is HONA; market cap 502/503, the gap is ARES |
| Measured Scope 1 (GHGRP) | 146 matched, 139 with a tonnage in some year, 128 non-zero in 2023 | 7 matched tickers report no tonnage at all. The 2023 set carries 44.8% of all US regulated direct emissions |
| Measured power CO2 (CAMD) | 48 with a tonnage, 40 non-zero in 2025 | 61 tickers match a CAMD facility; the other 13 have no CO2 on it |
| Plant-level intensity | 61 | the Article 12(1)(g) 100 gCO2e/kWh test |
| Voluntary Scope 1 | 112 | none newer than FY2022; 17 rows are order-of-magnitude suspect |
| Voluntary Scope 2, either basis | 111 | location basis only 10 |
| Voluntary Scope 3 total | 74 | by category, 7 |
| eGRID grid factor for HQ region | 502 | the miss is XYZ, whose `hq_location` is the string 'none' |
| PAB exclusions 12(1)(a) to (f) | 503 / 503 decided | 317 decided on measured segment revenue, 1,317 rule rows on the sector proxy |
| PAB conduct rule 12(1)(c) | 3 exclusions | CAT, DUK, FCX, all from one published list. Absence is untested, not clean |
| Climate targets | 461 / 503 (91.7%) | 341 carry a numeric annual reduction rate |
| Regulatory penalties | 468 / 503 measured non-zero | the other 35 were checked and have no records, so they are measured zero, not missing |
| Vendor ESG, any source | 492 | 475 excluding the AI-generated source. Benchmark only, never an input |
| Climate TRACE asset ownership | 73 | 25 with material foreign assets; the rest of the index is untested on non-US |

The number to say first: **139 listings carry a mandatory measured tonnage, 115 a voluntary one, 228
either, and 273 listings carry no emissions number of any kind from any source.**

The emissions gap is structural, not a join failure. Most of the S&P 500 operates no US facility above
the 25,000 tCO2e reporting threshold. Of 30 sampled uncovered tickers, 25 have no qualifying facility,
3 are 2025-26 spinoffs with no reporting history, and 2 are deliberate fund-holding exclusions.

`docs/coverage_and_validation.md` has the full picture: the vendor rank-correlation matrix, the
confusion matrices behind the GICS exclusion proxy, the size of the US-only bias, and what is still
missing.

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

**CAMD's `associated_stacks` column looks like a double count and is not one.** EPA's apportioned
annual feed publishes one row per unit and no row for a common stack; the column names the stack a
unit vents through, so the CO2 has already been apportioned back to the units. 397 of the 3,989 2025
unit rows name a stack and they carry 8.0% of the CO2. Summing units gives 1,635.1 M short tons for
2025, which is what EPA's own by-facility and by-state aggregations return over the same 1,311
facilities, to the short ton. `src/verify_camd_share.py` proves it.

**The S&P 500 share of 2025 measured power CO2 is 54.0%, and the way to get 49.0% is a unit
mismatch.** 801.6 MMT attributed over a national total of 1,483.4 MMT is 54.0%. Dividing the same
801.6 MMT by 1,635.1, which is the national total in *short* tons, gives 49.0%. The attribution also
closes: attributed 801.6 MMT plus the 681.7 MMT named to owners outside the index sums to the
national total exactly, so nothing is counted twice and nothing is lost.

**Fuzzy name matching is close to worthless on this data.** At `token_set_ratio >= 80` the top 36
candidates by tonnes are 36 false positives and zero true positives, because every US utility name is a
token subset of another one. CPS ENERGY matches CMS at 90, PORTLAND GENERAL ELECTRIC matches GENERAL
ELECTRIC at 100. The map is built from exact keys, a 28-entry hand-verified override table and a
9-entry blocklist instead.

**The vendor table is not six independent raters.** In `vendor_scores.parquet`, pritish509 and
rikinzala correlate at Spearman 0.99998 over 397 names and flamingmasamune at 0.948. All three are
re-uploads of the same dead Yahoo Finance `esgScores` pull. A second source, mashinii, is generated by
a language model and carries `ai_generated = True`. A third, alistairking, ranks the index close to
backwards (rho -0.13 against the Sustainalytics lineage) because its scale tracks disclosure volume,
not performance: ConocoPhillips holds its highest total score with an A grade. Quote the cross-lineage
pairs, never a six-by-six matrix as six raters agreeing.

**mrbossjaysrb's ticker column is unusable and joining on it is a silent disaster.** 151 of its 420
apparent S&P 500 tickers carry more than one row and the extras are unrelated companies. AMZN's only
row is Meezan Bank, a Pakistani bank. IBM carries ten rows including Business & Decision Benelux. Rows
are attributed by name with a hand-checked override and block list instead. A one-word name that is a
token subset of an S&P 500 name is the second trap: Automatic Labs passed as Automatic Data
Processing, Monster Worldwide as Monster Beverage, Nemours Children's Health as DuPont.

**In pandas 3, a missing value in a string column is truthy.** Assigning a list of str-or-None to a
DataFrame column gives a string dtype where a miss is `pd.NA`, and `if row['col']` then accepts every
row. This silently turned a 407-row match into 15. Keep per-row lookup tables as plain Python dicts
and lists, or test with `pd.notna()`.

**companyfacts cannot do segment revenue.** Sampled 25 S&P 500 companyfacts documents: 0 facts carry
any dimension. The API publishes consolidated series and drops every axis, so ExxonMobil's document
has one Revenues series and no product breakdown. The SEC DERA Financial Statement Data Sets are the
only public SEC product that keeps dimensions, in the `segments` column of `num.txt`, written as
`Axis=Member`. Four quarters are needed to catch every 10-K whatever the fiscal year end.

**Segment revenue classifiers read the wrong industry's words.** Bunge's `SoybeanProcessingAndRefining`,
Freeport's `RodAndRefiningSegment` and ADM's `RefinedProductsandOther` all look like oil refining on a
keyword match. Refining words are switched off per issuer when that issuer's own segment names carry
agricultural or metals vocabulary. Xcel read as 100% gas because `RegulatedOperatingRevenueGas` has
its own consolidated value, so the denominator is always total revenue now.

**Climate TRACE names no US owner in oil and gas.** 0 of 352 US oil-and-gas-production assets and 0 of
352 US oil-and-gas-transport assets carry a parent name, against 103 of each abroad. Every upstream
company's raw non-US share is therefore 100% by construction. Use `ct_nonus_share_balanced`, which
drops those subsectors, and read `ct_us_vs_epa_us` next to it.

**Climate TRACE's asset boundary is not corporate Scope 1.** Where a company also publishes a global
figure, refining and steel line up (Marathon 1.04x, Steel Dynamics 1.05x) but upstream does not: APA
reports 6.0 MMT and Climate TRACE attributes 25.3 MMT, a factor of 4.2. Midstream and aggregates go
the other way (Kinder Morgan 0.06x, Martin Marietta 0.12x). The non-US figures size an attribution
gap, not a reconciliation.

**The vendor tobacco screen tests a different thing from the regulation.** Against `flag_gics` it
scores precision 1.000, recall 0.087, kappa 0.152, because it is an involvement screen that catches
anyone who retails cigarettes: Walmart, Costco, Kroger, Chevron, Disney. Article 12(1)(b) excludes
cultivation and production. Against SEC segment revenue and against NBIM, both of which test
production, the sector proxy scores kappa 1.00. A low kappa against a vendor screen is not evidence
the proxy is wrong.

**The GICS exclusion proxy cannot see an activity that does not define a sector.** It misses Jacobs
Solutions on nuclear weapons (NBIM excludes it; GICS files it as engineering services), CSX and
Norfolk Southern on coal distribution (13.5% and 12.2% of revenue), and EQT and Expand Energy on the
50% gas bar. It also over-flags Expand Energy for oil, which measures 3.7% against a 10% threshold.
Use `flag_best`, which lets a measured revenue share override the proxy, and read `flag_dq`.

**New York's dominant eGRID subregion is not where its companies sit.** Generation weighting puts the
whole state on NYUP at 211 gCO2e/kWh, upstate hydro and nuclear, but 40 of the index's 52 New York
head offices are in the five boroughs, which is NYCW at 393 g/kWh. NYC and Long Island are
hand-assigned. Every other multi-subregion state was checked and its dominant subregion is also where
its head offices are.

**The `nopperl` emission-report ids carry an exchange prefix that decides the match.** LSE_BA is BAE
Systems, not Boeing. ASX_DOW is Downer, not Dow. TSX_T is Telus, not AT&T. Ignoring the prefix adds
131 false-positive rows. Restricting to NASDAQ, NYSE and OTC gives 101 S&P tickers.

**The project's name normaliser strips a trailing CO**, so `wesco` normalises to WES (Western
Midstream) and `graco` to GRA (W R Grace). Any report-URL-to-ticker map built on it has to be an
explicit table, not an automatic match.

**Two free report corpora contain no numbers at all.** The Kaggle jaidityachopra dataset strips every
digit in preprocessing: 866 report texts, 804 containing the word 'scope', 0 containing a single
numeral. CDP's public Flourish embeds carry 30,458 rows and 0 numeric cells outside name and country;
the grade is an icon URL. Neither can yield a tonnage by any method.

## Entity resolution

`docs/entity_resolution_audit.md` has the full audit. Precision on a seeded, tonnes-stratified random
sample of 50 matched pairs is 49/50, or 98.0%, with a 95% Wilson interval of 89.5% to 99.6%. Sampling
30 uncovered tickers found no recall misses. Three false positives were found and fixed, including
ENERGY HARBOR CORP mapped to Vistra, which had overstated Vistra's 2022 emissions by 13% because the
coal fleet was explicitly excluded from that acquisition.
