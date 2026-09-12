# master_company: the spreadsheet

Built by `src/build_master.py` against the real files on 2026-09-12. Every number below was
printed by the run, not read off a README.

```
data/master/master_company.parquet    503 rows x 136 columns
data/master/master_company.csv        the same
data/master/master_company.xlsx       the same, readable, registry on sheet 2
data/master/master_panel.parquet      51,441 rows x 9 columns, ticker x year x metric, 2010-2026
data/master/column_registry.csv       136 rows, one per column
data/master/coverage_table.csv        the table at the end of this file
data/interim/ghgrp_ticker_year.parquet  1,857 rows x 146 tickers, newly persisted
```

## What it is

One row per **listing**, 503 of them, not 500 companies. GOOGL/GOOG, FOXA/FOX and NWSA/NWS share a
CIK and share their financials. `is_primary_listing` is False on the three secondaries and sums to
500; filter it before summing tonnes, dollars or weight or Alphabet counts twice.

Every one of the 503 appears. Nothing is dropped for being unmeasurable: 181 primary listings carry
no Scope 1 figure from any source and they are in the table with a null, counted.

Every contested quantity carries three columns: the value, a `_basis` naming the source that won,
and a `_dq` on the PCAF 1-5 scale. Eleven quantities get the triple, and those eleven are exactly
the quantities where two sources disagreed: `scope1_t`, `scope2_market_t`, `scope3_total_t`,
`delivered_pct_yr`, `promised_pct_yr`, `revenue_musd`, `ebit_musd`, `ebitda_musd`,
`total_debt_musd`, `market_cap_musd`, `ev_ebitda_x`.

Nothing is zero-filled and nothing is mean-imputed. A missing value is null and appears in the
coverage table as a smaller count.

## How to use it

The model the table feeds, in order, each step a stored column at its default:

```
carbon_cost_musd        = (scope1_t x cov1 + scope2_market_t x cov2 + scope3_total_t x cov3)
                          x price_sector_usd_per_t
carbon_cost_abated_musd = carbon_cost_musd x abatement_factor
                          where abatement_factor = (1 + delivered_pct_yr/100) ^ (2030 - scope1_year)
d_ebit_musd             = carbon_cost_abated_musd x (1 - passthrough_pct/100)
d_ev_musd               = d_ebit_musd x ev_ebitda_x
d_ev_pct_of_ev          = d_ev_musd / ev_musd          <- the reweighting input
```

The stored values use one NGFS price, 100% Scope 1 and 2 coverage, 0% Scope 3, and the sector
passthrough defaults. The UI overwrites `price_sector_usd_per_t`, the three coverage columns and
`passthrough_pct` and recomputes the five columns below them. Nothing else changes.

Three things to know before quoting a number from it:

1. **`delivered_pct_yr` is the observed rate, never the promised one.** It is an OLS on measured
   tonnage over the company's longest clean window, 134 listings carry it, and it comes with
   `delivered_se_pct_yr`, `delivered_r2` and `delivered_n_years` so the fit can be judged.
   `abatement_factor` is 1.0 where there is no observed rate, which is the conservative reading:
   no credit for a cut nobody measured.
2. **`scope3_total_t` is not summable across the index.** One company's Scope 3 is another's
   Scope 1. `coverage_scope3_pct` is 0 by default for that reason.
3. **`d_ebit_pct_of_ebit` is null where operating income is zero or negative**, 20 of the 327 rows
   that have a cost. A ratio against a negative denominator is not earnings at risk. `ebit_musd`
   is the latest fiscal year, which for a cyclical in a trough makes the ratio look worse than
   the through-cycle number would.

`master_panel.parquet` is long: `ticker, year, metric, value, unit, source, provenance_class, dq,
headline_eligible`. 23 metrics, 2010-2026. `headline_eligible` is False on the rows the magnitude
screen demoted, so the panel keeps everything that was extracted and `master_company` reads only
what passed.

## Precedence as applied

### Scope 1, three boundaries, one decision

The three sources measure different things, so the table carries all three and decides a headline.
EPA GHGRP is US facilities over 25,000 tCO2e, mandatory, latest year 2023. A self-report is global
and whole-entity, voluntary, latest FY2024. Climate TRACE is a modelled asset inventory with no
corporate boundary.

`scope1_t` precedence, first hit wins, measured on the 500 primary listings:

