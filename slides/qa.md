# FILED: Q&A card

Five minutes before you go on, in this order:

| | | |
|---|---|---|
| 1 min | section 1 | the three sentences every answer lands on |
| 1 min | section 2 | the one question that can actually hurt, and the scripted answer |
| 2 min | section 3 | skim the bold question lines, read the two you are least ready for |
| 1 min | sections 6 and 7 | the numbers that are **wrong** and the sentences you must not say |

Sections 4 and 5 are lookup, for during the questions, not before them. The
eight-second corridor version is at the top of `script.md`.

---

## 1. If you only get one question

Whatever is asked, the answer lands on one of three sentences:

1. **We only use what a company is legally compelled to file.** No vendor score
   is an input to anything.
2. **We tried to break our own index and it broke.** 312-rank median band out of
   500. So the product is a priced exposure and a sensitivity, not a rank.
3. **What we cannot see is published as a number, not imputed.** 361 of 500 have
   no mandatory tonnage and being measurable makes your rank worse.

Never answer a hard question with "good question". Give the number first, then
the sentence.

---

## 2. The weakest point in the whole submission

**The say-do gap compares two different boundaries, and it is our opening
number.** The promise is usually global and covers Scope 1 and 2. The delivered
trend is US facilities only, Scope 1 only, above 25,000 tCO2e. `say_do.json`
says so in its own caveats. If a judge lands this cleanly, the first 20 seconds
of the deck go with it.

**The answer, in order, and do not improvise it:**

> We compare rates of change, not levels, so a fixed boundary difference
> cancels. It only fails if a company's US footprint moved at a different rate
> from its global one, and the direction of that bias runs against us: US
> industrial footprints have been shrinking, which makes companies look like
> they are delivering more than they promised, not less. It holds on the
> flag-free subset too, 36 of 46 at 78.3 percent, against 77.8 on the full 108.

If pressed further, concede the right thing: "it is a gap between a global
promise and a US trend, and we would not publish it as a compliance finding. We
publish it as a reason not to take the promise at face value."

**Second weakest: the zero weight change is an identity, not a discovery.** The
allocation runs on the rank of value at risk and the model is linear in price,
so a uniform reprice provably cannot move a weight. `allocate.js` says this in a
code comment. This is why beat 3 of the script says **"because the allocation
runs on rank"** out loud. Said first, it reads as rigour. Said in answer to a
judge, it reads as a caught mistake. **Do not drop those eight words.**

---

## 3. The ten hardest questions

**1. "Your emissions are US-only. Chevron operates in 14 countries. Isn't your
score meaningless for it?"**
For Chevron, largely yes, and we publish the multiple rather than hide it:
Climate TRACE puts 9.1 times more of its emissions outside the US than we
measure inside, ExxonMobil 4.3 times, and across the 25 companies with material
foreign assets 582.8 MMT sits abroad against the 375.7 MMT we see. That is why
Chevron carries a coverage tier and why the allocation prices only the tonnes we
can see. The honest claim is not "this is Chevron's footprint", it is "this is
what US mandatory disclosure can support about Chevron, and here is the size of
the rest".

**2. "You score 500 companies but can only measure 139. What are the other 361?"**
88 carry a self-reported figure and are tiered `reported`; 273 carry no
mandatory tonnage at all and are tiered `unmeasurable`; across the whole master
table, 181 of 500 carry no Scope 1 from any source, mandatory, voluntary or
modelled. None of them is given an invented number: they get a rank band that
spans the honest uncertainty and an explicit reason. The cost of that choice is
on slide 5 and it is not flattering to us: median rank 344 if we can measure
you, 224 if we cannot.

**3. "You say weights do not matter. Then why does your framework have weights?"**
Because someone has to choose them, and the industry's habit of arguing about
them while never mentioning imputation is the thing we are attacking. Across the
500, weights are 5.9 percent of the variance in a company's rank against 20.1
for the missing-data assumption; on the 139 we can actually measure they rise to
12.7 percent and become the largest single factor, which we publish too. We also
publish the audit that indicts us: nominal 0.25 each, effective 0.325, 0.231,
0.312, 0.132, d_m 0.595, which is worse than THES at 0.42 and better only than
the 2009 HDI at 0.63 and the SSI at 0.91.

**4. "How is this different from a carbon intensity screen with extra steps?"**
An intensity screen hands you one order and never tells you how fragile it is;
we measure the fragility and it is fatal, 312 ranks of median band and 497 of
500 companies wider than 100 ranks. So the deliverable is not an order, it is a
priced exposure plus the sensitivity that says which assumption moved the money:
missing data 0.201, sector exemptions 0.051, price level 0.000. And it is
empirically not the same screen anyone else runs: Spearman 0.14 against the
vendor consensus, n=470.

