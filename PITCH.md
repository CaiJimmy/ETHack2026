# GreenRank pitch: 3-minute flow

Audience: the team recording the video. Every number below is read from the current build (`web/data/master.json`, fund model at $150/t, 50% cap, tilt 1.0). Re-check them if the data is rebuilt.

## Verdict on the current deck

The seven slides have the right ingredients but read as a notes file, not a story. Specific problems:

- **No name.** Slide 3 still says "This is where NAME comes in". Call it GreenRank everywhere, or pick the name today.
- **The hook is buried.** Slide 1 opens with a persona. Open with the quiz question instead; move the persona into the problem slide.
- **No definition of sustainability and no dataset justification.** The challenge text asks for both explicitly. The Methods tab has them. The deck does not.
- **Slide 4 is a pasted script.** The concentration table is the strongest fact you have. It needs to be the visual, next to the treemap flip.
- **Slide 5 is a placeholder.** The real numbers are more interesting than "less utilities, more tech" and they are counter-intuitive: the fund changes only 4% of the portfolio.
- **Slide 6 (globe) does not fit, and the slide says so.** The globe colours countries by 2018 CO2 per person, which says nothing about an all-US index. See "Changes needed" for the fix.
- **Slide 7 mixes limits with advantages.** Judges score honesty and feasibility separately. Split them.

Structure that works for three minutes, at about 25 seconds a slide: hook, problem, definition and data, explore demo, fund demo, limits, why it survives. Seven slides, seven beats.

## Slide-by-slide

Speech is about 130 words a minute, so the whole script is under 400 words. Everything in *italics* is spoken.

### 1. Hook (0:00 to 0:20)

**Show:** Screen recording of the Quiz tab. Question: "Which company released more CO2 from its own US sites in 2023?" ExxonMobil or Duke Energy. Click Exxon. Reveal: Duke 72.8 Mt, Exxon 37.9 Mt.

**Say:** *Who emits more on US soil, ExxonMobil or Duke Energy? Most people pick Exxon. It is Duke, by almost double. Your intuition about sustainability is wrong, and so is most of the market's. We are GreenRank.*

**Criterion:** Presentation (problem framing), Impact (who this is for).

### 2. Problem (0:20 to 0:45)

**Show:** The S&P Global ESG anatomy diagram you already have (1,000 data points, 100 question scores, one number). Overlay three lines: "Raters agree about half the time", "Paid subscription", "You cannot see inside".

**Say:** *If you are an independent investor who wants a greener portfolio, you get this: a black box built from questionnaires, sold by subscription, and the big raters disagree with each other about half the time. We wanted a score anyone can check, built on data companies cannot opt out of.*

**Criterion:** Impact (retail investors and small pension funds benefit), Innovation (the fresh angle starts here).

### 3. Definition and data (0:45 to 1:05)

**Show:** One slide, three boxes. Left: the definition, quoted from the Methods tab: "A company is sustainable when it can keep its business in a world that puts a price on carbon, enforces labour and safety law, and holds the board responsible." Middle: the four pillars, E, S, G, Financial resilience, with the source of each: EPA GHGRP, Sustainalytics, Altman Z and Piotroski F. Right: how the score is made in three steps: rank each metric against the sector, average within pillar, weight the pillars with the sliders.

**Say:** *Our definition: a company is sustainable if it can keep its business in a world that prices carbon and enforces the law. Our anchor dataset is the EPA Greenhouse Gas Reporting Program. Every US site above 25,000 tonnes must report by law, and it is audited. We join it to financials and ratings for all 500 companies, then rank each company only against its own sector. A bank and a power company are never compared on emissions.*

**Criterion:** This slide answers the challenge's explicit asks: define sustainability, justify the indicators, justify the dataset. Innovation (legally mandated facility data instead of vendor scores; sector-relative percentiles).

### 4. Explore demo: the flip (1:05 to 1:45)

**Show:** Screen recording of the Explore tab in treemap view. Start with boxes sized by market value: tech dominates. Change the size dropdown to CO2. Utilities fill the screen, tech vanishes. Then click Duke Energy for the score card: each metric, sector percentile, source. Put the table below as a static overlay during the flip.

| Companies | Share of index's own US emissions | Share of index market value |
|---|---|---|
| Top 10 | 49% | 3.3% |
| Top 30 | 85% | 5.1% |
| All utilities and energy (51) | 82% | 5.3% |

**Say:** *This is the S&P 500 sized by market value. Now sized by CO2 from their own US sites. The picture inverts. Thirty companies hold five percent of the index's value and eighty-five percent of its direct emissions. The S&P 500's sustainability problem is thirty companies. Click any box and you see every metric, its sector percentile, and where the number came from.*

**Criterion:** Innovation (the concentration finding is the non-obvious insight), Technical Execution (500 real companies, working UI, transparent score card).

### 5. Net-Zero Fund (1:45 to 2:25)

**Show:** Screen recording of the Fund tab. Carbon price slider at $150. Point at the "companies cut" list, then the result tiles. Then the sector tilt bars.