| step | rule | listings |
|---|---|---:|
| 1 | `scope1_selfreported_t` where it exists **and clears the EPA-measured floor** | 270 |
| 2 | `scope1_measured_us_t`, GHGRP fossil equity, where no self-report exists | 33 |
| 2b | the same, where the self-report sat **below** what EPA measured | 15 |
| 3 | `scope1_modelled_t`, Climate TRACE equity | 1 |
| 4 | null, counted, never zero | 181 |

**The floor rule is the defensible part: a company does not get to report below what EPA measured
on its own US sites.** It fired on 15 listings. Eleven of the fifteen report within 10% of the
measured figure, which is boundary noise between equity share and operational control, and four are
materially below: FANG, MCHP, MLM, NUE. All fifteen take the mandatory number and carry
`scope1_below_measured_floor = True`, so the correction is visible rather than silent.

Coverage by sector, primary listings with any Scope 1:

| sector | n | with Scope 1 | % |
|---|---:|---:|---:|
| Utilities | 31 | 31 | 100 |
| Materials | 25 | 24 | 96 |
| Energy | 21 | 19 | 90 |
| Consumer Staples | 34 | 30 | 88 |
| Consumer Discretionary | 47 | 37 | 79 |
| Information Technology | 73 | 47 | 64 |
| Financials | 76 | 49 | 64 |
| Industrials | 83 | 38 | 46 |
| Communication Services | 21 | 9 | 43 |
| Real Estate | 30 | 13 | 43 |
| Health Care | 59 | 22 | 37 |
| **total** | **500** | **319** | **64** |

### Scope 1 measured: fossil only, and net of perimeter changes

`emissions_by_ticker.scope1_ghgrp_tonnes` is EPA's published CO2e **including gas_id 8, biogenic
CO2**, which the GHG Protocol keeps out of Scope 1. `src/compare_reported_measured.py` already
splits the gases and reconciles to `emissions_by_ticker` to 0.000000 tonnes over 1,857 ticker-years;
it simply never wrote the result down. This build persists it as
`data/interim/ghgrp_ticker_year.parquet` and reads the master table off it.

2023 totals over the 128 non-zero tickers: all-gas **1,208.5 MMT**, fossil only **1,161.9 MMT**,
biogenic **46.7 MMT**, and **1,107.1 MMT** after the perimeter correction below. The biogenic share
is 4.4% nationally and decisive per company: it is 81.6% at WY and 81.0% at PKG, so the all-gas
paper and packaging figures are five times too large.

The perimeter correction: our parent map attributes `CPN MANAGEMENT LP` to CEG, putting 47.7 MMT of
Calpine's 2023 fleet into Constellation's Scope 1 for an acquisition only agreed in January 2025.
`scope1_measured_us_t` is net of `PERIMETER_CHANGES` and `scope1_lookahead_excluded_t` carries what
was taken out. CEG goes 56.6 to 8.9 MMT and SW 5.92 to 0.08 MMT.

`scope1_ar6_t` restates CH4 and N2O from AR4 to AR6 GWPs. It is a band on the answer, not a
correction to apply: landfill and gas-distribution names move up to 19%.

### GHGRP 2023 against CAMD 2025

GHGRP has no 2024 or 2025 data. CAMD does, on 48 listings. **CAMD never sets a level**, because its
boundary is Acid Rain and CSAPR combustion units rather than the company, and a CAMD level inside a
GHGRP series puts a boundary break in the middle of a trend line. It appears as
`scope1_current_signal_t`, a currency check, and as `delivered_camd_pct_yr`, which extends the
observed trend to 2025 for 46 listings.

Four tickers stopped filing to GHGRP before 2023: IBM last filed 2014, IVZ 2016, NSC 2010, VMC 2013.
Their value is carried with its own `scope1_measured_us_year` but is not eligible for the headline,
because a 2013 level is not a statement about 2026.

Seven tickers matched GHGRP facilities and measured **zero** fossil tonnes in every year: AZO, CARR,
DOV, LII, TGT, TT, WMT. They carry `ghgrp_matched_zero_fossil = True`. That is a measured zero, not
a missing value, and it is not allowed to become a headline Scope 1.

### Scope 2 and 3: WBA first, PDF report second, never averaged

