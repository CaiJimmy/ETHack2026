# Coverage and validation

What the data actually supports, measured rather than asserted. Everything below is printed by
`src/validate_coverage.py`, which reads only tables already on disk and writes
`data/interim/vendor_rank_correlation.parquet`, `gics_proxy_validation.parquet`,
`coverage_summary.parquet` and `validation_summary.json`, with the CAMD national share in section 4
coming from `src/verify_camd_share.py`. No figure in this document was typed by hand. Run them and
the numbers reproduce.

Four questions: how far apart the ESG vendors are on our own universe, how well our GICS exclusion
proxy reproduces an independent screen, how much a US-only emissions spine understates the index,
and what every layer really covers out of 503 listings.

## Headline

| Question | Answer |
|---|---|
| Do the vendors agree? | No. 12 cross-lineage pairs span **rho -0.15 to 0.84**. One in four companies sits in the top quartile on one source and the bottom quartile on another |
| Is the GICS exclusion proxy good enough? | **Yes as a fallback, never as the decider.** Against measured segment revenue, kappa **0.83**; against a published institutional list, **0.77**; against the vendor screen, **0.19**, and on that rule the vendor screen is the one measuring the wrong thing |
| How blind is a US-only spine? | On the 25 companies with material foreign assets we see **39%** of their implied global Scope 1. The foreign tonnes alone are **48%** of everything our spine measures for the whole index |
| How much of the index carries a tonnage? | **139 of 503** listings have a mandatory measured tonnage, 115 have a voluntary one, 228 have either. **273 listings carry no emissions number of any kind from any source** |

## 1. The vendors do not agree with each other

Six free ESG datasets landed in `vendor_scores.parquet`. For each, the `esg_total` metric was put on
one axis (risk scales multiplied by -1 so that higher always means better) and every pair was ranked
against the other over the primary listings both cover. 486 companies, 15 pairs.

Spearman rho above the diagonal, pair count below it:

| | alistairking | flamingmasamune | mashinii | mrbossjaysrb | pritish509 | rikinzala |
|---|---|---|---|---|---|---|
| **alistairking** | 1.00 | -0.149 | -0.029 | -0.077 | -0.129 | -0.129 |
| **flamingmasamune** | n=347 | 1.00 | 0.414 | 0.748 | 0.948 | 0.949 |
| **mashinii** | n=372 | n=403 | 1.00 | 0.359 | 0.446 | 0.447 |
| **mrbossjaysrb** | n=215 | n=227 | n=262 | 1.00 | 0.838 | 0.838 |
| **pritish509** | n=341 | n=395 | n=398 | n=225 | 1.00 | 1.000 |
| **rikinzala** | n=341 | n=394 | n=397 | n=225 | n=397 | 1.00 |

On the environmental pillar alone, which is the part we care about, 10 pairs run from **-0.248 to
0.9999** with a median of **0.307**. The pillar agrees less than the total does.

### Read the matrix in two halves

Three of the six sources are not independent raters. pritish509 and rikinzala correlate at **0.99998**
on 397 names, and flamingmasamune sits at 0.948 and 0.949 against them. They are re-uploads of the
same dead Yahoo Finance `esgScores` pull. Those three pairs say nothing about rater disagreement, and
quoting a six-by-six matrix as six raters agreeing would be wrong.

The 12 cross-lineage pairs are the ones that test rater disagreement, and they span **-0.149 to 0.838**.

### Does it reproduce Berg, Koelbel and Rigobon?

Their six commercial raters correlate **0.38 to 0.71**. Of our 12 cross-lineage pairs, **3 fall inside
that band, 6 fall below it and 3 above**. Taken at face value we find far worse agreement than they
did.

That reading is too convenient, so here is the honest version. One source, alistairking (ESG
Enterprise), ranks the index close to backwards relative to everything else. The vendor-benchmark lane
verified the orientation against that file's own grade letters: ConocoPhillips holds the highest total
score in it with an A grade and AA on environment, while Adobe gets 621 and a B. It behaves like a
measure of disclosure volume, not of environmental performance. Set it aside as measuring a different
construct and the remaining **7 cross-lineage pairs run 0.359 to 0.838, median 0.447**. That brackets
the published 0.38 to 0.71 range and widens it at both ends.

So the finding is not "the literature is wrong". It is that the published range is measured across
raters who all agree they are scoring the same thing. Widen the sample to everything an analyst can
actually download and one of six sources inverts the ranking, which is a stronger version of the same
point.

