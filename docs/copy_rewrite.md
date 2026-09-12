# Copy audit: jargon, disclosure and the writing pass

Scope: every string that renders on screen. `site/index.html`, the six modules under `site/js/`,
the label and note fields those modules read out of `site/data/*.json`, and the slide text
`src/build_deck.py` writes into `slides/FILED.pptx` from the spec in `slides/outline.md`.
`slides/script.md` is spoken, not rendered, and is audited here only for the writing pass.

Counts, measured from the rendered DOM at 1600x1000 and from the deck builder:

| Corpus | Words on screen |
|---|---|
| Site, visible text | 5,434 |
| Site, text hidden in `title` tooltips | 556 |
| Deck, all six slides | 660 |
| **Total rendered** | **6,094** |
| `slides/script.md`, spoken only | 1,425 |

---

## 1. The verdict

Two separate problems are being blamed on one cause.

The writing is clean. The anti-AI pass found one hollow intensifier in 6,094 rendered words and
nothing else (section 5). No em dashes, no Tier 1 or Tier 2 vocabulary, no hedging, no copula
avoidance, no transition boilerplate. Nobody needs to rewrite the sentences.

The legibility is not. Section 3 audits 143 strings that render on screen. 44 of them a judge
already understands. 80 are load-bearing and need three plain words beside them. 10 are correct
and belong behind a disclosure control. 8 serve nobody. The six control-surface chips reading
`0.000 of advice` are the worst of the 80, because they look like prices. The fix is naming and
staging, not prose.

One structural point runs under everything below. Section 01 opens the site and it is the
densest screen we own: three columns, 35 controls, 6 unexplained decimal chips, and eleven
identical price sliders all reading 284. It is also the screen the 50-second recording opens on.
Every hour of this pass should go there first.

---

## 2. What a first-time viewer cannot understand, worst first

**2.1 The six `of advice` chips read as prices.** `0.000 of advice`, `0.201 of advice`,
`0.051 of advice`. They are eta-squared variance shares from `penalty.json`
`sensitivity.shares[key].allocation_fixed_lambda`, measured over 3,000 runs. Nothing on screen
says that. A finance judge reads `0.201` next to a carbon price as a number of dollars or a
probability. Four of the six read `0.000` or `0.001`, so the chip that carries the entire finding
sits in a row of four that look broken. Fix: keep two chips, in words, on the two controls the
contrast is about. Cut the other four. Full wording in section 3.1.

**2.2 `value at risk` collides with a term of art.** In finance, value at risk means the 95th or
99th percentile loss over a holding period. Here it means the share of a company's value the
carbon bill destroys, `dEV / EVIC * 100`. A finance-literate judge reads the treemap and is
confidently wrong. It appears 11 times across the allocate panel. Fix: gloss it at its first
appearance, which is the ramp key under the treemap, and keep the short form everywhere else.

**2.3 `181` and `361` and `273` are three different missing-data counts and the site uses all
three.** 181 companies carry no Scope 1 figure from any source, and that is the allocation lane.
361 carry no mandatory tonnage, which is 88 `reported` plus 273 `unmeasurable`, and that is the
score lane. The deck already documents the trap in `outline.md` slide 5 and does not mix them.
The site does: section 01 says 181, section 03 says 273, section 05 says 361. Fix: never put two
of them on the same screen, and add four words of scope to each.

**2.4 `PASS-THROUGH: Two grounded, nine flat` cannot be parsed by anyone.** Read from
`penalty.json` `passthrough`: pass-through is the share of the carbon bill a company pushes onto
customers through its prices, so it never reaches its own earnings. Eleven GICS sectors each need
a rate. Two of them have a published estimate we will stand behind: Utilities at 80% from Fabra
and Reguant 2014, Materials at 70% from Ganapati, Shapiro and Walker 2020. The other nine have
none, so all nine get one flat 50%. "Two grounded, nine flat" is the file's own honesty note
compressed into three words that mean nothing outside the repo. Fix in section 3.1.

**2.5 Eleven identical sliders.** The per-sector price block shows eleven rows, all reading 284,
all with an unlabelled `0` button beside them. It is a third of the control column and on first
load it carries no information at all. Fix: collapse behind a disclosure, default closed.

**2.6 Two different `0.201` on one site.** Section 01 prints `0.201 of advice` on the
missing-data control. Section 04 prints `0.201` for `the missing-data assumption` in the Sobol
table. They are different statistics, on different models, over different draw counts (3,000
against 10,000), and they agree to three decimals by coincidence. A judge who notices will
assume one is copied from the other. Once the section 01 chips go to words, the collision
disappears. Do not fix it by changing a number.

**2.7 The provenance footers are developer output.** Every panel in section 06 ends with
`source | scores.json | coverage.by_tier, coverage.by_indicator | mandatory`. Five of them. The
information is good and the format is a debug print. Fix: one disclosure per section headed
Sources.

**2.8 `Tilt strength, solved to a 5% budget 1.25`.** This is lambda from the bisection solver.
It is the single least legible string on the site and it sits in the advice column, at eye level.
Cut from the default view.

**2.9 `EVIC`.** Appears bare six times. It is the term the regulation uses and it must stay
reachable, but it should not be the first thing a reader meets. Gloss on first use, keep the
acronym in the drawer.

**2.10 The say-do lede restates its own heading.** Heading: `84 of 108 companies emit more than
they promised`. Lede, second sentence: `Above the line is emitting more than promised.` The first
sentence of that lede earns its place; the second does not.

---

## 3. Jargon table

Verdicts: **KEEP** (a judge already knows it), **GLOSS** (load-bearing, needs three plain words
next to it), **DEMOTE** (correct, belongs behind a disclosure control), **CUT** (serves nobody).

### 3.1 Section 01, the control surface