`wba_emissions` and `scope23` never cover the same fiscal year for Scope 1 alone. WBA's scope `1`
series exists only for FY2023-24 and `scope23` ends at FY2022. On the tickers in both, WBA's year is
newer every time. There is nothing to average. Latest fiscal year wins, `_basis` records which table
spoke. WBA does not label market against location basis, so `scope2_basis` says which table the
figure came from and not which accounting convention, and `scope2_location_t` is only filled where a
report stated a location figure separately, on 10 listings.

### The PDF extraction needed a magnitude screen

`scope23.parquet` is an extraction from sustainability PDFs and it is not reliable at magnitude.
PTC's extracted Scope 1 goes 1,073 t in FY2018 to 1,054,119 t in FY2019 and its Scope 2 goes 14,200
to 11,270,214, a factor of about a thousand in one year at a software company. Steel Dynamics goes
1.9 MMT, 1,081 t, 1.7 MMT in three consecutive years.

Two screens, both measured rather than hand-picked, dropping **69 of 951 tonnage rows over 29
tickers**:

- the upstream `magnitude_suspect` flag, which tests a report against the company's own GHGRP
  tonnage. 17 rows. It only catches a report far below a measured figure, so it cannot see a company
  with no EPA facilities.
- a within-company consistency test on Scope 1 and Scope 2 only. Where a ticker-scope has three or
  more years, a year more than 10x from the median of that series goes; where it has exactly two and
  they differ by more than 10x, both go, because there is no way to tell which is the typo. 52 rows.
  Scope 3 is exempt, because a company that starts counting category 1 purchased goods really does
  jump three orders of magnitude.

Net cost to coverage: **one listing**. PTC now carries no Scope 1, which is correct, because we do
not know it. Everything else recovered from WBA at a sane value: COST 1.42 MMT, STLD 2.75 MMT,
BKNG 2,268 t, SWKS 28,960 t, AKAM 45 t.

### Revenue, EBIT, capex, debt: ours

`financials.parquet`, latest fiscal year carrying each field, **per field, not per row**, with `fy`
and `period_end` carried. Their `sec_revenue`, `sec_ebit` and `sec_capex` are rejected outright: the
extractor takes `RevenueFromContractWithCustomerExcludingAssessedTax`, which is a crumb for a bank
or a REIT. CPT books 1,542,027,000 of lease income where theirs shows 3,451,000; MTB books
10,224,000,000 of interest income where theirs shows 1,484,000,000.

- `da_musd` is **theirs**, `sec_dep_amort_*`, the only depreciation and amortisation anywhere in the
  project. It is labelled `da_basis = sec_secondhand` because we did not extract it, and it feeds
  the EBITDA denominator and nothing else. 364 listings.
- `ebitda_musd` is **built**: our operating income at the D&A's own year plus that D&A, so the two
  halves cover the same period (364 rows); else Yahoo's trailing twelve months (130); else null (9).
  Their `sec_ebitda` is rejected because it inherits their EBIT.
  Checked against their `sec_ebitda_2024`: 266 of 279 agree within 1%, so the only difference is
  our better EBIT. The two bases are not comparable to each other, and `ebitda_basis` says which
  one a row carries: a fiscal-year figure against a trailing twelve months diverges most where the
  cycle turned, which is why WDC's FY2024 EBITDA is 3% of its current TTM and Micron's is 13%.
  `ebitda_musd` is a reference column and feeds nothing in the model chain, which runs on
  `ebit_musd` and `ev_ebitda_x`.
- `total_debt_musd` is SEC XBRL on 466 and Yahoo on 37.
- `revenue_ttm_musd_check` is Yahoo's TTM revenue, kept as a cross-check only. TTM and fiscal year
  are different periods and must not be mixed.

### Market cap, EVIC, EV, and the multiple

`market_cap_musd` is ours, SEC cover-page shares times the 2026-09-11 price, with **four named
overrides** where ours and Yahoo's differ by more than 25%: IBKR 40.6 to 155.7bn, BX 96.5 to 153.6,
VMRK 24.6 to 50.7, ERIE 6.1 to 12.8. All four are up-C or multi-class structures where the cover
page counts one class. Understating a holding by four times in a $1bn allocation is worse than the
vendor-provenance cost of the override. The 34 listings whose share count predates 2026 carry
`market_cap_shares_stale`; that is the 10-to-25% band against Yahoo and it is a staleness to flag,
not a bug to fix. ARES has no market cap from us and takes Yahoo's.

