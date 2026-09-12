# master_company: inventory, conflict resolution and column spec

Written before anything is merged. Every count below was produced by running against the real
files on 2026-09-12, not read off a README.

The build target is one row per **listing** (503) with `is_primary_listing` carried, because the
carbon-penalty model reweights a portfolio and a portfolio holds listings. Anything that sums
tonnes or dollars filters `is_primary_listing` first.

The model this table has to feed, in order:

```
cost_usd      = sum over scopes of  tonnes_scope x price_sector_usd_per_t x coverage_scope
abated        = cost after applying the company's OBSERVED annual reduction rate
dEBIT_usd     = abated_cost x (1 - passthrough_sector)
dEV_usd       = dEBIT_usd x the company's own EV/EBITDA multiple
weight        = reweight by dEV/EV, subject to EU 2020/1818 Article 12
```

Five columns are load-bearing and every one of them has a conflict: `scope1_t`,
`delivered_pct_yr`, `ev_ebitda_x`, `ev_musd`, `ebit_musd`. Sections 3 and 4 decide each.

---

## 1. What we hold

61 data tables read end to end: 42 parquet + 6 JSON + 1 CSV in `data/interim`, plus 12 new raw
tables nobody had processed. `sp500_wba_overview.xlsx` is a four-sheet rendering of the WBA-join
CSVs and carries no new quantity.

Provenance classes, as the repo defines them: **mandatory** (a government filing), **voluntary**
(a company said so), **vendor** (a third party scored it; never an input to the headline),
**modelled** (we or someone else computed it).

### 1.1 Universe and identity

| table | rows | grain | key | carries | class |
|---|---|---|---|---|---|
| `universe.parquet` | 503 | listing | `ticker` | CIK, GICS sector/sub-industry, HQ, SEC entity and former names, `is_primary_listing`, `date_added` | mandatory |
| `cik_ticker.parquet` | 10,426 | SEC registrant-ticker | `ticker` | every SEC ticker→CIK, `in_sp500` | mandatory |
| `ticker_aliases.json` | 15 keys, 511 aliases | lookup | — | ticker spellings, 808 normalised name keys, CIK co-filers | mandatory |
| `universe_turnover.json` | 4 windows | — | — | index churn at 1/3/5/10y with departed and joined lists | mandatory |

`universe.parquet` is 503 **listings**. GOOGL/GOOG, FOXA/FOX, NWSA/NWS share a CIK.

### 1.2 Emissions, mandatory

| table | rows | grain | key | carries | class |
|---|---|---|---|---|---|
| `ghgrp_facilities.parquet` | 148,833 | facility-year-parent | `facility_id`,`year` | EPA GHGRP facility CO2e, parent strings, `ownership_frac`, NAICS, lat/lon | mandatory |
| `ghgrp_parent_year.parquet` | 50,906 | parent-year | `parent_name_clean`,`year` | Scope 1 rolled to parent, apportioned and not | mandatory |
| `emissions_by_ticker.parquet` | 8,551 | ticker-year (503 x 17, 2010-2026) | `ticker`,`year` | `scope1_ghgrp_tonnes` (1,739 non-null), `scope1_camd_tonnes` (699), facility counts, `dq`, `match_method` | mandatory |
| `camd_unit_year.parquet` | 74,896 | unit-year, 2010-2026 | `oris_code`,`unit_id`,`year` | Part 75 stack-monitored CO2, heat input, gross load | mandatory |
| `camd_unit_quarter.parquet` | 38,932 | unit-quarter, 2024-2026 | + `quarter` | same at quarterly resolution | mandatory |
| `oris_ghgrp_crosswalk.parquet` | 2,089 | facility | `ghgrp_facility_id` | ORIS ↔ GHGRP, 98.4% of 2025 CAMD CO2 | mandatory |
| `parent_ticker_map.parquet` | 8,778 | parent string x source | `parent_name_clean`,`source` | 7,304 `ghgrp_parent` + 1,474 `camd_owner` strings, 497 carrying a ticker, `match_method`, `unmatched_note` | modelled |
| `unmatched_top_emitters.csv` | 6,867 | parent string | — | what we could not attribute, largest first | modelled |

### 1.3 Emissions, voluntary and modelled

| table | rows | grain | key | carries | class |
|---|---|---|---|---|---|
| `scope23.parquet` | 3,969 (951 with a tonnage) | ticker-fy-scope | `ticker`,`fy`,`scope` | Scope 1/2/3 from PDF reports, 112 tickers, FY2005-2022 median 2019; plus the eGRID HQ grid factor on 3,012 rows that carry no tonnage | voluntary |
| `wba_emissions.parquet` | 3,430 | ticker-fy-scope | `ticker`,`fy`,`scope` | WBA self-reported `1`,`2`,`3`,`1+2`,`1+2+3`; 244 tickers; scope `1` alone only FY2023-24 (235 tickers), `1+2` back to 2018 | voluntary |
| `wba_company.parquet` | 247 | ticker | `ticker` | WBA identity, ISIN/LEI/QID, disclosure level, verification, pathway names, `profile_scope_1/2/3` (235/235/217) | voluntary |
| `wba_targets.parquet` | 988 | ticker-target | `ticker`,`wba_target_id` | scope, horizon, base/target year, reduction %, SBTi classification, 1.5 alignment | voluntary |
| `wba_pathway.parquet` | 20,928 | ticker-year-series | `ticker`,`year`,`series` | `s1x2_spcp`, `s1x2_cpcp`, `s3_spcp`, `s3_cpcp` 2019-2050; 17,158 rows are projections | modelled |
| `wba_sources.parquet` | 6,942 | ticker-source | `ticker`,`wba_source_id` | the document behind each WBA assertion | voluntary |
| `climatetrace_company.parquet` | 1,578 | ticker-year-sector-subsector-country | `ticker`,`year`,`sector`,`subsector`,`iso3_country` | 73 tickers, gross and `equity_share_tonnes_co2e` | modelled |
| `climatetrace_nonus_share.parquet` | 438 | ticker-year | `ticker`,`year` | non-US share, `ct_nonus_share_balanced`, EPA comparison | modelled |
| `reported_vs_measured.parquet` | 187 | ticker-fy-mode | `ticker`,`fy`,`mode` | 96 tickers; **the only place the fossil/biogenic split currently lives**: `meas_all_equity`, `meas_fossil_equity`, `meas_biogenic_equity`, `meas_fossil_ar6`, `biogenic_share`, `lookahead_share` | modelled |