### What the disagreement costs you

418 companies carry a percentile from at least three sources. The gap between the highest and lowest
percentile for one company:

- median **46.0 percentile points**
- 90th percentile **79.9 points**
- **186 companies (44%)** span more than 50 points
- **106 companies (25%)** are top-quartile on one source and bottom-quartile on another

Widest: CBRE 98.7 points across six sources, Elevance 96.9 across five, Adobe 95.6, ConocoPhillips
95.0, CDW 95.0, Lowe's 94.1. Vintage is part of it. flamingmasamune dates Elevance to 2018-10-01 with
a risk score of 49.33 while every other source puts it near 11.

### The check that matters for us

Vendor consensus percentile against the Scope 1 we measure from mandatory filings, 2023, 125 companies
with both:

| | rho | p |
|---|---|---|
| vs emissions intensity (t per $m revenue) | **-0.131** | 0.145 |
| vs absolute tonnes | **-0.198** | 0.027 |

The sign is right, dirtier companies do score slightly worse, but the relationship is weak enough to
be invisible in practice and the intensity version is not significant at n=125. A consensus of six ESG
datasets carries almost no information about how much carbon a company actually put in the air
according to EPA. That is the argument for building the score from filings.

**Caveat on this section.** These are free re-uploads of vendor data on Kaggle, not direct vendor
feeds, and their vintages span 2018 to 2026. Some of the disagreement is staleness rather than
methodology. We did not scrape any vendor site to check, and we are not going to.

## 2. The GICS exclusion proxy

Article 12 of Regulation (EU) 2020/1818 excludes companies by revenue share from six activities. A
sector code is not a revenue share, so the question is how often the proxy gets the same answer as
something that measures revenue. Three independent screens exist in
`revenue_exclusions.parquet`: measured SEC segment revenue, a commercial vendor involvement screen,
and Norges Bank Investment Management's published exclusion list.

Per rule, GICS against each comparator where both spoke:

| Article | Comparator | n | TP | FP | FN | Precision | Recall | Kappa |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 12(1)(a) weapons | vendor | 387 | 2 | 9 | 0 | 0.182 | 1.000 | **0.302** |
| 12(1)(a) weapons | NBIM | 500 | 8 | 5 | 1 | 0.615 | 0.889 | **0.721** |
| 12(1)(b) tobacco | vendor | 387 | 2 | 0 | 21 | 1.000 | 0.087 | **0.152** |
| 12(1)(b) tobacco | SEC segment | 306 | 2 | 0 | 0 | 1.000 | 1.000 | **1.000** |
| 12(1)(b) tobacco | NBIM | 500 | 2 | 0 | 0 | 1.000 | 1.000 | **1.000** |
| 12(1)(d) coal | SEC segment | 257 | 0 | 0 | 2 | n/a | 0.000 | **0.000** |
| 12(1)(e) oil | SEC segment | 299 | 8 | 1 | 0 | 0.889 | 1.000 | **0.939** |
| 12(1)(f) gas | SEC segment | 312 | 2 | 0 | 2 | 1.000 | 0.500 | **0.664** |
| 12(1)(c) conduct | any | 0 | | | | | | no sector proxy exists |

Pooled over every rule where both screens spoke:

| Comparator | n | Precision | Recall | Kappa |
|---|---:|---:|---:|---:|
| SEC segment revenue | 1,174 | 0.923 | 0.750 | **0.825** |
| NBIM published list | 1,000 | 0.667 | 0.909 | **0.766** |
| Commercial vendor screen | 812 | 0.308 | 0.160 | **0.194** |

### Every disagreement, by name

**12(1)(b) tobacco, GICS vs vendor, kappa 0.152.** The vendor flags 21 companies GICS does not: ADM,
ADP, ALL, APO, CMCSA, COST, CVX, DG, DIS, DLTR, DRI, HLT, HST, IFF, KR, LVS, MGM, RCL, TSCO, WMT,
WYNN. Both flag MO and PM. The vendor field is an *involvement* screen and catches anyone who retails
cigarettes, which is why Walmart, Costco, Kroger, Chevron and Disney are on it. Article 12(1)(b)
excludes "cultivation and production of tobacco". Against the two screens that test production, SEC
segment revenue and NBIM, the GICS proxy scores **kappa 1.00 on both**: MO and PM, exactly. The low
kappa is the vendor screen failing to match the regulation, not the proxy failing to match reality.

