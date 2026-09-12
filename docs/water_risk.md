# Water risk: additive information, or a restatement of carbon?

We joined every S&P 500 facility that reports to the EPA GHGRP to the WRI Aqueduct 4.0 basin it
physically sits in, by point-in-polygon, and asked one question: does water exposure tell us
anything our carbon numbers do not?

It does. Water exposure is statistically independent of measured carbon intensity, of our own
composite rank, and of the vendor ESG consensus. The rank correlation with carbon intensity is
+0.058 across 135 companies. Carbon explains 0.3% of the variance in the water ranking. On the
subset with enough facilities to measure properly it turns slightly negative.

The recommendation is therefore: ship water as a separate axis in the interface, not as a fifth
pillar of the composite score. The reasons are in section 5, and the low correlation is the
argument for both halves of that sentence.

## What is being measured

Source: WRI Aqueduct 4.0 baseline annual, July 2023 release, CC BY 4.0, attribution to the World
Resources Institute. `provenance_class = modelled`. Aqueduct is a hydrological model, not a filing
and not a regulator's meter, and it is labelled as such everywhere it appears. What is *not*
modelled is the thing we contribute: the facility coordinates are EPA GHGRP filings made under
legal penalty, and the placement of a facility inside a basin is geometry.

The headline metric is a share, not an index:

> **share of a company's US reporting facilities that sit in a basin WRI classes High (40-80% of
> renewable supply withdrawn) or Extremely High (>80%) baseline water stress.**

A share is checkable. Count the plants, count the ones in a stressed basin, divide. A mean of a
0-5 index is not checkable by anyone in the room.

Coverage: 142 of 503 tickers, 3,545 facilities, 3,724 facility-ticker links. GHGRP is US-only, so a
company with no US reporting facility has **no water score**. It is never shown as low risk.

National baseline for context: 27.7% of all 11,138 GHGRP facilities with a basin are in High or
Extremely High stress today, 32.2% by 2030 and 33.5% by 2050 under WRI business-as-usual
(SSP3 RCP7.0).

## 1. Is it additive, or a restatement of carbon?

Spearman rank correlations, pairwise-complete n reported on every line.

| Water exposure against | rho | p | n |
|---|---|---|---|
| Carbon intensity (t CO2e per $m revenue, measured) | **+0.058** | 0.51 | 135 |
| Carbon intensity, companies with 5 or more facilities | **-0.208** | 0.054 | 86 |
| Carbon intensity, residualised within GICS sector | -0.087 | 0.32 | 135 |
| Scope 1 absolute tonnes | +0.105 | 0.23 | 135 |
| Our composite percentile | +0.050 | 0.56 | 142 |
| Our composite median rank | -0.050 | 0.56 | 142 |
| Vendor ESG consensus percentile | -0.092 | 0.28 | 139 |
| Our physical-risk pillar | -0.062 | 0.47 | 142 |
| Market capitalisation (log) | +0.159 | 0.059 | 142 |

Not one of these is significant at 5%. **Carbon rank explains 0.33% of the variance in water
rank.** Water is not a restatement of anything we already show.

Three checks that the answer is not an artefact of the metric we chose:

| Alternative water metric against carbon intensity | rho | p | n |
|---|---|---|---|
| Mean baseline water stress score (0-5) | -0.147 | 0.090 | 135 |
| CO2-weighted water stress score | -0.053 | 0.55 | 128 |
| Share of facilities in Extremely High stress only | +0.199 | 0.021 | 135 |
| Share of facilities over a falling water table | +0.184 | 0.033 | 135 |

Two of the four lean slightly positive, two slightly negative, none above 0.2. The signal is
absent, not hidden by the choice of metric.

The negative sign on the 5-facility subset is the most interesting number in the table, and it has
a physical explanation. America's biggest carbon emitters are coal and gas utilities in the wet
East. America's most water-stressed basins are in the arid West and Southwest. Evergy is the most
carbon-intense company in the covered set at 4,224 t CO2e per $m revenue, the 99th percentile, and
**zero** of its 24 facilities sit in a High or Extremely High stress basin. Broadcom is at 0.96
t CO2e per $m, the 7th percentile, and its one US reporting facility sits in an Extremely High
stress basin. A carbon-only score rates those two backwards on water, and it is not close.