**5. "Who actually uses this on a Tuesday morning?"**
A portfolio manager who has to defend a tilt to a client or a regulator and
needs to name the assumption that drove it, which is what the value-at-risk
chain and the sensitivity table are for. A stewardship team picking which of the
84 companies visibly missing their own target to challenge, with the company's
own filing as the evidence. It runs as static JSON in a browser with no server
and no licence fee, so the cost of the second user is zero.

**6. "Your Monte Carlo says nothing is identified. So your own ranking is
useless too?"**
Yes, as a ranking, and slide 2 says so in four words: "ours included". Pin the
design to the single most defensible specification we have, available-case,
absolute lens, all four pillars, and the median band still runs 128.9 ranks wide
and 206.4 on the measured names. What survives is not the order; it is the
interval, the reason it is wide, and a priced exposure that does not need an
order at all.

**7. "Sector reallocation is how every index works. Why is 97.4% a finding
rather than arithmetic?"**
It is arithmetic that nobody publishes, against a regulation whose Article 7
requires a 7 percent annual reduction that a manager can satisfy entirely by
trading. We measured the split for a compliant book: 97.4 percent reallocation,
20.5 percent improvement, -17.8 percent interaction, -0.1 percent selection, and
at lambda 120 with a 70 percent active share it is still 82.3 percent
reallocation. The concrete cost is the one on the slide: Article 6 invites you
to overweight 19 companies cutting 7 percent a year and Article 12 bans 9 of
them outright.

**8. "What stops this dying when the EPA programme is rescinded?"**
Nothing we control, which is exactly why the method is a recipe over a filing
obligation rather than a proprietary dataset: swap GHGRP for the EU ETS or UK
SECR and the same pipeline runs. The exposure is already live and we state it:
GHGRP stops at reporting year 2023 and RY2025 is not due until 30 October 2026,
so we are running on a two-year-old spine. CAMD stack monitors publish through
2026 and cover the power sector whatever happens to GHGRP.

**9. "Is your index just company size in disguise?"**
On the 128 companies with a measured intensity, our percentile does load on
size, +18.5 points per decade of market cap, t=4.08, and that slope is sector
mix: hold GICS sector fixed and it is t=-0.99, p=0.32, gone. The vendors are the
interesting case. Their consensus does not load on size directly at all, t=0.44,
R-squared 0.0004, but it loads hard on disclosure, +18.2 percentile points
within sector, t=4.39, and size buys disclosure, t=6.89; apply a zero-fill rule
to ours and it picks up a +5.2 point size loading, t=2.62. The bias is in the
imputation, not the indicators.

**10. "Do companies lie about their emissions?"**
Mostly no, and we went looking. Of 90 companies where we hold both an EPA
measured and a company self-reported Scope 1, 19 of 90, 21 percent, publish a
number below EPA's; after biogenic CO2, which the GHG Protocol excludes from
Scope 1 and which is 80 percent of International Paper's measured figure, after
consolidation basis, and after our own entity look-ahead, 4 of 90 survive,
Wilson 95 percent interval 2 to 11 percent. That is a rigour result, not an
accusation, and it is emphatically not the Nature Climate Change finding, which
measures restatements of one series over time.

---

## 4. Second tier, one line each

**"Your own $1bn book is 86.1% sector reallocation. Same sin."** Correct, and we
print that number on our own allocation page rather than only on the
regulator's, which a judge who watched the demo has already seen. The difference
is the claim attached: we say the book prices an exposure and never say it
decarbonises anything, while Article 7 requires a 7 percent annual trajectory
and the regulation's own framing sells that as decarbonisation. Criticising the
PAB for reallocation is not "we do better", it is "the label is wrong".

**"How much does your book actually cut?"** At the default price, 1.47 percent
of the book at risk against 3.49 for the index, a 57.7 percent cut in value at
risk for a 19.2 percent active share and an effective breadth of 53 names. Every
one of those numbers is on the page, including the four mega-caps whose weight
the 5 percent cap moves before the carbon penalty touches them.

**"A billion dollars is nothing."** Correct, 0.00144 percent of the index; the
allocation answers the question as asked and the method does not care about the
size of the book.

**"Why is your carbon model cutting NVIDIA and Apple?"** It is not: AAPL 6.95,
GOOGL 5.94, MSFT 5.28 and NVDA 7.54 percent breach the 5 percent UCITS
single-issuer cap, so most of those moves are the cap redistributing mega-cap
weight, and `penalty.json` says so in `reference.position_cap_note`.