**12(1)(a) weapons, GICS vs NBIM, kappa 0.721.** GICS flags five NBIM does not: AXON, GE, HWM, RTX,
TDG. NBIM flags one GICS does not: **J** (Jacobs Solutions), excluded for production of nuclear
weapons, which no sector code can see because Jacobs files as engineering services. Both flag BA, GD,
HII, HONA, LHX, LMT, NOC, TXT. The vendor screen here flags only LHX and LMT out of 387 names, so its
recall against NBIM is poor too (NBIM vs vendor on this rule: kappa 0.440).

**12(1)(e) oil, GICS vs SEC segment, kappa 0.939.** One disagreement: **EXE** (Expand Energy). GICS
puts it in Oil & Gas Exploration & Production, so the proxy excludes it. Its own segment revenue is
3.7% oil, well under the article's 10% threshold. The proxy is wrong and the filing is right. This is
exactly the case a revenue test exists to catch.

**12(1)(f) gas, GICS vs SEC segment, kappa 0.664.** Two disagreements, both proxy misses: **EQT**
(81.2% natural gas) and **EXE** (61.3%) clear the 50% bar on measured segment revenue, and no GICS
sub-industry mapping would have found them.

**12(1)(d) coal, GICS vs SEC segment, kappa 0.000.** GICS flags nobody, because the S&P 500 contains
no coal miner and the Coal & Consumable Fuels sub-industry has zero constituents. Segment revenue
flags **CSX** (13.5% of revenue from coal haulage) and **NSC** (12.2%). Article 12(1)(d) lists
"distribution" among the excluded coal activities and rail haulage of coal is distribution on the
plain reading. That is a legal call, not a data one, and it is carried behind a `sec_broad_reading`
column so the portfolio builder can switch it off. Kappa 0.000 here means the proxy is blind to the
only way this rule bites in this index, not that it is noisy.

### Where the proxy decides alone

Of 3,000 primary company-rule rows, the deciding source is measured segment revenue for 1,174, the
GICS proxy for 1,317, and NBIM for 509. 40 companies are excluded on `flag_best`. **15 of them rest on
the GICS proxy for at least one rule with nothing to check it**, across 17 rule rows:

| Rule | Tickers decided by GICS alone |
|---|---|
| 12(1)(a) weapons | AXON, GE, HWM, RTX, TDG |
| 12(1)(e) oil | APA, COP, EQT, KMI, OXY, TPL, TRGP, WMB, XOM |
| 12(1)(f) gas | OKE, TRGP, WMB |

All 17 have `flag_sec` null: those filers publish no product or segment axis, so no revenue share is
recoverable at any price. For ExxonMobil, Occidental, ConocoPhillips and APA the proxy is obviously
right on the merits. For Kinder Morgan, Targa and Williams it is a midstream sub-industry standing in
for an oil revenue share, and Kinder Morgan's own segment data puts it at 65.0% natural gas pipelines
with the oil share undetermined. Those three are the softest exclusions in the portfolio.

### Ship it, with this caveat

Ship the GICS proxy as the fallback, never as the decider where a filing speaks. That is what
`flag_best` already does: measured revenue share wins, the proxy fills the gap, and `flag_dq` records
which happened (1 for a measured share against the article's own threshold, 3 or 4 for the proxy, 5
for nobody). On this index the proxy agrees with measured segment revenue at kappa 0.825 and gets
exactly two companies wrong, both named above, both already corrected in the output.

The caveat to say out loud: **the proxy is structurally blind to two things.** It cannot see an
activity that does not define a company's sector, which is how it misses Jacobs on nuclear weapons and
CSX on coal distribution. And it cannot see a conduct rule at all. Article 12(1)(c), the UN Global
Compact and OECD Guidelines test, has no sector proxy and no vendor coverage in our data. It rests
entirely on NBIM's published decisions and yields three exclusions in 500 companies: CAT, DUK, FCX.
That is a findings list, not a systematic review. Any company not on it is untested, not clean.

## 3. How badly a US-only spine understates the index

Climate TRACE's bulk sector packages ship an asset ownership layer with parent name, LEI and equity
share. Joined to our universe it names an owner for **73 of 503 listings**. 25 of those hold at least
250,000 tonnes abroad, and that set is where the bias estimate lives. All figures are 2023, the last
year EPA GHGRP has published, and all use equity share rather than gross asset emissions because joint
ventures otherwise double count (73 tickers sum to 2,379 MMT gross against 1,508 MMT on equity).

