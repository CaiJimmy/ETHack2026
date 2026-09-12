# Cold-eye UX critique

Read as a hackathon judge who has never seen this project, has 30 seconds before the next pitch, and
knows what a portfolio is but not what EVIC or 40 CFR Part 98 are.

Method: live site at https://ethack.tyrolize.ch, Chromium at 1280x720, every section screenshotted
and looked at. All counts below are measured off the rendered DOM, not estimated.

---

## 1. Measured baseline

| Thing | Count |
|---|---|
| **Words rendered on the page** | **6 283** |
| Words in the first 720px, on load | 485 |
| Page height | 18 421px, 25.6 viewports of scroll |
| Left nav, repeated on every screen | 50 words |
| 01 Allocate | 458 words in one 720px screen |
| 02 Hero | 212 words |
| 03 Say and do | 341 words |
| 04 Rank intervals | 1 028 words, 3 657px |
| 05 The $1bn fund | 2 144 words, 6 255px |
| 06 What we cannot see | 2 050 words, 5 734px |
| Sliders | 16 |
| Dropdowns | 3 |
| Buttons | 28 |
| **Disclosure controls of any kind** | **0** |

That last row is the whole problem in one number. There is no `<details>`, no drawer, no toggle
anywhere on the site. Every sentence sits at the same level of prominence as every other sentence,
so nothing is prominent. A judge does not triage this page. A judge bounces off it.

The panel-level breakdown, for budgeting the cuts:

- 05: article-by-article 372, Article 12 exclusions 270, Brinson 295, largest holdings 249, what
  this is not 224, who kept the improvement 139, the book 117, missing-data rules 105, tracking
  error 95, where the weight went 45.
- 06: six things this score cannot see 595, vendor bias 500, provenance table 456, coverage tiers
  273, two companies 205.
- 04: variance decomposition 321, Pareto and head-to-head 219, what would narrow the band 176,
  interval chart 127, side card 103.

Two panels, "six things this score cannot see" (595) and the vendor bias regression (500), are each
longer than the entire hero section that carries the argument.

---

## 2. Section by section

### 01 Allocate $1bn: the opening screen, and the one in the video

**1. What is it trying to say?** "Change how you treat the companies you cannot measure and $123m of
a $1bn fund moves." **Can you tell in 5 seconds? No.** The claim is bolded at the end of the third
line of a right-aligned paragraph in the top-right corner, the lowest-attention position on the
screen. The number that proves it, "Spread $123m", is 11px grey text at the bottom of the left
column, below four dollar figures that are each larger than it.

**2. Controls a first-timer gets wrong.**

- **The six `0.000 of advice` chips.** These are the worst thing on the site. Nothing on screen says
  what they are. The only explanation is a `title=` tooltip, which needs a one-second hover to find
  and does not exist on touch. First guess: "this control is broken" or "this value is zero". Real
  meaning: the share of variance in the 500 advised weights that this control explains on its own.
  Worse, the cyan hint box says **"Move the price slider"** while the chip directly above the price
  slider says **`0.000 of advice`**. The screen tells the judge to use a control it has labelled as
  doing nothing.
- **`40 CFR Part 98 threshold`** as a radio label. Guess: a law. Meaning: assume these companies sit
  just under the 25 000-tonne reporting floor.
- **`Abstain`.** Guess: do not invest in them. Meaning: do not score them, renormalise over the names
  we can measure.
- **`BY SECTOR, 0 EXEMPTS`, 11 sliders all reading `284` and `0`.** This block is roughly 40% of the
  left column's height and at default carries zero information: every row is identical to the master
  slider above it. Guess: eleven broken duplicate controls, or a results table someone forgot to
  format.
- **`SCOPE COVERAGE / Scope 1 100% / Scope 2 80% / Scope 3 0%`.** Guess: "this fund covers 80% of
  Scope 2." Meaning: what share of each scope the penalty is levied on.
- **`PASS-THROUGH / Two grounded, nine flat`.** Unparseable. Meaning: how much of the carbon cost a
  company hands to customers; two sectors have a real estimate, nine are assumed.
- **`BOOK AT RISK 1.47%` / `INDEX AT RISK 3.49%`.** At risk of what? A judge reads "1.47% of my
  capital". It is a share of operating income. The clarification is 800px below, in 11px grey.
