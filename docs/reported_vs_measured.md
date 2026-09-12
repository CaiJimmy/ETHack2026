# Self-reported against measured

Built by `src/compare_reported_measured.py`. Output table `data/interim/reported_vs_measured.parquet`,
187 rows over 96 tickers. Every number below is printed by that script when it runs.

## The answer first

We cannot honestly say that S&P 500 companies systematically report less Scope 1 than they
physically emit in the United States. We tested it properly and the claim does not survive.

For the 90 companies where we hold both an EPA-measured and a company self-reported Scope 1
figure within one year of each other, **19 (21%) publish a global Scope 1 below EPA's published
US CO2e. After the four adjustments below, 4 remain (4%, Wilson 95% CI 2 to 11%), by a median
shortfall of 14%, and for three of those four a single 2024 asset sale would cover the gap.**

Four fifths of the apparent gap is our measurement's definitions, not their honesty. The
defensible sentence is the one that says so.

What the data does support, and what we should say instead:

1. **The mandatory spine is most of the number, not a proxy for it.** Across those 90 companies
   the self-reported global Scope 1 sums to 1,127.8 MMT and the EPA-measured US fossil CO2e sums
   to 910.9 MMT. **81% of what these companies say about themselves globally is already measured
   under legal penalty in the United States.** At the median company the ratio is 1.57, so the
   measured US figure is 64% of the global self-report. The 81% is tonnage-weighted and 48 of the
   90 companies are utilities, energy or materials carrying 88% of those tonnes, so it is a
   statement about where the emissions are, not about a typical S&P 500 name.
2. **The self-reported figures behave exactly as the boundary predicts**, which is positive
   evidence for both datasets. Companies WBA records as operating in one country have a median
   self-to-measured ratio of 1.05; companies operating in more than one country, 2.00. The ratio
   rises with the number of countries of operation (Spearman +0.36, n=66) and with Climate TRACE's
   measured non-US asset share (Spearman +0.39, n=46).
3. **The far bigger problem is silence, not misstatement.** 275 of 500 companies had no emissions
   figure of any kind before this lane; with WBA, 171 still have none.
4. **Suggestive but not significant: the reported improvement sits in the part nobody measures.**
   Over 2019 to 2023, at the median company the EPA-measured US part fell 4.2% while everything
   else in the reported figure fell 21.0%. Wilcoxon p = 0.135. On a tonnage-weighted basis the two
   move together (-10.6% measured, -10.2% remainder), so this is a statement about the median
   company, not about the index.

## What is being compared

| side | source | table | class |
|---|---|---|---|
| measured | EPA GHGRP, filed under 40 CFR 98 with penalties for misreporting | `emissions_by_ticker.parquet`, rebuilt here with the gas dimension | `mandatory` |
| self-reported | World Benchmarking Alliance SDG2000 climate profiles and emissions time series | `wba_emissions.parquet` | `voluntary` |

Two tests, because WBA publishes Scope 1 alone for only one year per company.

**Test A, like for like.** WBA's climate-profile Scope 1 against measured Scope 1. n = 95, of which
18 profiles are FY2023 and 77 FY2024. GHGRP's last reporting year is 2023, so 75 of the 90 usable
pairs carry a one-year gap. This is the primary test.

**Test B, strictly conservative.** WBA's Scope 1+2 time series against measured Scope 1, same
calendar year, n = 92 (89 at 2023). Scope 1+2 is always at least Scope 1, so a company below its US
measured Scope 1 on this test is below it by more than the test shows. No year gap at all.

The output parquet carries both, tagged in a `mode` column, with `self_provenance_class = voluntary`
and `measured_provenance_class = mandatory` on every row.

## Why the test is conservative in our favour

GHGRP covers **US facilities emitting more than 25,000 tCO2e a year**. It sees no foreign plant, no
vehicle fleet, no aircraft, and no small site. A company self-reports **global** Scope 1. So the
measured figure is a floor on an honest self-report, and the interesting case is a company sitting
below its own domestic measurement. Every company above the line tells us nothing.