| | MMT |
|---|---:|
| Measured US Scope 1 across those 25 companies (EPA GHGRP) | **375.7** |
| Climate TRACE attribution abroad for the same 25 | **582.8** |
| Share of their implied global Scope 1 our spine sees | **39%** |
| For scale: everything our spine measures across the whole index in 2023 | 1,209 |
| The foreign tonnes above, as a share of that | **48%** |

Three of the 25 (APA, EOG, SLB) sit entirely in subsectors where Climate TRACE names no US owner at
all, so their non-US share is 100% by construction. On the other 22, where the ownership layer sees
both sides, measured US is 369.2 MMT against 133.3 MMT abroad and the visible share is **73%**. Quote
both numbers. 39% is the raw reading and 73% is the reading with the known ownership blind spot
removed.

### The names that look clean only because the plant is abroad

Non-US tonnes as a multiple of measured US tonnes, 2023:

| Ticker | Company | Measured US, MMT | Climate TRACE non-US, MMT | Multiple | Ownership blind spot |
|---|---|---:|---:|---:|---|
| **APA** | APA Corporation | 1.34 | 25.29 | **18.8x** | yes, upstream only |
| **CVX** | Chevron | 23.05 | 210.26 | **9.1x** | no |
| **FCX** | Freeport-McMoRan | 0.47 | 3.43 | **7.3x** | no |
| **GE** | GE Aerospace | 0.27 | 1.74 | **6.4x** | no |
| **OXY** | Occidental Petroleum | 11.26 | 71.28 | **6.3x** | no |
| **XOM** | ExxonMobil | 42.28 | 180.18 | **4.3x** | no |
| **SLB** | Schlumberger | none filed | 1.30 | n/a | yes, upstream only |

Freeport-McMoRan and GE Aerospace are the cleanest examples of the point. Freeport files 0.47 MMT in
the US and Climate TRACE attributes 3.4 MMT to its copper mines, 2.58 MMT of it in Indonesia and the
rest in Peru and Chile. GE Aerospace files 0.27 MMT in the US and carries 1.7 MMT abroad in power
generation equity stakes across the UAE, Bangladesh, Ghana and Chile, which is a business line no
GICS code and no US filing puts anywhere near its emissions profile. Neither company sits in the oil
and gas subsectors where the ownership layer is US-blind, so the multiple is a finding, not an
artefact. Microsoft belongs in the same category one order of magnitude down: 79.6 kt in Ireland and
no US GHGRP filing at all.

### Two validations and one warning

**The US comparison holds up well.** On the 44 companies where Climate TRACE attributes more than 1
MMT inside the United States, the ratio of its US figure to our measured EPA figure has a **median of
0.95, quartiles 0.71 to 1.05**. Satellite-derived modelling and mandatory stack filings agree within
5% at company level, reached through two completely different ownership routes. That is the strongest
independent check on the whole emissions spine.

**The global comparison does not.** Climate TRACE's asset boundary is not the corporate Scope 1
boundary. For the eight companies where we also have a self-published global Scope 1:

| Ticker | FY | Company reported, MMT | Climate TRACE, MMT | Ratio |
|---|---|---:|---:|---:|
| MPC | 2022 | 33.70 | 35.06 | 1.04 |
| STLD | 2019 | 1.70 | 1.79 | 1.05 |
| MSFT | 2015 | 0.09 | 0.08 | 0.93 |
| **APA** | 2022 | 6.00 | 25.29 | **4.22** |
| SRE | 2021 | 6.80 | 1.92 | 0.28 |
| MLM | 2020 | 4.50 | 0.53 | 0.12 |
| KMI | 2021 | 15.30 | 0.95 | 0.06 |
| AAPL | 2021 | 0.24 | 0.00 | 0.00 |

Refining and steel line up almost exactly. Upstream oil and gas does not: APA's own report says 6.0
MMT global Scope 1 and Climate TRACE attributes 25.3 MMT to the same company, a factor of 4.2. And for
midstream and aggregates Climate TRACE sees almost nothing (Kinder Morgan 0.06, Martin Marietta 0.12).
So the 39% and 73% figures size *an attribution gap*, not a reconciliation against what these
companies say about themselves. n=8 is too thin to correct with. State it as the direction and rough
scale of the bias, not as a number to subtract.

**The reach limit matters more than either ratio.** Climate TRACE's ownership layer names only 73
of 503 listings, and it only covers power, manufacturing, fossil fuel operations and mineral
extraction. For the other 430, most of the index, the non-US question is untested rather than
answered. A software company with a factory contract in Asia looks identical to one with no foreign
footprint at all in every dataset we hold.