**The obvious attack, answered.** The 142 companies we can score are selected on having a GHGRP
facility, which is a carbon-based selection. Could restriction of range be flattening a real
correlation? No. Carbon intensity inside these 142 spans 0.5 to 4,224 t CO2e per $m revenue, four
orders of magnitude. That is not a restricted range. What we cannot claim is anything about the
361 companies with no US reporting facility, and we do not.

## 2. Sector pattern: not the same sectors

Percentiles are within the 142 scored companies. High percentile is the bad end on both axes.

| GICS sector | n | facilities | median share in High+ stress | median carbon pct | median water pct | water minus carbon |
|---|---|---|---|---|---|---|
| Information Technology | 11 | 33 | **50.0%** | 36.3 | 82.4 | **+46.1** |
| Energy | 18 | 1,585 | 31.9% | 69.3 | 64.8 | -4.5 |
| Materials | 20 | 266 | 23.4% | 63.0 | 53.0 | -10.0 |
| Utilities | 30 | 863 | 20.9% | 88.5 | 48.2 | **-40.3** |
| Health Care | 12 | 29 | 20.0% | 13.7 | 45.1 | **+31.4** |
| Consumer Staples | 16 | 117 | 10.6% | 33.3 | 37.9 | +4.5 |
| Consumer Discretionary | 5 | 37 | 0.0% | 21.5 | 16.2 | -5.3 |
| Industrials | 24 | 547 | 0.0% | 27.0 | 16.2 | -10.8 |

The two sectors at the extremes are the two that invert. Utilities carry the carbon (88th
percentile) and are middling on water (48th). Information Technology is below the median on carbon
(36th) and worst in the index on water (82nd). Health Care is the cleanest sector on carbon (14th
percentile) and sits mid-pack on water (45th).

Sub-industry is where it sharpens, because semiconductors and brewers get averaged away at sector
level:

| Sub-industry | n | facilities | mean share in High+ stress | median carbon pct | median water pct |
|---|---|---|---|---|---|
| **Semiconductors** | 10 | 28 | **57.3%** | 34.4 | 82.4 |
| Construction Materials | 2 | 17 | 44.2% | 70.7 | 76.9 |
| Multi-Utilities | 12 | 286 | 35.9% | 87.8 | 69.7 |
| Integrated Oil & Gas | 2 | 297 | 35.9% | 57.0 | 68.7 |
| Biotechnology | 3 | 5 | 33.3% | 14.1 | 82.4 |
| Oil & Gas Refining & Marketing | 3 | 284 | 30.9% | 67.4 | 67.6 |
| Oil & Gas Exploration & Production | 8 | 351 | 30.7% | 69.6 | 61.4 |
| Aerospace & Defense | 8 | 41 | 28.2% | 24.1 | 48.4 |
| Packaged Foods & Meats | 6 | 47 | 25.8% | 20.7 | 36.1 |
| Pharmaceuticals | 5 | 14 | 21.3% | 13.3 | 16.2 |

The usual suspects the challenge names are real in our data, and they are real for a physical
reason: US fabs were built in Arizona, New Mexico, Utah, Idaho and coastal California, which is
where the water stress is. The caveat is honest and should be stated before anyone else states it:
**Information Technology rests on 33 facilities across 11 companies.** The direction is
unambiguous, the denominator is small, and semiconductors are not monolithic. Analog Devices is 0
of 4 and NXP is 0 of 1.

## 3. Named examples

Carbon percentile and water percentile are both within the 142. Facility counts are the
denominator, printed every time.

### Clean on carbon, exposed on water

Five or more facilities, so the denominator holds up:

| Ticker | Company | t CO2e / $m rev | carbon pct | in High+ stress | in Extremely High | water pct |
|---|---|---|---|---|---|---|
| PEP | PepsiCo | 3.5 | 23 | 5 of 10 | 2 of 10 | 82 |
| ABT | Abbott Laboratories | 3.4 | 22 | 2 of 5 | 1 of 5 | 74 |
| GE | GE Aerospace | 4.0 | 27 | 5 of 13 | 2 of 13 | 71 |
| FCX | Freeport-McMoRan | 20.5 | 44 | 5 of 9 | 5 of 9 | 86 |
| MRK | Merck & Co. | 6.1 | 33 | 2 of 5 | 2 of 5 | 74 |
| TAP | Molson Coors | 27.6 | 47 | 3 of 6 | 3 of 6 | 82 |
| INTC | Intel | 14.6 | 40 | 2 of 5 | 1 of 5 | 74 |
| IFF | Intl Flavors & Fragrances | 27.8 | 47 | 3 of 7 | 0 of 7 | 77 |

Below the 5-facility floor, and worth quoting only with the denominator visible, because these are
the sharpest cases in the dataset:

| Ticker | Company | t CO2e / $m rev | carbon pct | in High+ stress |
|---|---|---|---|---|
| MDLZ | Mondelez | 0.51 | 2 | 1 of 1 |
| AVGO | Broadcom | 0.96 | 7 | 1 of 1, Extremely High |
| QCOM | Qualcomm | 1.36 | 9 | 2 of 2, both Extremely High |
| MU | Micron Technology | 19.6 | 42 | 2 of 2, 1 Extremely High |
| ON | ON Semiconductor | 4.1 | 28 | 1 of 1 |

The places, because a claim needs an address behind it:

- **Broadcom**, Avago Technologies, Larimer County, Colorado. Extremely High. 34,457 t CO2e.
- **Qualcomm**, Morehouse Drive and Pacific Center, both San Diego County, California. Both
  Extremely High.
- **Micron**, Boise, Ada County, Idaho, Extremely High. Manassas, Virginia, High.
- **Intel**, Ocotillo Campus, Maricopa County, Arizona, Extremely High, 378,991 t CO2e. Rio Rancho,
  Sandoval County, New Mexico, High. Its two Oregon campuses are Low, which is why Intel is 2 of 5
  and not 5 of 5.
- **Molson Coors**, the Golden Brewery, Jefferson County, Colorado, Extremely High, 224,200 t CO2e.
  The brewery whose entire brand is Rocky Mountain spring water is in an Extremely-High-stress
  basin, and so is the bottle plant next door and the Fort Worth brewery.
- **PepsiCo**, the Frito-Lay cogen plant in Kern County, California, Extremely High, and Frito-Lay
  in Craighead County, Arkansas, Extremely High, on the over-drafted Mississippi alluvial aquifer.
- **Merck**, Rahway and Union, New Jersey. Both Extremely High, which surprises people who assume
  water stress is a Western problem.
- **Newmont**, all three facilities in Eureka County, Nevada, all Extremely High, including the TS
  Power Plant at 1,088,648 t CO2e. Newmont is the 51st percentile on carbon intensity and 100% of
  its facilities and 100% of its measured CO2e sit in Extremely-High-stress basins.

Weighting by the CO2e we already measure rather than by facility count sharpens several of these,
because the exposed sites are often the big ones. **76.3% of Molson Coors' measured CO2e, 62.2% of
Intel's and 41.9% of PepsiCo's** sits in High or Extremely High stress basins, against facility
shares of 50%, 40% and 50%. This is the column that connects the water axis back to the carbon data
we already hold, and it is in `site/data/water.json` as `share_co2e_high`.

### Heavy on carbon, unexposed on water

| Ticker | Company | t CO2e / $m rev | carbon pct | in High+ stress | 2050 BAU |
|---|---|---|---|---|---|
| EVRG | Evergy | 4,224 | 99 | **0 of 24** | 16.7% |
| PPL | PPL Corporation | 3,239 | 99 | 0 of 14 | 7.1% |
| CF | CF Industries | 3,104 | 96 | 0 of 6 | 0.0% |
| AEE | Ameren | 2,639 | 95 | 0 of 17 | 5.9% |
| AEP | American Electric Power | 2,580 | 94 | 0 of 38 | 7.9% |
| FE | FirstEnergy | 1,192 | 84 | 0 of 24 | 8.3% |
| ETR | Entergy | 3,147 | 97 | 3 of 52 | 5.8% |
| SO | Southern Company | 3,038 | 96 | 6 of 75 | 16.0% |
| DOW | Dow Inc. | 373 | 73 | 0 of 20 | 0.0% |
| EQT | EQT Corporation | 264 | 70 | 0 of 28 | 0.0% |

