# FILED: slide specification

Five slides, 16:9, 1920x1080. Dark, matching the site exactly so the demo GIF
does not look like a different product.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0b0d10` | slide ground |
| `--bg-sunk` | `#08090c` | chart plot ground |
| `--ink` | `#eceef1` | headline |
| `--ink-2` | `#aab3bf` | secondary lines |
| `--ink-3` | `#79838f` | 8pt source line |
| `--accent` | `#ff7a45` | the one thing the slide is about, nothing else |
| `--cool` | `#4fc3d9` | the counterpart state, measured tier |
| `--muted` | `#5a6470` | anything we cannot measure |

Type: Inter for words, JetBrains Mono for every figure without exception.
Headline 40pt, the one big figure 96pt mono, secondary 19pt, source line 8pt.

Furniture on all five slides, and nothing else: slide number in 10pt mono top
right (`01` to `05`), and a 9pt footer, left `FILED  the S&P 500 scored only on
what it files under legal penalty`, right the site URL. No logos, no team slide,
no agenda, no thank you slide.

Every figure on every slide is read from the site's own JSON, which is read from
the fetch scripts in `src/`. If a number here cannot be found in
`site/data/*.json`, it does not go on the slide.

Two rules the copy is cut to, and `src/build_deck.py` fails the build on the
second of them.

**Plain words on the slide, the term of art in the notes.** A slide is read in
the three to eight seconds the speaker stands on it, by a judge who has seen
five pitches today and knows what a portfolio is. "Company value" on the slide,
`EVIC, Article 1(d)` in the speaker notes. "Trimming the extremes" on the slide,
`winsorisation` in the notes. Nothing is deleted; it moves to where there is
time to read it.

**Every source line is one line.** They exist so a judge can go and check us,
which is worth points, and a paragraph at the foot of a slide is read by
nobody. So each one names the regulation, the dataset or the file in the repo
and stops: `docs/entity_resolution_audit.md` beats three sentences describing
the audit. `source_line()` measures the string against the content width in the
rendered face and raises if it wraps.

---

## Slide 1. Say and do

**Claim.** Companies are missing the promises they made themselves.

**The number.** `77.8%` set at 96pt mono in accent, with `84 of 108` beneath it
in 19pt mono.

**Headline.** Four in five miss their own emissions promise.

**Rendered.** One scatter, nothing else. Screenshot the live `#saydo` panel at
1600px and crop to the plot. **Match the live panel's orientation exactly.** Its
axes are percent-per-year *change*, where negative is falling, so missing the
promise is ABOVE the identity line, not below. `saydo.js` prints
`Above the line is emitting more than promised`.

- x axis: promised, implied annual %/yr change from the company's own target.
  Domain -29.0 to +0.6.
- y axis: delivered, fitted annual %/yr change in measured EPA Scope 1,
  log-linear OLS. Domain -39.2 to +10.1.
- The 45 degree line is "kept the promise". Label it once, in `--ink-2`.
- 84 points sit ABOVE that line. Those are in `--accent`, hollow.
- 33 of the 84 sit above zero on y: promising cuts, emitting more. Same accent,
  filled. Shade the band above y=0 and label it once, `33 emitting more`.
- Two mono lines under the plot: `promised, median   5.92% a year` and
  `delivered, median  1.87% a year`. The unit is said out; `%/yr` is not read
  at ten feet. The two labels are the same character count, so the figures
  column in the mono face.

**Not on this slide.** No company names. No vendor comparison. No mention of the
Nature paper in the body text: it is the premise, and it lives in the source
line where it cannot be mistaken for our result.

**Source line, 8pt.**
`n=108 S&P 500 companies with a numeric target and 4+ years of filed Scope 1. EPA GHGRP, 40 CFR Part 98, RY2010-2023; Net Zero Tracker; SBTi. Premise, not our result: Cohen, Rouen and Sachdeva, Nature Climate Change 2026.`

The trend method and the flag-free subset (46 companies, 36 missing, 78.3%) are
in the speaker notes, where there is room for them.

---

## Slide 2. There is no identified ranking

**Claim.** Rank the index every defensible way at once and no company has a rank.

**The number.** `312` at 96pt mono, with `ranks wide, out of 500, for the median
company` beneath in 19pt. The measured value is 312.5; the big figure reads 312
and the source line carries the exact number and what the band is (5th to 95th
percentile of the 10,000 draws).

**Headline.** There is no one ranking, ours included.

`identified` is the econometrics word and it is what the speaker says. On the
screen it reads as "we have not found one yet", which is the opposite of the
claim, so the slide says `one` and the notes say so.