- **`Effective number of names 53`** sits under **`433 held`**. Reads as a contradiction.
- **`Active share vs the index 19.2%`.** Section 05 gives the same book, same label, **14.4%**. Two
  different numbers 5 000px apart.
- **`Tilt strength, solved to a 5% budget 1.25`.** Nobody outside the repo can use this line.

**3. Deletable with no loss.** "Every control recomputes all 500 companies live" (the controls prove
this by moving). "A uniform reprice scales value at risk and moves no weight at all. This line
measures it every time you change a control." (24 words explaining a 4-word hint). "n=500 priced",
"n=500, sized by market cap", "$1bn, daily liquidity assumed" as column subtitles; liquidity is never
mentioned again anywhere on the site. The column numbers 01/02/03, which collide with the nav's own
01 to 06.

**4. Serves the builder, not the reader.** All six sensitivity chips. The 11 sector sliders at
default. Tilt strength, effective names, active share. `seed 20260912` in the nav footer. The
deflator held at 1.44.

**5. Where the eye goes.** To the treemap, specifically the white Apple square and the Amazon square,
because they are the only large light shapes on a black field. That instinct is right; the treemap is
the best object on the site. But it is decorative until you know that colour means value at risk and
that hatched cells are the companies with no tonnage, and both keys are 10px grey along its bottom
edge. Second look lands on `433 held`, the largest numeral on the right. Nothing at all pulls the eye
to $141m against $244m, which is the finding.

### 02 The argument (hero)

**1.** "Ratings run on numbers companies choose to publish. We only used filings." Yes, in 5 seconds.
This is the strongest screen on the site and it is second, behind a dashboard. The evidence arrives
before the claim.

**2.** "312.5 / 500 ranks wide, 5th to 95th percentile". Percentile of what? A judge guesses
percentile of companies. It is the 5th to 95th percentile of 10 000 draws. "84 / 108" reads as a
score out of 108 rather than a count.

**3.** Three filename credits under three headline stats: `scores.json · 10 000 draws`,
`say_do.json · EPA GHGRP against the company's own target`, `portfolio.json · Brinson decomposition,
EU 2020/1818`. That is 20 words of file paths on the hero. Also "ran every defensible modelling
choice at once, and kept what held", which section 04 says better.

**4.** The filenames, the build stamp, the seed.

**5.** Eye goes to `312.5`. Correct.

### 03 Say and do

**1.** "84 of 108 companies emit more than they promised." Yes, in 5 seconds. Best-executed section
on the site: the headline states the claim, the chart shows it, the card holds the numbers.

**2.** "coverage tier measured" as a link inside a caption. `Flag-free subset 46 cos, 36 missing` and
`Median gap, flag-free +2.62 %/yr`: two rows that mean nothing without the flag taxonomy. "Rising in
absolute terms 33". The edge triangles.

**3.** "Promised on the horizontal, EPA-measured on the vertical". Both axes are labelled. "Median
of the companies carrying both a published target and an EPA-measured emissions trend" (16 words)
duplicates `n = 108 of 503 listings` two lines below it. The 23-word caption sentence naming the five
companies pinned as triangles.

**4.** The flag-free rows, the coverage-tier vocabulary, the listings-versus-companies distinction in
a stat card.

**5.** Eye goes to the orange point cloud, then the headline. Right.

**Worth protecting:** the "Every listing is accounted for" panel (108 / 233 / 26 / 136) is the single
most valuable honesty artefact on the site. It answers "what about the other 392?" before the judge
thinks to ask. It is currently below the fold in a section people scroll past.

### 04 Rank intervals

**1.** "There is no single ranking. Every company is a wide interval." The picture says it in one
second. The title does not: **"There is no identified ranking, and the weights are not the reason"**
carries two claims, and "identified" is an econometrics word that a judge reads as "we have not
identified one yet", which is the opposite of the point.

**2.** `MEASURED 139 / REPORTED 88 / UNMEASURABLE 273` as filter chips whose meanings are not defined
until section 06, two sections later. Then the whole variance panel: "first-order share of the
variance", "3 settings", `Dirichlet(1,1,1,1) over the four pillars`, and a top bar reading
**"interactions and what no single choice explains 47.5%"**, which a judge reads as "we cannot
explain half of our own result". Then `d_m 0.595`, "Paruolo, Saisana and Saltelli 2013 equation 6",
"eta^2 with the standard bias correction", "81 simplex cells". Then twelve rows named `copeland
only`, `NMAR-pessimistic only`, `absolute lens only`, `available-case only`.