`evic_musd` is market cap plus total debt, **gross of cash**, which is EVIC as PAB Article 5 defines
it and the right denominator for a financed-emissions intensity. It reproduces
`portfolio.parquet` on 499 shared rows with a median ratio of 1.0000 and 466 within 1%.

`ev_musd` is `yh_enterprise_value`, net of cash, for the valuation leg. We have no EV of our own.

`ev_ebitda_x` is guarded, because dEV = dEBIT x multiple and a 1942x multiple destroys the answer.
Reject where Yahoo's EBITDA is not positive (BRK.B, BA, MRNA), winsorise to the sector 5th and 95th
percentile, clamp to [4, 40], fall back to the GICS sector median. Result: **398 taken as published,
71 winsorised or clamped, 34 on the sector median, 0 null.** The raw vendor figure stays in
`ev_ebitda_raw_x` so the guard is visible. 31 of the 34 sector-median rows are Financials, where a
bank has almost no Scope 1 and the multiple moves nothing.

### Targets and the promised rate

SBTi status, classification and years come from `targets_company.parquet`, 261 near-term and 118 net
zero. `promised_pct_yr` is ours on 341 listings with the WBA backfill on the 17 it covers and we do
not, **358 of 503**, and `promised_basis` says which. On the 153 both cover, the median difference
is exactly 0.000 pp, so the two are the same underlying targets read twice.

### The WBA crosswalk, and the one row in it that is wrong

Their `sp500_wba_crosswalk.csv` routes CIK to Wikidata QID to WBA QID, matches 250 tickers against
our 247, **ours is a strict subset of theirs, and the `wba_company_id` agrees on all 247 in common**.
Three are new: BG, EQT and GOOG.

**One of the three is a different company.** Their EQT is **EQT AB Group**, the Swedish alternative
asset manager (QID Q1275733, ISIN SE0012853455, HQ SWE), matched by `exact_normalized_name` against
**EQT Corporation**, the US natural-gas producer (QID Q5323987, CIK 0000033213). Its self-reported
Scope 1 is **33 tonnes**, against **1.82 MMT** that EPA measured on EQT Corporation's own wells in
2023. Their own file records the disagreement: the two QID columns differ on that row.

The rule applied: **accept a crosswalk row that is new to us only where the two Wikidata QIDs agree,
or where one side has no QID.** Six of the 250 disagree on QID. Five of the six (AMCR, AVGO, DOW,
HWM, WM) are the same company under a second QID and are independently confirmed by our own ISIN or
LEI match, so only EQT is rejected. Accepted gains: BG and GOOG, where GOOG is Alphabet's secondary
listing. Net: 249 tickers.

### Exclusions and conduct

`excluded` fires where any Article 12 rule does: 67 listings, 40 from `revenue_exclusions.flag_best`
and 27 from the Article 12(1)(g) power test alone. `excl_basis` names the screen and `excl_dq` is 1
where measured segment revenue was tested against the article's own threshold and 4 or 5 for a
sector proxy. `conduct_measured_zero` is True where Violation Tracker was searched and found no
environmental penalty: a measured zero, not a missing value.

### Provenance, and the schema as the enforcement

Two provenance columns, not one. A single worst-of column reads `vendor` on all 503 rows, because
the EV/EBITDA multiple and the second-hand D&A are vendor numbers on nearly every row, and a column
with one value says nothing.

- `provenance_class` is the class of the headline emissions fact: **mandatory 48, voluntary 270,
  modelled 1, null 181** on the 500 primary listings. The build asserts it is never `vendor`. That
  assertion is the rule "do not let vendor provenance touch `scope1_t`" made mechanical.
- `financial_provenance_class` is the worst of the four financial facts we extracted ourselves:
  **mandatory 463, vendor 40**. Vendor is permitted here and only here.

## The modelled assumptions, labelled as such

Three inputs are assumptions with defaults, not data, and they are labelled `modelled` with dq 5
wherever they appear.

- **`passthrough_pct` has no empirical source anywhere in this repo.** The defaults are Utilities 80,
  Consumer Staples 70, Health Care 70, Energy 60, Information Technology 60, Communication Services
  60, Real Estate 60, Industrials 50, Financials 50, Consumer Discretionary 40, Materials 35. The
  reasoning is regulated cost recovery at the top, inelastic demand in the middle, and trade-exposed
  commodity producers competing against unpriced imports at the bottom. It is a dial, not a
  measurement, and it must never be presented as one.