The boundary is large and visible in the data. United Airlines reports 38.5 MMT of global Scope 1
against 0.027 MMT of GHGRP-reportable facilities, a ratio of 1,423, because jet fuel burned in the
air is Scope 1 and is not a facility. AT&T is 338x, Mondelez 66x, Delta 30x. Those are not anomalies,
they are the test working.

## Where the apparent gaps actually come from

| tier | what is removed | Test A below 1 | Test B below 1 |
|---|---|---|---|
| 0 | nothing, all pairs | 21 of 95 (22%) | 11 of 92 (12%) |
| 1 | measured years more than one year stale | 19 of 90 | 11 of 92 |
| 2 | biogenic CO2, which the GHG Protocol keeps out of Scope 1 | 15 | 7 |
| 3 | consolidation: measure only wholly owned facilities | 10 | 4 |
| 4 | roll the floor to the reported year on CAMD, restate GWP to AR6 | 12 | 4 |
| 5 | fleets our parent map attributes by today's owner | 8 | 3 |
| 6 | measured figures that are mostly fluorinated gas under subpart I | 6 | 3 |
| 7 | shortfalls smaller than the company's own year-to-year swing | **4** | **2** |

### Tier 1, stale measurement

Five companies stopped having a GHGRP-reportable facility years ago and still self-report: IBM (last
measured 2014), AT&T (2014), Invesco (2016), Mondelez (2018), Kraft Heinz (2021). Invesco's apparent
ratio of 0.014 compares a 2024 self-report to a 2016 measurement of a facility it no longer has.
Dropped, not adjusted.

### Tier 2, biogenic CO2 (the single biggest correction)

EPA's headline CO2e includes gas_id 8, biogenic CO2 from biomass combustion: 118.7 MMT of the 2,697
MMT direct-emitter total for 2023, 4.4%. The GHG Protocol reports biogenic CO2 **outside** Scope 1.
Our published `scope1_ghgrp_tonnes` therefore includes tonnes no company would ever put in Scope 1.

It is not a rounding error for anyone who burns black liquor:

| ticker | company | biogenic share of measured | ratio before | ratio after |
|---|---|---|---|---|
| PKG | Packaging Corporation of America | 81.0% | 0.25 | 1.33 |
| IP | International Paper | 80.4% | 0.22 | 1.14 |
| SW | Smurfit Westrock | 71.0% | 0.40 | 1.38 |
| WY | Weyerhaeuser | 81.6% | 1.79 | 9.72 |
| WM | Waste Management | 9.9% | 1.05 | 1.16 |

Once the stale measurements and our own parent-map artefact are out, the three worst apparent
offenders in the comparison are all pulp and paper, and all three are fully explained. Anyone running this test without the gas dimension would have led a pitch with
International Paper "hiding 78% of its emissions". It does not.

### Tier 3, equity share against operational control

Our rollup is ownership-weighted, an equity-share view. A company on the operational-control basis
books 100% of what it operates and nothing of what it does not, so the floor that no consolidation
choice escapes is the tonnage from facilities it holds outright. Five companies clear on that alone:

| ticker | part-owned share of measured | ratio equity | ratio at the floor |
|---|---|---|---|
| WEC | 45.4% | 0.95 | 1.73 |
| CMS | 38.7% | 0.95 | 1.55 |
| XEL | 37.7% | 0.91 | 1.46 |
| AEP | 8.7% | 0.96 | 1.05 |
| NEE | 4.4% | 0.99 | 1.03 |

WEC's Elm Road (84%), Weston (76%) and Columbia (27.5%), Xcel's Sherco (84%) and Comanche (83%),
CMS's J H Campbell (96%). Every one of these is a jointly owned plant where the two conventions give
different answers by design.

### Tier 4, fiscal year and the 2024 hole