**Rendered.** Two panels on one grid, 2:1.

- Left, the rank interval wall from `#ranks`: 500 horizontal bands, one per
  company, sorted by median rank, x axis 1 to 500. The point is the overlap, so
  do not thin the bands and do not sort by sector. One mono line beneath:
  `497 of 500 companies have a band wider than 100 ranks`.
- Right, Sobol first-order variance shares as horizontal bars, ordered as
  measured, with every label in plain words. Only the weights bar is in
  `--accent`; everything else `--muted`. The panel keeps its own head,
  `What moves a rank is not the weights`, and its own n.

  | Bar | Share | Was called |
  |---|---|---|
  | what we assume about missing data | 20.1% | the missing-data assumption |
  | which pillars are in | 11.3% | unchanged |
  | judged against its sector, or against everyone | 7.0% | sector-relative or absolute |
  | how scores are put on one scale | 6.9% | normalisation |
  | **the weights** | **5.9%** | `Dirichlet(1,1,1,1) over the four pillars` under it |
  | how the four pillars are combined | 1.3% | the aggregation rule |
  | trimming the extremes | 0.004% | winsorisation |
  | choices acting together, and what no one choice explains | 47.5% | interactions and what no single choice explains |

  Sub over the bars: `How much of a rank's movement each choice explains on its
  own.` The residual keeps the honest half of its name: "choices acting
  together" alone would claim attribution the number does not have.

  The picture is `slides/img/02b_sobol_bars_plain.png`, written by
  `src/capture_sobol.py`. It is not redrawn: the script loads the site, lets the
  site's own JS paint the panel out of `scores.json`, rewrites the row labels in
  the DOM and photographs the result. Every bar, every share and the n are the
  page's own.

**Not on this slide.** The effective weight audit (0.325 / 0.231 / 0.312 /
0.132, d_m 0.595). It is the right answer to a question, not a thing to show.

**Source line, 8pt.**
`10,000 draws varying normalisation, trimming, pillar inclusion, missing data, aggregation, weights and the sector lens at once (OECD/JRC handbook). Band: 5th to 95th percentile, median 312.5 ranks. EPA GHGRP, EPA CAMD, SEC XBRL.`

`No vendor ESG score is an input to anything` moved to the speaker notes, where
it is a sentence to say rather than 8pt grey nobody reads. So did `EPA CAMD Part
75` and `40 CFR Part 98`, which the slide-1 and slide-5 source lines still carry
in full.

---

## Slide 3. The demo

**Claim.** Here is the bonus question answered, and the control that moves the
money is not the one you would expect.

**The number.** `0.00%`, the largest weight change across 500 names when carbon
is repriced 3.5x. It is not slide furniture: the recording's own advice panel
prints it at 0:05, next to the reason it is zero.

**Headline.** A 40px strip at the top, nothing more: `03  THE BONUS QUESTION:
$1bn under a carbon price`. Everything else is the recording.

**Rendered.** `docs/demo.mp4`, full bleed, measured at **50.00 seconds**,
rebuilt by `src/record_demo.py` after the site was rewritten in plainer words
and the navigation collapsed to a rail. It is a tour of the whole site, not a
recording of `#allocate` alone, and it ends on its opening frame so it loops.

No captions need burning in. The interface's own copy is the caption, and it is
better than anything we would write over it. At 0:11 the third column prints
`Weights unchanged. Since the last change, value at risk ×3.52, largest weight
change 0.00 bp. The allocation runs on the rank of value at risk, and a scalar
cannot reorder a ranking.` At 0:16 the missing-data control moves and it prints
`Weights moved. Largest weight change 121 bp.` with the money on the 181 going
$141m to $244m to $121m. That contrast is the slide.

Verified timeline, spoken cues and the two silent blocks are in `script.md`,
beat 3. In one line: the scenario goes Current Policies to Net Zero 2050 and the
price 284 to 1000 $2010/t and nothing moves, the missing-data control moves and
the money moves, then 24 seconds of silent tour through the argument, say-do,
the rank wall, the carbon-cut waterfall and the coverage tiers.

The back half re-shows slides 1, 2 and 4. Keep it: it is the strongest evidence
for the technical-execution criterion, and it costs nothing as long as nobody
narrates over it.

Ship the deck as a PDF and the demo as a separate full screen file. Play it on
the venue machine before the session, with the deck open behind it. A demo that
will not start costs more than any slide on this list. The fallback is the live
site at `#allocate`: the two states are one drag and one click apart.

**One extra line, 9pt, top right, always visible.**
`An exposure model, not a forecast. $1bn is 0.00144% of the index.`