**3.** The 74-word methods paragraph under the variance bars. "Rows keep the all-index order in every
view, so the bars stay comparable" (a chart explaining its own behaviour). The d_m comparison against
seven published indices, which is an academic move nobody in the room can act on.

**4.** The d_m panel in full. The 12-slice table with its `DRAWS USED` column. The 20x20 head-to-head
ticker matrix. The Pareto front list.

**5.** Eye goes to the cyan and grey interval chart, which is the best single image on the site: it
makes the argument without words. Then it has to travel 3 000px of supporting apparatus.

1 028 words and five viewports to deliver a claim one picture already made.

### 05 The $1bn fund

**1.** "A Paris-aligned fund cuts its carbon by selling companies, not by anyone emitting less." The
title says it. Then you land in a wall of EU article numbers and the chart that proves it is 4 000px
further down.

**2.** `EVIC`. `Scope 1 / EVIC`. `tracking error` (fine for a finance judge, opaque to a climate
judge). `FAILS ART 3, 12` and `PASSES 3, 9, 11, 12` as chips. `Article 12(1)(g)`. "high impact NACE
sections". `PCAF data quality 5`. `sub-threshold`. `Brinson decomposition`. "the cross term".
`Interaction +1.90 / −17.8% of the cut`, a negative percentage of a cut drawn as a positive bar.
`CAMD`. `clean_multiple_needed`. `revenue_exclusions.parquet`. `EUR-Lex CELEX 32020R1818`.

**3.** Five verbatim EU regulation quotes, about 130 words of legalese, in the default view. "The
book / Precomputed, then read back. Switching rebuilds every figure on this page." The wall of 67
excluded tickers. "Source: EUR-Lex, (c) European Union, 1998-2026. Retrieved 2026-09-12."

**4.** The article quotes. The ticker wall. `1 556 return cells filled`, `top 12 of 432`, `11 sectors
/ 499 names`, `13 rules read from the text`. The parquet filename. The ES honesty note, which is a
real and creditable admission sitting at completely the wrong altitude for a front page.

**5.** Eye goes to `$1 000 000 000` in big monospace, which is the least informative object in the
panel; the reader already knows the fund is $1bn from the nav, the hero and the section title. The
three book cards below it are the actual comparison and they are visually quieter than the money bar.

**Worth protecting:** the Brinson waterfall is the best explanatory chart on the site. Bar by bar it
shows that the money moved and the factories did not. It should be the second thing in this section,
not the sixth panel.

### 06 What we cannot see

**1.** "Here is exactly what this score cannot see." Yes in 5 seconds, and it is the right instinct.
But one heading is carrying three different arguments: coverage tiers, a regression about vendor
bias, and six named limits. 2 050 words, eight viewports.

**2.** `coverage tier`, `provenance class`, `provenance_class vendor`, `coverage_tier unmeasurable`,
`meta.us_only_note`. A full regression readout on a pitch page: `β +18.2  t +4.39  p < 0.0001  R²
0.039  n 470`. "points from the sector mean" as an axis label. "share of the voluntary disclosure
checklist filed". `MMT`. `PCAF`. `CAMD`. `Climate TRACE`.

**3.** The 55-word paragraph on the six vendor datasets being re-uploads of one dead pull. The LSEG
methodology quote. The Berg, Fabisik and Sautner citation. The multivariate check sentence
ending "(t = −1.07) while disclosure holds (t = 5.02, n = 469)". All of it defends against a
challenge nobody has made yet.

**4.** Four `SOURCE scores.json / meta.us_only_note` footers. The regression readouts. The 11-row
provenance table with its four-way class filter.

**5.** Eye goes to the three coverage blocks, 139 / 88 / 273 drawn as squares. Correct. That graphic
is clearer than anything in section 01 and it should probably be on screen one.

---

## 3. Cross-cutting faults

**A. Four different counts of "companies we cannot measure", on four screens, unreconciled.**