| On screen now | Verdict | Replacement |
|---|---|---|
| `0.201 of advice` and five siblings | CUT four, GLOSS two | `moves the most money` (accent) on the 181 control, `moves no money` (cool) on the carbon price. Delete the chips on Horizon, By sector, Scope coverage and Pass-through. One shared caption above the column: `Tags say how much each control moves the $1bn. Measured over 3,000 runs.` |
| `NGFS scenario` | GLOSS | `Carbon price scenario`. NGFS moves to the drawer and the deck source line, where it already is. |
| `Horizon` / `price + abatement` / `2030` | GLOSS | `Year` / `sets the price, and how much they have cut by then` / `2030` |
| `181 with no tonnage` | GLOSS | `181 companies file no emissions figure` |
| `Sector median intensity` | GLOSS | `Charge them their sector's median` |
| `40 CFR Part 98 threshold` | GLOSS | `Assume they sit just under the limit`. Drawer keeps: `40 CFR Part 98 makes a facility report only above 25,000 tonnes a year.` |
| `Abstain` | GLOSS | `Leave them unscored` |
| `Zero (what buying silence looks like)` | GLOSS | `Treat them as zero`. The editorial moves to the drawer, where it is stronger. |
| `Each figure is that option's money on the 181. Spread $123m.` | GLOSS | `Each figure is what those 181 companies get under that rule. The gap between best and worst is $123m.` |
| `Carbon price, $2010/t` | GLOSS | Label `Carbon price`, unit line under the group: `US dollars a tonne, 2010 money` |
| `every sector` | KEEP | unchanged |
| `By sector, 0 exempts` | DEMOTE | Becomes the summary of a closed disclosure: `Set a price per sector` |
| `0` (the exempt button) | GLOSS | `off`, with `title` = `charge this sector nothing` |
| `Scope coverage` | GLOSS | `How much of each scope we charge for` |
| `Scope 1 / Scope 2 / Scope 3` | GLOSS | Keep the names, add a sub-line: `direct  ·  bought power  ·  supply chain` |
| `Pass-through` | GLOSS | `Cost passed to customers` |
| `Two grounded, nine flat` | GLOSS | `Measured where we have it, 50% elsewhere` |
| `Repo sector table` | CUT | Remove from the dropdown. `penalty.json` says it has no empirical source. |
| `Nobody passes it on` | GLOSS | `Companies absorb all of it` |
| `Everybody passes half` | GLOSS | `Half passed on, everywhere` |
| `Everybody passes it all` | GLOSS | `All passed on, everywhere` |
| `n=500 priced` | GLOSS | `priced: 500 of 500` |
| `The assumption` / `The index` / `The advice` | KEEP | unchanged, they work |
| `n=500, sized by market cap` | KEEP | unchanged |
| `$1bn, daily liquidity assumed` | DEMOTE | Head becomes `$1bn`. `Daily liquidity assumed.` joins the foot caveats. |
| `value at risk` (ramp key) | GLOSS | `share of company value at risk` |
| `181 with no measured tonnage` (key) | GLOSS | `181 we cannot measure` |
| `433 held` | KEEP | unchanged |
| `67 excluded by Article 12` | GLOSS | `67 barred by the EU rulebook, Article 12` |
| `8.5% of index cap, before any tilt` | GLOSS | `they are 8.5% of the index` |
| `Book at risk` / `Index at risk` | GLOSS | `Our book` / `The index`, under one heading `Share of value at risk` |
| `Money on the 181 we cannot measure` | KEEP | unchanged, it already works |
| `Largest adds` / `Largest cuts` | KEEP | unchanged |
| `Where the cut in value at risk comes from` | GLOSS | `Where the risk cut comes from` |
| `Sector reallocation` | GLOSS | `Moving money between sectors` |
| `Picking inside a sector` | GLOSS | `Picking names inside a sector` |
| `Active share vs the index` | GLOSS | `How far this book sits from the index` |
| `Effective number of names` | DEMOTE | To the drawer. |
| `Tilt strength, solved to a 5% budget` | DEMOTE | To the drawer, reworded: `Tilt strength (lambda), solved to a 5% active-share budget` |
| `A tilt inside a rulebook, not an optimisation of returns.` | GLOSS | `We reweight inside a rulebook. We do not try to beat the market.` Keep the rest of that caveat as is. |
| `An exposure model, not a forecast.` | KEEP | The most important sentence on the page. Unchanged. |
| Tooltip `Value at risk ... % of EVIC` | GLOSS | `% of company value` |
| Card row `Priced tonnes` | GLOSS | `Tonnes we charge for` |
| Card row `Hit to EV` | GLOSS | `Hit to company value` |
| Card row `Value at risk ... of EVIC` | GLOSS | `Share of value at risk ... of company value` |
| Card row `Advised weight` | GLOSS | `Our weight` |
| Card row sub `Article 12` | KEEP | unchanged, it sits next to `excluded` |
| `Weights unchanged.` / `Weights moved.` | KEEP | The single best sentence pair on the site. Do not touch. |

### 3.2 Section 02, the hero

Clean. `Scope 1` is the only term and the tier line below it defines all three states. No changes
except one: `Zero vendor ESG inputs.` is the strongest four words on the page and it is set in
the smallest type in the section. Promote it, do not rewrite it.

### 3.3 Section 03, say and do

| On screen now | Verdict | Replacement |
|---|---|---|
| `Above the line is emitting more than promised.` | CUT | Restates the heading. Delete the sentence, keep `Promised on the horizontal, EPA-measured on the vertical.` |
| `All 108 plotted companies are coverage tier measured.` | GLOSS | `All 108 plotted are companies the EPA measures directly.` |
| `EaR at $300/t` | GLOSS | `Carbon cost at $300 a tonne` |
| `Flag-free subset` | GLOSS | `Cleanest subset` |
| `Rising in absolute terms` | GLOSS | `Emitting more than they used to` |
| `Fit flag: reporting boundary drifts across the window.` | KEEP | Already glossed in `FLAGS`. Unchanged. |
| `SBTi scope 1+2 absolute`, `Net Zero Tracker interim` | KEEP | These are the target's provenance and a climate judge knows them. |
| `Rank band 118–430` | KEEP | The bar under it does the explaining. |
| `Trend fit  R² 0.87` | KEEP | unchanged |
| `Every listing is accounted for` panel | KEEP | The best-designed honesty block we have. Do not touch it. |

### 3.4 Section 04, rank intervals