The first sentence is the most important caveat the project owns and until this
pass it existed only inside a screenshot, where it was 8 pixels tall. It gets
9pt of its own, on the slide the whole model runs on. `The method does not
depend on the size of the book` moved to the speaker notes under IF ASKED WHY
$1bn.

The line sits on the same band as the strip rather than under the video, so the
slide carries one row of type and then nothing but the recording. The video grew
to fill what that left: 10.95 x 6.16 in, centred.

**The $123m, stated precisely.** The page prints `Spread $123m` under the four
treatment options and it means the swing in the dollars allocated to the 181
non-filers: $121m abstain, $141m sector median, $184m threshold, $244m
zero-fill. It is not $123m of turnover. One-way turnover at the extreme is
$107m, a different number, and a judge who has read `penalty.json` knows both.
Say "what the 181 get moves by 123 million", never "123 million of the billion
moves".

**Source line, 8pt.**
`site/data/penalty.json, all 500 recomputed live: price -> cost -> earnings -> company value -> rank -> weight. The tilt runs on rank, so a uniform reprice cannot move a weight: the zero is an identity. NGFS Phase 5, Net Zero 2050, US 2030.`

The identity is the one claim on this slide a judge can attack, so it stays on
the slide. The deflator, the pass-through step, the EV/EBITDA step and the
sensitivity table (missing data 0.201, exemptions 0.051, Scope 3 0.007, price
0.000) are in the speaker notes and in `qa.md`. The recording prints the third
column's own version of the identity on screen at 0:08, which is better than any
sentence we would set under it.

---

## Slide 4. A Paris aligned fund sells the decarbonisers

**Claim.** The standard rulebook does not decarbonise companies, it reshuffles
the ones you hold, and it sells the fastest cutters.

**The number.** `97.4%` at 96pt mono, with `of the carbon cut is money moving,
not companies cutting` beneath. "Reallocation" is the decomposition's own word
and it is in the chart's bar label, where the legend defines it; the caption
says what it means.

**Headline.** A Paris-aligned fund sells the decarbonisers.

**Rendered.** One horizontal waterfall, four bars, against `share of the PAB
portfolio's carbon intensity cut`:

| Term | Share | Colour |
|---|---|---|
| Reallocation | +97.4% | `--accent` |
| Selection | -0.1% | `--muted` |
| Improvement | +20.5% | `--cool` |
| Interaction | -17.8% | `--muted` |

Print the signs. Do not describe the interaction term as positive or negative in
words anywhere on the slide: the convention is a trap and the bar shows it.

One mono line beneath, and one only. It is the line the spoken script carries,
because it is the one claim on this slide with no counter-example in it:
`Article 6 invites overweighting 19 companies cutting 7% a year. Article 12 bans 9 of them.`

The second mono line, `at lambda 120, an active share of 70.5%, still 82.3%
reallocation`, is cut. Nobody in the room can read `lambda 120` at ten feet. It
is an answer to a hard follow-up, it is in `qa.md`, and it is now in the speaker
notes under IF ASKED. The left column is centred on the waterfall beside it rather
than top-aligned, because with that line gone the top alignment left a quarter
of the slide empty.

**Do not add** a line reading the cross term as "a PAB sells the decarbonisers".
It is a fair reading of the decomposition and it has a counter-example on the
same page: `article7.organic` puts the compliant book's held names at -5.71 %/yr
against the index at -5.03. The waterfall shows the sign; let it.

**Not on this slide.** The three-book comparison, the active share, the sector
weights. They are in the site's section 05 and they are a Q&A answer.

**Source line, 8pt.**
`Commission Delegated Regulation (EU) 2020/1818, articles 6, 11 and 12, encoded as 24 rules. Brinson decomposition of the intensity cut. Article 12 exclusions alone put the book 63.1% below the index, so the solver returned no tilt.`

`universe` became `index`, `bisection solver` became `solver` and `lambda = 0`
became `no tilt`. Same three numbers, same claim, one line.

---

## Slide 5. What we cannot see

**Claim.** Here is the boundary of the measurement, as numbers, and here is what
refusing to impute costs us.

**The number.** `361` at 96pt mono in `--muted`, with `companies file no
emissions figure the law requires. We never invent one, and we never call it
zero` beneath. `no mandatory tonnage` is the repo's phrase and it is two nouns a
judge does not own; the caption says the same thing in the law's own effect.

The number changed from `181`. Both are correct and they are different lanes.
`181 of 500` carry no Scope 1 from **any** source, mandatory, voluntary or
modelled: that is the allocation lane, and it is the number in the demo caption.
`361 of 500` carry no **mandatory** tonnage: that is the score lane, 88 tiered
`reported` plus 273 `unmeasurable`, and it is the split the closing line is
computed on. Putting 181 above a line computed on 361 was the trap. One number
per slide, and the other in the source line.