### 1.4 Power sector

| table | rows | grain | key | carries | class |
|---|---|---|---|---|---|
| `eia_plant_generation.parquet` | 399,709 | plant-year-fuel-primemover | `plant_code`,`year` | net generation; three nesting levels, filter `row_level` | mandatory |
| `eia_plant_totals.parquet` | 105,710 | plant-year | `plant_code`,`year` | the intensity denominator | mandatory |
| `egrid_plant.parquet` | 71,475 | plant-year, 2018-2023 | `orispl_code`,`year` | eGRID rates, subregion, CHP flag, fuel mix | mandatory |
| `egrid_subregion.parquet` | 161 | subregion-year | `subregion_code`,`year` | the 27 grid factors, `co2e_rate_g_per_kwh` | mandatory |
| `plant_intensity.parquet` | 114,078 | plant-year | `oris_code`,`year` | `intensity_best_g_per_kwh`, `intensity_basis`, `above_pab_threshold`, three-source reconciliation | modelled |

### 1.5 Financial

| table | rows | grain | key | carries | class |
|---|---|---|---|---|---|
| `financials.parquet` | 5,379 | ticker-fy, 2015-2025 | `ticker`,`fy` | revenue, operating income, net income, assets, equity, capex, R&D, total debt, shares — **each with the XBRL tag and the method it came from** | mandatory |
| `market_cap.parquet` | 503 | ticker | `ticker` | price (all asof 2026-09-11), shares, `market_cap`, `public_float_usd`, `market_cap_company` | mandatory |

FY2024 coverage: revenue 502/503, operating income 502/503 (miss: HONA). Market cap 502/503
(miss: ARES). **No D&A, no EBITDA, no enterprise value, no beta anywhere in the repo.**

### 1.6 Targets, conduct, scenarios, exclusions

| table | rows | grain | key | carries | class |
|---|---|---|---|---|---|
| `targets.parquet` | 1,352 | ticker-target | `ticker`,`source` | one row per target, NZT + SBTi | voluntary |
| `targets_company.parquet` | 503 | ticker | `ticker` | `promised_annual_reduction_pct` (341), SBTi status/classification/years, NZT interim, `promised_basis` | voluntary |
| `say_do_gap.parquet` | 503 | ticker | `ticker` | `delivered_pct_yr` (134, OLS on measured tonnage with `delivered_se`, `delivered_r2`, `n_years`), `promised_pct_yr` (341), `gap_pct_yr` (108), CAMD-only variant (46), intensity variant (126) | modelled |
| `violations.parquet` / `_by_agency` / `_summary` | 12,846 / 6,778 / 503 | ticker-year-offence / ticker-agency / ticker | `ticker` | penalties 2000-2026, environment subtotal split out, 468 measured non-zero | mandatory |
| `violations_aliases.json` | 468 keys | lookup | — | facility name aliases per ticker | modelled |
| `ngfs_scenarios.parquet` | 61,469 | scenario-model-region-variable-year | 5-tuple | 7 scenarios, `Price\|Carbon` plus **`Price\|Carbon\|Demand\|Industry`, `\|Transportation`, `\|Residential and Commercial`, `\|Supply`** — a four-way sector split of the price. Unit is **US$2010/tCO2**, deflate before use | modelled |
| `pab_rules.json` | 24 rules | rule | `rule_id` | EU 2020/1818 encoded with article and source sentence | mandatory |
| `revenue_exclusions.parquet` | 3,018 | listing x 6 rules | `ticker`,`rule_id` | 4 independent screens plus decided `flag_best`, `flag_basis`, `flag_dq` | mixed, tagged per column |

### 1.7 Vendor benchmarks and validation, never inputs

`vendor_scores.parquet` (9,154, ticker-metric-source), `esg_vendor_consensus.parquet` (489),
`vendor_rank_correlation.parquet` (25), `gics_proxy_validation.parquet` (18),
`coverage_summary.parquet` (26), `disclosure_bias.parquet` (500),
`camd_share_verification.json`, `validation_summary.json`. All `vendor` or `modelled`.

### 1.8 Already-built outputs the master table supersedes or consumes

`scores.parquet` (503 x 63, the uncertainty-sampled rank), `portfolio.parquet` (499 x 49, five
weight variants and `evic_usd`), `earnings_at_risk.parquet` (45,773 = ticker x scenario x year).
`earnings_at_risk` is the previous generation of the penalty model: it hard-codes NGFS scenarios
where the new one takes a user-set price per sector. Keep it as the validation check, not the
engine.

---

## 2. The new raw drops

### 2.1 `data/raw/master_dataset.csv` — 503 rows x 66 columns

Keys join perfectly: 503 `Symbol` values, zero duplicates, exact set equality with
`universe.ticker`. No alias work needed.

Full column list, with what we already hold beside it:

| # | column | non-null /503 | verdict |
|---|---|---|---|
| 0-6 | `Symbol`, `name`, `sector`, `sub_industry`, `hq`, `index_since`, `CIK` | 503 | duplicate of `universe.parquet`. Drop. |
| 7-19 | `epa_s1_2011` … `epa_s1_2023` | 105-121 | **reject**, see 3.2 |
| 20-21 | `epa_s1_years_reported`, `epa_reports` | 503 | derived from the rejected series. Drop. |
| 22-36 | `sec_revenue_{2022,23,24}`, `sec_ebit_*`, `sec_dep_amort_*`, `sec_capex_*`, `sec_ebitda_*` | 467-471 / 388-393 / 354-360 / 336-348 / 279-286 | revenue, EBIT, capex **reject** (3.4). **`sec_dep_amort_*` accept — it is the only D&A in the project.** `sec_ebitda_*` reject, rebuild it. |
| 37 | `yh_market_cap` | 502 | accept as cross-check and as the override on 4 names (3.5) |
| 38 | `yh_enterprise_value` | 500 | **accept, new** |
| 39 | `yh_revenue_ttm` | 502 | cross-check only; SEC revenue wins |
| 40 | `yh_ebitda_ttm` | 472 | **accept as fallback**, second after SEC-built EBITDA |
| 41 | `yh_op_margin` | 502 | derived. Drop. |
| 42-43 | `yh_total_debt`, `yh_total_cash` | 501, 501 | **accept**; cash is new, debt fills our 40 SEC gaps |
| 44 | `yh_fcf` | 470 | **accept, new**, not used by the chain |
| 45 | `yh_beta` | 497 | **accept, new**; needed if the reweight is risk-adjusted |
| 46 | `yh_ev_ebitda` | 471 | **accept, load-bearing**, with the guards in 3.6 |
| 47-52 | `sbti_near_term_status`, `_classification`, `_target_year`, `sbti_net_zero_status`, `_year`, `sbti_ordinal` | 252, 215, 215, 106, 68, 503 | reject, ours dominates (3.7) |
| 53-65 | `calc_*` (13 columns) | 68-502 | every one is computed from a rejected input. Drop all. |