- **The NGFS deflator is a hard constant.** NGFS publishes in US$2010 per tCO2, and per tCO2 rather
  than tCO2e. `USD2010_TO_USD2026 = 1.44` is BEA's GDP implicit price deflator and is written into
  `src/build_master.py`, not fetched. `price_usd2010_per_t` carries the undeflated figure beside it
  so the conversion is visible and reversible.
- **The price is one model, named, never an average.** GCAM 6.0 NGFS, Net Zero 2050, USA, 2030:
  98.59 US$2010/tCO2, 141.96 USD/tCO2 after deflation. REMIND gives 283.70 for the same scenario and
  the same year. Averaging them produces a number no model published.

## Coverage table

Every column of `master_company` and its non-null count. `n / 503` counts all listings, `n / 500
primary` counts the 500 after filtering `is_primary_listing`. Boolean columns are complete by
construction and count 503. Also written to `data/master/coverage_table.csv`.

| column | unit | class | n / 503 | n / 500 primary | % |
|---|---|---|---:|---:|---:|
| `ticker` |  | mandatory | 503 | 500 | 100.0 |
| `company_name` |  | mandatory | 503 | 500 | 100.0 |
| `cik` |  | mandatory | 503 | 500 | 100.0 |
| `gics_sector` |  | mandatory | 503 | 500 | 100.0 |
| `gics_sub_industry` |  | mandatory | 503 | 500 | 100.0 |
| `nace_section` |  | modelled | 503 | 500 | 100.0 |
| `is_primary_listing` | bool | mandatory | 503 | 500 | 100.0 |
| `share_class_siblings` |  | mandatory | 6 | 3 | 1.2 |
| `hq_country_iso` |  | mandatory | 503 | 500 | 100.0 |
| `date_added` | date | mandatory | 503 | 500 | 100.0 |
| `scope1_measured_us_t` | tCO2e | mandatory | 146 | 146 | 29.0 |
| `scope1_measured_us_year` | year | mandatory | 146 | 146 | 29.0 |
| `scope1_measured_allgas_t` | tCO2e | mandatory | 146 | 146 | 29.0 |
| `scope1_biogenic_t` | tCO2e | mandatory | 146 | 146 | 29.0 |
| `scope1_ar6_t` | tCO2e | modelled | 132 | 132 | 26.2 |
| `scope1_lookahead_excluded_t` | tCO2e | modelled | 146 | 146 | 29.0 |
| `scope1_facility_count` | count | mandatory | 146 | 146 | 29.0 |
| `ghgrp_matched_zero_fossil` | bool | mandatory | 503 | 500 | 100.0 |
| `scope1_current_signal_t` | tCO2e | mandatory | 48 | 48 | 9.5 |
| `scope1_current_signal_year` | year | mandatory | 48 | 48 | 9.5 |
| `scope1_selfreported_t` | tCO2e | voluntary | 288 | 285 | 57.3 |
| `scope1_selfreported_year` | year | voluntary | 288 | 285 | 57.3 |
| `scope1_selfreported_source` |  | voluntary | 288 | 285 | 57.3 |
| `scope1_modelled_t` | tCO2e | modelled | 73 | 73 | 14.5 |
| `scope1_modelled_year` | year | modelled | 73 | 73 | 14.5 |
| `scope1_t` | tCO2e | mixed | 322 | 319 | 64.0 |
| `scope1_year` | year | mixed | 322 | 319 | 64.0 |
| `scope1_basis` |  | mixed | 322 | 319 | 64.0 |
| `scope1_dq` | 1-5 | mixed | 322 | 319 | 64.0 |
| `scope1_below_measured_floor` | bool | mixed | 503 | 500 | 100.0 |
| `scope2_market_t` | tCO2e | voluntary | 284 | 281 | 56.5 |
| `scope2_basis` |  | voluntary | 284 | 281 | 56.5 |
| `scope2_dq` | 1-5 | voluntary | 284 | 281 | 56.5 |
| `scope2_location_t` | tCO2e | voluntary | 10 | 10 | 2.0 |
| `scope2_year` | year | voluntary | 284 | 281 | 56.5 |
| `scope3_total_t` | tCO2e | voluntary | 259 | 257 | 51.5 |
| `scope3_basis` |  | voluntary | 259 | 257 | 51.5 |
| `scope3_dq` | 1-5 | voluntary | 259 | 257 | 51.5 |
| `scope3_year` | year | voluntary | 259 | 257 | 51.5 |
| `scope12_t` | tCO2e | voluntary | 246 | 245 | 48.9 |
| `scope12_year` | year | voluntary | 246 | 245 | 48.9 |
| `grid_factor_hq_g_per_kwh` | gCO2e/kWh | mandatory | 502 | 499 | 99.8 |
| `power_intensity_g_per_kwh` | gCO2e/kWh | modelled | 36 | 36 | 7.2 |
| `power_gen_mwh` | MWh | mandatory | 36 | 36 | 7.2 |
| `delivered_pct_yr` | %/yr | modelled | 134 | 134 | 26.6 |
| `delivered_basis` |  | modelled | 134 | 134 | 26.6 |
| `delivered_dq` | 1-5 | modelled | 134 | 134 | 26.6 |
| `delivered_se_pct_yr` | %/yr | modelled | 134 | 134 | 26.6 |
| `delivered_r2` |  | modelled | 134 | 134 | 26.6 |
| `delivered_n_years` | count | modelled | 134 | 134 | 26.6 |
| `delivered_year_start` | year | modelled | 134 | 134 | 26.6 |
| `delivered_year_end` | year | modelled | 134 | 134 | 26.6 |
| `delivered_camd_pct_yr` | %/yr | modelled | 46 | 46 | 9.1 |
| `promised_pct_yr` | %/yr | voluntary | 358 | 356 | 71.2 |
| `promised_basis` |  | voluntary | 358 | 356 | 71.2 |
| `promised_dq` | 1-5 | voluntary | 358 | 356 | 71.2 |
| `promised_target_year` | year | voluntary | 341 | 339 | 67.8 |
| `promised_baseline_year` | year | voluntary | 341 | 339 | 67.8 |
| `gap_pct_yr` | %/yr | modelled | 108 | 108 | 21.5 |
| `sbti_near_term_status` |  | voluntary | 261 | 259 | 51.9 |
| `sbti_near_term_classification` |  | voluntary | 227 | 225 | 45.1 |
| `sbti_net_zero_status` |  | voluntary | 118 | 117 | 23.5 |
| `sbti_net_zero_year` | year | voluntary | 78 | 77 | 15.5 |
| `revenue_musd` | USD millions | mandatory | 503 | 500 | 100.0 |
| `revenue_basis` |  | mandatory | 503 | 500 | 100.0 |
| `revenue_dq` | 1-5 | mandatory | 503 | 500 | 100.0 |
| `revenue_fy` | year | mandatory | 503 | 500 | 100.0 |
| `revenue_period_end` | date | mandatory | 503 | 500 | 100.0 |
| `ebit_musd` | USD millions | mandatory | 502 | 499 | 99.8 |
| `ebit_basis` |  | mandatory | 502 | 499 | 99.8 |
| `ebit_dq` | 1-5 | mandatory | 502 | 499 | 99.8 |
| `ebit_fy` | year | mandatory | 502 | 499 | 99.8 |
| `capex_musd` | USD millions | mandatory | 481 | 478 | 95.6 |
| `capex_fy` | year | mandatory | 481 | 478 | 95.6 |
| `da_musd` | USD millions | vendor | 364 | 364 | 72.4 |
| `da_basis` |  | vendor | 364 | 364 | 72.4 |
| `da_fy` | year | vendor | 364 | 364 | 72.4 |
| `ebitda_musd` | USD millions | mixed | 494 | 491 | 98.2 |
| `ebitda_basis` |  | mixed | 494 | 491 | 98.2 |
| `ebitda_dq` | 1-5 | mixed | 494 | 491 | 98.2 |
| `ebitda_fy` | year | mixed | 364 | 364 | 72.4 |
| `total_debt_musd` | USD millions | mixed | 503 | 500 | 100.0 |
| `total_debt_basis` |  | mixed | 503 | 500 | 100.0 |
| `total_debt_dq` | 1-5 | mixed | 503 | 500 | 100.0 |
| `total_debt_fy` | year | mandatory | 466 | 463 | 92.6 |
| `total_cash_musd` | USD millions | vendor | 501 | 498 | 99.6 |
| `market_cap_musd` | USD millions | mixed | 503 | 500 | 100.0 |
| `market_cap_basis` |  | mixed | 503 | 500 | 100.0 |
| `market_cap_dq` | 1-5 | mixed | 503 | 500 | 100.0 |
| `market_cap_shares_stale` | bool | mandatory | 503 | 500 | 100.0 |
| `evic_musd` | USD millions | mixed | 503 | 500 | 100.0 |
| `evic_debt_observed` | bool | mixed | 503 | 500 | 100.0 |
| `ev_musd` | USD millions | vendor | 500 | 497 | 99.4 |
| `ev_ebitda_x` | x | vendor | 503 | 500 | 100.0 |
| `ev_ebitda_basis` |  | vendor | 503 | 500 | 100.0 |
| `ev_ebitda_dq` | 1-5 | vendor | 503 | 500 | 100.0 |
| `ev_ebitda_raw_x` | x | vendor | 471 | 468 | 93.6 |
| `fcf_musd` | USD millions | vendor | 470 | 467 | 93.4 |
| `beta_x` | x | vendor | 497 | 494 | 98.8 |
| `revenue_ttm_musd_check` | USD millions | vendor | 502 | 499 | 99.8 |
| `index_weight_pct` | % | mixed | 503 | 500 | 100.0 |
| `price_usd2010_per_t` | US$2010/tCO2 | modelled | 503 | 500 | 100.0 |
| `price_sector_usd_per_t` | USD/tCO2 | modelled | 503 | 500 | 100.0 |
| `coverage_scope1_pct` | % | modelled | 503 | 500 | 100.0 |
| `coverage_scope2_pct` | % | modelled | 503 | 500 | 100.0 |
| `coverage_scope3_pct` | % | modelled | 503 | 500 | 100.0 |
| `passthrough_pct` | % | modelled | 503 | 500 | 100.0 |
| `carbon_cost_musd` | USD millions | mixed | 327 | 324 | 65.0 |
| `abatement_factor` |  | modelled | 503 | 500 | 100.0 |
| `carbon_cost_abated_musd` | USD millions | mixed | 327 | 324 | 65.0 |
| `d_ebit_musd` | USD millions | mixed | 327 | 324 | 65.0 |
| `d_ebit_pct_of_ebit` | % | mixed | 307 | 304 | 61.0 |
| `d_ev_musd` | USD millions | mixed | 327 | 324 | 65.0 |
| `d_ev_pct_of_ev` | % | mixed | 322 | 319 | 64.0 |
| `model_dq` | 1-5 | modelled | 327 | 324 | 65.0 |
| `excl_12g` | bool | modelled | 503 | 500 | 100.0 |
| `excluded` | bool | mixed | 503 | 500 | 100.0 |
| `excl_articles` |  | mixed | 67 | 67 | 13.3 |
| `excl_basis` |  | mixed | 67 | 67 | 13.3 |
| `excl_dq` | 1-5 | mixed | 503 | 500 | 100.0 |
| `high_impact_nace` | bool | modelled | 503 | 500 | 100.0 |
| `penalty_usd_environment` | USD | mandatory | 468 | 465 | 93.0 |
| `case_count_environment` | count | mandatory | 468 | 465 | 93.0 |
| `penalty_usd_total` | USD | mandatory | 468 | 465 | 93.0 |
| `conduct_measured_zero` | bool | mandatory | 503 | 500 | 100.0 |
| `vendor_percentile` | percentile | vendor | 470 | 470 | 93.4 |
| `vendor_n_sources` | count | vendor | 489 | 486 | 97.2 |
| `our_percentile` | percentile | modelled | 503 | 500 | 100.0 |
| `rank_median` | rank | modelled | 503 | 500 | 100.0 |
| `rank_p05` | rank | modelled | 503 | 500 | 100.0 |
| `rank_p95` | rank | modelled | 503 | 500 | 100.0 |
| `coverage_tier` |  | modelled | 503 | 500 | 100.0 |
| `score_mirrored_from` |  | modelled | 3 | 0 | 0.6 |
| `provenance_class` |  | modelled | 322 | 319 | 64.0 |
| `financial_provenance_class` |  | modelled | 503 | 500 | 100.0 |
| `generated_at` | timestamp | modelled | 503 | 500 | 100.0 |