| Screen | Reads |
|---|---|
| 01 Allocate | `181 WITH NO TONNAGE`, `MONEY ON THE 181 WE CANNOT MEASURE` |
| 02 Hero | "273 with no mandatory tonnage" |
| 03 Say and do | "233 Target, no measurement" |
| 05, 06 | "361 of 500 companies file no mandatory tonnage" |

The hero and the portfolio use the identical phrase "no mandatory tonnage" for two different numbers,
273 and 361. The repo already knows: `penalty.json meta.coverage_conflict` documents the 273/181
split. A judge who notices reads it as sloppiness, and carefulness is the entire pitch. One
reconciling sentence, placed where the second number first appears, fixes it.

**B. Active share is 19.2% on screen 1 and 14.4% on screen 5.** Same book, same label.

**C. Three broken internal cross-references.** The copy says "section 03 publishes an interval" (the
intervals are nav 04), "the promise half of section 02" (say-do is nav 03), "the portfolio in section
04" (the fund is nav 05). Two numbering systems run at once: nav 01 to 06, and Finding 01 to 03. Pick
one and renumber, or drop the numbers from the prose.

**D. One typographic voice for everything.** `THE BONUS QUESTION`, `01 THE ASSUMPTION`, `NGFS
SCENARIO`, `0.000 of advice` and `EPA GHGRP · SEC XBRL` are all mono caps at similar weight and size.
A section kicker, a control label, a diagnostic chip and a source credit are four different classes of
information wearing the same uniform, so the eye cannot rank them.

**E. Eleven file-and-field credits in the body copy.** `scores.json · coverage.by_tier,
coverage.by_indicator`. `bias.json · points[BA], points[MLM]`. These serve the person marking
reproducibility, not the person deciding. They belong in one place, once, behind a control.

---

## 4. Jargon: keep, hide, or cut

"Keep" means it stays in the default view with a plain gloss attached. "Hide" means it moves behind a
disclosure control, unchanged. "Cut" means it leaves the site.