**"Berg et al. found 0.38 to 0.71. What did you find?"** Worse: 12
cross-lineage pairs spanning rho -0.15 to 0.84, only 3 of them inside Berg's
band and 6 below it, and three of the six public "raters" are re-uploads of one
source correlating at 0.99998, so some of the apparent agreement in public ESG
data is the same file counted twice.

**"How do you know the company matching is right?"** 49 of 50 on a
tonnes-stratified random sample, 98 percent precision, Wilson 89.5 to 99.6, 25
of 25 on the top-100 rows by tonnes, tonnes-weighted precision on the RY2023
basis 100.00 percent, and zero recall failures in 30 sampled uncovered tickers.

**"Isn't fuzzy matching doing the work?"** The opposite: `token_set_ratio`
returns 100 for any token subset, so on this data ENERGY matches ENTERGY and
PORTLAND GENERAL ELECTRIC matches GENERAL ELECTRIC, which is why the stage runs
at threshold 90 behind a head-token guard and accepts one GHGRP string and two
CAMD strings worth 0.0 MMT of current-year emissions.

**"Did anyone independent check you?"** Yes, and they found a real error: a
teammate's separate extraction was right that our Scope 1 included biogenic CO2,
which the GHG Protocol excludes, so our paper and packaging numbers were 5x too
large and we took the fix; their own entity resolution was worse than ours, low
by more than 50 percent on 11 of 114 shared tickers including PEG at 0.03
percent of the true figure.

**"Your three sources validate each other?"** Partly circular and we say so:
eGRID republishes EIA generation and reads the same CAMD monitors, so the
reconciliation validates the ORIS join, not source independence.

**"Why is water not in the score?"** Because it is a second axis, not a
restatement: Spearman 0.058, p=0.51, n=135, carbon explains 0.3 percent of the
water ranking, and 57.3 percent of US semiconductor reporting facilities sit in
High or Extremely High stress while the sector is near the clean end on carbon.

**"Do companies that talk about water manage it better?"** No measurable
difference: the 34 companies that name water most have 34.5 percent of
facilities stressed, the quietest 34 have 31.8, Mann-Whitney p=0.44, and only 34
of 6,942 voluntary disclosure documents mention water in the title.

**"Is the credibility pillar not built on voluntary data?"** The promise is,
because a promise can only come from the company; every quantity we **measure**
is mandatory, and the pillar scores the gap between their voluntary claim and
our mandatory measurement, which is the opposite of trusting the claim.

**"Your foreign-exposure number comes from a model."** It does, Climate TRACE,
and it is used only to size the blind spot and is never an input to a score or a
weight; drop the three companies whose ownership view we cannot balance and the
visible share rises from 39 to 73 percent on the remaining 22.

---

## 5. The numbers card