**Headline.** What we cannot see.

The headline used to read `What we cannot see, stated as a number`. The number
is already set at 96pt beside it, so half that sentence described the layout.
Four words, and they are the four the speaker opens the beat with.

**Rendered.** Four rows. Figure **right-aligned** in a 3.05 in column, 40pt
mono; label left, 18pt, vertically centred on the figure. Right-aligning the
figures makes the gutter one width instead of four, which is what made the old
five-row block read as a wall. Nothing else until the rule.

| | |
|---|---|
| `25,000 t` | below this, a US facility files nothing |
| `582.8` | million tonnes estimated abroad at 25 companies. We measure 375.7 here |
| `2023` | the last year EPA data covers. The next filing lands Oct 2026 |
| `62 of 503` | left the index since Aug 2023. 37 still file with the SEC |

Four rows, four blind spots, and between them they carry every boundary the
model has: the reporting threshold, the border, the last year of data, and the
index churn.

A fifth row, `361 of 500  no mandatory tonnage. Never imputed, always tiered`,
is cut. It repeated the 96pt `361` directly above it, which is a slide restating
itself. `MMT` is cut too: the unit is written into the label so the figure can
be the figure.

Row 2 is **modelled** and the slide says `estimated`. The 582.8 is sized with
Climate TRACE, which is never an input to a score or a weight; the 375.7 beside
it is measured. The tool's name is in the speaker notes.

Row 4 said "no longer exist". They left the **index**; 37 are still SEC
registrants (`universe_turnover.json`, `left_but_still_an_sec_registrant: 37`).
An overstated caveat is still a wrong number.

Then a hairline rule, then one line at 26pt across the width, in `--ink`:

`median rank 344 if we can measure you, 224 if we cannot`

and under it, 18pt `--ink-2`: `Rank 1 is best, so being measurable makes you
look worse. That is the opposite of what vendors reward.`

The rank convention used to be in the speaker notes only, which left the closing
line unreadable to anyone who did not already know that 344 is worse than 224.
"What refusing to impute costs" is spoken in beat 5; the slide does not need to
say it twice.

Rank 1 is best (`scores.json meta.rank_convention`), so 344 is the worse
position. Both the `reported` and `unmeasurable` tiers sit at a median rank of
224, which is why "if we cannot" is fair across the whole 361.

**Source line, 8pt.**
`139 of 500 carry a mandatory measured tonne. The other 361 are a declared category, never a zero: 88 self-reported, 273 with no source. Matching audited at 98% precision. docs/coverage_and_validation.md, docs/entity_resolution_audit.md.`

Both documents are named, so the Wilson interval, the sampling design, the
181/361 reconciliation and the Climate TRACE multiples are one click away
instead of three sentences at 8pt. The claim that must never leave the slide is
the one that stayed: the 361 are **a declared category, never a zero**.

---

## Appendix slide. Water, held for questions

Not part of the 2:30 and the kicker says so: `APPENDIX   Q&A BACKUP   NOT PART
OF THE 2:30`, in `--accent` mono. Do not advance to it during the pitch.

**Headline.** Water is a second axis, and carbon does not predict it.

**The number, in words first.** `Carbon explains 0.3% of the water ranking.` at
20pt, and the statistic under it at 16pt mono in `--accent`:
`rank correlation 0.058, p = 0.51, n = 135`. The plain sentence leads; a judge
who wants the test gets it on the next line. `rho` is spelled out.

**Two companies, two lines each.** Broadcom at the 7th percentile on carbon with
its one US facility in an Extremely High stress basin; Evergy at the 99th with
none of its 24 in a stressed basin. Then the close: `One number would put them
in the same place. So water is a separate axis in the interface, and it is not
in the score.`

**Rendered.** The site's own treemap with the `CARBON / WATER` toggle set to
WATER, cropped out of the allocate view at build time. The full-page capture was
a grey smear at slide size; the crop keeps the toggle, the basin colouring and
the `358 with no US facility` key, which is the honest part of the picture.

**Source line, 8pt.**
`site/data/water.json. WRI Aqueduct 4.0 annual water stress, July 2023, CC BY 4.0, joined to EPA GHGRP facility coordinates: 11,200 of 11,358 facilities, 142 of 503 tickers. A model, labelled as one, never an input. docs/water_risk.md.`

---

## Why this order

The arc is: they are missing their own promises, so we tried to rank them, so
ranking does not work, so price the risk instead, and the official rulebook that
claims to do this sells the wrong companies, and here is what we still cannot
see.

