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
- Two mono lines under the plot: `promised, median 5.92 %/yr cut` and
  `delivered, median 1.87 %/yr cut`.

**Not on this slide.** No company names. No vendor comparison. No mention of the
Nature paper in the body text: it is the premise, and it lives in the source
line where it cannot be mistaken for our result.

**Source line, 8pt.**
`n=108 S&P 500 companies with a numeric target and 4+ years of filed Scope 1. Trend: log-linear OLS with a perimeter-break rule. Holds on the flag-free subset the site shows: 46 companies, 36 missing, 78.3%. Sources: EPA GHGRP, 40 CFR Part 98, RY2010-2023; Net Zero Tracker; SBTi. Premise, not our result: Cohen, Rouen & Sachdeva, Nature Climate Change, Jan 2026.`

---

## Slide 2. There is no identified ranking

**Claim.** Rank the index every defensible way at once and no company has a rank.

**The number.** `312` at 96pt mono, with `ranks wide, 5th to 95th percentile,
median company` beneath in 19pt. The measured value is 312.5; the big figure
reads 312 and the source line carries the exact number.

**Headline.** There is no identified ranking. Ours included.

**Rendered.** Two panels on one grid, 2:1.

- Left, the rank interval wall from `#ranks`: 500 horizontal bands, one per
  company, sorted by median rank, x axis 1 to 500. The point is the overlap, so
  do not thin the bands and do not sort by sector. One mono line beneath:
  `497 of 500 companies have a band wider than 100 ranks`.
- Right, Sobol first-order variance shares as six horizontal bars, labelled and
  ordered as measured: missing-data assumption 20.1, pillar inclusion 11.3,
  sector-relative 7.0, normalisation 6.9, **weights 5.9**, aggregation 1.3. Only
  the weights bar is in `--accent`. Everything else `--muted`. Header over the
  bars: `share of the variance in a company's rank`.

**Not on this slide.** The effective weight audit (0.325 / 0.231 / 0.312 /
0.132, d_m 0.595). It is the right answer to a question, not a thing to show.

**Source line, 8pt.**
`10,000 Monte Carlo draws varying normalisation, winsorisation, pillar inclusion, imputation, aggregation, weights and the sector-relative toggle simultaneously (OECD/JRC composite indicator handbook). Median band width 312.5 ranks. Sobol first-order indices on the same design. Inputs: EPA GHGRP 40 CFR Part 98, EPA CAMD Part 75, SEC XBRL. No vendor ESG score is an input to anything.`

---

## Slide 3. The demo

**Claim.** Here is the bonus question answered, and the control that moves the
money is not the one you would expect.

**The number.** `0.00%`, the largest weight change across 500 names when carbon
is repriced 3.5x. It is not slide furniture: the recording's own advice panel
prints it at 0:05, next to the reason it is zero.

**Headline.** A 40px strip at the top, nothing more: `03  THE BONUS QUESTION:
$1bn under a carbon price`. Everything else is the recording.

**Rendered.** `docs/demo.mp4`, full bleed, measured at **50.08 seconds**. It
already exists and it is not what this section originally specified: it is a
tour of the whole site, not a recording of `#allocate` alone. Ship the file that
exists. Do not re-record it the night before.

No captions need burning in. The interface's own copy is the caption, and it is
better than anything we would write over it. At 0:05 the advice panel prints
`Weights unchanged. Value at risk x3.52, largest weight change 0.00 bp. The
allocation runs on the rank of value at risk, and a scalar cannot reorder a
ranking.` At 0:09 the missing-data control moves and it prints `Weights moved.
Largest weight change 30 bp.` with the money on the 181 falling from $141m to
$121m. That contrast is the slide.

Verified timeline, spoken cues and the two silent blocks are in `script.md`,
beat 3. In one line: the price goes 284 to 1000 $2010/t and nothing moves, the
missing-data control moves and the money moves, then 36 seconds of silent tour
through say-do, the rank wall, the weight audit and the PAB waterfall.

The back half re-shows slides 1, 2 and 4. Keep it: it is the strongest evidence
for the technical-execution criterion, and it costs nothing as long as nobody
narrates over it.

Ship the deck as a PDF and the demo as a separate full screen file. Play it on
the venue machine before the session, with the deck open behind it. A demo that
will not start costs more than any slide on this list. The fallback is the live
site at `#allocate`: the two states are one drag and one dropdown apart.

**One extra line, 9pt, bottom right, always visible.**
`$1bn is 0.00144% of the index. The method does not depend on the size of the book.`

**The $123m, stated precisely.** The page prints `Spread $123m` under the four
treatment options and it means the swing in the dollars allocated to the 181
non-filers: $121m abstain, $141m sector median, $184m threshold, $244m
zero-fill. It is not $123m of turnover. One-way turnover at the extreme is
$107m, a different number, and a judge who has read `penalty.json` knows both.
Say "what the 181 get moves by 123 million", never "123 million of the billion
moves".

