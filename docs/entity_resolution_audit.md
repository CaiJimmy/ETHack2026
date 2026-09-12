# Adversarial audit of the entity resolution

Scope: everything `src/match_parents.py` produces, audited by a separate pass with no stake in the
result. The question is not whether the lane works. It is how often it is wrong, and by how many
tonnes.

Everything below reproduces from the repo. Samples are drawn with fixed seeds
(`random_state=20260912` for matched pairs, `7` for unmatched tickers) so a judge can redraw them.

## Headline

| Measure | Result |
|---|---|
| Row precision, 50 hand-checked matches | **49 / 50 = 98.0%**, 95% Wilson interval **[89.5%, 99.6%]** |
| Precision on the top-100 rows by tonnes | 25 / 25 = 100% |
| Precision on the tail | 24 / 25 = 96% |
| Tonnes-weighted precision, RY2023 / 2025 basis | **100.00%** (the one bad row carries no current-year tonnes) |
| Tonnes-weighted precision, largest-year basis | **97.97%** (13.8 MMT of 678.5 MMT sampled) |
| Recall, 30 sampled S&P 500 tickers with no match | **0 matching failures.** 25 with no US facility over the threshold, 3 spin-offs that post-date the data, 2 deliberate policy exclusions |
| Recall by tonnes: misses found in the top 150 unmatched GHGRP strings (920.8 MMT, 62% of all unmatched tonnes) | **0** |
| Misses found in the top 40 unattributed CAMD owner groups (301.1 MMT, 44% of unattributed) | **0** |
| Errors found and fixed | **3 false positives, 1 latent key collision, 2 hygiene defects** |

The honest reading: the matching is very good on the numbers that drive the score, and it was
noticeably weaker on the historical series than the current-year headline suggests. Every error we
found lives in years before 2023. That is not luck, it is structure: a wrong corporate-action call
shows up where the company no longer owns the asset, which is the past.

## What we checked

1. **Precision.** 50 matched parent-string-to-ticker pairs, stratified so 25 come from the top 100
   rows by tonnes and 25 from the remaining 404. Each verified against the physical facilities EPA
   files under that exact string (name, state, sector, ownership percentage, years present), and
   against the corporate-action record where an acquisition was claimed.
2. **Recall.** 30 S&P 500 tickers the lane leaves uncovered, weighted toward Utilities, Energy,
   Materials, Industrials and Consumer Staples. For each, every distinctive token of the company
   name and of its SEC registrant name was searched against all 7,304 GHGRP parent strings, all
   11,358 GHGRP facility names and all 1,474 CAMD owner strings. Separately, the top 150 unmatched
   GHGRP strings and the top 40 unattributed CAMD groups were read one by one.
3. **Joint ownership.** Every RY2023 facility with more than one named parent, plus every facility
   named to two or more distinct S&P 500 tickers.
4. **Key safety.** Every matching key that produced a match, checked for whether a second, different
   company could reach it.

## Errors found and fixed

### 1. Energy Harbor was sent to Vistra. Vistra never bought those plants. (11-13% of Vistra's 2021-22)

The override `ENERGY HARBOR CORP -> VST` was justified as "Vistra closed the Energy Harbor
acquisition in March 2024". The acquisition is real. The facilities are not. The only two GHGRP
facilities EPA files under that string are **W H Sammis** (Ohio, 6.03 MMT) and **Pleasants Power
Station** (West Virginia, 7.73 MMT), and Vistra's own deal announcement says it did not acquire any
part of Energy Harbor's coal fleet: both plants had already been sold to third parties. Pleasants
went to Omnis Fuel Technologies, which the lane's own notes already list as private.

| VST, MMT Scope 1 | before | removed | after | overstated by |
|---|---:|---:|---:|---:|
| 2021 | 112.57 | 12.57 | 100.00 | 11.2% |
| 2022 | 109.32 | 13.75 | 95.57 | 12.6% |