GHGRP has no 2024, and 75 of 90 self-reports are FY2024. CAMD does publish 2024, so where a stack
monitor covers at least half a company's measured tonnage (13 companies) the floor is rolled forward
on the observed CAMD 2024/2023 ratio. It cuts both ways: it lifts two companies above the line and
pushes two below, because measured US power CO2 rose for some in 2024. Across the 27 compared
companies with a monitor the median move was +3.2%, p10 to p90 -17% to +18%. That band is the size
of the timing risk on any single name.

14 of the 90 close their books off the calendar year. Only one of them, Microchip (March year end),
is anywhere near the line, and it is removed at tier 6 for a different reason.

### Tier 4, gases and GWP vintage

GHGRP CO2e covers CO2, CH4, N2O, SF6, NF3, HFCs, PFCs and HFEs by subpart, on the AR4 GWP values in
40 CFR 98 Table A-1. Companies increasingly publish on AR5 or AR6. Restating the measured figure to
AR6 (CH4 25 to 29.8, N2O 298 to 273) moves it by 0.00% at the median, +3.5% at p95 and +19.2% at the
maximum, which is Expand Energy, whose measured tonnage is 20% methane. It never decides a case on
its own. CF Industries is 25% N2O and the restatement narrows its gap without closing it.

### Tier 5, entity look-ahead (our error, not theirs)

The parent map deliberately applies today's ownership to historical facilities. That is right for
survivorship but wrong for this test. A systematic rule flags every ticker where more than half the
measured tonnage sits under a parent family that is not the index name: 11 candidates, of which a
deal-date check confirmed 3.

| ticker | family | share of measured | deal |
|---|---|---|---|
| CEG | CPN Management / Calpine | 84.2% | Constellation agreed to buy Calpine in January 2025 |
| SW | WestRock | 100% of fossil | Smurfit Kappa and WestRock combined 5 July 2024 |
| EXE | Southwestern Energy | 58.3% | Chesapeake and Southwestern combined 1 October 2024 |

Constellation's apparent 0.15 ratio is 47.7 MMT of Calpine gas plants it did not own in the measured
year. The other 8 candidates (Sempra Energy, Pacific Gas & Electric, Arconic, Honeywell UOP, DuPont
de Nemours, Eli Lilly, United Continental, Berry Global at 0.067 MMT) are renames and subsidiary
spellings and are kept.

### Tier 6, fluorinated gases under subpart I

Nine of the 90 have a measured figure that is more than half fluorinated gas: NXPI 88%, MCHP 88%,
TXN 87%, SWKS 83%, ADI 83%, MU 67%, INTC 60%, MMM 60%, AVGO 54%. Subpart I lets a semiconductor
facility use EPA default emission factors or its own measurements including abatement, so the
measured and the self-reported number are not the same calculation. Two of the nine sit below the
line (MCHP 0.61, TXN 0.96) and are removed as not comparable on method rather than counted as
understatement. The other seven sit above it.

### Tier 7, shortfalls inside the company's own noise

A shortfall smaller than a company's own median year-on-year swing in measured tonnage cannot be told
apart from the one-year reporting gap. That removes AEP (2.5% shortfall against a 15.4% swing),
Consolidated Edison (1.5% against 2.8%), Vistra (0.4% against 4.6%) and Waste Management (2.4%
against 7.5%).

## The four that survive everything

Test A, FY2024 self-report against reporting year 2023 measured, both figures as published:

| ticker | company | self-reported global Scope 1 | measured US floor | ratio | shortfall | largest single US site |
|---|---|---|---|---|---|---|
| MLM | Martin Marietta Materials | 2.900 MMT | 3.999 MMT | 0.73 | 1.099 MMT (27.5%) | 1.321 MMT |
| NUE | Nucor | 4.139 MMT | 5.222 MMT | 0.79 | 1.091 MMT (20.9%) | 1.087 MMT |
| CF | CF Industries | 18.800 MMT | 20.579 MMT | 0.93 | 1.345 MMT (6.7%) | 9.475 MMT |
| PPL | PPL Corporation | 26.663 MMT | 28.288 MMT | 0.94 | 1.658 MMT (5.9%) | 9.678 MMT |