| On screen now | Verdict | Replacement |
|---|---|---|
| Section lede: `Ten thousand draws over normalisation, winsorisation, pillar inclusion, the missing-data assumption, aggregation, sector framing and the weights themselves.` | CUT and rewrite | `We rebuilt the ranking ten thousand times, changing every modelling choice a defensible method could make. The order fell apart. The weights, which is the thing everyone argues about, were only the fifth biggest reason.` |
| `First-order share of the variance of a company rank, one row per modelling choice.` | GLOSS | `How much of a company's rank movement each choice explains on its own.` |
| `normalisation` | GLOSS | `how scores are put on one scale` |
| `winsorisation` | GLOSS | `trimming the extremes` |
| `the aggregation rule` | GLOSS | `how the four pillars are combined` |
| `sector-relative or absolute` | GLOSS | `judged against its sector, or against everyone` |
| `which pillars are in` | KEEP | unchanged |
| `the missing-data assumption` | KEEP | unchanged, it is the plain version already |
| `Dirichlet(1,1,1,1) over the four pillars` | GLOSS | `every weighting, drawn at random` |
| `4 settings`, `3 settings` | KEEP | unchanged |
| `interactions and what no single choice explains` | KEEP | unchanged |
| `Pearson correlation ratio eta^2 with the standard bias correction ...` (the note) | DEMOTE | Behind a `How this is measured` disclosure. |
| `d_m 0.595` on the axis | GLOSS | `FILED  0.60`. The axis ends already say `stated equals effective` and `one pillar does all the work`. |
| `d_m, the distance between stated and effective importance, against published composite indicators` | KEEP | unchanged. It is the gloss. |
| `Paruolo, Saisana and Saltelli 2013 equation 6 ...` | DEMOTE | Into the same disclosure as the estimator note. |
| `Reference specification: equal weights, linear aggregation, global percentile normalisation, no winsorisation, sector-median imputation, absolute` | DEMOTE | Same disclosure. |
| `On the first Pareto front` | GLOSS | `beaten by nobody on all four pillars at once`. Keep `Pareto front` in the sub. |
| `head-to-head pairs ... settled in 95% of draws` | KEEP | unchanged |
| `rank acceptability` | not present | Listed in the brief, does not render anywhere. No action. |
| `One fixed specification` | GLOSS | `If we had picked one method and stopped` |
| `Our percentile` / `Vendor percentile` | KEEP | unchanged |
| `all triggers live` (conditional-bands row) | GLOSS | `nothing held fixed (what we publish)` |
| `NMAR-pessimistic only` | GLOSS | `pessimistic about non-filers only` |
| `available-case only` | GLOSS | `measured companies only` |

### 3.5 Section 05, the $1bn fund

| On screen now | Verdict | Replacement |
|---|---|---|
| Section lede: `Three books built against Commission Delegated Regulation (EU) 2020/1818, article by article, against a fourth that applies the position cap and no carbon rule at all. Then a Brinson decomposition, to find out who actually did the cutting.` | CUT and rewrite | `We built the EU's Paris-aligned fund from the regulation itself, article by article, plus a control book with no carbon rule in it at all. Then we split the carbon cut to find out who actually did the cutting.` |
| `EUR-Lex CELEX` / `32020R1818` | DEMOTE | To the sources disclosure. The article table already cites the regulation in full. |
| `Intensity  Scope 1 / EVIC` | GLOSS | `Carbon intensity  tonnes per $m of company value` |
| `Weighted average carbon intensity` / `tCO2e / $m EVIC` | GLOSS | `Carbon intensity of the book` / `tonnes per $m of company value` |
| `Cut against the investable universe` | GLOSS | `Cut against the whole index` |
| `Index weight not held` / `dropped or capped away` | KEEP | unchanged |
| `Realised tracking error` / `5th to 95th percentile` | GLOSS | `Tracking error` with sub `how far its returns drift from the index` |
| `Tonnes financed by the $1bn` | KEEP | unchanged. Strong. |
| `PAB compliant` | GLOSS | `Paris-aligned (PAB)` |
| `Naive exclusion` | KEEP | unchanged |
| `Transition leader` | KEEP | unchanged |
| `passes 3, 9, 11, 12` / `fails Art 3, 12` | GLOSS | `passes all four tests` / `fails Articles 3 and 12` |
| `Sector floor. Exposure to the high impact NACE sections must be at least the universe's.` | GLOSS | `Sector floor. The book must hold at least as much of the high-emitting industries as the index does.` NACE stays inside the quoted regulation text below it. |
| `Decarbonisation trajectory` | GLOSS | `Falling every year` |
| `Climate Transition Benchmark baseline` | GLOSS | `The lower bar (CTB)` |
| `Paris-aligned baseline` | GLOSS | `The Paris bar` |
| `by construction` / `not asserted` | GLOSS | `we do not claim this one` |
| `A Brinson decomposition of the move from the 2018 universe intensity to the book's 2023 intensity.` | GLOSS | `We split the fall in carbon intensity into the part companies delivered and the part the manager bought by changing who they own. 2018 to 2023.` Brinson moves to the drawer. |
| `Improvement: the same companies, cleaner` | KEEP | unchanged. Excellent. |
| `Reallocation: the same year, different companies` | KEEP | unchanged |
| `Interaction: weight moved off the improvers` | KEEP | unchanged |
| `the cross term` | GLOSS | `the overlap between the two` |
| `Basis` column | GLOSS | Header `Where it came from` |
| `EPA filed` / `sub-threshold` / `sector median` | GLOSS | `EPA filing` / `below the limit` / `our estimate` |
| `sector median is imputed at PCAF data quality 5` | GLOSS | `the sector median is our own estimate, which is the weakest input there is`. PCAF dq 5 moves to the drawer. |
| `Change  +22 bp` | GLOSS | Header `Change (bp)` with sub `100 bp = 1%` |
| `effective breadth is 53` | GLOSS | `it behaves like 53 equal positions` |
| `Article 12 chips` block | KEEP | unchanged. It is the clearest thing in the section. |
| `12(1)(g)` | KEEP | unchanged. It sits next to its own plain sentence. |
| `Sector median imputed (headline)` | GLOSS | `Sector median (what we publish)` |
| `Bounded by the GHGRP threshold` | GLOSS | `Just under the reporting limit` |
| `Measured names only, renormalised` | GLOSS | `Measured companies only` |
| `Non-disclosers scored zero` | KEEP | unchanged |
| `capped_index_only` / `Position cap alone, no carbon rule` | KEEP | unchanged |
| `What this is not` / `The caveats the file carries with it.` | CUT the sub | The heading says it. Delete `The caveats the file carries with it.` |