RY2023 is unaffected, so the headline 44.82% does not move. The trajectory does, and the trajectory
is what this project sells.

Fixed: moved from `OVERRIDES` to `BLOCKED` with the evidence written in.

### 2. Legacy DuPont was sent to DuPont de Nemours. Four fifths of it is Chemours. (up to 13.4 MMT/yr)

The override `E I DU PONT DE NEMOURS & CO -> DD` gave DuPont de Nemours the whole of old DuPont's
2010-2018 footprint. Reading the facility list settles it:

| Facility | Max share, t | Where it actually went |
|---|---:|---|
| Chemours Louisville Works | 6,005,571 | Chemours, 2015 spin |
| SRW Cogen LP | 2,585,691 | Sabine River Works, performance materials, to Dow in 2019 |
| Sabine River Operations | 1,086,284 | same |
| Chemours Washington Works | 1,025,451 | Chemours |
| Chemours Chambers Works | 1,012,122 | Chemours |
| Chemours DeLisle, Fayetteville, Johnsonville, Belle, El Dorado, Memphis, Corpus Christi | ~2,050,000 | Chemours |
| DuPont Old Hickory, Circleville, Experimental Station, La Porte, Kinston | ~0.3 MMT/yr | DuPont de Nemours, and already matched under `DUPONT DE NEMOURS INC` |

Roughly 79% of the 12.8 MMT this string carries in 2014 sits at Chemours plants. Chemours is a
separate listed company (CC) and not an index constituent.

The consequence before the fix: DD showed 9.36 MMT in 2010 falling to 0.18 MMT in 2023, a 98% cut
that is entirely corporate restructuring. After the fix DD's series starts in 2019 at 1.16 MMT and
runs to 0.18 MMT, with nulls before. We lose about 0.3 MMT/yr of DuPont's real small sites in
2010-2018. A null is the right answer there; a 13 MMT fabrication is not.

Fixed: moved to `BLOCKED`.

### 3. Waste Industries was sent to Waste Management. It went to GFL. (0.47 MMT/yr)

`WASTE INDUSTRIES USA INC` matched WM. Waste Industries USA was a Raleigh hauler bought by **GFL
Environmental in 2018**. The mechanism is the failure mode the lane said it had eliminated: the
strict key strips `INDUSTRIES`, `USA`, `SERVICES` and `INC`, so both `WASTE INDUSTRIES USA INC` and
WM's SEC former name `USA WASTE SERVICES INC` collapse to the five-letter key `WASTE`. The two
facilities are W I Taylor County Landfill (Georgia) and Lakeway Sanitation (Tennessee).

| WM, MMT | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 |
|---|---:|---:|---:|---:|---:|---:|
| before | 27.85 | 18.31 | 16.15 | 14.25 | 15.56 | 16.32 |
| after | 27.45 | 17.88 | 15.75 | 13.83 | 15.11 | 15.85 |

Fixed: moved to `BLOCKED`.

### 4. The NV Energy override was keyed on the single word ENERGY (latent, 0 MMT today)

`key_strict("NV ENERGY")` is `"ENERGY"`, because the GHGRP normaliser strips `NV` as a legal form.
The override table was indexed on that key, so **any** string reducing to the bare word `ENERGY`
became Berkshire Hathaway. Two already do: CAMD's `Energy Co.` (a co-owner on ORIS 56806, 0.82 MMT
of 2025 CO2) and `AG Energy, LP`. Neither was actually booked, because both sit on units with more
than one named owner and the sole-owner rule blocked them. The exposure today is **0.0 MMT**. The
exposure from the next CAMD refresh is not bounded by anything.

Fixed in `src/match_parents.py`, in nine lines: overrides are now indexed on a punctuation-only key
(`NVENERGY`) as well as the tolerant key, and the tolerant key is refused when it collapses to a
single non-identifying word. NV Energy keeps its 5.66 MMT; `Energy Co.` and `AG Energy, LP` fall
back to unmatched. This is the only change outside the overrides file and it is easy to revert.