Test B, same calendar year, no timing gap at all, self-reported Scope 1+2 against measured Scope 1:

| ticker | company | self-reported Scope 1+2, 2023 | measured US floor, 2023 | ratio | shortfall |
|---|---|---|---|---|---|
| CF | CF Industries | 18.507 MMT | 20.579 MMT | 0.92 | 2.072 MMT (8.1%) |
| PPL | PPL Corporation | 25.294 MMT | 26.919 MMT | 0.94 | 1.625 MMT (6.1%) |

CF Industries and PPL appear on both tests, including the one with no year gap, which is as strong as
this dataset gets. CF's six US ammonia and nitric acid plants measure 20.58 MMT on an equity basis
with no jointly owned site at all, against a global self-report of 18.5 to 18.8 MMT for a company that
also operates in Canada and the United Kingdom. PPL's 14 facilities measure 26.92 MMT wholly owned
against 25.29 MMT reported for the same year.

**We are not calling these four companies dishonest and neither should the deck.** For three of the
four the shortfall is smaller than the company's own largest US site, so one 2024 divestiture would
account for it and GHGRP cannot yet say, because reporting year 2024 is not due until 30 October 2026.
Two other explanations we cannot test from this data: CO2 captured and sold as product, which CF does
at scale and which a reporter may exclude from Scope 1 while 40 CFR 98 still counts it, and any
segment of the business a company scopes out of its own inventory boundary. The honest description is
an unresolved discrepancy with both numbers on the table, not an accusation.

## What we cannot claim, stated plainly

The Nature Climate Change finding we currently cite (Cohen, Rouen and Sachdeva, January 2026: 58% of
public firms revised their self-reported emissions, 74% among the S&P 500, understatement exceeding
overstatement by more than two to one) measures **restatements over time of the same self-reported
series**. We measure **a level gap between two different sources in one year**. These are different
quantities and our result neither confirms nor contradicts theirs. We should keep citing the paper for
what it says and cite our own number for what ours says.

Within the WBA data there is one restatement-shaped fact the lane already found: WBA holds two
readings of the same company-year-scope from its climate profile and its emissions time series, and of
416 overlapping pairs only 178 agree to the tonne, with the profile figure higher 190 times. That is a
self-reported-against-self-reported inconsistency, not a measured comparison, and it belongs in a
different argument.

## Trend, the one comparison the caveats cannot touch

Every level caveat above (US-only boundary, biogenic share, consolidation basis, GWP vintage, subpart I
method) is roughly fixed within a company, so it cancels in a within-company change. 68 companies have
both sides in 2019 and 2023; restricting to the 44 where the measured US part is at least 20% of the
global self-report in both years, so the comparison is not noise on a small base:

- self-reported global change, median **-10.8%**
- EPA-measured US change, median **-4.9%**
- 28 of 44 report a better trend than their measured US emissions delivered (binomial p = 0.096,
  Wilcoxon p = 0.114)
- 3 of 44 report a falling global figure while measured US emissions rose more than 5%: Howmet
  (self -26.5%, measured +40.8%), Devon Energy (-16.1% against +44.0%), Analog Devices (-20.6%
  against +9.6%)

Splitting the reported figure into the measured US part and everything else, for the 33 companies
where the remainder is positive in both years: the measured part fell 4.2% at the median and the
remainder fell 21.0%. The reported improvement is five times faster in the part nobody audits. At
p = 0.135 that is suggestive and not significant, and on a tonnage-weighted basis it disappears
entirely (-10.6% measured, -10.2% remainder), so it is a statement about the median company and a
larger panel would be needed to make it stick.

## Scope 2 and Scope 3: how much of the hole WBA closes

Counts are companies out of 500 primary listings.