### 3.6 Section 06, what we cannot see

| On screen now | Verdict | Replacement |
|---|---|---|
| `Three coverage tiers, and every company sits in one` | KEEP | unchanged |
| `Measured` / `Reported` / `Not measurable` + their `desc` | KEEP | The desc fields are already the gloss. |
| `EPA GHGRP tonnage, filed under 40 CFR Part 98` | KEEP | unchanged. It is the product. |
| `Four provenance classes. Only one of them is allowed to move a score.` | GLOSS | `Four kinds of source. Only one of them is allowed to move a score.` |
| `provenance_class` chips: `mandatory` etc. | KEEP | The legend under the table defines all four. |
| `source \| scores.json \| coverage.by_tier, coverage.by_indicator \| mandatory` | DEMOTE | Five of these. Collapse into one `Sources` disclosure per section. |
| `β 18.2  t 4.39  p < 0.0001  R² 0.039  n 470` | DEMOTE | Keep the sentence above it (`Filing the whole checklist instead of none of it is worth +18.2 percentile points ...`), move the statistics behind `The regression`. |
| `The mechanism is a chain, not a size effect` | KEEP | unchanged |
| `log₁₀ USD` | GLOSS | `per 10x of market cap` |
| `disclosure coverage` | GLOSS | `voluntary disclosure checklist` |
| `Six things this score cannot see` | KEEP | unchanged. The best heading on the site. |
| `Climate TRACE names an asset owner for 73 of 503 listings` | KEEP | unchanged |
| `MMT` | GLOSS | `million tonnes` on first use |
| `Wilson interval` | DEMOTE | `95% confidence interval 89.5% to 99.6%` on screen, Wilson in the drawer. |
| `precision, 49 of 50 hand-checked` | KEEP | unchanged |
| `Entity resolution is audited, not assumed` | GLOSS | `Matching filings to companies is audited, not assumed` |
| `Facility filings name a parent string, not a ticker.` | KEEP | unchanged. It explains itself. |
| `Survivorship is measured, not corrected` | GLOSS | `Companies that left the index are counted, not corrected for` |

### 3.7 The deck

| On screen now | Verdict | Replacement |
|---|---|---|
| Slide 2, `share of the variance in a company's rank` | GLOSS | `how much each choice moves a company's rank` |
| Slide 2 bar labels (`missing-data assumption`, `pillar inclusion`, `sector-relative`, `normalisation`, `weights`, `aggregation`) | GLOSS | Same replacements as section 3.4. Six bars, six plain labels. |
| Slide 3 strip, `THE BONUS QUESTION: $1bn under a carbon price` | KEEP | unchanged |
| Slide 4, `of the carbon cut is reallocation` | GLOSS | `of the carbon cut is money moving, not companies cutting` |
| Slide 4, `at lambda 120, an active share of 70.5%, still 82.3% reallocation` | CUT | Nobody in the room can read `lambda 120`. It is a robustness answer and it belongs in `qa.md`. |
| Slide 5, `no mandatory tonnage. Never imputed, always tiered` | GLOSS | `file no legally required emissions figure. We never invent one.` |
| Slide 5, `median rank 344 if we can measure you, 224 if we cannot` | KEEP | The single best line in the deck. Do not touch. |
| All six source lines, 8pt | KEEP | They exist so a judge can check us. Length is the point. |

---

## 4. What goes behind a disclosure control

There is no disclosure pattern on the site today. Add one: a `<details class="drawer">` with a
`<summary>`, one CSS block in `app.css`, and a helper `FILED.drawer(summaryText, node)` in
`data.js` so all six modules use the same thing. Three summary wordings only, so the reader
learns the pattern once:

- `How this is measured`
- `Sources`
- `What this cannot tell you`

### Visible by default

Everything a judge needs to follow the argument with no context:

1. **Section 01.** The three column headings. The scenario dropdown. The year slider. The four
   missing-data buttons with their four dollar figures. One carbon price slider for all sectors.
   The three scope sliders. The treemap with its glossed ramp key. The advice column: names held,
   share of value at risk for book and index, the `Weights unchanged / Weights moved` verdict
   line, money on the 181, largest adds and cuts, where the risk cut comes from, and one
   concentration figure. The three foot caveats stay visible, all three.
2. **Section 02.** Unchanged.
3. **Section 03.** The scatter, the card, the four declared states, the caveat list. All visible.
4. **Section 04.** The rank wall, the card, the seven-row variance table, the stated-against-
   effective weight chart, the Pareto front, the conditional bands.
5. **Section 05.** The mandate strip, the three book cards, the six tiles, the article table, the
   holdings table, the Article 12 chips, the waterfall, the sector shift, the four missing-data
   rules, the caveat list.
6. **Section 06.** The waffle, the indicator bars, the two bias scatters with their one-sentence
   readings, the two named companies, all six limitations, the provenance table.

Nothing in the "must not be lost" list moves out of default view. Every chart keeps its `n`.
Every caveat block stays where it is. The coverage section loses nothing.

### Behind `How this is measured`

1. Section 01: the eleven per-sector price sliders and their exempt buttons.
2. Section 01: `Effective number of names` and `Tilt strength (lambda), solved to a 5%
   active-share budget`.
3. Section 01: the measured variance shares as numbers, with their estimator named, replacing the
   chips that now read in words.
4. Section 04: the estimator note (`Pearson correlation ratio eta^2 ...`, `weights binning`).
5. Section 04: the `d_m` definition, the reference specification, the bounds, the available-case
   figure.
6. Section 05: `Brinson`, `PCAF data quality 5`, `EVIC` spelled out, the position-limit arithmetic.
7. Section 06: the five regression statistic strips (`β t p R² n`), keeping the plain sentence
   above each one visible.
8. Section 06: `Wilson`.

### Behind `Sources`

9. The five `cv-prov` footer strips in section 06, and the `EUR-Lex CELEX 32020R1818` pair in
   section 05, collapsed into one `Sources` disclosure per section.