| | |
|---|---|
| Say-do | 84 of 108 = 77.8% missing. Promised 5.92 %/yr, delivered 1.87. Gap +2.91. 24 beating, 33 rising. Flag-free subset 36 of 46 = 78.3%, median gap +2.62 |
| Rank band | median 312.5 ranks of 500. 497 of 500 wider than 100. Min 58, max 495 |
| Sobol, all 500 | missing data .201, pillars .113, sector-relative .070, normalisation .069, weights .059, aggregation .013. First order sums to .525 |
| Sobol, measured 139 | weights .127, pillars .110, missing data .107 |
| Pinned specification | available-case only 144.5 ranks. Absolute + available-case + four pillars 128.9, measured 206.4 |
| Weight audit | nominal .25 each, effective .325 / .231 / .312 / .132, d_m 0.595 (2010 HDI .07, THES .42, 2009 HDI .63, SSI .91) |
| Coverage, score lane | 139 measured, 88 reported, 273 unmeasurable. Median rank 344 / 224 / 224 |
| Coverage, master table | 319 of 500 carry a Scope 1 from some source, 181 carry none |
| Price | NGFS Phase 5 REMIND, Net Zero 2050, US, 2030 = 283.70 US$2010/t. Deflator 1.44. GCAM says 98.60 for the same cell |
| Invariance | 284 to 1000 $2010/t scales value at risk 3.52x (= 1000/283.7). Largest weight change 0.00 bp, by construction. Switch the 181 treatment and it is 30 bp |
| Allocation sensitivity | treatment .201, sector exemptions .051, Scope 3 .007, price level .000 |
| Missing-data money | the 181 non-filers get $121.1m neutral-rank, $140.7m sector-median, $184.3m threshold, $244.4m zero-fill. Swing $123.3m |
| PAB | reallocation 97.4%, improvement 20.5%, interaction -17.8%, selection -0.1%. Still 82.3% at lambda 120 and a 70.5% active share. Exclusions alone 63.1% vs 50% required, lambda 0, 67 names, 8.54% of cap |
| Article 6 vs 12 | 19 qualifiers cutting 7%/yr, 9 of them banned: AEP, AES, EIX, EXE, FE, GE, MO, NI, NRG |
| Understatement | 19 of 90 (21%) look low, 4 of 90 (4%) survive, Wilson 2-11% |
| Disclosure bias | vendor ~ size t=0.44 R2=.0004; vendor ~ disclosure within sector +18.2 t=4.39; disclosure ~ size t=6.89; ours ~ disclosure -5.2 t=-0.58 p=.561; zero-filled ours ~ size +5.2 t=2.62 |
| Boeing | files 23% of the checklist, 4.4th percentile vendor ESG, 3.24 t/$m, cleaner than 83% of what we measure |
| Entity resolution | 49/50 = 98%, Wilson 89.5-99.6. Top-100 by tonnes 25/25. RY2023 tonnes-weighted 100.00%. Recall 0 failures in 30. Vistra 2022 was overstated 12.6% before the fix |
| Water | rho 0.058 p=0.51 n=135. Join 11,200 of 11,358 = 98.6%. 142 of 503 tickers scored. Semis 57.3% High+ |
| Vendors | ours vs consensus Spearman 0.14, n=470. Cross-lineage rho -0.15 to 0.84. 106 of 418 flip quartile |
| Scale | $1bn = 0.00144% of the index. GHGRP 2023 tonnes matched 44.8%. CAMD 2025 attributed 54.0% |
| Vintage | GHGRP ends RY2023. RY2025 due 30 Oct 2026. CAMD runs to 2026 |
| Turnover | 62 of 503 left the index since Aug 2023; 37 still file with the SEC |

---

## 6. Four numbers from the first draft that did not reproduce

These were checked against `site/data/`, `data/interim/` and `docs/`. **Do not
say them.** The replacement is what the repo actually contains.

| Draft said | Repo says | Use instead |
|---|---|---|
| "22% of the 90 look like they understate" | 19 of 90 is 21%. The 22% figure is 21 of **95**, a different sample, at adjustment level 0 (`docs/reported_vs_measured.md` line 77) | **21 percent, 19 of 90** |
| "zero-fill gives our index a +4.35 size loading, unscored leaves it at -2.66" | No such pair anywhere. Regression 6 in `bias.json`: zero-filled score ~ log market cap, beta **+5.16**, t=2.62, p=0.009, n=499. Available-case, regression 3p: **+18.46**, t=4.08, n=128, and that is sector mix, t=-0.99 within sector | **+5.2 zero-filled, t=2.62; within sector t=-0.99** |
| "a teammate's independent matcher agrees on 84 of 122 shared tickers to 0.1%" | Not in the repo. `docs/master_table_spec.md`: their two artifacts agree with **each other** on 72 of 116; their wide columns agree with our fossil-only series on 66 of 114 and are low by >50% on 11 | **They were right about biogenic and we took the fix. Their entity resolution was worse than ours.** |
| "at token_set_ratio 80 the top 36 candidates by tonnes are 36 false positives" | Not measured anywhere. The real evidence: subsets score 100 (ENERGY/ENTERGY, PORTLAND GENERAL ELECTRIC/GENERAL ELECTRIC), so the lane runs at 90 with a head-token guard and accepts 3 strings worth 0.0 MMT | **The named collisions, and "fuzzy buys us three strings and zero tonnes"** |

Two more corrections landed on the slides themselves: the slide 1 scatter had
its axes inverted (missing the promise is ABOVE the identity line, not below),
and slide 5's "62 tickers that no longer exist" was wrong, they left the
**index** and 37 still file with the SEC.

---

## 7. Never say

- "The Nature paper found 78 percent." It did not. It found 58 percent of public
  firms and 74 percent of the S&P 500 **restating**. Ours is a different
  quantity on a different sample. Cite it as the premise, never as our result.
- "Companies are lying." 4 of 90, and the interval runs to 11 percent.
- "A Paris aligned fund sells the decarbonisers" as a claim about the held book.
  The compliant book's held names cut at 5.71 %/yr against the index at 5.03.
  Say Article 6 against Article 12 instead: 19 qualifiers, 9 banned.
- "Our sources independently validate each other." eGRID reads the same CAMD
  monitors.
- "We cover the S&P 500." We measure 139 of it.