### 5 and 6. Hygiene

- `UNMATCHED_NOTES` had two duplicate keys (`INVENERGY LLC`, `REMC ASSETS LP`). Python kept the
  later one silently.
- The `MPLX LP` entry carried Pioneer's verification comment stapled to the end of its own, and
  `SEMPRA ENERGY` had no comment at all despite the file's claim that every entry carries one.

Both fixed, and 43 new notes added for unmatched emitters that were carrying no reason. An
unclassified 3 MMT emitter looks like a miss to a judge; 21 of the top 150 remain unclassified, down
from 59.

## Before and after

| | before | after |
|---|---:|---:|
| Overrides | 28 | 26 |
| Blocked impostor strings | 9 | 12 |
| Unmatched notes | 118 | 161 |
| Map rows carrying a ticker | 504 | 497 |
| Ticker-years carrying a measured value | 1,869 | 1,860 |
| Tickers with non-zero RY2023 Scope 1 | 128 | 128 |
| RY2023 share of US GHGRP direct emissions | 44.82% | 44.82% |
| CAMD 2025 attributed | 801.6 MMT (54.0%) | 801.6 MMT (54.0%) |
| Phantom tonnes removed from the historical series | | **13.75 MMT (VST 2022), 13.45 MMT (DD 2011), 0.47 MMT (WM 2018)** |

The current-year headline is unchanged because all three false positives carried zero RY2023 tonnes.
Runtime 2.3s, no network I/O, and a second run leaves all three outputs byte-identical.

## Joint ownership: no double counting found

This was the check most likely to find a systematic problem, and it came back clean.

- RY2023 has 11,281 facilities, 602 with more than one named parent.
- Stated ownership fractions sum above 101% on **1** facility, which carries no reported CO2e.
- They sum below 99% on 57 facilities holding 10.98 MMT. Those tonnes are left unclaimed rather than
  scaled up, which is the honest treatment.
- Summed across every parent, RY2023 shares total **2,696.5 MMT** against a facility total of
  **2,697.0 MMT**. The 0.4 MMT gap is exactly the under-100% residual. Nothing is counted twice.
- 123 RY2023 facilities are named to two or more distinct S&P 500 tickers. Every spot check
  reconciles to the stated percentages:

  | Facility | Named parents, RY2023 | Sum | Our tickers get |
  |---|---|---:|---:|
  | Scherer (GA) | Oglethorpe 40.00, Southern 30.60, MEAG 20.13, NextEra 8.33 | 99.06% | SO + NEE = 38.93% |
  | Craig (CO) | Tri-State 49.33, Salt River 19.34, Berkshire 12.86, Platte River 12.00, Xcel 6.47 | 100.00% | BRK.B + XEL = 19.33% |
  | Columbia (WI) | Alliant 53.50, Integrys 27.50, MGE 19.00 | 100.00% | LNT + WEC = 81.00% |
  | Chevron Phillips Cedar Bayou (TX) | Chevron 50.00, Phillips 66 50.00 | 100.00% | CVX + PSX = 100% |

  The co-ops, municipals and public power districts keep their share and it stays unattributed,
  which is the correct answer rather than a rounding-up to the listed owner.
- The lane's own correction for EPA listing one parent twice at 100% still fires on 22 facility-year
  rows and removes 8.59 MMT across all years. We reproduced it and found no further duplicates.
- Calpine's three filing names (`CALPINE CORP` 2011-2018, `VOLT PARENT LP` 2019-2022,
  `CPN MANAGEMENT LP` 2022-2023) all point at CEG. **Zero** facility-years are claimed by two of
  them, so the 56.6 MMT is not inflated by the handover.

## Things that are right, but the slide has to say them carefully

**Coverage is 139 measured, not 146.** Seven of the 146 tickers flagged `covered=True` never carry a
measured tonne in any year: AZO, CARR, DOV, LII, TGT, TT, WMT. They are real GHGRP reporters, but
under a subpart with no direct emissions (refrigerants), so EPA names them as a parent with a null
tonnage. The matches are correct. The coverage claim is not. Say 139.