That is 9 disclosures across 6 sections. Any more and the page becomes a filing cabinet.

---

## 5. The anti-AI writing pass

Run over the rendered DOM, the `title` tooltips, `slides/outline.md` and `slides/script.md`, with
word-boundary matching so `every` does not score as `very`.

| Pattern | Site (5,434 w) | Tooltips (556 w) | Outline (2,308 w) | Script (1,425 w) |
|---|---|---|---|---|
| Em dash, U+2014 | 0 | 0 | 0 | 0 |
| Double hyphen used as a dash | 0 | 0 | 0 | 0 |
| Tier 1 vocabulary (delve, robust, leverage, seamless, comprehensive, utilise, game-changer, 40 others) | 0 | 0 | 0 | 0 |
| Tier 2 vocabulary (harness, empower, streamline, foster, crucial, 33 others) | 0 | 0 | 0 | 0 |
| Hollow intensifiers (genuine, truly, really, incredibly, absolutely, simply, very) | 0 | 0 | 0 | 1 |
| Hedging (perhaps, arguably, potentially, notably, importantly, interestingly) | 0 | 0 | 0 | 0 |
| Hedge phrases (could potentially, it is worth noting, that being said) | 0 | 0 | 0 | 0 |
| Copula avoidance (serves as, functions as, represents a, boasts, stands as) | 0 | 0 | 0 | 0 |
| Transition boilerplate (moreover, furthermore, additionally, in conclusion, when it comes to) | 0 | 0 | 0 | 0 |
| Chatbot artefacts | 0 | 0 | 0 | 0 |
| Rhetorical-question openers | 0 | 0 | 0 | 0 |
| "It is not X, it is Y" | 0 | 0 | 0 | 0 |
| Three-item lists | 7 | 1 | 3 | 1 |
| **Total flagged** | **7** | **1** | **3** | **1** |

Every three-item list is a real triple: author names (`Cohen, Rouen and Sachdeva`,
`Paruolo, Saisana and Saltelli`, `Berg, Fabisik and Sautner`), `Scope 1, 2 and 3`, and
`Articles 6, 11 and 12`. None is padded to three. No action.

The one hollow intensifier is in `slides/script.md`: `Even at a very slow 120 wpm this lands at
159 s.` Cut `very`. It is spoken-word planning prose, not rendered copy, so this is optional.

**Verdict: the copy was already clean.** The anti-AI pass changes one word. Do not spend the
remaining hours rewriting sentences that pass. Spend them on section 3 and section 4.

### The four real prose problems the word-pattern scan does not catch