| Term, as it appears now | Verdict | What to do |
|---|---|---|
| `0.000 of advice`, `0.201 of advice` (x6) | **Cut** | Delete the chips. Replace with one sentence above the controls: "Only one of these controls changes who you own. The rest change what the risk is worth." |
| `181 WITH NO TONNAGE` | **Keep, gloss** | "181 companies file no emissions. You have to assume something." |
| `40 CFR Part 98 threshold` | **Keep, rename** | "Just under the reporting floor" |
| `Abstain` | **Keep, rename** | "Leave them out" |
| `Zero (what buying silence looks like)` | **Keep** | Already the best label on the screen. Trim to "Treat as zero". |
| `Sector median intensity` | **Keep, rename** | "Their sector's median" |
| `CARBON PRICE, $2010/T` | **Keep, rename** | Label "Carbon price". Move `$2010/t` to the value. |
| `HORIZON / price + abatement` | **Hide** | Under "Model assumptions" |
| `BY SECTOR, 0 EXEMPTS` (11 sliders) | **Hide** | Under "Model assumptions". Default view keeps the one master price slider. |
| `SCOPE COVERAGE` (3 sliders) | **Hide** | Under "Model assumptions" |
| `PASS-THROUGH / Two grounded, nine flat` | **Hide** | Under "Model assumptions", relabelled "How much cost is passed to customers" |
| `NGFS SCENARIO` | **Keep, rename** | "Climate scenario", options unchanged. Gloss: "central bank scenarios, the standard set" |
| `BOOK AT RISK` / `INDEX AT RISK` | **Keep, rename** | "Earnings at risk, your fund" / "Earnings at risk, the index". The words "of operating income" go in the sub-label, not 800px away. |
| `Tilt strength, solved to a 5% budget` | **Cut** | |
| `Effective number of names 53` | **Cut** from 01. Keep once in 05, glossed "the five biggest holdings are 5% each, so the book behaves like 53 names, not 432." | |
| `Active share vs the index` | **Cut** from 01, keep once in 05, and reconcile 19.2 against 14.4 | |
| `n=500 priced`, `n=500, sized by market cap`, `daily liquidity assumed` | **Cut** | |
| `coverage tier` / `MEASURED, REPORTED, UNMEASURABLE` | **Keep, rename** | "Measured by the EPA" / "Self-reported only" / "No mandatory number exists". Define once, on first use, not in section 06. |
| `provenance class` / `MANDATORY, VOLUNTARY, VENDOR, MODELLED` | **Keep** the four words, **hide** the phrase "provenance class" | The four labels are self-explaining. The category name is not. |
| `EVIC` | **Keep, gloss** | "market value plus debt" on first use |
| `Scope 1` | **Keep, gloss** | "emissions from a company's own sites" |
| `Scope 2`, `Scope 3` | **Keep, gloss** | "bought electricity" / "supply chain and products" |
| `say-do gap` | **Keep** | Already plain. |
| `tracking error` | **Keep, gloss** | "how far the fund drifts from the index" |
| `Brinson decomposition` | **Hide** the name, **keep** the chart | The waterfall's own bar labels do the work. Name it in the details. |
| "the cross term" / `Interaction` | **Keep, rename** | "Weight moved off the improvers" is already the legend text. Use it as the bar label. |
| `PCAF data quality 5` | **Hide** | |
| `sub-threshold` | **Keep, gloss** | "under the reporting floor, so this is an upper bound" |
| `Article 12(1)(g)`, `Article 3`, `Article 7(1)(a)`, `Article 9`, `Article 11` | **Keep** the article numbers, **hide** the quoted text | The numbers plus a one-line plain test is the credibility. The legalese is the proof, and proof belongs behind a control. |
| `high impact NACE sections` | **Keep, rename** | "heavy industry sectors" |
| `CAMD` | **Hide** | Spell out once in the details: "EPA stack monitors on power plants" |
| `clean_multiple_needed`, `revenue_exclusions.parquet`, `meta.us_only_note` | **Cut** | Variable names are not copy. |
| `EUR-Lex CELEX 32020R1818` | **Hide** | |
| `d_m 0.595`, "Paruolo, Saisana and Saltelli 2013 equation 6" | **Hide** the whole panel | Keep the one-line finding: "we say the four pillars are equal; the maths says one of them does a quarter more work than another." |
| "first-order share of the variance" | **Keep, rename** | "how much of the movement each choice explains" |
| `3 settings`, `5 settings`, `Dirichlet(1,1,1,1)` | **Hide** | |
| "interactions and what no single choice explains 47.5%" | **Keep, rename** | "choices acting together, 47.5%". "What no single choice explains" reads as a confession of ignorance. |
| `copeland only`, `NMAR-pessimistic only`, `absolute lens only`, `available-case only` | **Hide** the whole 12-row table | |
| `β +18.2  t +4.39  p < 0.0001  R² 0.039  n 470` | **Hide** | Default keeps the sentence: "filing the whole checklist is worth 18 percentile points of vendor standing. In ours it is worth nothing." |
| "points from the sector mean" | **Keep, rename** | "percentile points above or below its sector" |
| `MMT` | **Keep, rename** | "million tonnes" |
| `Climate TRACE` | **Keep, gloss** | "satellite-derived emissions data" |
| `40 CFR Part 98` (the source credit) | **Keep once**, in section 06 | It is the load-bearing phrase for "under legal penalty". Say it once, well, and not as a control label. |
| `seed 20260912` | **Cut** from the nav, **hide** in the drawer | |
| `scores.json`, `bias.json`, `ear.json`, `portfolio.json`, `say_do.json` and field paths (11 places) | **Hide** | One "Where this comes from" list in the drawer. |

---

## 5. Cut list

Delete outright. These are not moved, they leave.

1. **All six `0.000 of advice` chips.** The idea survives as one sentence; the chips are a variance
   diagnostic wearing the costume of a control readout, and they actively contradict the hint box
   next to them.
2. **The 11 per-sector price sliders in the default view.** 40% of the left column, identical values
   at rest, and a judge will never move eleven sliders in 30 seconds. One master price slider does
   the job.
3. **`Tilt strength, solved to a 5% budget 1.25`.** Unusable outside the repo.
4. **`Active share vs the index 19.2%` and `Effective number of names 53` in section 01.** Both
   belong once, in section 05, where there is room to gloss them.
5. **`n=500 priced`, `n=500, sized by market cap`, `$1bn, daily liquidity assumed`.** Column
   subtitles that read as footnotes. Liquidity never appears again.