## 4. Coverage by layer

One row per layer, out of 503 listings and 500 companies.

| Layer | Listings | Companies | % of 503 | Class | Supports | Does not support |
|---|---:|---:|---:|---|---|---|
| Universe and identity | 503 | 500 | 100.0 | mandatory | every join, GICS logic, index weights | nothing, all 503 agree with SEC on CIK |
| Financials, revenue | 503 | 500 | 100.0 | mandatory | intensity denominators, earnings at risk | segment revenue, which the companyfacts API drops |
| Financials, operating income | 502 | 499 | 99.8 | mandatory | the earnings-at-risk numerator | one listing files no operating income line |
| Market cap and float | 502 | 499 | 99.8 | mandatory | portfolio weights, PAB benchmark | forward valuation |
| Matched to a GHGRP facility | 146 | 146 | 29.0 | mandatory | proof entity resolution reached the company | a tonnage; 7 of these report none |
| **Measured Scope 1, GHGRP, any year** | **139** | **139** | **27.6** | mandatory | the headline score, promised vs delivered | non-US, sub-threshold, 2024 onward |
| Measured Scope 1, GHGRP, 2023 | 128 | 128 | 25.4 | mandatory | the current-year score | the same limits, one year narrower |
| Measured power CO2, CAMD, any year | 48 | 48 | 9.5 | mandatory | stack-monitored power CO2, Article 12(1)(g) | anything outside power |
| Measured power CO2, CAMD, 2025 | 40 | 40 | 8.0 | mandatory | the only current feed we have | non-power sectors; 2026 is part-year |
| Plant-level intensity, gCO2e/kWh | 61 | 61 | 12.1 | mandatory | the 100 g/kWh electricity-producer test | generation in unconsolidated JVs |
| Voluntary Scope 1, from reports | 112 | 109 | 22.3 | voluntary | a global cross-check on the US spine, to FY2022 | anything current or audited; 17 rows are magnitude-suspect |
| Voluntary Scope 2, either basis | 111 | 108 | 22.1 | voluntary | benchmarking the asset-light names | index-wide Scope 2, or any year after 2022 |
| Voluntary Scope 2, location basis | 10 | 10 | 2.0 | voluntary | the grid comparison a market-based number hides | almost the whole index |
| Voluntary Scope 3 total | 74 | 72 | 14.7 | voluntary | an order of magnitude for the value chain | ranking; every filer draws the boundary differently |
| Voluntary Scope 3 by category | 7 | 7 | 1.4 | voluntary | category structure on worked examples | anything at index scale |
| Grid factor for HQ region, eGRID | 502 | 499 | 99.8 | modelled | a Scope 2 estimate the moment a kWh exists | a tonnage by itself; per-company kWh is not free |
| PAB exclusions 12(1)(a) to (f) | 503 | 500 | 100.0 | mandatory | a decided flag on every rule with its basis | 12(1)(c) conduct |
| of which on measured segment revenue | 317 | 317 | 63.0 | mandatory | a measured revenue share vs the article threshold | filers with no product or segment axis |
| Conduct rule 12(1)(c) | 503 | 500 | 100.0 | voluntary | 3 exclusions from one published list | a systematic norms review |
| Climate targets, NZT or SBTi | 461 | 458 | 91.7 | voluntary | whether a company promised anything | whether the promise is kept |
| of which with a numeric rate | 341 | 339 | 67.8 | voluntary | promised vs delivered as a number | targets with no arithmetic in them |
| Regulatory penalties, non-zero | 468 | 465 | 93.0 | mandatory | conduct with a dollar figure; the other 35 are measured zero | conduct outside the US |
| Vendor ESG, any source | 492 | 489 | 97.8 | vendor | benchmarking, and the disagreement slide | any input to our score; the schema forbids it |
| Vendor ESG, excluding the AI source | 475 | 475 | 94.4 | vendor | the same without a language model in the loop | the same limit |
| Vendor ESG consensus percentile | 489 | 486 | 97.2 | vendor | one comparable number per company | a defensible ranking; its inputs disagree |
| Climate TRACE asset ownership | 73 | 73 | 14.5 | modelled | the non-US gap for heavy industry, EPA validation | the 430 listings with no heavy physical asset |

### The CAMD national share, settled

Two lanes disagreed on the S&P 500 share of 2025 measured power CO2, 54.0% against 49.0%, and neither
could rule out a common-stack double count, because `camd_unit_year.parquet` carries an
`associated_stacks` column. `src/verify_camd_share.py` prints everything below.