**The perimeter is retroactive, and it matters more than the lane's note implies.** Applying today's
ownership to 2010-2023 is defensible for a like-for-like trend, and the lane flags it. But the effect
is large and asymmetric. Exelon runs at 8 to 15 MMT from 2010 to 2021 and then falls to 0.32 MMT in
2022, because the generation fleet went to Constellation in the February 2022 spin and CEG's own
string picks it up from there. Edison International runs at 41 to 46 MMT from 2010 to 2013 and then
falls to 2.57 MMT in 2014, because Edison Mission Energy went through Chapter 11 and NRG bought
Midwest Generation. Neither drop is decarbonisation. Anyone drawing a "who emitted what in 2014"
chart off this table will be wrong; a trend chart of what a company owns now is fine, and the two
should never share an axis.

**The CAMD owner field is stale and the lane is right not to trust it.** ORIS 2828, Cardinal, Ohio.
CAMD still names AEP Generation Resources as owner of Unit 1 in 2025, worth 3.31 MMT. AEP sold that
unit to Buckeye Power in August 2022, and GHGRP books the whole plant to Buckeye. We went in expecting
a 3.3 MMT recall miss for AEP and came out with a vindication of the design decision to prefer GHGRP
ownership over the CAMD owner string. It also means the 3.31 MMT sitting in the unattributed list is
correctly unattributed.

**AT&T owns half a biomass plant.** EPA names AT&T Inc as 50% parent of Wadham Energy LP, a
California rice-hull plant, 2014-2023. The identity is EPA's own and the match is correct. The
economics are a passive partnership interest, closer in kind to the fund holdings the lane already
excludes. Under 100,000 t, so it changes nothing, but a judge who clicks on AT&T deserves the note.

**MPLX is a policy call, not a fact.** Marathon Petroleum consolidates MPLX, which is separately
listed with public unitholders. Attributing MPLX's 4.67 MMT to MPC is right if the denominator is
consolidated too. Worth one line in the methodology so nobody thinks it was an accident.

**The crosswalk holds.** Of 1,579 ORIS codes that reach a GHGRP facility, 6 land on a facility more
than 25 km away or in another state, holding 2.88 MMT of 2025 CO2, and in every case the two
facilities share a name so the divergence is an EPA coordinate error. 120 land on a facility that is
not classified as a power plant; those are industrial cogeneration units correctly resolving to the
refinery or chemical plant they sit inside (South Houston Green Power to Marathon's Galveston Bay
refinery, Whiting Clean Energy to BP Whiting), which is what makes the ownership snapshot right.

**Fuzzy matching survived the audit.** The lane's claim that fuzzy buys nothing reproduces. It
accepts one GHGRP string and two CAMD strings, worth 0.0 MMT of current-year emissions, and the one
we sampled (`Ameren Energy Resources` to AEE, E D Edwards and Duck Creek, 2011-2013) is correct for
the years it covers: CAMD's own string records the December 2013 transfer to Illinois Power.

## Where the audit itself is weak

- 50 rows out of 504 is a 10% sample. At 49/50 the interval on precision runs from 89.5% to 99.6%.
  We can say the error rate is probably under 10%; we cannot say it is under 2%.
- Verification is facility-level and documentary, not audited against each company's 10-K segment
  disclosure. A match can be right about who owns the stack and still be wrong about whether that
  entity is consolidated.
- The three errors we fixed were found by targeted search on top of the sample, not by the sample.
  Two of the three would have been missed by the random draw. Read that as evidence that the true
  error rate on the tail is at the higher end of the interval.
- Recall by tonnes is checked to 62% of unmatched GHGRP tonnes and 44% of unattributed CAMD tonnes.
  The long tail of 6,100 small strings is unchecked. Each one is under 2 MMT, but there are a lot
  of them.