| layer | before WBA | WBA | union | WBA adds |
|---|---|---|---|---|
| Scope 2, any basis | 108 | 235 | 281 | **173 companies, 35 pp of the index** |
| Scope 3 total | 73 | 230 | 257 | **184 companies, 37 pp of the index** |
| Scope 1, voluntary | 109 | 235 | | |
| Scope 1, measured (GHGRP or CAMD) | 139 | | | |

Any emissions number of any kind rises from 225 companies to 329. **Silence falls from 275 companies
to 171.** That is the single largest coverage gain any lane in this project has produced.

What it does not fix:

- **One year, not a series.** WBA's separate Scope 1 and Scope 2 exist only in the climate profile,
  which carries one assessment year per company: 63 companies at 2023 and 184 at 2024. There is no
  Scope 2 history. The Scope 1+2 and Scope 3 time series do run 2019 to 2024, for 242 and 205
  companies, but Scope 2 alone cannot be separated out of them.
- **No location/market label.** The Scope 2 figure carries no basis of its own. It has to be read off
  each company's `available_emissions` scope codes, where 217 list a location-based figure as
  available and 212 a market-based one, and 198 list both, so for most companies we cannot say which
  one WBA took. Apple is the clean demonstration: its profile Scope 2 of 1,224,500 tCO2e is the
  location-based number, while its Scope 1+2 time series total of 58,500 implies a market-based figure
  near 3,300, a factor of 370 apart.
- **No Scope 3 categories.** WBA publishes a single Scope 3 total and no category split anywhere in
  the feed. Our category-level coverage stays at 7 companies. Anything that needs category 11 (use of
  sold products) separated from category 1 (purchased goods) is no better off than before.
- **219 companies still have no Scope 2 and 243 no Scope 3.** WBA's SDG2000 simply does not contain
  253 of the index, including Caterpillar, UnitedHealth, RTX, Thermo Fisher, Deere, Abbott, Union
  Pacific, Lockheed Martin, Medtronic, Altria, T-Mobile and Danaher.
- **Voluntary, and it must stay labelled that way.** Every WBA-derived column carries
  `provenance_class = voluntary`. It closes a coverage hole; it does not turn into the mandatory spine
  and must never be summed into a mandatory column.

## How to reproduce

```bash
nix develop --command .venv/bin/python src/compare_reported_measured.py
```

Reads `data/raw/epa_ghgrp/pub_facts_sector_ghg_emission_*.csv` (the gas dimension, which
`fetch_epa_ghgrp.py` aggregates away), `ghgrp_facilities.parquet`, `parent_ticker_map.parquet`,
`emissions_by_ticker.parquet`, `wba_emissions.parquet`, `wba_company.parquet`,
`data/raw/wba/WBA Data/footprintattributes.csv`, `climatetrace_nonus_share.parquet`,
`financials.parquet`, `universe.parquet` and `scope23.parquet`. No network calls.

The equity-weighted column it rebuilds reconciles with the published `scope1_ghgrp_tonnes` to
0.000000 tonnes over 1,857 ticker-years, and the script asserts it.

## Known weaknesses of this analysis

- **n is small and the survivors are fewer still.** 4 of 90 has a Wilson 95% interval of 2 to 11%. No
  conclusion here should be quoted without n.
- **The M&A check is manual.** The rule that surfaces candidates is systematic and printed; the
  verdict on each of the 11 is a hand check against a deal date, not a data join, and the deal dates
  are not sourced from a table in this repo.
- **No 2024 GHGRP.** 75 of 90 comparisons carry a one-year gap that CAMD can only close for the 13
  power-dominated names. Rerunning this in November 2026 with reporting year 2024 would settle three
  of the four survivors.
- **The subpart I argument is directional, not sized.** We can show a measured figure is 88%
  fluorinated gas and that the regulation permits two different calculation methods. We cannot show
  from this data which way the difference runs for a given fab.
- **WBA's licence is CC BY-NC-ND 4.0.** Publish findings, not a redistributed copy of its tables.