| Check | Result |
|---|---|
| Rows keyed by a stack rather than a unit | **0**. EPA's apportioned annual feed already apportions a common stack back to its units, so the column is an attribute, not a second row |
| 2025 unit rows naming a stack | 397 of 3,989, carrying 8.0% of the CO2 |
| Duplicate `(oris_code, unit_id)` keys in 2025 | 0 |
| Our unit sum vs EPA's own `by-facility` aggregation | 1,635.128 against 1,635.128 M short tons over the same 1,311 facilities, difference **0.000 short tons** |
| Our unit sum vs EPA's own `by-state` aggregation | identical again |
| Facilities where our sum exceeds EPA's | **0** |

So the national total is 1,635.1 M short tons, which is 1,483.4 MMT, and there is no double count to
remove. The S&P 500 carries 801.6 MMT of it, **54.0%**, over 40 tickers. The attribution closes:
801.6 MMT attributed plus 681.7 MMT spread over 600 owner strings outside the index sums to the
national total to the tonne. That residual is a long tail, not a missed parent: the largest single
owner in it is the Tennessee Valley Authority at 44.0 MMT, 3.0% of the national total, and the 15
largest hold 28% of the residual between them.

49.0% is 801.6 divided by 1,635.1, metric tonnes over short tons. It is a unit mismatch, not a
different treatment of stacks, and 54.0% is the figure to quote.

### The union, which is the number that matters

- listings with a **mandatory** measured tonnage: **139**
- listings with a **voluntary** tonnage: **115**
- listings with **either**: **228**
- listings with **no emissions number of any kind, from any source, and no Climate TRACE asset**: **273**

More than half the index has no emissions measurement we can point at. That is the honest headline and
it should be on a slide before anyone else says it.

It is also not a join failure. The entity resolution audit sampled 30 uncovered tickers and found zero
matching misses: 25 operate no US facility above the 25,000 tCO2e reporting threshold, 3 are
spinoffs that post-date the data, 2 are deliberate policy exclusions. The gap is what mandatory US
disclosure covers, which is heavy industry and power and almost nothing else.

## What is still missing

Named first, so it cannot be used against us.

1. **273 of 503 listings carry no emissions tonnage at all.** Not from EPA, not from a voluntary
   report, not from Climate TRACE. For those companies our score has no emissions input and the site
   must say so rather than showing a zero.
2. **No non-US mandatory data anywhere.** GHGRP and CAMD are US programmes. Climate TRACE covers the
   gap for 73 listings in four heavy sectors, and its boundary does not match corporate Scope 1 for
   upstream oil and gas (APA at 4.2x its own published figure). For the other 430 listings the foreign
   footprint is untested.
3. **No Scope 3 that can be ranked.** 74 listings have a Scope 3 total, none newer than FY2022, and
   every filer draws the boundary differently. Seven have category detail. Scope 3 is the majority of
   most companies' footprint and we can say almost nothing about it.
4. **Voluntary data is old.** The newest figure anywhere in `scope23.parquet` is FY2022 and only 12
   companies reach it. 83 stop at FY2021. It benchmarks 2020 to 2022, not today.
5. **GHGRP stops at 2023.** Reporting year 2025 is due 30 October 2026. CAMD is the only current feed
   and it only sees power.
6. **Article 12(1)(c) is three companies deep.** CAT, DUK and FCX, all from one published institutional
   list. Absence from that list is not evidence of good conduct.
7. **15 companies are excluded on a sector code alone**, across 17 rule rows, with no filing to check
   them. Twelve of those rows are the oil and gas rules, where the filer publishes no segment axis and
   no revenue share is recoverable at any price.
8. **The vendor benchmark is not six independent raters.** Three of six sources are re-uploads of one
   dead Yahoo pull, one is generated by a language model, and one appears to measure disclosure volume
   rather than performance. The disagreement finding survives all of that; any claim about a specific
   vendor's methodology does not.
9. **Survivorship bias is measured but not corrected.** Today's membership applied to historical
   emissions. 62 of the 503 tickers in the index on 2023-08-30 are gone, and the departed set is
   energy-heavy.
10. **17 voluntary emission rows are order-of-magnitude suspect**, caught by checking a claimed global
    Scope 1 against a US-only measured figure it cannot legally be smaller than. The check only reaches
    24 of the 112 tickers with voluntary Scope 1. The other 88 are unverified.