- We did not re-derive `ghgrp_facilities.parquet` or `violations_aliases.json`. If the Violation
  Tracker alias file carries a wrong subsidiary-to-parent assignment, this audit inherits it. The
  Integrys case, where Violation Tracker pointed at EXC and the right answer was WEC, shows that
  file is not infallible; the lane caught that one by hand.

## Appendix A: the 50 sampled matches

Drawn with `random_state=20260912`, 25 from the top 100 rows by tonnes and 25 from the rest.
Rank is by RY2023 (GHGRP) or 2025 (CAMD) tonnes across all 504 matched rows in the pre-fix table.

| # | Src | EPA parent string | → | Route | RY2023 / 2025 t | Verdict | Evidence checked |
|---:|---|---|---|---|---:|---|---|
| 2 | GHGRP | SOUTHERN CO | SO | exact/index | 76.72 | correct | 46 facilities, Miller, Bowen, Gaston, Barry, Scherer at the stated 29%. Southern's own fleet. |
| 7 | GHGRP | NEXTERA ENERGY INC | NEE | exact/index | 42.87 | correct | West County, Martin, Manatee, Fort Myers, all Florida Power & Light plants. |
| 13 | GHGRP | DOMINION ENERGY INC | D | exact/index | 29.53 | correct | Mount Storm, Chesterfield, Greensville, Brunswick. Dominion's Virginia fleet. |
| 20 | CAMD | Georgia Power Company | SO | exact/violations_subsidiary | 23.69 | correct | Georgia Power is Southern's Georgia utility. Scherer, Bowen, McDonough. |
| 24 | GHGRP | NRG ENERGY INC | NRG | exact/index | 22.46 | correct | W A Parish, Limestone, Powerton, Joliet. NRG's own fleet. |
| 29 | GHGRP | CF INDUSTRIES HOLDINGS INC | CF | exact/index | 20.58 | correct | Donaldsonville, Verdigris, Port Neal, Yazoo City. CF's nitrogen plants. |
| 33 | CAMD | Duke Energy Florida, LLC | DUK | exact/violations_subsidiary | 18.21 | correct | Crystal River, Hines, Bartow, Anclote. Duke's Florida utility. |
| 37 | CAMD | Detroit Edison Company | DTE | exact/violations_subsidiary | 16.84 | correct | Monroe, Belle River, St. Clair. DTE Electric's former name. |
| 45 | GHGRP | ALLIANT ENERGY CORP | LNT | exact/index | 13.02 | correct | Edgewater, Columbia 53.5%, Ottumwa 48%, Lansing. Alliant's Wisconsin and Iowa fleet. |
| 46 | GHGRP | WASTE MANAGEMENT INC | WM | exact/index | 12.93 | correct | 247 RY2023 facilities, all landfills. The Wheelabrator rows EPA still files under WM carry a null tonnage, so the sold incinerator fleet adds nothing. |
| 47 | CAMD | Kentucky Utilities Company | PPL | exact/violations_subsidiary | 12.29 | correct | Ghent, Trimble County, Cane Run. LG&E and KU are PPL's Kentucky utilities. |
| 51 | GHGRP | OCCIDENTAL PETROLEUM CORP | OXY | exact/index | 11.26 | correct | Oxy Permian, OxyChem Taft and Ingleside, OxyVinyls La Porte. |
| 57 | CAMD | La Frontera Holdings, LLC | VST | manual | 9.59 | correct | Forney, Lamar, Odessa-Ector. EPA independently names Vistra Corp 100% owner of the same three facilities. |
| 69 | CAMD | Indianapolis Power & Light Company | AES | exact/violations_subsidiary | 7.66 | correct | Petersburg, Harding Street, Eagle Valley. AES Indiana's former name. |
| 72 | CAMD | Mississippi Power Company | SO | exact/violations_subsidiary | 6.52 | correct | Daniel, Watson, Greene County, Ratcliffe. Southern's Mississippi utility. |
| 75 | CAMD | NV Energy | BRK.B | manual | 5.66 | correct | Lenzie, Harry Allen, Higgins, Silverhawk. EPA names Berkshire Hathaway Inc as parent of the same ORIS plants. The override key was unsafe and has been fixed. |
| 76 | CAMD | Indiana Michigan Power Company | AEP | exact/violations_subsidiary | 5.61 | correct | Rockport and Tanners Creek. AEP's Indiana Michigan utility. |
| 77 | GHGRP | NUCOR CORP | NUE | exact/index | 5.50 | correct | 26 Nucor Steel mills. |
| 84 | GHGRP | MPLX LP | MPC | manual | 4.67 | correct by policy | 41 MarkWest and Ohio Gathering plants. MPLX is separately listed but Marathon Petroleum consolidates it, so it belongs in a consolidated Scope 1. Flagged as a policy call, not an identity error. |
| 85 | GHGRP | CRH AMERICAS INC | CRH | exact/index | 4.65 | correct | Ash Grove Cement and Suwannee American. CRH bought Ash Grove in 2018 and the index list carries CRH from 2025-12-22. |
| 87 | CAMD | Duke Energy Progress, Inc. | DUK | exact/violations_subsidiary | 4.23 | correct | Roxboro, Richmond County, Mayo, H F Lee. Duke's Carolinas utility. |
| 88 | CAMD | Midwest Generation EME, LLC | NRG | exact/violations_subsidiary | 4.23 | correct | Powerton, Joliet, Waukegan, Will County. NRG bought Edison Mission Energy in 2014 and CAMD still names Midwest Generation EME as owner in 2025. |
| 89 | GHGRP | CENTERPOINT ENERGY INC | CNP | exact/index | 4.19 | correct | A B Brown and F B Culley, CenterPoint's Indiana plants after the Vectren deal. |
| 92 | GHGRP | ONEOK INC | OKE | exact/index | 3.89 | correct | 48 ONEOK gas processing and fractionation plants. |
| 94 | GHGRP | PIONEER NATURAL RESOURCES USA INC | XOM | manual | 3.76 | correct | Permian gathering and processing. ExxonMobil closed the Pioneer acquisition in May 2024. |
| 106 | GHGRP | STEEL DYNAMICS INC | STLD | exact/index | 2.57 | correct | 12 Steel Dynamics mills including Columbus and Mesabi Nugget at the stated 83%. |
| 120 | GHGRP | INTEGRYS ENERGY GROUP INC | WEC | manual | 1.67 | correct | Weston, Pulliam, Columbia 31.8%, Fox Energy, Peoples Gas. All Wisconsin and Illinois assets WEC bought with Integrys in 2015, not the retail arm Exelon bought. |
| 140 | GHGRP | 3M CO | MMM | exact/index | 1.01 | correct | Cordova, Cottage Grove, Decatur. 3M's own plants. |
| 151 | GHGRP | GENERAL MOTORS LLC | GM | exact/index | 0.60 | correct | Defiance, Wentzville, Fort Wayne, Lordstown. GM assembly and casting. |
| 157 | GHGRP | Bunge Holdings North America, Inc. | BG | exact/violations_subsidiary | 0.47 | correct | 11 Bunge North America oilseed plants. |
| 195 | GHGRP | BRISTOL-MYERS SQUIBB CO | BMY | exact/index | 0.10 | correct | Three New Jersey and Connecticut sites including E R Squibb & Sons. |
| 236 | GHGRP | Denbury Resources, Inc. (2010) | XOM | exact/violations_subsidiary | 0 | correct | Elk Basin Gas Plant at 47%. ExxonMobil bought Denbury in November 2023. |
| 240 | GHGRP | ENERGY HARBOR CORP | VST | manual | 0 | **WRONG** | W H Sammis and Pleasants Power Station only. Vistra bought Energy Harbor's nuclear and retail business in March 2024 and the deal explicitly excluded both coal plants, which had already been sold on. Blocked. |
| 246 | GHGRP | DOVER CORP | DOV | exact/index | 0 | correct, caveat | Correct company, but the five rows carry a null sector and a null tonnage. Dover is a GHGRP reporter with no direct emissions, so it should not count as measured coverage. |
| 267 | GHGRP | AT&T INC | T | exact/index | 0 | correct, caveat | EPA names AT&T Inc as 50% parent of Wadham Energy LP, a California rice-hull biomass plant. The identity is EPA's own; the economics are a passive partnership interest, not AT&T operations. |
| 325 | GHGRP | International Business Machines Corporation | IBM | exact/sec | 0 | correct | GlobalFoundries East Fishkill 2011-2014, which IBM owned until the 2015 sale. EPA renamed the facility retroactively. |
| 329 | GHGRP | Chevron USA Inc (CUSA) | CVX | exact/index | 0 | correct | Pasadena Refining System, bought from Petrobras in 2019. |
| 350 | CAMD | Merck & Company, Inc. | MRK | exact/index | 0 | correct | Merck West Point, Pennsylvania. Zero CAMD tonnage. |
| 351 | CAMD | WestRock Virginia Corporation | SW | exact/violations_subsidiary | 0 | correct | WestRock Covington, Virginia. Smurfit Westrock owns the legacy WestRock mills. |
| 352 | CAMD | WestRock Coated Board, LLC | SW | exact/violations_subsidiary | 0 | correct | WestRock Mahrt Mill, Alabama. |
| 374 | GHGRP | HAWKER BEECHCRAFT CORP | TXT | exact/violations_subsidiary | 0 | correct | The two facilities are literally named Textron Aviation/Beechcraft Division and Textron Aviation/East Campus. Textron bought Beechcraft in 2014. |
| 396 | GHGRP | Florida Power & Light Co (FPL) | NEE | exact/violations_subsidiary | 0 | correct | St. Johns River Power at the stated 20%, which is FPL's documented share alongside JEA. |
| 432 | GHGRP | SCANA CORP | D | manual | 0 | correct | Wateree, Williams, Cope, Canadys. Dominion bought SCANA in January 2019. |
| 433 | GHGRP | ROSETTA RESOURCES OPERATING LP | CVX | exact/violations_subsidiary | 0 | correct | Gulf Coast and Permian gathering. Rosetta went to Noble in 2015 and Noble to Chevron in 2020. |
| 443 | GHGRP | SRC ENERGY INC | CVX | exact/violations_subsidiary | 0 | correct | SRC Energy went to PDC Energy in 2020 and PDC to Chevron in August 2023. |
| 444 | GHGRP | SOUTHWESTERN ELECTRIC POWER CO (SWEPCO) | AEP | exact/violations_subsidiary | 0 | correct | Dolet Hills at the stated 50%. SWEPCO is AEP's Arkansas, Louisiana and Texas utility. |
| 461 | GHGRP | The Procter & Gamble Paper Products Company | PG | exact/violations_subsidiary | 0 | correct | P&G Paper Products, Wisconsin. |
| 475 | GHGRP | TRANE TECHNOLOGIES CORP | TT | exact/index | 0 | correct, caveat | Correct company, null sector and null tonnage. Same refrigerant-reporter case as Dover. |
| 476 | GHGRP | NOBLE ENERGY INC | CVX | exact/violations_subsidiary | 0 | correct | Denver-Julesburg and Permian gathering plus deepwater Gulf platforms. Chevron bought Noble in October 2020. |
| 504 | GHGRP | LYONDELLBASELL ACETYLS, LLC | LYB | exact/violations_subsidiary | 0 | correct | La Porte syngas and methanol, LyondellBasell's own plants. |