Results at the defaults:

| Metric | Index | GreenRank fund |
|---|---|---|
| CO2 per $1M revenue | 42 t | 7 t |
| Profit at risk at $150/t | 2.2% | 0.4% |
| Active share | | 4% |
| Utilities weight | 2.2% | 0.8% |
| Energy weight | 3.2% | 2.0% |
| Technology weight | 32.6% | 34.0% |

**Say:** *The bonus question: tomorrow the world goes net zero, and you run a billion dollars. We put a price on carbon, $150 a tonne. At that price twelve companies lose their entire operating profit to the carbon bill, mostly coal and gas utilities. Our fund cuts emissions per dollar by more than 80 percent and cuts profit at risk five-fold. And here is the surprise: it changes only 4 percent of the portfolio. You do not sell the index. You surgically reweight thirty names. That is the practical answer, and it is the only one a fiduciary could actually execute.*

**Criterion:** Impact (a fiduciary can act on this), Innovation (carbon shadow price turns emissions into a profit number), Feasibility (the answer is executable, not a fantasy portfolio).

### 6. Limits (2:25 to 2:45)

**Show:** Four bullets, nothing else. Read them straight.

**Say:** *What the model does not know. One: US sites only, so a company with no big US site scores zero emissions, which is a gap, not a fact. Two: no supply chain emissions, and for banks and retailers that is where most of it is. Three: sector ranking hides that the best utility still out-emits the worst bank. Four: the ratings copy is from 2024, the emissions from 2023, the prices from this month.*

**Criterion:** Presentation (honest about limitations). Judges have this as a named item. Say the limits before they ask.

### 7. Why it survives the weekend (2:45 to 3:00)

**Show:** One line each: no backend, no API keys, zero running cost. All sources public and listed with links. One script rebuilds the dataset. EPA publishes every year, so the refresh is one command. Then the URL or QR code.

**Say:** *GreenRank is a static site with no backend and no cost. Every source is public and linked. One script rebuilds it, and the EPA publishes new data every year. Free, transparent, and built on what companies already have to disclose. Try it.*

**Criterion:** Feasibility, Impact (free access), Presentation (finished on time).

## Criteria checklist

| Criterion | Where it is answered | The one sentence to land |
|---|---|---|
| Impact | Slides 2, 5, 7 | Independent investors and small funds get an auditable score for free, and fiduciaries get an executable net-zero portfolio. |
| Innovation | Slides 3, 4, 5 | Legally mandated facility emissions instead of vendor scores, sector-relative ranking, and a carbon price that turns tonnes into profit at risk. The 30-company finding is the insight. |
| Technical Execution | Slides 4, 5, demo | 500 companies, five working tabs, 2,265 hand-matched EPA facilities, 492 checked logos, a quiz that reads live values. |
| Feasibility | Slide 7 | Zero cost, public data, one rebuild script, yearly refresh from a legal filing. |
| Presentation | Slides 1, 6, whole flow | Quiz hook, one visual reveal, one-sentence bonus answer, limits stated unprompted, under three minutes. |

## Changes needed before recording

Ordered by how much they matter.

1. **Replace the world globe with a US facility map.** The EPA data already has coordinates for every reporting site. Joining the parent-company file to the by-year sheet gives 2,265 facilities with lat/lon for 127 S&P 500 companies. Plot them on the existing flat map (or the globe zoomed to the US), sized by tonnes, coloured by company. The largest single sites are James H Miller Jr (Southern, 16.6 Mt), Labadie (Ameren, 15.4 Mt), and Martin Lake (Vistra, 12.8 Mt). This turns the weakest tab into a second visual reveal and it is a two-hour job, since the join is already in `data/build_master.py`. If there is no time, cut the globe from the pitch entirely and give it one sentence on slide 7 as future work.
2. **Head-office pins are now complete.** 502 of 503 companies have a checked location (was 455). The 47 missing ones were index additions and spin-offs absent from both snapshots; they are hand-listed in `data/build_hq.py`. Nvidia and six others were pinned to the Santa Clara county centroid and are now in the city. The one unplaced row is "Vivmark Residential", an OCR artefact with no real company behind it.
3. **Boeing shows 100% profit at risk.** Its EBITDA is negative, so the model floors it at $50M and any carbon bill swamps it. Exclude negative-EBITDA companies from the hit calculation, or a judge will spot Boeing in the cut list and ask why an aircraft maker is a carbon casualty.
4. **Vistra and Constellation have no EBITDA** and fall back to 15% of revenue. They are the two largest emitters, so this assumption drives the top of the cut list. Fill the two numbers by hand or add them to the limits slide.
5. **Name the product.** Replace NAME on slide 3. The site already says GreenRank.
6. **Record the two demos as clips**, not live. The treemap flip and the fund slider are the only moving parts you need. Live demos eat the clock.
7. **Add the definition slide.** The challenge text asks for it. It is the cheapest slide to make, since the text exists on the Methods tab.