**P1. A sentence that restates its own heading.** `saydo.js:113`. Heading reads `84 of 108
companies emit more than they promised`; the lede's second sentence reads `Above the line is
emitting more than promised.` Cut the second sentence.

**P2. A sub that restates its own heading.** `portfolio.js:702`. Heading `What this is not`, sub
`The caveats the file carries with it.` Cut the sub.

**P3. Two seven-item jargon lists doing the job of one sentence.** The section 04 and section 05
ledes in `index.html`. Both rewritten in section 3.

**P4. One heading that promises a number and does not deliver one.** `What we cannot see, stated
as a number` (`index.html:149`) is followed by `Where the mandatory record stops, the score stops
with it.`, which is a sentence, not a number. The deck's slide 5 gets this right: the number is
`361` at 96pt. Put the number in the section head: `361 of 500 companies file no legally required
emissions figure. We invent nothing for them.`

---

## 6. Cut list

Remove outright. Each one costs a reader attention and returns nothing.

| Item | Where | Why |
|---|---|---|
| Four `of advice` chips (horizon, by sector, scope coverage, pass-through) | `allocate.js:504, 562, 602, 612` | Read `0.000`, `0.051`, `0.007`, `0.001`. Three of the four say "this control does nothing", which is not worth a chip. |
| `Repo sector table` dropdown option | `allocate.js:52` | `penalty.json` states it has no empirical source. Shipping an option we will not defend is the opposite of the pitch. |
| `Effective number of names 53` | `allocate.js:1093-1095` | Demote, not delete. Nobody reads it in 50 seconds. |
| `Tilt strength, solved to a 5% budget 1.25` | `allocate.js:1096-1098` | Demote. Least legible string on the site. |
| `, before any tilt` | `allocate.js:1037-1038` | The sentence works without it. |
| `daily liquidity assumed` from the column head | `allocate.js:727` | Moves to the foot, does not disappear. |
| `Above the line is emitting more than promised.` | `saydo.js:113` | Restates the heading. |
| `The caveats the file carries with it.` | `portfolio.js:702` | Restates the heading. |
| Eleven per-sector price sliders, from the default view | `allocate.js:585-600` | Collapse. A third of the control column, all reading 284. |
| Five `cv-prov` footer strips, from the default view | `coverage.js:192, 345, 550, 699, 808` | Collapse into one `Sources` disclosure per section. |
| Five `β t p R² n` statistic strips, from the default view | `coverage.js:350-358` | Collapse. The plain sentence above each one stays. |
| `at lambda 120, an active share of 70.5%, still 82.3% reallocation` | slide 4, `build_deck.py:541-545` | Unreadable at ten feet. Belongs in `qa.md`, where it already is. |
| `very` | `slides/script.md`, timing paragraph | One hollow intensifier. |
| `Custom` scenario option | `allocate.js:498` | Optional. It appears only after the reader has already moved a slider, so it labels a state rather than offering one. Low priority. |

---

## 7. Find and replace

Apply in order. Line numbers are from the files as they stand at the time of this audit; match on
the string, not the line. Every `OLD` is the current source text with its indentation and its
line breaks collapsed, so search for a distinctive fragment rather than pasting the whole cell.

### 7.1 `site/js/allocate.js`

| # | Line | OLD | NEW |
|---|---|---|---|
| A1 | 52 | `['repo_sector_table', 'Repo sector table'],` | delete the whole array entry |
| A2 | 53 | `['flat_0', 'Nobody passes it on'],` | `['flat_0', 'Companies absorb all of it'],` |
| A3 | 54 | `['flat_50', 'Everybody passes half'],` | `['flat_50', 'Half passed on, everywhere'],` |
| A4 | 55 | `['flat_100', 'Everybody passes it all']` | `['flat_100', 'All passed on, everywhere']` |
| A5 | 51 | `['default_two_grounded', 'Two grounded, nine flat'],` | `['default_two_grounded', 'Measured where we have it, 50% elsewhere'],` |
| A6 | 454 | `class: cls, text: v.toFixed(3) + ' of advice',` | `class: cls, text: v >= 0.05 ? 'moves the most money' : 'moves no money',` |
| A7 | 455-457 | `title: 'Share of the variance in the 500 advised weights that this ' + 'control explains on its own, over 3000 draws. 1.000 would mean it ' + 'decides the allocation by itself.'` | `title: 'Measured over 3000 runs: this control explains ' + v.toFixed(3) + ' of the variance in the 500 advised weights, on its own.'` |
| A8 | 501 | `wrap.appendChild(group('NGFS scenario', null, sel));` | `wrap.appendChild(group('Carbon price scenario', null, sel));` |
| A9 | 504 | `wrap.appendChild(group('Horizon', 'horizon', FILED.el(` | `wrap.appendChild(group('Year', null, FILED.el(` (drops the chip) |
| A10 | 505 | `text: 'price + abatement',` | `text: 'sets the price, and how much they have cut by then',` |
| A11 | 537 | `wrap.appendChild(group('181 with no tonnage', 'treatment', [` | `wrap.appendChild(group('181 companies file no emissions figure', 'treatment', [` |
| A12 | 540-541 | `'Each figure is that option\'s money on the 181. Spread $' + spread.toFixed(0) + 'm.'` | `'Each figure is what those 181 get under that rule. Best to worst, the gap is $' + spread.toFixed(0) + 'm.'` |
| A13 | 562 | `FILED.el('span', { text: 'By sector, 0 exempts' }), share('sectors_exempt')` | `FILED.el('span', { text: 'Set a price per sector' })` (chip dropped, block moves into a drawer) |
| A14 | 575-576 | `class: 'ac-ex', type: 'button', text: '0', title: 'exempt ' + s + ' from the carbon price',` | `class: 'ac-ex', type: 'button', text: 'off', title: 'charge ' + s + ' nothing',` |
| A15 | 584 | `wrap.appendChild(group('Carbon price, $2010/t', 'price_level', priceBody));` | `wrap.appendChild(group('Carbon price', 'price_level', priceBody));` plus a unit line inside `priceBody`: `FILED.el('div', { class: 'ac-hint', text: 'US dollars a tonne, 2010 money.' })` |
| A16 | 602 | `wrap.appendChild(group('Scope coverage', 'coverage_scope3', cov));` | `wrap.appendChild(group('How much of each scope we charge for', null, cov));` and add above the rows `FILED.el('div', { class: 'ac-hint', text: 'direct  ·  bought power  ·  supply chain' })` |
| A17 | 612 | `wrap.appendChild(group('Pass-through', 'passthrough_level', ps));` | `wrap.appendChild(group('Cost passed to customers', null, ps));` |
| A18 | 683, 716 (`keyText` init and the water toggle) | `'181 with no measured tonnage'` (twice) | `'181 we cannot measure'` |
| A19 | 680 | `dom.rampK = FILED.el('span', { text: 'value at risk' });` | `dom.rampK = FILED.el('span', { text: 'share of company value at risk' });` |
| A20 | 710-711 | `? 'high-stress sites' : 'value at risk';` | `? 'high-stress sites' : 'share of company value at risk';` |
| A21 | 727 | `colShell('03', 'The advice', '$1bn, <b>daily</b> liquidity assumed');` | `colShell('03', 'The advice', '$1bn');` |
| A22 | 759-760 | `'A tilt inside a rulebook, not an optimisation of returns. No expected ' + 'return, no covariance matrix, no alpha claim.'` | `'We reweight inside a rulebook. We do not try to beat the market: no expected return, no covariance matrix, no alpha claim. Daily liquidity assumed.'` |
| A23 | 966 | `row('Value at risk', ... + '% of EVIC' : 'not priced')` | `row('Share of value at risk', ... + '% of company value' : 'not priced')` |
| A24 | 1011 | `r('Value at risk', ..., 'of EVIC');` | `r('Share of value at risk', ..., 'of company value');` |
| A25 | 1008 | `r('Priced tonnes', ...)` | `r('Tonnes we charge for', ...)` |
| A26 | 1010 | `r('Hit to EV', ...)` | `r('Hit to company value', ...)` |
| A27 | 1017 | `r('Advised weight', ...)` | `r('Our weight', ...)` |
| A28 | 1032 | `dom.leftN.innerHTML = 'n=<b>' + priced + '</b> priced';` | `dom.leftN.innerHTML = 'priced: <b>' + priced + '</b> of 500';` |
| A29 | 1035-1038 | `nEx + ' excluded by Article 12<br>' + ... + '% of index cap, before any tilt'` | `nEx + ' barred by the EU rulebook, Article 12<br>they are ' + ... + '% of the index'` |
| A30 | 1041 | `'<div class="k">Book at risk</div>'` | `'<div class="k">Our book</div>'` |
| A31 | 1044 | `'<div class="k">Index at risk</div>'` | `'<div class="k">The index</div>'` (add one `av-sub` heading above the pair: `Share of value at risk`) |
| A32 | 1092 | `'<span class="kv-k">Active share vs the index</span>'` | `'<span class="kv-k">How far this book sits from the index</span>'` |
| A33 | 1093-1098 | the `Effective number of names` and `Tilt strength` rows | move both into the `How this is measured` drawer |
| A34 | 1103 | `'<div class="av-sub">Where the cut in value at risk comes from</div>'` | `'<div class="av-sub">Where the risk cut comes from</div>'` |
| A35 | 1107 | `'<span>Sector reallocation</span>'` | `'<span>Moving money between sectors</span>'` |
| A36 | 1109 | `'<span>Picking inside a sector</span>'` | `'<span>Picking names inside a sector</span>'` |

Also add, once, above the first `ac-group` in `buildLeft()`:
`FILED.el('div', { class: 'ac-hint', text: 'The tags say how much each control moves the $1bn. Measured over 3000 runs.' })`

### 7.2 `site/js/saydo.js`

| # | Line | OLD | NEW |
|---|---|---|---|
| S1 | 111-113 | `'Promised on the horizontal, EPA-measured on the vertical. ' + 'Above the line is ' + spec.above_line + '.'` | `'Promised on the horizontal, EPA-measured on the vertical.'` |
| S2 | 399-400 | `'All ' + ... + ' plotted companies are coverage tier ' + '<span class="u-cool">measured</span>. '` | `'All ' + ... + ' plotted are companies the EPA measures directly. '` |
| S3 | 512 | `row('EaR at $300/t',` | `row('Carbon cost at $300 a tonne',` |
| S4 | 471 | `row('Flag-free subset', ...)` | `row('Cleanest subset', ...)` |
| S5 | 473 | `row('Median gap, flag-free', ...)` | `row('Median gap, cleanest subset', ...)` |
| S6 | 470 | `row('Rising in absolute terms', ...)` | `row('Emitting more than they used to', ...)` |

### 7.3 `site/js/ranks.js`

| # | Line | OLD | NEW |
|---|---|---|---|
| R1 | 19 | `normalisation: 'normalisation',` | `normalisation: 'how scores are put on one scale',` |
| R2 | 22 | `winsorisation: 'winsorisation'` | `winsorisation: 'trimming the extremes'` |
| R3 | 21 | `aggregation: 'the aggregation rule',` | `aggregation: 'how the four pillars are combined',` |
| R4 | 18 | `sector_relative: 'sector-relative or absolute',` | `sector_relative: 'judged against its sector, or against everyone',` |
| R5 | 224-225 | `'First-order share of the variance of a company rank, ' + 'one row per modelling choice.'` | `'How much of a company\'s rank movement each choice explains on its own.'` |
| R6 | 851-854 | `so.estimator + ' Weights enter as ' + so.weights_binning + '. Where the EPA does measure a '...` | Keep the sentence from `Where the EPA does measure` onward visible. Move `so.estimator` and `weights_binning` into a `How this is measured` drawer. |
| R7 | 972-973 | `'">d_m ' + fmt.num(wa.d_m, 3) + '</text>'` | `'">FILED  ' + fmt.num(wa.d_m, 2) + '</text>'` |
| R8 | 944-947 | `wa.definition + ' Reference specification: ' + ...` | Whole note into a `How this is measured` drawer. |
| R9 | 715 | `row('One fixed specification', ...)` | `row('If we had picked one method and stopped', ...)` |
| R10 | 1021 | `'<div class="rk-biglab">on the first Pareto front</div>'` | `'<div class="rk-biglab">beaten by nobody on all four pillars at once</div>'` |
| R11 | `scores.json` `trigger_factors.weights` | `"Dirichlet(1,1,1,1) over the four pillars"` | `"every weighting, drawn at random"` (edit `src/score.py`, then rebuild) |
| R12 | `scores.json` `conditional_bands` keys | `all triggers live`, `available-case only`, `NMAR-pessimistic only` | `nothing held fixed (what we publish)`, `measured companies only`, `pessimistic about non-filers only` (edit `src/score.py`, then rebuild) |

### 7.4 `site/js/portfolio.js`

| # | Line | OLD | NEW |
|---|---|---|---|
| P1 | 184 | `kv('Intensity', 'Scope 1 / EVIC')` | `kv('Carbon intensity', 'tonnes per $m of company value')` |
| P2 | 182 | `kv('EUR-Lex CELEX', m.regulation)` | move into the `Sources` drawer |
| P3 | 258-259 | `k: 'Weighted average carbon intensity'` / `return 'tCO2e / $m EVIC';` | `k: 'Carbon intensity of the book'` / `return 'tonnes per $m of company value';` |
| P4 | 261 | `k: 'Cut against the investable universe'` | `k: 'Cut against the whole index'` |
| P5 | 273-274 | `k: 'Realised tracking error'` | `k: 'Tracking error'`, unit `'how far its returns drift from the index'` |
| P6 | 24 | `name: 'PAB compliant'` | `name: 'Paris-aligned (PAB)'` |
| P7 | 251 | `text: fails.length ? 'fails Art ' + fails.join(', ') : 'passes 3, 9, 11, 12'` | `text: fails.length ? 'fails Article' + (fails.length > 1 ? 's ' : ' ') + fails.join(', ') : 'passes all four tests'` |
| P8 | 312 | `'Sector floor. Exposure to the high impact NACE sections must be at least the universe\'s.'` | `'Sector floor. The book must hold at least as much of the high-emitting industries as the index does.'` |
| P9 | 319 | `'Decarbonisation trajectory. At least 7% intensity reduction a year, geometrically, from the base year.'` | `'Falling every year. At least 7% off the carbon intensity a year, compounding, from the base year.'` |
| P10 | 326 | `'Climate Transition Benchmark baseline. At least 30% below the investable universe.'` | `'The lower bar (CTB). At least 30% below the whole index.'` |
| P11 | 333 | `'Paris-aligned baseline. At least 50% below the investable universe.'` | `'The Paris bar. At least 50% below the whole index.'` |
| P12 | 321 | `got: function () { return 'by construction'; }` | `got: function () { return 'we do not claim this one'; }` |
| P13 | 501-503 | `'A Brinson decomposition of the move from the ' + base_year + ' universe intensity to the book\'s ' + latest_year + ' intensity.'` | `'We split the fall in carbon intensity into the part companies delivered and the part the manager bought by changing who they own. ' + base_year + ' to ' + latest_year + '.'` |
| P14 | 65-67 | `BASIS_SHORT = { measured_mandatory: 'EPA filed', ghgrp_threshold_bound: 'sub-threshold', sector_median_imputed: 'sector median' }` | `{ measured_mandatory: 'EPA filing', ghgrp_threshold_bound: 'below the limit', sector_median_imputed: 'our estimate' }` |
| P15 | 400 | `th('Basis', 'left')` | `th('Where it came from', 'left')` |
| P16 | 400 | `th('Change')` | `th('Change (bp)')` and add to the table note: `100 bp is 1%.` |
| P17 | 847-849 | `'sector median is imputed at PCAF data quality 5'` | `'sector median is our own estimate, the weakest input there is'` |
| P18 | 776-778 | `'but its effective breadth is ' + fmt.num(p.effective_n, 0) + ', because'` | `'but it behaves like ' + fmt.num(p.effective_n, 0) + ' equal positions, because'` |
| P19 | 1035-1038 | `SCHEME_LABEL` four values | `imputed: 'Sector median (what we publish)'`, `threshold: 'Just under the reporting limit'`, `available_case: 'Measured companies only'`, `zerofill: 'Non-disclosers scored zero'` |
| P20 | 702 | `panelHead('What this is not', 'The caveats the file carries with it.', ...)` | `panelHead('What this is not', '', ...)` |
| P21 | 1091 | `'and the cross term hands ' + ... + ' of that straight back.'` | `'and the overlap between the two hands ' + ... + ' of that straight back.'` |

### 7.5 `site/js/coverage.js`

| # | Line | OLD | NEW |
|---|---|---|---|
| C1 | 769 | `'Four provenance classes. Only one of them is allowed to move a score.'` | `'Four kinds of source. Only one of them is allowed to move a score.'` |
| C2 | 350-358 | `statLine()` output, `β t p R² n` | wrap in a `The regression` drawer, keep the `cv-read` sentence above it visible |
| C3 | 384 | `node('Market cap', 'log' + sub10() + ' USD')` | `node('Market cap', 'per 10x of market cap')` |
| C4 | 386 | `node('Disclosure coverage', ...)` | `node('Voluntary disclosure', ...)` |
| C5 | 669 | `'Entity resolution is audited, not assumed'` | `'Matching filings to companies is audited, not assumed'` |
| C6 | 659 | `'Survivorship is measured, not corrected'` | `'Companies that left the index are counted, not corrected for'` |
| C7 | 671-672 | `'95% Wilson interval ' + DOC_FACTS.audit_ci.s` | `'95% confidence interval ' + DOC_FACTS.audit_ci.s`, Wilson to the drawer |
| C8 | 617-619 | `fmt.num(DOC_FACTS.us_mmt.v, 1) + ' MMT'` and `nonus_mmt` | `... + ' million tonnes'` on first use, `MMT` after |
| C9 | 192, 345, 550, 699, 808 | five `prov(...)` calls | collapse into one `Sources` drawer per section |

### 7.6 `site/index.html`

| # | Line | OLD | NEW |
|---|---|---|---|
| H1 | 127-128 | `<p class="sec-lede">Ten thousand draws over normalisation, winsorisation, pillar inclusion, the missing-data assumption, aggregation, sector framing and the weights themselves.</p>` | `<p class="sec-lede">We rebuilt the ranking ten thousand times, changing every modelling choice a defensible method could make. The order fell apart. The weights, which is the thing everyone argues about, were only the fifth biggest reason.</p>` |
| H2 | 138-140 | `<p class="sec-lede">Three books built against Commission Delegated Regulation (EU) 2020/1818, article by article, against a fourth that applies the position cap and no carbon rule at all. Then a Brinson decomposition, to find out who actually did the cutting.</p>` | `<p class="sec-lede">We built the EU's Paris-aligned fund from the regulation itself, article by article, plus a control book with no carbon rule in it at all. Then we split the carbon cut to find out who actually did the cutting.</p>` |
| H3 | 149-150 | `<h2 class="sec-title">What we cannot see, stated as a number</h2><p class="sec-lede">Where the mandatory record stops, the score stops with it.</p>` | `<h2 class="sec-title">361 of 500 file no legally required emissions figure</h2><p class="sec-lede">We invent nothing for them. Where the mandatory record stops, the score stops with it.</p>` |
| H4 | 38-40 | `<p class="al-lede">Every control recomputes all 500 companies live. The carbon price moves every number here except the allocation. <b>The missing data moves the money.</b></p>` | keep, it is the best lede on the site |

### 7.7 `src/build_deck.py`

| # | Line | OLD | NEW |
|---|---|---|---|
| D1 | 541-545 | `Para("at lambda 120, an active share of 70.5%, still 82.3% reallocation", ...)` | delete the `Para` and the `textbox` that places it |
| D2 | 528 | `Para("of the carbon cut is reallocation", ...)` | `Para("of the carbon cut is money moving, not companies cutting", ...)` |
| D3 | slide 2 bar image | `02b_sobol_bars.png` labels | regenerate with the section 3.4 wording, and the header `how much each choice moves a company's rank` |
| D4 | 601-602 | `Para("companies with no mandatory tonnage. We impute nothing for them", ...)` | `Para("companies file no legally required emissions figure. We invent nothing for them", ...)` |
| D5 | 613 | `("361 of 500", "no mandatory tonnage. Never imputed, always tiered")` | `("361 of 500", "file no legally required emissions figure. Never imputed, always tiered")` |

### 7.8 `slides/script.md`

| # | OLD | NEW |
|---|---|---|
| X1 | `Even at a very slow 120 wpm this lands at 159 s` | `Even at 120 wpm this lands at 159 s` |

---

## 8. Checklist for whoever applies this

Before you commit, confirm each of these still renders in the default view, with no click:

- [ ] `181 companies file no emissions figure` and its four options, with four dollar figures
- [ ] `Money on the 181 we cannot measure  $141m`
- [ ] Every chart still prints its `n`: `n = 500 companies`, `n = 108 of 503 listings`,
      `n = 470 rated`, `n = 2 of 128`, `n = 499 names`
- [ ] `An exposure model, not a forecast.` in the section 01 foot, all three foot caveats
- [ ] `Six things this score cannot see`, all six rows
- [ ] `US facilities only`, `The reporting threshold`, `GHGRP stops at reporting year 2023`
- [ ] `Every listing is accounted for`, all four declared states
- [ ] `What this chart cannot tell you`, all five caveats
- [ ] `What this is not` list in section 05, all six items
- [ ] The three coverage tiers with their descriptions
- [ ] `Weights unchanged.` / `Weights moved.`
- [ ] `Zero vendor ESG inputs.`

Then re-run `src/build_bundle.py`, reload over `file://`, and check the console says
`allocate.js model check` with no error. Nothing in this document changes a number.