Evergy is the pair to Broadcom and the two of them are the slide. Evergy is the single most
carbon-intense company in the covered set and has zero water exposure today. Broadcom is in the 7th
percentile on carbon and 100% exposed. Any score that reduces both to one number puts them in the
same place.

Evergy is also the sharpest forward-looking case: 0 of 24 today, 4 of 24 by 2050 under WRI
business-as-usual. Exelon is the largest single deterioration in the index, 17.6% to 47.1%, and
Phillips 66 goes 34.6% to 47.2% across 127 facilities.

Across the 86 companies with 5 or more facilities, **25 have a water percentile and a carbon
percentile more than 40 points apart**, and 43 are more than 25 points apart. Half the covered
universe is materially misranked by a carbon-only view.

## 4. The say-do test, applied to water

We hold voluntary disclosure. The honest result is a null, twice, and the reason is a third finding
that matters more than either.

**Finding first: the voluntary disclosure infrastructure we hold is not about water.** Of 6,942
disclosure documents the World Benchmarking Alliance collected across the S&P 500, **34 have water
in the title. 0.49%.** Eleven are CDP Water Security responses, for eleven companies: Avery
Dennison, Colgate, Dow, Devon, McDonald's, Monster, Procter & Gamble, Ralph Lauren, Sysco,
Tapestry, Tyson. Five of the 34 belong to American Water Works, which is a water utility. **Of the
142 companies we can measure water exposure for, 7 have any water document at all.** Almost
everything a company voluntarily publishes about the environment is carbon.