**`yh_enterprise_value` and `yh_ev_ebitda` checked, not assumed.** `yh_ev_ebitda` reproduces
`yh_enterprise_value / yh_ebitda_ttm` to within 2% on **471 of 471** rows, so it is a true
quotient and not a second vendor opinion. `yh_enterprise_value` reproduces
`mcap + debt - cash` to within 2% on 401 of 499 and within 10% on 472 of 499; the residual is
minority interest and preferred, which is correct behaviour. Distribution of `yh_ev_ebitda`:
median 14.80, p05 6.85, p95 39.24, min -67.39, max 1942.08. **Three are negative** (BRK.B
-1.79, BA -67.39, MRNA -24.43, all from a negative or odd EBITDA) and **11 exceed 60x**
(CRWD 1942, DDOG 913, AXON 243, PLTR 148, PANW 145, TSLA 132, LITE 103, AMD 87, MRVL 73,
COIN 63, GEV 63). **32 are missing, 31 of them Financials**, because Yahoo publishes no EBITDA
for banks. Sector medians are sane and ordered as you would expect: Energy 8.96, Materials 11.29,
Financials 11.85, Consumer Staples 12.59, Communication Services 12.95, Utilities 13.11,
Consumer Discretionary 13.35, Health Care 14.10, Industrials 16.82, Real Estate 18.83, IT 22.90.
Section 3.6 says what to do about the tails.

### 2.2 `data/raw/wba_join/` — their crosswalk beats ours, take it

Unzipped to `data/raw/wba_join/WBA join SP500/`. 10 CSVs plus a 4-sheet xlsx rendering.

| file | rows | what it adds |
|---|---|---|
| `sp500_wba_crosswalk.csv` | 503 | ticker → WBA company id, 250 matched |
| `sp500_wikidata_identifiers.csv` | 503 | ticker → Wikipedia title and Wikidata QID for every constituent |
| `wba_wikidata_cik.csv` | 467 | WBA QID → CIK, the bridge that makes the match work |
| `sp500_wba_aggregate.csv` | 672 | 100 pre-aggregated WBA fields per ticker |
| `sp500_not_in_wba.csv` | 253 | the misses, named |
| `sp500_wba_gap_source_coverage.csv` | 253 | for each miss, which of 8 other climate sources has it, with match method |
| `sp500_wba_gap_source_summary.csv` | 13 | the same rolled up |
| `sp500_wba_sector_coverage.csv` | 12 | WBA match rate per GICS sector |
| `wba_attribute_coverage.csv` | 30 | the 30 WBA footprint attributes with year ranges |
| `wba_table_profile.csv` | 6 | grain and caveat for each raw WBA table |

**Their crosswalk is better and there is nothing to resolve.** Theirs matches 250 tickers, ours
(`src/fetch_wba.py` → `wba_company.parquet`) matches 247, **ours is a strict subset of theirs,
and on the 247 in common the `wba_company_id` agrees on every single one — zero conflicts.**
Theirs adds BG, EQT and GOOG. GOOG is the secondary listing of Alphabet so it is not a new
company, leaving **two real gains, BG and EQT**, both of which we want because both are high
emitters.

The reason theirs is better is the method, not luck. Ours matches on ISIN (233), name (10), LEI
(4). Theirs goes CIK → Wikidata QID → WBA QID for 231 of its 250, then QID direct for 13,
normalised name for 5 and website domain for 1. Routing through a stable identity beats routing
through a security identifier, because ISIN is per-security and a company with several listings
or a changed ISIN drops out.

Action: replace our match key with `sp500_wba_crosswalk.csv`, keep our
`wba_emissions/targets/pathway/sources` extractions unchanged, and re-run the ticker attach.
Expected gain 247 → 250 rows, 249 unique companies.

`sp500_wba_gap_source_coverage.csv` is worth keeping for the honesty slide: of the 253 without a
WBA profile, 184 are in Net Zero Tracker, 148 in TPI management quality, 122 in SBTi, 122 in the
Open Sustainability Index, 34 have an EPA GHGRP parent and 21 are queryable in Climate TRACE.

### 2.3 `git show origin/main:data/ghgrp_matches.csv` — 143 rows, confirmed

143 parent strings over 127 tickers, one column of tonnage, `tCO2e_2023_attributed`, summing to
1,118.1 MMT.

**Every claim in the brief is confirmed.** Against our `parent_ticker_map` + GHGRP roll-up:
**122 tickers in common, 84 identical to within 0.1%**, 92 within 1%, 102 within 5%. They have
5 tickers we do not (ARES, BLK, BX, GS, NXP); we have 6 they do not (AMCR, BG, CRH, NXPI, UAL,
WAB). NXP/NXPI is a ticker-spelling miss on their side, not a real difference.

**The asset-manager misattribution is real and is the whole of their exclusive set.**

| ticker | their parent string | tonnes | ours |
|---|---|---|---|
| ARES | ARES MANAGEMENT CORP | 1,454,174 | not attributed |
| BLK | BLACKROCK INC | 187,750 | not attributed |
| BX | BLACKSTONE GSO HOLDINGS LLC | 59,809 | not attributed |
| GS | THE GOLDMAN SACHS GROUP INC | 15,642 | not attributed |

These are portfolio holdings, not operated assets. A private-equity fund named as a GHGRP parent
holds the facility as an investment; booking its stack emissions as the manager's Scope 1 is a
category error, and it is the same error twice because the operating company is usually also in
the GHGRP file. Three of the four (ARES, BLK, GS) propagate into `master_dataset.csv`. Our
blocklist already excludes them. **Keep the blocklist.**