6. **"A uniform reprice scales value at risk and moves no weight at all. This line measures it every
   time you change a control."** 24 words explaining a 4-word hint.
7. **"Every control recomputes all 500 companies live."** The controls demonstrate this.
8. **Column numbers 01/02/03 inside section 01.** They collide with the nav's 01 to 06.
9. **"Promised on the horizontal, EPA-measured on the vertical."** Both axes carry labels.
10. **"Median of the companies carrying both a published target and an EPA-measured emissions
    trend."** Duplicates `n = 108` two lines below.
11. **"Rows keep the all-index order in every view, so the bars stay comparable."** A chart
    describing its own behaviour.
12. **The d_m comparison against seven published indices** (Sustainable Society Index, 2009 HDI,
    THES, ARWU, Index of African Governance, 2010 HDI). An academic flourish no judge can act on.
13. **The `DRAWS USED` column** in the 12-slice table.
14. **"Precomputed, then read back. Switching rebuilds every figure on this page."** Implementation
    detail sold as a feature.
15. **"Source: EUR-Lex, (c) European Union, 1998-2026. Retrieved 2026-09-12."** in the body. Once, in
    the drawer.
16. **The 55-word paragraph on vendor datasets being re-uploads of one dead pull**, plus the LSEG
    methodology quote and the Berg, Fabisik and Sautner citation, plus the multivariate check
    sentence. Four separate defences of one finding nobody has attacked yet. Keep the finding.
17. **Every `SOURCE <file>.json / <field path>` footer** in the body, four in section 06 alone.
18. **`clean_multiple_needed`, `revenue_exclusions.parquet`, `meta.us_only_note`** and every other
    variable or file name in prose.
19. **`seed 20260912`** in the nav footer.

Nothing on this list is a caveat. Every caveat moves; none is deleted.

---

## 6. Disclosure plan

**Principle.** The default view carries the claim and the evidence for that claim. Everything else
sits one click away behind a control a judge can see without hunting.

**Three mechanisms, because there are three different problems.**

**(a) A per-panel details bar.** Native `<details>` with a full-width `<summary>` styled as a row:
chevron, a specific label, and a count. Default closed. No JavaScript, keyboard and screen-reader
accessible, opens in print, and works over `file://`, which matters because the deck opens the site
locally. The summary label must name its contents: **"Method and caveats (5)"**, not "More". This
takes methods paragraphs, statistics readouts, regulation quotes, source credits, and the flag-free
subsets.

**(b) One "How this works" drawer.** A persistent button in the left nav, under the section list,
opening a 480px panel over the right of the screen. It holds the material referenced from five
different places, so it has to be reachable without losing scroll position: the three coverage-tier
definitions, the four provenance-class definitions, the four missing-data rules, how the 10 000 draws
work, the d_m panel, the 12-slice table, the build stamp and the seed, and the "where every number
comes from" table. One drawer, six entry points.

**(c) A dotted-underline gloss on the dozen terms that must stay.** Hover, focus and tap all show a
one-sentence definition. Applies to: EVIC, Scope 1, Scope 2, Scope 3, tracking error, coverage tier,
say-do gap, earnings at risk, sub-threshold, high impact sectors, NGFS, EVIC-based intensity. A
tooltip you have to discover is not disclosure, which is exactly why `of advice` fails today; the
dotted underline is the discoverability, and it has to be visible in the default paint.

### What is visible by default, section by section

**01 Allocate.** Fits 1280x720 with no scroll.

- Visible: the title; a 12-word lede; the missing-data control with four options and four dollar
  figures; the spread promoted to a headline number ("$123m moves, on the same 500 companies"); the
  carbon price slider; the scenario dropdown; the treemap with its colour legend and hatch key; on
  the right, money on the 181, largest adds, largest cuts.
- Behind a details bar at the foot of the left column, labelled **"Model assumptions (4)"**: horizon,
  per-sector prices, scope coverage, pass-through.
- Behind a details bar at the foot of the screen, labelled **"What this model is not (3)"**: the
  exposure-not-a-forecast line, the units and deflator line, the operating-loss line, all three
  verbatim.
- Cut: the six chips, tilt strength, effective names, active share, the column subtitles.