## Appendix B: the 30 sampled tickers with no match

Drawn with `random_state=7`, weighted toward the heavy-emitting sectors.

| Ticker | Company | Sector | Verdict | Evidence checked |
|---|---|---|---|---|
| ABNB | Airbnb | Consumer Discretionary | no US facility | No AIRBNB string anywhere in either programme. |
| AME | Ametek | Industrials | no US facility | No AMETEK string anywhere. |
| CASY | Casey's | Consumer Staples | no US facility | CASEY CO in GHGRP is Kern Energy, a Bakersfield refinery owned by the Casey family, not Casey's General Stores. Now carries that note in the unmatched CSV. |
| CHD | Church & Dwight | Consumer Staples | no US facility | Only the Church of Jesus Christ and two compressor stations named Church share a token. |
| CHRW | C.H. Robinson | Industrials | no US facility | Freight broker, owns no plant. Only Elementis Worldwide and ERCO Worldwide share a token. |
| CI | Cigna | Health Care | no US facility | No CIGNA string anywhere. |
| CLX | Clorox | Consumer Staples | no US facility | No CLOROX string anywhere. |
| COST | Costco | Consumer Staples | no US facility | No COSTCO string anywhere. Warehouses sit below the 25,000 t threshold. |
| CPRT | Copart | Industrials | no US facility | No COPART string anywhere. |
| CRWD | CrowdStrike | Information Technology | no US facility | No CROWDSTRIKE string anywhere. |
| CTAS | Cintas | Industrials | no US facility | No CINTAS string anywhere. |
| FAST | Fastenal | Industrials | no US facility | No FASTENAL string anywhere. |
| GPC | Genuine Parts Company | Consumer Discretionary | no US facility | Automotive parts distribution. Only Precision Cast Parts and retail parts stores share a token. |
| LDOS | Leidos | Industrials | no US facility | No LEIDOS string anywhere. |
| LHX | L3Harris | Industrials | no US facility | No L3HARRIS string anywhere. |
| LYV | Live Nation Entertainment | Communication Services | no US facility | Concert promoter and venue operator. The only GHGRP strings containing its tokens are Binderholz Live Oak, Caesars and the Navajo Nation. |
| MAS | Masco | Industrials | no US facility | No MASCO string anywhere. |
| PCAR | Paccar | Industrials | no US facility | No PACCAR string in any parent or facility name. Truck and engine plants fall below threshold. |
| PH | Parker Hannifin | Industrials | no US facility | No PARKER or HANNIFIN string anywhere. |
| PM | Philip Morris International | Consumer Staples | no US facility | US tobacco manufacturing is Altria's. Only City of Morris and a Sharples trust share a token. |
| PWR | Quanta Services | Industrials | no US facility | No QUANTA string anywhere. |
| SPG | Simon Property Group | Real Estate | no US facility | Mall REIT. Only unrelated strings containing PROPERTY share a token. |
| TDY | Teledyne Technologies | Information Technology | no US facility | No TELEDYNE string anywhere. |
| TKO | TKO Group Holdings | Communication Services | no US facility | No distinctive token appears in any GHGRP parent, GHGRP facility name or CAMD owner. |
| TRV | Travelers Companies (The) | Financials | no US facility | No TRAVELERS string anywhere. |
| APO | Apollo Global Management | Financials | policy exclusion | EPA names Apollo as a facility parent (US Silica). Excluded by the fund-owner rule, tonnes reported unattributed. Not a matching failure. |
| MS | Morgan Stanley | Financials | policy exclusion | EPA names Morgan Stanley as parent of Durango Midstream, held in Morgan Stanley Infrastructure Partners. Same rule. |
| FDXF | FedEx Freight | Industrials | structural | FedEx Freight was spun out of FedEx on 2026-06-01. GHGRP stops at RY2023, so no history can exist under this entity. Its emissions sit on FDX. |
| HONA | Honeywell Aerospace | Industrials | structural | Honeywell Aerospace was spun out on 2026-06-29. HONEYWELL INTERNATIONAL INC is matched, to HON. |
| Q | Qnity Electronics | Information Technology | structural | Qnity Electronics was spun out of DuPont on 2025-11-03. No RY2023 history can exist under this entity. |