One deviation from the proposed running order. Finding 6 was to close; it sits
at slide 4 and the limits close instead. Two reasons. The limits slide is a
scored criterion and the judges remember what came last. And the last line of
slide 5 is not an apology: "being measurable is a penalty in our index" is the
most contrarian sentence in the deck and it is a limitation at the same time, so
we close honest and contrarian in one breath.

If the team disagrees, slides 4 and 5 swap cleanly. Neither depends on the
other, and the only edit is the "before you ask" opener on slide 5, which has to
become "one more thing" if it moves earlier.

If a slide has to go, it is slide 4. Never slide 3, never slide 5.

## What was fact-checked and what moved

Every figure above was re-read from `site/data/*.json`, `data/interim/` and
`docs/` rather than from the brief. Five corrections landed in this file:
the slide 1 scatter orientation (missing the promise is ABOVE the line, not
below), the slide 3 caption wording on the $123m, the slide 3 source line now
stating the price invariance as the identity it is, the slide 4 instruction not
to read the cross term aloud, and the whole of slide 5's coverage arithmetic.
The failures and the exact sources are listed in `qa.md`.

## What is deliberately not in the deck

The disclosure bias regressions, water as a second axis, the entity resolution
audit, and the reported against measured work. Four findings, all measured, all
held for Q&A with the numbers written out in `script.md`. They are worth more as
answers than as slides, and none of them fits in 150 seconds without displacing
something stronger.

Price invariance is the half exception, and deliberately so. It gets no slide
and no argument, but it is what the demo does on screen, and the one sentence
after the GIF states it. Spending a slide on it would cost 25 seconds to say
what 6 seconds of recording already shows. The sensitivity table behind it
(missing data 0.201, exemptions 0.051, Scope 3 0.007, price 0.000) stays in the
Q&A card.

---

## The legibility pass

Measured off the built `.pptx` with `python-pptx`, words that render on the
slide, furniture included. The speaker notes are not counted and they grew: the
detail did not leave the deck, it moved to where the speaker can read it.

| Slide | Before | After | |
|---|---|---|---|
| 01 Say and do | 104 | 82 | source line 60 words to 38 |
| 02 There is no one ranking | 97 | 76 | eight bar labels in plain words |
| 03 The demo | 148 | 78 | source line 108 words to 43, video 5% bigger |
| 04 The Paris-aligned fund | 100 | 85 | the lambda line cut |
| 05 What we cannot see | 211 | 149 | five rows to four, headline 8 words to 4 |
| A Water | 177 | 144 | picture cropped to the control |
| **Total** | **837** | **614** | **-27%** |

Nothing on the "must not be lost" list left the deck. Every one of them is still
in the default view of the slide it belongs to:

- companies we cannot measure are a declared category, never a zero: slide 5
  caption, `We never invent one, and we never call it zero`, at 19pt
- every chart states how many companies it covers: the captured panels carry
  their own n (`n = 500 companies`, `n = 108 plotted`, `n = 500 x 10 000 draws`)
- the model is an exposure estimate, not a forecast: **added** to slide 3 at
  9pt, top right, where it used to exist only inside the screenshot
- US facilities only, above a reporting threshold, and stopping in 2023: slide
  5, rows 1, 2 and 3, at 40pt

Numbers did move. Every figure that came off a slide landed in that slide's
speaker notes or in a document the source line names, and none of them was a
caveat:

| Moved off the slide | To |
|---|---|
| `at lambda 120, an active share of 70.5%, still 82.3% reallocation` | slide 4 notes, IF ASKED, and `qa.md` |
| flag-free subset, 46 companies, 36 missing, 78.3% | slide 1 notes, IF ATTACKED |
| sensitivity 0.201 / 0.051 / 0.007 / 0.000, `US$2010/t`, the deflator 1.44, the full model chain | slide 3 notes |
| Wilson 95% CI 89.5-99.6% on 50 hand-checked matches | slide 5 notes, and `docs/entity_resolution_audit.md` |
| Chevron 9.1x, ExxonMobil 4.3x; Climate TRACE as the tool | slide 5 notes |
| `361 of 500` as a row | nowhere: the 96pt `361` above it already said it |
| the 98.6% Aqueduct join rate | appendix notes, and `docs/water_risk.md` |

Two things were **added** to a slide rather than taken off one. `Rank 1 is best`
on slide 5, which was in the notes only and left the closing line unreadable to
anyone who did not already know that 344 is worse than 224. And `An exposure
model, not a forecast.` on slide 3, which is the caveat this project is built on
and which had never been set in type anywhere in the deck.