**02 Hero.** Nearly finished. Move the three filename credits into the drawer. Add one line under the
stat row: "503 listings, 500 companies. 139 measured by the EPA, 88 self-reported only, 273 with no
mandatory number at all." That is the only place the three tiers need to appear before section 06.

**03 Say and do.** Chart, headline, card and the four-state panel stay visible; that panel is the
honesty and it earns its space. Behind **"What this chart cannot tell you (5)"**: the five caveats,
verbatim. Behind **"How the trend is measured"**: the flag-free subset rows and the triangle note.

**04 Rank intervals.** Visible: the interval chart, the "312.5 of 500" card, the three tier rows, and
the one-sentence finding that the missing-data assumption moves ranks more than the weights do.
Behind **"What moves a rank (7 choices)"**: the full variance bar chart and its methods paragraph.
Behind **"Stated weights against effective weights"**: the whole d_m panel. Behind **"What would
narrow the band (12 slices)"**: the slice table. The Pareto front and the head-to-head matrix become
one details bar, **"Results that hold under any weighting"**. Retitle the section to a single claim:
**"Every company is an interval, not a rank."** Keep "and the weights are not the reason" as the lede
sentence, in plain words.

**05 The $1bn fund.** Reorder. Visible: the three book cards, then the Brinson waterfall, then the
"who kept the improvement" table. That is the argument in three objects. Behind **"Article by article
(5 tests)"**: the compliance table with its quoted text. Behind **"Largest holdings (12 of 432)"**:
the holdings table. Behind **"What Article 12 takes out (67 names)"**: the exclusions table and the
ticker wall. Behind **"Tracking error and missing-data rules"**: those two panels. Behind **"What
this is not (8)"**: the caveat list, verbatim. Cut `$1 000 000 000` down to a normal-weight line; it
is the third time the reader has been told the fund is $1bn.

**06 What we cannot see.** Split the heading's three arguments and let two of them collapse. Visible:
the three coverage blocks (139 / 88 / 273), the indicator coverage rows, and the one-sentence vendor
finding with the two-company example. Behind **"Six things this score cannot see"**: the six limits,
verbatim, all 595 words, because this is the part that must never be cut and it is also the part
nobody reads on a first pass. Behind **"The disclosure test in full"**: both scatter plots, both
regression readouts, and the four defensive paragraphs. Behind the drawer: the provenance table.

### The four things that must stay reachable, and where they land

| Must remain | Lands |
|---|---|
| Companies we cannot measure are a declared category, never a zero | **Default view**, twice: the four-state panel in 03, and the three coverage blocks in 06. Also the missing-data control in 01, which is the interactive version of the same claim. |
| Every chart states how many companies it covers | **Default view**, unchanged. The `n = 108`, `n = 500`, `n = 470` labels stay exactly where they are. Cut the duplicate prose versions, not the labels. |
| An exposure estimate, not a forecast | **Default view** in 01 as a single line under the treemap, and verbatim inside "What this model is not". |
| US facilities only, above a reporting threshold, stops in 2023 | **Default view** as one line in the 06 heading area: "US facilities above 25 000 tonnes a year, through 2023." Full text stays verbatim behind "Six things this score cannot see". |

### Budget

| | Words |
|---|---|
| Now, all visible | 6 283 |
| After: visible by default | about 1 800 |
| After: one click away | about 3 700 |
| After: cut | about 800 |

Nothing in the middle row is lost. The goal is fewer words on screen, not fewer facts on the site.

---

## 7. If there is time for only five things

1. Kill the six `of advice` chips and replace them with one sentence. They are the single largest
   source of "I do not understand this screen", and they contradict the hint box beside them.
2. Collapse the 11 sector sliders, the horizon, the scope sliders and the pass-through dropdown under
   one **"Model assumptions"** details bar. Screen 01 goes from 7 control groups to 3.
3. Promote **"$123m moves"** to a headline on screen 01. It is the finding, and right now it is the
   smallest text in the column.
4. Reconcile the four missing-data counts (181, 233, 273, 361) with one sentence, and fix the active
   share mismatch (19.2 against 14.4). Carefulness is the pitch; visible arithmetic conflicts cost
   more than any amount of density.
5. Put a details bar on every panel in sections 04, 05 and 06. That alone removes roughly 3 000 words
   from the default paint without deleting a single fact.