One further finding the brief did not ask for: **their two artifacts contradict each other.**
`ghgrp_matches.csv` is a materially better extraction than the `epa_s1_*` columns in
`master_dataset.csv` built by the same teammate. Comparing the two on 116 shared tickers, only
72 agree to 0.1% and 24 differ by more than 5%, with `master_dataset` low by 99.97% on PEG,
99.2% on DVN, 94.2% on EOG and 87.5% on COP. Whatever built the wide columns lost most of the
facilities. Neither file should be used; section 3.2 says what to use instead.

---

## 3. Conflict resolution

Every rule below is stated as **take X, because Y**, with the measurement that decided it.

### 3.1 Scope 1: EPA GHGRP vs WBA self-report vs Climate TRACE

The three sources measure different boundaries, so "best" is not a single answer, and pretending
it is would be the silent merge we were told to avoid. The boundaries:

- EPA GHGRP: **US facilities emitting over 25,000 tCO2e**, measured or mass-balance, mandatory,
  latest year 2023.
- WBA / company self-report: **global, whole entity**, voluntary, latest year 2024.
- Climate TRACE: **modelled asset inventory**, global, latest year 2026, no corporate boundary.

Measured, not asserted: on the **89 primary listings that carry both** a GHGRP 2023 fossil figure
and a WBA self-reported Scope 1, the ratio GHGRP-US / WBA-global has **median 0.642**, p25 0.365,
p75 0.934. The US regulated slice is roughly two thirds of a global self-report at the median,
which is what a US-heavy index should look like and is a sanity check on both.

**The rule. Carry three columns, not one, and make the model read the one that fits the question.**

```
scope1_measured_us_t     GHGRP fossil-only, equity-apportioned, latest year     mandatory
scope1_selfreported_t    WBA preferred, else PDF report, latest fy              voluntary
scope1_modelled_t        Climate TRACE equity share, latest year                modelled
scope1_t                 the decided headline
scope1_basis             which of the three produced scope1_t
scope1_dq                PCAF 1-5
```

`scope1_t` precedence, in order, first hit wins:

1. **`scope1_selfreported_t` where it exists and is at least `scope1_measured_us_t`** (285 of 500
   primary listings). A global self-report is the right perimeter for a carbon penalty applied to
   a global company, it is newer (median FY2024 against GHGRP's 2023), and where it is larger
   than the US measured figure it is consistent with the measured floor. `dq` 2.
2. **`scope1_measured_us_t`** where no self-report exists, or where the self-report is smaller
   than the US measured figure. The second half matters: 9 of the 89 overlapping companies report
   a global number **below** their own US regulated total, which is not possible on boundary
   alone. In those cases the mandatory measurement wins and the row is flagged. `dq` 1 or 2.
3. **`scope1_modelled_t`** only where neither exists (1 listing). `dq` 4.
4. Null, counted, never zero-filled (181 of 500).

The floor rule is the defensible part and the one to say out loud: **a self-report is only
accepted where it clears the mandatory measurement.** Companies do not get to report below what
EPA measured on their own US sites.

Resulting coverage, primary listings out of 500, measured by running it:

| source | listings |
|---|---|
| GHGRP fossil 2023 > 0 | 128 |
| CAMD 2025 > 0 | 40 |
| WBA or report self-declared Scope 1 | 285 |
| Climate TRACE equity | 73 |
| **any Scope 1 at all** | **319** |
| none | 181 |
| mandatory available | 128 |
| voluntary only, no mandatory | 190 |
| modelled only | 1 |

**This supersedes the number in `data/README.md`.** That README says 228 listings carry an
emissions number and 273 carry none. The WBA extraction landed at 17:05 today and takes voluntary
Scope 1 from 112 tickers to 285. The correct headline is now **319 of 500 primary listings carry
a Scope 1 figure, 181 do not**, and the sector split is Utilities 31/31, Materials 24/25,
Energy 19/21, Consumer Staples 30/34, IT 48/73, Financials 48/76, Industrials 38/83,
Health Care 22/59, Real Estate 13/30, Communication Services 9/21, Consumer Discretionary 37/47.
Every doc that quotes 228 needs the correction.

### 3.2 Our EPA Scope 1 vs their `epa_s1_*`: biogenic. They are right, we are wrong.

This one is settled by evidence, not judgement.

`emissions_by_ticker.scope1_ghgrp_tonnes` is **EPA's published CO2e including gas_id 8, biogenic
CO2 from biomass combustion**. The GHG Protocol excludes biogenic CO2 from Scope 1 and requires
it reported separately. So our headline Scope 1 is wrong for any company that burns biomass.

Proof, not assertion. `reported_vs_measured.parquet` already splits the gases, and their
`ghgrp_matches.csv` value divided by our `meas_fossil_equity` is:

| ticker | sector | our all-gas | our fossil-only | their value | theirs / our fossil |
|---|---|---|---|---|---|
| WY | Real Estate | 223,262 | 41,145 | 41,145 | 1.000012 |
| PKG | Materials | 7,874,692 | 1,498,344 | 1,498,344 | 1.000000 |
| IP | Materials | 27,957,300 | 5,486,685 | 5,404,388 | 0.985 |
| SW | Materials | 20,400,700 | 5,923,602 | 5,842,031 | 0.986 |
| WM | Industrials | 12,926,360 | 11,650,460 | 11,650,460 | 1.000000 |

Biogenic share for those five is 81.6%, 81.0%, 80.4%, 71.0% and 9.9%. **Our paper and packaging
numbers are 5x too large.** Nationally the biogenic share is 4.4% of the 2023 GHGRP direct total
(118.7 MMT of 2,697.0 MMT), so it is small in aggregate and decisive per company.

**The rule: Scope 1 is fossil-only. `co2e_fossil = co2e_total - co2e_gas_id_8`, apportioned by
`ownership_frac`. Carry biogenic in its own column, never in the headline.**

**But do not take their numbers.** The teammate got the boundary right and the entity resolution
wrong. `master_dataset.csv`'s wide columns agree with our fossil-only series on only 66 of 114
shared tickers and are low by more than 50% on 11, including PEG at 0.03% of the true figure,
DVN 0.8%, EOG 6.1%, COP 9.8%, PCG 10.4%, HWM 16.5%, ATO 17.7%, APA 21.4%, OKE 29.2%. Their
`ghgrp_matches.csv` is better but still misses 6 tickers we have and adds 4 asset managers.

**Build it ourselves.** `src/compare_reported_measured.py` already contains
`load_facility_gas()` and `build_measured()`, which produce exactly this, reconcile to
`emissions_by_ticker` to **0.000000 tonnes over 1,857 ticker-years**, and cover **146 tickers x
2010-2023, 1,857 rows**. They are simply not persisted. Persist them as
`data/interim/ghgrp_ticker_year.parquet` and read `master_company` off that.

2023 totals over the 128 non-zero tickers: all-gas 1,208.5 MMT, **fossil-only 1,161.9 MMT**,
biogenic 46.7 MMT.

**A second correction the same rebuild has to make: the Calpine lookahead.** Our parent map
attributes `CPN MANAGEMENT LP` to CEG, which puts **47.7 MMT of Calpine's 2023 fleet into
Constellation's 2023 Scope 1 — 84.2% of CEG's total — when Constellation only agreed to buy
Calpine in January 2025.** Same error class as the ENERGY HARBOR / Vistra one already fixed in
`docs/entity_resolution_audit.md`. `PERIMETER_CHANGES` in `compare_reported_measured.py` names
all of them and `meas_fossil_lookahead` measures them: CEG 84.2% of its total, SW 98.6%,
EXE 58.3%, IP 1.5%. `master_dataset.csv` gets CEG right (8.94 MMT, exactly our fossil figure
minus the lookahead) purely because its weak matcher missed the string.

**The rule: `scope1_measured_us_t` is fossil-only, equity-apportioned, and net of
`PERIMETER_CHANGES` for the year in question.** Carry `scope1_lookahead_excluded_t` so the
correction is visible rather than silent. This moves CEG from 56.6 to 8.9 MMT and SW from 5.92
to 0.08 MMT, and it is the single largest number in our whole emissions table.

Also carry `scope1_ar6_t`. EPA publishes on AR4 GWPs; restating CH4 and N2O to AR6 lifts landfill
and gas-distribution names by up to 19% (RSG +19.2%, ES +19.2%, PEG +19.1%, WM +18.9%,
EXC +18.8%, ATO +16.0%). That is a band on the answer, not a correction to apply silently.

### 3.3 GHGRP 2023 vs CAMD 2025: the currency problem

GHGRP has no 2024 or 2025 data; reporting year 2025 is due 30 October 2026. CAMD is the only
current feed and covers 40 primary listings with a 2025 tonnage.

**The rule: `scope1_t` uses the GHGRP fossil year (2023) as the level, and carries
`scope1_year`. CAMD never replaces the level, because its boundary is combustion units in the
Acid Rain / CSAPR programmes, not the company.** CAMD is used for two things only: the
`delivered_camd_pct_yr` trend, which extends the observed reduction rate to 2025 for 46 tickers,
and as the 2024/2025 currency check in `scope1_current_signal_t`. Mixing a CAMD level into a
GHGRP series would put a boundary break in the middle of a trend line.

### 3.4 Operating income and revenue: ours, decisively

| quantity | ours | theirs `sec_*` | Yahoo | winner |
|---|---|---|---|---|
| revenue FY2023 | 502 | 470 | 502 (`yh_revenue_ttm`, TTM not FY) | **ours** |
| operating income FY2023 | 502 | 393 | — | **ours** |
| D&A FY2023 | **0** | 360 | — | **theirs** |
| capex FY2023 | 4,973 rows over 2015-2025 | 338 | — | **ours** |
| EBITDA | 0 | 286 | 472 (`yh_ebitda_ttm`) | **rebuild** |

Coverage is not the main argument; the tag is. On FY2023 revenue, 393 of 470 shared rows agree to
within 1% and **36 differ by more than 25%**. All 36 are cases where their extractor took a
narrow XBRL tag and ours took the right one, and 22 of the 36 are Financials or Real Estate:

| ticker | ours | theirs | our tag |
|---|---|---|---|
| CPT | 1,542,027,000 | 3,451,000 | `OperatingLeaseLeaseIncome` |
| UDR | 1,627,501,000 | 6,843,000 | `Revenues` |
| MET | 66,905,000,000 | 2,229,000,000 | `Revenues` |
| MTB | 10,224,000,000 | 1,484,000,000 | `InterestAndDividendIncomeOperating` |
| COF | 36,787,000,000 | 5,645,000,000 | `Revenues` |

A REIT books rent as lease income and a bank books interest as interest income; neither appears
in `RevenueFromContractWithCustomerExcludingAssessedTax`. Their column is the contract-revenue
crumb. `financials.parquet` carries `revenue_tag` and `revenue_method` on every row, which is
how this was diagnosed in two minutes; keep that habit.

Operating income differs by more than 25% on 10 of 393 shared rows with 2 sign flips, and the
worst are fiscal-year label mismatches — WDC's FY2023 ends 2023-06-30, so their calendar-2023
figure is a different period. Ours carries `period_end`; theirs does not.

**The rules:**

- `revenue_musd`, `ebit_musd`, `capex_musd`, `total_debt_musd` come from `financials.parquet`,
  latest fiscal year with the field present, carrying `fy` and `period_end`. Never their `sec_*`.
- `da_musd` comes from **their `sec_dep_amort_{fy}`**, the only D&A in the project, 354 of 503 at
  FY2024. It is `vendor`-grade provenance in the sense that we did not extract it, so it is
  labelled `sec_secondhand` in `da_basis` and it never feeds the score — only the EBITDA
  denominator.
- `ebitda_musd` is built, not taken:
  1. `ebit_musd + da_musd` where both exist (354). Reproduces their `sec_ebitda_2024` to within
     1% on 263 of 286, and their own EBITDA equals their EBIT + their D&A on 286 of 286, so the
     only difference is our better EBIT.
  2. else `yh_ebitda_ttm` (472 alone; union of the two is **492 of 503**), basis `yahoo_ttm`.
  3. else null.
- `yh_revenue_ttm` is kept only as `revenue_ttm_musd_check`. TTM and fiscal year are different
  periods and must not be silently mixed.

### 3.5 Market cap: ours, with four named overrides

Ours is SEC XBRL shares x observed price, every price `asof 2026-09-11`. Theirs is Yahoo's
figure. On 501 shared rows the ratio ours/Yahoo has median **1.0000**, p05 0.973, p95 1.031;
437 agree within 2%, 476 within 5%, 489 within 10%. **Four are off by more than 25%** and all
four are the same structural thing:

| ticker | ours | Yahoo | ratio | why |
|---|---|---|---|---|
| IBKR | 40.6bn | 155.7bn | 0.26 | Up-C. The 10-K cover page counts only the public Class A float |
| ERIE | 6.1bn | 12.8bn | 0.48 | Class A / Class B split, cover page counts one class |
| VMRK | 24.6bn | 50.7bn | 0.48 | recent spin, partial cover-page count |
| BX | 96.5bn | 153.6bn | 0.63 | Up-C, common units held outside the registrant |

**The rule: `market_cap_musd` is ours. Where `abs(ours/yh - 1) > 0.25`, take `yh_market_cap` and
set `market_cap_basis = 'yahoo_override_upc'`.** Four rows. The failure mode is understating a
holding's weight by 4x in a $1bn allocation, which is worse than the vendor-provenance cost of
the override. The other 12 rows between 10% and 25% are share-count asof drift (our `shares_asof`
ranges from 2025-03-31 to 2026-07-31 because it is the latest cover page) and are left alone,
flagged by `market_cap_shares_stale` where `shares_asof < 2026-01-01`.

ARES has no market cap from us; Yahoo supplies it.

### 3.6 Enterprise value and the EV/EBITDA multiple: theirs, guarded

We have no EV. `portfolio.evic_usd` is market cap + total debt, which is EVIC as PAB Article 5
defines it — **deliberately gross of cash** — and is the right denominator for a financed-emissions
intensity. It is the wrong denominator for a valuation impact. Median `evic_usd /
yh_enterprise_value` is 1.007 and 461 of 496 agree within 25%, so they are close, but the
difference is exactly the cash the model should not ignore (median cash/EV 2.8%).

**The rules:**

- `evic_musd` stays ours, PAB-defined, for the intensity and exclusion legs.
- `ev_musd` = `yh_enterprise_value`, 500 of 503, for the valuation leg. Basis `yahoo`.
- `ev_ebitda_x` = `yh_ev_ebitda`, **winsorised and floored**, because dEV = dEBIT x multiple and a
  negative or 1942x multiple destroys the answer:
  1. Reject the multiple where `yh_ebitda_ttm <= 0` (3 rows: BRK.B, BA, MRNA).
  2. Winsorise to the sector-specific 5th and 95th percentile, then clamp globally to [4, 40].
     That moves 11 rows down (CRWD 1942→40, DDOG 913→40, AXON 243→40, PLTR, PANW, TSLA, LITE,
     AMD, MRVL, COIN, GEV) and a handful up.
  3. Where the multiple is missing or rejected (35 rows, 31 of them Financials because Yahoo
     publishes no bank EBITDA), fall back to the **GICS sector median**: Energy 8.96,
     Materials 11.29, Financials 11.85, Consumer Staples 12.59, Communication Services 12.95,
     Utilities 13.11, Consumer Discretionary 13.35, Health Care 14.10, Industrials 16.82,
     Real Estate 18.83, Information Technology 22.90.
  4. Carry `ev_ebitda_basis` in {`yahoo`, `yahoo_winsorised`, `sector_median`} and
     `ev_ebitda_dq` in {2, 3, 4}.

Financials are where this matters least and is most visible: a bank has almost no Scope 1, so a
sector-median multiple on a near-zero cost moves nothing, and saying so on the slide is better
than hiding a null.

### 3.7 Targets: ours for SBTi, WBA for the target text, ours for the promised rate

Where both speak, they agree exactly. Our `targets_company.sbti_near_term_status` matches their
`master_dataset.sbti_near_term_status` on **239 of 239** shared rows — perfect agreement across
"Targets set" (208), "Commitment removed" (24) and "Committed" (7) — and the temperature
classification agrees on 208 of 208. Both pull the same SBTi export.

Coverage is where they differ, and ours wins: **261 vs 252 on near-term status, 118 vs 106 on
net zero**. We have 22 they lack (ABT, BG, CRM, CTSH, CTVA, DD, DPZ, FDS, HLT, J, LOW, LULU,
LYB, MRK, NWS, NWSA, PSKY, SW, TAP, TTWO, VMRK, WTW) and they have 13 we lack (ARES, DVN, EG,
HCA, HON, INTC, MAS, MU, NUE, SMCI, SWKS, VLO, VRT). Their year column is also dirty — it
contains fiscal-year strings like `FY2030`, `FY2027` mixed with plain years, and one real
disagreement (WM 2031 ours, 2030 theirs).

**The rules:**

- SBTi status, classification and years: `targets_company.parquet`. Backfill the 13 they have and
  we do not by re-running `fetch_targets.py` against the current SBTi export rather than copying
  a CSV; if that cannot be done in time, take their 13 with
  `sbti_basis = 'master_dataset_backfill'` and parse `FY2030` before casting.
- `promised_pct_yr`: ours, 341 of 503, from `say_do_gap.parquet`, with `promised_source` in
  {`sbti_s12_absolute` 208, `nzt_interim` 91, `netzero_inferred` 34, `sbti_combined` 8}. WBA has
  170; on the 153 both cover the **median difference is exactly 0.000 pp** and 110 of 153 agree
  within 0.5pp, so the two are the same underlying targets read twice. Ours covers 188 WBA does
  not; WBA covers 17 we do not. Take ours, backfill the 17 from WBA with
  `promised_source = 'wba'`. Expected 358 of 503.
- `wba_targets.parquet` stays as the per-target detail with the target wording, and is what the
  UI shows when a user clicks a company.

### 3.8 Voluntary Scope 1/2/3: WBA first, PDF reports second, no averaging

`wba_emissions` and `scope23` never cover the same fiscal year for Scope 1 alone: WBA's scope
`1` series exists only for FY2023-24 and `scope23` ends at FY2022 (median FY2019). On the 59
tickers in both, WBA's year is newer in **all 59**. There is nothing to average and nothing to
reconcile.

**The rule: latest fiscal year wins, source recorded.** WBA preferred rows (`preferred == True`,
3,014 of 3,430) first, `scope23` second. Union coverage, primary listings of 500:
**Scope 1 285, Scope 2 281, Scope 3 256** — against 112, 111 and 74 from `scope23` alone. This
is the largest single coverage gain available to the project and it is already extracted.

For a multi-year voluntary trend use WBA's `1+2` series (1,319 rows back to 2018), not scope `1`,
which only exists for two years. Label it `scope12` and never let it into a Scope-1-only column.

### 3.9 Precedence summary, one table

| quantity | winner | runner-up | fallback | rejected outright |
|---|---|---|---|---|
| Scope 1 headline | self-report ≥ measured floor | GHGRP fossil equity | Climate TRACE equity | our all-gas figure, their `epa_s1_*`, their `ghgrp_matches` asset-manager rows |
| Scope 1 measured | rebuilt fossil-only, ex-perimeter-change | — | — | `emissions_by_ticker.scope1_ghgrp_tonnes` as a headline |
| Scope 1 current signal | CAMD 2025 | — | — | CAMD as a level |
| Scope 2, Scope 3 | WBA latest fy | `scope23` | — | — |
| delivered rate | `say_do_gap.delivered_pct_yr` (OLS on measured) | `delivered_camd_pct_yr` | — | any promised rate |
| revenue, EBIT, capex, debt | `financials.parquet` | — | `yh_total_debt` for debt only | their `sec_revenue/ebit/capex` |
| D&A | their `sec_dep_amort_*` | — | — | — |
| EBITDA | our EBIT + their D&A | `yh_ebitda_ttm` | — | their `sec_ebitda_*` |
| market cap | ours | `yh_market_cap` on 4 up-C names | — | — |
| EVIC | ours (PAB, gross of cash) | — | — | — |
| EV | `yh_enterprise_value` | — | — | — |
| EV/EBITDA | `yh_ev_ebitda` winsorised | sector median | — | raw negatives and >60x |
| SBTi status | `targets_company` | their `sbti_*` for 13 backfills | — | their unparsed `FY2030` years |
| promised rate | `targets_company` | WBA for 17 backfills | — | — |
| WBA identity | their `sp500_wba_crosswalk.csv` | ours | — | — |
| carbon price | user input | NGFS `Price\|Carbon\|Demand\|*` by sector | NGFS `Price\|Carbon` World | — |
| passthrough | user input | sector default, modelled | — | — |
| exclusions | `revenue_exclusions.flag_best` | — | — | vendor tobacco screen |

---

## 4. `master_company` column list

One row per listing, **503 rows**. Every numeric column carries its unit in the name. Columns
marked **triple** get the `_basis` and `_dq` companions described under the group.

### 4.1 Identity — 10 columns, mandatory

```
ticker                        str   PK, uppercase, dots not dashes
company_name                  str
cik                           str
gics_sector                   str
gics_sub_industry             str
nace_section                  str   from portfolio.parquet, for the PAB high-impact test
is_primary_listing            bool  filter this before any sum
share_class_siblings          str   the other listing, where one exists
hq_country_iso                str
date_added                    date
```

### 4.2 Emissions — 22 columns

```
scope1_t                      float  the decided headline, fossil-only        TRIPLE
scope1_year                   int    fiscal or reporting year of scope1_t
scope1_measured_us_t          float  GHGRP fossil equity, ex-perimeter-change  mandatory
scope1_measured_us_year       int
scope1_measured_allgas_t      float  including biogenic, for reconciliation only
scope1_biogenic_t             float  reported separately per GHG Protocol
scope1_ar6_t                  float  CH4/N2O restated to AR6, as a band
scope1_lookahead_excluded_t   float  tonnes removed for a perimeter change
scope1_selfreported_t         float  WBA preferred, else PDF report            voluntary
scope1_selfreported_year      int
scope1_modelled_t             float  Climate TRACE equity share               modelled
scope1_current_signal_t       float  CAMD 2025, currency check only           mandatory
scope1_facility_count         int
scope2_market_t               float                                           TRIPLE, voluntary
scope2_location_t             float                                           voluntary
scope2_year                   int
scope3_total_t                float                                           TRIPLE, voluntary
scope3_year                   int
scope12_t                     float  WBA combined series, for the trend only  voluntary
grid_factor_hq_g_per_kwh      float  eGRID subregion factor for the HQ region mandatory
power_intensity_g_per_kwh     float  36 listings, the Article 12(1)(g) test   modelled
power_gen_mwh                 float
```

`scope1_t`, `scope2_market_t`, `scope3_total_t` each get `_basis` (which source) and `_dq`
(PCAF 1-5). Nothing is zero-filled; a null is a null and is counted.

### 4.3 Trajectory — 10 columns, modelled

```
delivered_pct_yr              float  OBSERVED annual reduction, OLS on measured tonnage  TRIPLE
delivered_se_pct_yr           float  bootstrap standard error
delivered_r2                  float
delivered_n_years             int
delivered_year_start          int
delivered_year_end            int
delivered_camd_pct_yr         float  the 2024-25 extension, 46 listings
promised_pct_yr               float  what they said they would do                        TRIPLE
promised_target_year          int
gap_pct_yr                    float  promised minus delivered, 108 listings
```

`delivered_pct_yr` is the abatement input to the model and **is never the promised rate**. 134
listings carry it. `delivered_basis` says `ghgrp_fossil`, `camd` or `wba_s12`;
`promised_basis` says `sbti_s12_absolute`, `nzt_interim`, `netzero_inferred`, `sbti_combined`
or `wba`.

### 4.4 Financial — 16 columns

```
revenue_musd                  float  SEC XBRL, latest fy                       TRIPLE, mandatory
revenue_fy                    int
revenue_period_end            date
ebit_musd                     float  SEC XBRL operating income                 TRIPLE, mandatory
da_musd                       float  from master_dataset sec_dep_amort         basis sec_secondhand
ebitda_musd                   float  ebit + da, else yh_ebitda_ttm             TRIPLE
capex_musd                    float  SEC XBRL                                  mandatory
total_debt_musd               float  SEC XBRL, else yh_total_debt              TRIPLE
total_cash_musd               float  yh_total_cash                             vendor
market_cap_musd               float  ours, 4 Yahoo overrides                   TRIPLE
evic_musd                     float  market cap + debt, PAB Article 5, gross of cash
ev_musd                       float  yh_enterprise_value                       vendor
ev_ebitda_x                   float  winsorised, sector-median fallback        TRIPLE
fcf_musd                      float  yh_fcf                                    vendor
beta_x                        float  yh_beta                                   vendor
index_weight_pct              float  free-float market cap share
```

### 4.5 Penalty model, computed — 12 columns, modelled

These are what the UI recomputes on every slider move. They are stored at the default settings so
the page renders before the first interaction.

```
price_sector_usd_per_t        float  the user's input, default from NGFS by sector
coverage_scope1_pct           float  share of Scope 1 the penalty touches, default 100
coverage_scope2_pct           float  default 100
coverage_scope3_pct           float  default 0
passthrough_pct               float  sector default, settable                  modelled
carbon_cost_musd              float  before abatement
carbon_cost_abated_musd       float  after delivered_pct_yr to the horizon
d_ebit_musd                   float  abated cost x (1 - passthrough)
d_ebit_pct_of_ebit            float  earnings at risk
d_ev_musd                     float  d_ebit x ev_ebitda_x
d_ev_pct_of_ev                float  value at risk, the reweighting input
model_dq                      int    worst dq among the inputs that fed it
```

`passthrough_pct` has **no empirical source in this repo**. It is a modelled assumption with a
sector default and it must be labelled as one everywhere it appears. Do not dress it as data.

### 4.6 Constraints and conduct — 10 columns

```
excluded                      bool   any Article 12 rule fires
excl_articles                 str    which ones
excl_basis                    str    from revenue_exclusions.flag_basis
excl_dq                       int
excl_12g                      bool   the 100 gCO2e/kWh power test
high_impact_nace              bool   PAB high-impact sector
penalty_usd_environment       int    Violation Tracker, 468 measured non-zero  mandatory
case_count_environment        int
penalty_usd_total             int
conduct_measured_zero         bool   checked and found clean, not missing
```

### 4.7 Benchmark and provenance — 8 columns, never inputs

```
vendor_percentile             float  esg_vendor_consensus, provenance_class vendor
vendor_n_sources              int
our_percentile                float  scores.parquet rank_median
rank_p05                      float
rank_p95                      float
coverage_tier                 str
provenance_class              str    the worst class among the columns that fed the row
generated_at                  timestamp
```

**Total: 88 columns.** 11 get the value/basis/dq triple: `scope1_t`, `scope2_market_t`,
`scope3_total_t`, `delivered_pct_yr`, `promised_pct_yr`, `revenue_musd`, `ebit_musd`,
`ebitda_musd`, `total_debt_musd`, `market_cap_musd`, `ev_ebitda_x`. Those eleven are every
quantity where two sources disagreed, which is the point of the triple.

---

## 5. Grain warnings for whoever builds this

1. **503 listings, not 500 companies.** GOOGL/GOOG, FOXA/FOX, NWSA/NWS share a CIK and share
   financials. Filter `is_primary_listing` before summing tonnes, revenue or portfolio weight, or
   Alphabet counts twice. `scores.parquet` mirrors 3 rows (`mirrored_from`); `portfolio.parquet`
   has 499 rows, not 503.
2. **`emissions_by_ticker` is a complete 503 x 17 grid with nulls, not a list of hits.** 8,551
   rows, only 1,739 carrying a GHGRP tonnage and 699 a CAMD one. Absence is recorded on purpose.
   A `len()` on it is not a coverage number.
3. **`scope23.parquet` has 3,969 rows and 951 tonnages.** 3,018 rows are the eGRID HQ grid factor
   with no tonnage. `tonnes_co2e.notna()` before counting anything.
4. **`wba_emissions.scope` values are `1`, `2`, `3`, `1+2`, `1+2+3`, not `scope1`.** A
   `startswith('scope')` filter silently returns zero rows and every downstream count reads as
   nothing-is-covered. This cost fifteen minutes during this inventory. Filter `preferred == True`
   as well or you get 3,430 rows where you wanted 3,014.
5. **`ghgrp_facilities` is facility-year-**parent**, so a facility with two named parents appears
   twice.** Drop duplicates on `(facility_id, year, ticker)` before an unapportioned sum, and
   normalise `ownership_frac` where the per-facility sum exceeds 1.01 — EPA sometimes lists one
   parent twice, each at a full share.
6. **`sector_type == 'E'` or the GHGRP total is three times US emissions.** The feed mixes direct
   emitters with fuel suppliers. 2023 direct is 2,697.0 MMT; unfiltered it is 7,364 MMT.
7. **NGFS carbon price is in US$2010/tCO2.** Deflate before putting a dollar on a slider or the
   whole model is 30% low. It is also per **tCO2**, not tCO2e.
8. **`ngfs_scenarios` has 61,469 rows over 5 key columns** and several models per scenario.
   Averaging across models silently blends GCAM's 2030 US price of 98.6 with REMIND's 314.3.
   Pick one model, name it, or show the range.
9. **`financials.parquet` is ticker-fy with up to 11 rows per ticker.** Take the latest fy that
   has the field, per field, not the latest row. FY2025 has 503 rows but many fields are still
   empty.
10. **Fiscal years are not calendar years.** 119 of 502 FY2023 rows have a `period_end` outside
    December. This is what broke the teammate's operating-income comparison on WDC, STX and DLTR.
    Join on `fy` and carry `period_end`.
11. **In pandas 3 a missing value in a string column is truthy.** Assigning a list of str-or-None
    gives a string dtype where a miss is `pd.NA`, and `if row['col']` accepts every row. Keep
    per-row lookups as plain dicts or test with `pd.notna()`. This has bitten this repo twice.
12. **Never join on a vendor ticker column.** `mrbossjaysrb`'s AMZN row is Meezan Bank. Join on
    the crosswalks in `ticker_aliases.json` and `sp500_wba_crosswalk.csv`.
13. **`market_cap.shares_asof` spans 2025-03-31 to 2026-07-31** because it is the latest SEC cover
    page. Prices are all 2026-09-11. That mismatch is the 10-25% market-cap band, and it is not a
    bug to fix, it is a staleness to flag.
14. **`climatetrace_company` gross double counts joint ventures.** Use
    `equity_share_tonnes_co2e`: gross sums to 2,379 MMT against 1,508 MMT on equity over the same
    73 tickers.
15. **Do not let `vendor` provenance touch `scope1_t`, `delivered_pct_yr` or the score.** The
    schema is the enforcement. `yh_*` columns are permitted in the financial denominators, where
    they are labelled, and nowhere else.