**Test A, the companies' own words.** We have 263 sustainability reports as text, 68 of them for
companies with a water score. Counting water language per 10,000 tokens, and separately counting
stewardship phrases ("water stewardship", "water stress", "water scarcity", "water risk", "water
security", "watershed", "water replenish" and twelve more):

| | rho | p | n |
|---|---|---|---|
| Water language density against facility exposure | +0.118 | 0.34 | 68 |
| Stewardship phrases against facility exposure | +0.030 | 0.81 | 68 |
| Water language density against carbon intensity | +0.050 | 0.69 | 66 |

Split at the median: the 34 companies that talk about water most have a mean exposure of **34.5%**,
the 34 that talk about it least **31.8%**. Mann-Whitney p = 0.44.

**Test B, the vendor SDG 6 flag.** A vendor codes whether a company is aligned to SDG 6, Clean
Water and Sanitation. Vendor opinion, not a filing, and labelled as such. 117 of our companies are
coded. The 21 flagged aligned average **25.4%** of facilities in stressed basins; the 96 not
flagged average **29.6%**. p = 0.45.

**Conclusion, stated as a null.** Water language carries no information about where the facilities
actually are, in either direction. This is a weaker claim than "companies lie about water", and we
should make the weaker claim, because it is the one the data supports. Companies in stressed basins
do not talk about it more, and companies that talk about it are not less exposed. A reader who
wanted to know which companies have plants in over-drafted basins could not find out by reading
the sustainability reports. They can find out by counting the plants.

That is the same argument as the rest of this project, arriving from a new direction. It is also
why the vendor ESG consensus shows no correlation with water exposure (rho -0.092, n = 139): the
vendors cannot price something almost nobody files.

## 5. Recommendation: a separate axis, not a fifth pillar

**Ship water as a second axis in the interface. Do not fold it into the composite score.**

The argument has four parts, all from the numbers.

**Coverage makes it an imputation rule, not a pillar.** 142 of 503 tickers, 28.2%. A pillar that is
missing for 71.8% of the index is mostly a decision about missing data wearing a pillar's clothes.
The score lane already measured pillar inclusion at 11.3% of rank variance. This would add a fresh
missing-data choice on top of it.

**The simulation says it is not a free change.** Adding water as an equal fifth pillar moves the
median covered company **34 rank places**, p90 106, maximum 135. **59 of the 142 covered companies
move more than 50 places.** Overall Spearman against the four-pillar rank stays at 0.973, which is
exactly the trap: the aggregate looks stable while the companies we actually talk about move a
long way.

**The missing-data convention, which contains no information about any company, moves real
companies further than the water data does.** Two defensible treatments of the 361 uncovered
names, fill the water pillar at the median or renormalise the weights, give:

| Company | facilities | 4-pillar rank | 5-pillar, median fill | 5-pillar, renormalised |
|---|---|---|---|---|
| Illinois Tool Works | 1 | 127 | **19** | **99** |
| Wabtec | 1 | 122 | **18** | **96** |
| Pfizer | 4 | 167 | **50** | **126** |
| Analog Devices | 4 | 140 | 44 | 117 |
| Halliburton | 2 | 271 | 406 | 348 |

The five-pillar *score* is identical for every covered company under both treatments. The entire
80-place swing is the 361 uncovered companies sliding past them. A rank that moves 80 places on a
convention is a rank that collapses the first time somebody asks how the convention was chosen,
and this hackathon's whole point is that we do not put numbers on slides that collapse.

**And the positive reason, which is the strongest.** Water is uncorrelated with everything we
already show: +0.058 against carbon intensity, +0.050 against our composite, -0.092 against the
vendor consensus. That independence is precisely why it is worth having, and precisely why
averaging it away is the wrong move. Averaging two independent axes into one number destroys the
information that made the second axis worth collecting. On two axes, Broadcom sits in the
clean-carbon high-water corner and Evergy sits in the heavy-carbon no-water corner, and both are
visible. On one axis they land on top of each other in the middle.

The low correlation is the argument for showing water. It is the same number that argues against
scoring it.

### What to build

- A second axis in the interface: carbon intensity percentile against water exposure percentile,
  both within the 142. Top right is bad on both.
- Label only companies with 5 or more facilities. Show the rest as points without labels, and show
  the denominator in the tooltip, always.
- The 361 companies with no US reporting facility get an explicit **no data** state. Never a zero,
  never a median, never grey-shaded to look low-risk.
- A facility map layer from `site/data/water.json`, 3,668 points with basin category and measured
  CO2e. This is the picture that makes the argument without a sentence: Intel's Arizona campus and
  Evergy's Kansas plants on the same map, coloured by water stress.
- Aqueduct is labelled `modelled` wherever it appears. The coordinates are filed under penalty; the
  basin stress is a model. We say which is which.

## Files

- `docs/water_risk.md`, this document.
- `site/data/water.json`, 258 KB. 142 companies with 21 fields each, 3,668 facility points, the
  full correlation table, the say-do results, the sector and sub-industry tables and the
  fifth-pillar simulation, plus meta with the licence and the WRI attribution string.
- `src/water_additivity.py`, the analysis. Run:
  `nix develop --command .venv/bin/python src/water_additivity.py`
- `data/interim/water_additivity_dump.json`, every company in the named-example tables, so the
  numbers above can be checked against a run.

Upstream, from the join lane: `src/fetch_aqueduct.py`,
`data/interim/water_facility.parquet` (11,358 facilities),
`data/interim/water_by_ticker.parquet` (142 tickers),
`data/interim/provenance/aqueduct.json`.

## Limitations

1. GHGRP is US-only. 142 of 503 tickers, and a company scored on its US fleet may operate very
   differently abroad. TSMC's Taiwanese fabs are not in this dataset and neither is anything else
   outside the US.
2. Facility counts, not water withdrawals. We know where the plants are, not how much water each
   one takes. A facility in a stressed basin that withdraws nothing is counted the same as a fab.
   This is the honest ceiling of the method, and it is why the metric is named "exposure" and not
   "impact".
3. The Information Technology result rests on 33 facilities across 11 companies, and five of the
   named examples are at or below a 5-facility denominator. Denominators are printed everywhere
   for this reason.
4. Aqueduct is `modelled`. Everything else in this project is a filing or a regulator's meter.
5. 158 offshore platforms carry no water stress by design, and 62 facilities sit in basins Aqueduct
   scores as No Data (37 Hawaii, 11 Alaska, 10 Guam). Both are documented in the join provenance.
6. The say-do corpus is 68 companies with reports from 2020 to 2023, matched against a 2023
   facility fleet. The null result is a null at that sample size; it is not proof of no effect.