**Source line, 8pt.**
`site/data/penalty.json, recomputed in the browser for all 500 companies: price x deflator -> coverage -> abatement at the observed rate -> cost -> dEBIT after sector pass-through -> dEV at the company's own EV/EBITDA -> value at risk -> RANK -> weight. The chain is linear in price and the tilt runs on the rank, so a uniform reprice provably cannot move a weight: the zero is an identity, stated as one. Price DISPERSION across sectors does move it. NGFS Phase 5 REMIND, Net Zero 2050, US, 2030, US$2010/t. Allocation sensitivity at a fixed tilt: missing data 0.201, sector exemptions 0.051, Scope 3 coverage 0.007, price level 0.000.`

---

## Slide 4. A Paris aligned fund sells the decarbonisers

**Claim.** The standard rulebook does not decarbonise companies, it reshuffles
the ones you hold, and it sells the fastest cutters.

**The number.** `97.4%` at 96pt mono, with `of the carbon cut is reallocation`
beneath.

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

One mono line beneath, and it is the line the spoken script carries because it
is the one claim on this slide with no counter-example in it:
`Article 6 invites overweighting 19 companies cutting 7%/yr. Article 12 bans 9 of them.`
One more, smaller: `at lambda 120, an active share of 70.5%, still 82.3% reallocation`.

**Do not add** a line reading the cross term as "a PAB sells the decarbonisers".
It is a fair reading of the decomposition and it has a counter-example on the
same page: `article7.organic` puts the compliant book's held names at -5.71 %/yr
against the index at -5.03. The waterfall shows the sign; let it.

**Not on this slide.** The three-book comparison, the active share, the sector
weights. They are in the site's section 05 and they are a Q&A answer.

**Source line, 8pt.**
`Commission Delegated Regulation (EU) 2020/1818, articles 6, 11 and 12, encoded as 24 rules. Brinson-style decomposition of the change in portfolio carbon intensity. Article 12 exclusions alone put the book 63.1% below the universe against Article 11's 50% requirement, so the bisection solver returned lambda = 0.`

---

## Slide 5. What we cannot see

**Claim.** Here is the boundary of the measurement, as numbers, and here is what
refusing to impute costs us.

**The number.** `361` at 96pt mono in `--muted`, with `companies with no
mandatory tonnage. We impute nothing for them` beneath.

The number changed from `181`. Both are real and they are different lanes.
`181 of 500` carry no Scope 1 from **any** source, mandatory, voluntary or
modelled: that is the allocation lane, and it is the number in the demo caption.
`361 of 500` carry no **mandatory** tonnage: that is the score lane, 88 tiered
`reported` plus 273 `unmeasurable`, and it is the split the closing line is
computed on. Putting 181 above a line computed on 361 was the trap. One number
per slide, and the other in the source line.

**Headline.** What we cannot see, stated as a number.

**Rendered.** Five rows. Number left, 40pt mono, label right, 19pt. Nothing else
until the rule.

| | |
|---|---|
| `25,000 t` | the EPA reporting floor. Below it, a facility files nothing |
| `582.8 MMT` | held abroad by 25 companies, against 375.7 MMT we measure here |
| `2023` | last GHGRP reporting year. RY2025 is due 30 Oct 2026 |
| `62 of 503` | left the index since Aug 2023. 37 of them still file with the SEC |
| `361 of 500` | no mandatory tonnage. Never imputed, always tiered |

Row 4 said "no longer exist". They left the **index**; 37 are still SEC
registrants (`universe_turnover.json`, `left_but_still_an_sec_registrant: 37`).
An overstated caveat is still a wrong number.

Then a hairline rule, then one line at 26pt across the width, in `--ink`:

`median rank 344 if we can measure you, 224 if we cannot`

and under it, 19pt `--ink-2`: `being measurable is a penalty in our index. That
is the inverse of the vendor incentive, and it is what refusing to impute costs.`

Rank 1 is best (`scores.json meta.rank_convention`), so 344 is the worse
position. Both the `reported` and `unmeasurable` tiers sit at a median rank of
224, which is why "if we cannot" is fair across the whole 361.

**Source line, 8pt.**
`Score lane: 139 of 500 carry a mandatory measured tonne, 361 do not (88 reported, 273 unmeasurable) and are never imputed. Master table: 319 of 500 carry a Scope 1 from some source, 181 carry none. Foreign exposure on the 25 companies with material foreign assets, sized with Climate TRACE, a model, never an input: Chevron 9.1x, ExxonMobil 4.3x. Entity resolution audited at 98% precision, Wilson 95% CI 89.5-99.6%, on a tonnes-stratified random sample of 50. docs/coverage_and_validation.md, docs/entity_resolution_audit.md.`

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
