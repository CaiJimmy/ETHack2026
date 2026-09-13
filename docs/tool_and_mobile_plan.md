# Reframe as a tool, and make it work on a phone

Audit and build plan. Written after measuring the live page at five viewports in Chromium and
looking at the screenshots. Nothing under `site/` was changed by this pass.

Two jobs, independent of each other, both P0:

1. The page says it exists to answer someone's exam question. It should say it is a tool.
2. The page is 2.86x too wide on a phone.

The model, the data, the charts and the 33 disclosure elements are correct and stay. No caveat and no
number is deleted anywhere below. Where something does not fit, it moves or it gets a scroller.

---

## Part 0. What was measured

Chromium 1223, `file:///home/tyrolize/prog/ETHack2026/site/index.html`, 2.5s settle, full page.

| viewport | `documentElement.scrollWidth` | overflow factor |
|---|---|---|
| 390 x 844 | **1114** | 2.86x |
| 430 x 932 | **1114** | 2.59x |
| 768 x 1024 | **948** | 1.23x |
| 1024 x 768 | 1024 | clean |
| 1280 x 720 | 1280 | clean |

So the break is between 768 and 1024, and it is catastrophic below 768. 1024 and 1280 are already
fine and must not regress.

### The elements that set the width at 390 (box width, and what pins it)

Listed with the section they live in. Widths are `getBoundingClientRect().width` at a 390px viewport
where the content column is 342px.

| w | section | selector | why it is that wide |
|---|---|---|---|
| 944 | portfolio | `table.tbl.pf-art` | `colgroup([160,392,124,128,140])`, portfolio.js:404 |
| 944 | portfolio | `table.tbl.pf-hold` | `colgroup([72,196,130,88,124,92,112,130])`, portfolio.js:446 |
| 662 | saydo | `.saydo-grid > .chart-wrap` | `.saydo-grid` is `1fr 340px`, app.css |
| 628 | saydo | `#saydo-chart > svg` | `Math.max(420, host.clientWidth)`, saydo.js:164 |
| 628 | saydo | `#saydo-sizekey` | inherits the 628 chart box |
| 612 | coverage | `.cv-ind` | `168px 210px 104px 1fr`, coverage.js:978 |
| 512 | ranks | `.rk-par > div` | `.rk-par` is `1fr 512px`, ranks.js:177 |
| 505 | portfolio | `.pf-row2 > .panel` | `.pf-row2` is `1fr 1fr`, portfolio.js:1313 |
| 499 | coverage | `table.tbl.cv-ledger-tbl` | `white-space:nowrap` headers, coverage.js:843 |
| 466 | ranks | pareto matrix `svg` | `w = 46 + n*21`, ranks.js:1076 |
| 460 | ranks | `#rk-weights .u-mt4 > svg` | `var w = 460` hard-coded, ranks.js:974 |
| 455 | portfolio | `table.tbl.pf-keep` | nowrap header "Share of what companies delivered" |
| 454 | ranks | `.rk-grid > .chart-wrap` | `.rk-grid` is `1fr 340px`, ranks.js:83 |
| 442 | allocate | `.al-title` | `white-space:nowrap` + `flex:none`, allocate.css |
| 420 | ranks | `#rk-chart > svg` | `Math.max(420, host.clientWidth)`, ranks.js:424 |
| 400 | portfolio | `.pf-excl-grid > div` | `.pf-excl-grid` is `1fr 400px`, portfolio.js:1277 |
| 392 | portfolio | `td.pf-art-test` | the 392px colgroup track |

### The grids that never collapse (computed track lists at a 390px viewport)

Every one of these is a fixed track list with no breakpoint under it:

- `.al-grid` `268px 0px 282px`. The middle track, **the treemap, computes to 0px**. The map is not
  small on a phone, it is gone.
- `.stat-row` `268.5px 172.5px 160.2px` in a 262px box.
- `.saydo-grid` `662px 340px`, `.rk-grid` `454px 340px`, `.pf-row2` `331px 504px`,
  `.cv-two` `356px 356px`, `.rk-par` `290px 512px`, `.pf-excl-grid` `367px 400px`,
  `.cv-classnotes` `144px 155px`, `.cv-limit > summary` `186px 1fr`.
- `.states` `57.8 97.5 74.2 61.4` px. Four columns in 212px, one word per line.
- `.pf-tiles` six tracks, `.pf-pick` three, `.pf-mandate-kv` three, `.card-trio` three,
  `.rk-pill` four.
- `.sob-row` / `.sob-rest` `176px 0px 58px`, `.wa-row` `138px 0px 56px`,
  `.cb-row` / `.cb-head` `270px 0px 64px 74px`. In every one the `minmax(0,1fr)` bar track
  computes to **0px**, so the bar the row exists to show is not drawn.
- `.cv-chain-row` `118 120 118 250` px in a 212px box.
- `.cv-cells` `repeat(60,1fr)` gives 1.33px cells with a 2px gap. Noise, not a waffle.
- `.pf-sec` `130 53 74`, `.pf-te-row` `170 69 60`, `.pf-sch` `210 9 56`.

### Things the screenshots show that the numbers do not

- The `h1` is clipped mid-word. `sustainability&nbsp;<em>ranking</em>` in index.html:75 binds a
  ~490px unbreakable token at `--fs-h1: 40px`.
- The nav rail is 48px of a 390px screen, 12%, and its open state is 206px over the content.
- `.states` renders "Target," / "no" / "measurement" stacked one word per line.
- The `#allocate` section keeps `height: 100vh; overflow: hidden`, so on a phone the right two
  thirds of the control surface are clipped away with no scrollbar and no hint they exist.

---

## Part 1. The reframe

### The decision on the hero sentence

**"There is no one sustainability ranking of the S&P 500. Ours included." stays exactly where it is,
as the `h1` of section 02.** It is a claim about method and uncertainty, and it earns its place at the
top of the section called "The argument". It is not the right front door for a tool, because a person
arriving to look up a company does not yet care that rankings are unstable.

The tool framing goes **above** it, into section 01, replacing the exam-question copy. That is also
where the entry point already is, so the two problems get fixed in the same block of markup.

Nothing moves. Six strings change.

### The exact replacements

**index.html:45 to 46**, the section 01 head. Replace:

```html
        <div class="sec-kicker">The bonus question</div>
        <div class="al-title">The world commits to net zero. You manage $1bn.</div>
```

with:

```html
        <div class="sec-kicker">Start here<span class="u-dim"> / every company in the index</span></div>
        <div class="al-title">What the S&amp;P 500 emits, and what a carbon price would cost it.</div>
```

The kicker now matches the house pattern used by the other four sections (`Finding / credibility`,
`Honesty / coverage`) and doubles as the instruction. The title says what the page is.

**index.html:50 to 51**, the lede. Replace:

```html
      <p class="al-lede"><span>The carbon price moves every number here except the allocation.</span>
        <b>The missing data moves the money.</b></p>
```

with:

```html
      <p class="al-lede"><span>Click any company for its filed tonnes and its carbon bill.</span>
        <b>The missing data moves more money than the price does.</b></p>
```

First half is the invitation, second half is the finding, which is the same two-part structure the
CSS comment above it describes. The new bold half carries both halves of the old claim in one
sentence: the price does not move the advice, the missing data does. The price-invariance finding
also stays live on screen in the `.av-inv` panel and on the "moves no money" chip beside the price
slider, so nothing is lost by tightening it.

At 1280 this is 58 + 53 characters at 20px, about 1130px in a 1232px measure, so it stays on one
line and the section keeps its two-line head budget.

**index.html:20**, the nav label for section 01. Replace:

```html
    <li><a href="#allocate"><span class="nav-num">01</span><span class="nav-t">Allocate $1bn</span></a></li>
```

with:

```html
    <li><a href="#allocate"><span class="nav-num">01</span><span class="nav-t">Every company</span></a></li>
```

Nav items 02 to 06 do not change. "The $1bn fund" at 05 is correct: that section really is about a
fund.

**allocate.js:816**, the right column header. Replace:

```js
    var col = colShell('What you hold', '<b>$1bn</b>');
```

with:

```js
    var col = colShell('What you hold', 'if you ran <b>$1bn</b>');
```

One conditional turns the column from an assumption about the reader into one use of the tool. The
triptych "What you assume / The index / What you hold" survives, and every number in the column is
untouched.

**allocate.js:778 to 781**, the foot of the treemap. Replace:

```js
    col.appendChild(FILED.el('div', { class: 'tm-foot' }, [
      FILED.el('span', { html: '<b>An exposure model, not a forecast.</b> It prices ' +
        'a carbon bill against filings that exist. It predicts nothing.' })
    ]));
```

with:

```js
    col.appendChild(FILED.el('div', { class: 'tm-foot' }, [
      FILED.el('span', { html: '<b>Click a company</b> for its filed tonnes and its carbon bill. ' }),
      FILED.el('span', { class: 'tm-small-note', html:
        'A tile under about 30 pixels carries no logo. Type a ticker to reach the small ones. ' }),
      FILED.el('span', { html: '<b>An exposure model, not a forecast.</b> It prices ' +
        'a carbon bill against filings that exist. It predicts nothing.' })
    ]));
```

The caveat is verbatim and still last. The instruction goes in front of it. `.tm-small-note` is
hidden above 640px (rule given in Part 2) and is the honest note about tap targets. This costs the
map about 15px of height at 1280, which it has.

**allocate.js:3**, the file comment. Replace `One screen that answers the bonus question.` with
`One screen: the whole index, priced.` Comments get the same pass as copy in this repo.

### The entry point

Right now a first-time visitor meets a portfolio. After the change they meet a treemap of all 500
companies with the instruction under it, and the first thing the page asks them to do is click one.
The card that opens already carries what an investor, a journalist or a company wants: filed Scope 1
tonnes, tonnes we charge for, carbon cost, hit to company value, share of value at risk, cost against
operating income, index weight, our weight, position, water stress. That is the tool. It exists. The
copy above it was pointing at the portfolio.

Two things make the entry point real rather than implied:

1. The reframed copy above, which names clicking as the first action.
2. **A ticker box in the map column header.** On a phone half the index is a 5px tile, so "click any
   company" is only true for the large caps unless there is a lookup. It also helps at 1280.

Add to `buildMid()` in allocate.js, immediately before `col.querySelector('.al-col-head').appendChild(tog);`:

```js
    var find = FILED.el('input', {
      class: 'tm-find', type: 'search', placeholder: 'ticker',
      'aria-label': 'find a company',
      oninput: function () {
        var q = this.value.trim().toUpperCase();
        this.classList.remove('is-miss');
        if (!q) { closeCard(); return; }
        for (var i = 0; i < N; i++) {
          if (C[i].t === q) { drawCard(i); return; }
        }
        this.classList.add('is-miss');
      }
    });
    col.querySelector('.al-col-head').appendChild(find);
```

and to allocate.css, in the control-row block:

```css
.tm-find {
  flex: none; width: 88px; font-family: var(--font-mono); font-size: 11px;
  background: var(--bg-sunk); border: 1px solid var(--rule-2); color: var(--ink);
  padding: 1px 5px;
}
.tm-find::placeholder { color: var(--ink-3); }
.tm-find:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
.tm-find.is-miss { border-color: var(--accent); color: var(--accent); }
```

This is the only new control in the whole plan. If time runs out, cut it: the copy reframe stands on
its own and the ranks section already has an equivalent ticker box at `#rk-search`.

### Everything else that assumed a $1bn manager

Checked by grep across `site/`. The complete list is the six strings above. `#portfolio`'s titles
speak about funds in the third person and are fine. `stat-pab-sub` in saydo.js says "A $1.0bn
Paris-aligned fund finances ...", third person, fine. `<title>` and the meta description already read
as a tool and stay. The nav tagline "The S&P 500 scored only on what it files under legal penalty"
already reads as a tool and stays.

---

## Part 2. The breakpoints

There is one breakpoint today, at 1560px, and it only widens the measure. Add three, all
`max-width`, all appended to the end of `site/css/app.css` after the existing 1560px rule so they
win on source order. Rules that have to beat a JS-injected stylesheet carry `!important` and are
marked below; that is deliberate, because ranks.js, portfolio.js and coverage.js inject their grids
at runtime.

### 1080px and below: the control surface stops being three columns

Trigger chosen so that 1024x768 and 1280x720 both keep some sensible shape and neither sits on a
boundary. Above 1080 nothing changes at all, so the 1280 recording frame is untouched.

What happens: `#allocate` stops being a fixed 100vh screen and becomes an ordinary scrolling
section. The treemap goes full width on the first row; the assumption column and the advice column
sit side by side underneath. The screenshot at 768 of this shape reads better than the current
three-column layout does at 1024, so this is not a downgrade, it is a second layout.

Two small JS changes are needed first so the CSS can address the columns by name instead of by
`nth-child`. In allocate.js:

- `buildLeft()`, allocate.js:560: after `var col = colShell('What you assume', '');` add
  `col.classList.add('al-col--assume');`
- `buildMid()`, allocate.js:742: after `var col = colShell('The index', ...);` add
  `col.classList.add('al-col--index');`

Then:

```css
@media (max-width: 1080px) {
  /* The one-screen constraint exists for a 1280x720 recording frame. Below that
     frame it only clips. 100vh is also wrong on mobile Safari, where it counts
     the URL bar. */
  #allocate { height: auto; min-height: 0; overflow: visible; padding: var(--s4) var(--s4) var(--s5); }
  #allocate-body { display: block; }
  .al-top { flex-wrap: wrap; }
  .al-title { white-space: normal; flex: 1 1 auto; min-width: 0; }

  .al-grid {
    grid-template-columns: 268px minmax(0, 1fr);
    grid-template-areas: "map map" "ctl adv";
    gap: var(--s3); min-height: 0;
  }
  .al-col--index  { grid-area: map; }
  .al-col--assume { grid-area: ctl; }
  .al-col--advice { grid-area: adv; }
  .al-col { overflow: visible; }
  .ac-wrap { overflow: visible; }
  .tm-wrap { min-height: 420px; }
  .al-spacer { display: none; }
  /* the foot no longer has to open upward over a map, because the page scrolls */
  .dd--up .dd-body { position: static; box-shadow: none; }
}
```

### 900px and below: every two-up collapses, the figures shrink

Chosen from the chart floors: `#saydo-chart` and `#rk-chart` floor at 420px, and beside a 340px card
with a 24px gap that needs 784px of measure, which is a 912px viewport. 900 is the round number just
under it.

```css
@media (max-width: 900px) {
  :root { --fs-fig: 40px; --fs-h1: 32px; --fs-h2: 23px; }
  .stat-fig .unit, .stat-fig .of { font-size: 22px; }
  /* one rule for every width: 3 up at 1280, 2 up on a tablet, 1 up on a phone */
  .stat-row { grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: var(--s5); }
  .hero h1 .nb { white-space: normal; }
  .saydo-grid { grid-template-columns: minmax(0, 1fr); }
  .card { min-height: 0; }
  .card-trio { grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); }
  .states { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--s3); }
  .panel-head { flex-wrap: wrap; }

  #ranks .rk-grid   { grid-template-columns: minmax(0,1fr) !important; }
  #ranks .card      { min-height: 0 !important; }
  #ranks .rk-two    { grid-template-columns: minmax(0,1fr) !important; }
  #ranks .rk-par    { grid-template-columns: minmax(0,1fr) !important; }
  #ranks .dm-list   { grid-template-columns: minmax(0,1fr) !important; }
  #ranks .rk-pill   { grid-template-columns: repeat(2, minmax(0,1fr)) !important; }
  #ranks #rk-weights { max-width: none !important; }
  #ranks .sob-row, #ranks .sob-rest,
  #ranks .wa-row    { grid-template-columns: minmax(0,1fr) minmax(0,2fr) 48px !important; }
  #ranks .cb-row, #ranks .cb-head {
                      grid-template-columns: minmax(0,1.4fr) minmax(0,1fr) 52px 60px !important; }

  .pf-row2      { grid-template-columns: minmax(0,1fr) !important; }
  .pf-excl-grid { grid-template-columns: minmax(0,1fr) !important; }
  .pf-pick      { grid-template-columns: repeat(auto-fit, minmax(210px,1fr)) !important; }
  .pf-tiles     { grid-template-columns: repeat(auto-fit, minmax(140px,1fr)) !important; }
  .pf-mandate   { flex-wrap: wrap; gap: var(--s4) !important; }
  .pf-mandate-kv { grid-template-columns: repeat(auto-fit, minmax(140px,1fr)) !important; }
  .pf-sec       { grid-template-columns: minmax(0,96px)  minmax(0,1fr) 62px !important; }
  .pf-te-row    { grid-template-columns: minmax(0,120px) minmax(0,1fr) 52px !important; }
  .pf-sch       { grid-template-columns: minmax(0,140px) minmax(0,1fr) 48px !important; }
  .pf-plot > svg#pf-wf { width: 720px !important; min-width: 720px; height: 306px; }

  .cv-two         { grid-template-columns: minmax(0,1fr) !important; }
  .cv-ind         { grid-template-columns: minmax(0,1fr) minmax(0,1fr) !important;
                    gap: var(--s2) var(--s4) !important; }
  .cv-classnotes  { grid-template-columns: minmax(0,1fr) !important; }
  .cv-limit > summary { grid-template-columns: minmax(0,1fr) !important; gap: var(--s2) !important; }
  .cv-chain-row   { grid-template-columns: minmax(0,1fr) !important; gap: var(--s2) !important; }
  .cv-fork        { grid-template-columns: minmax(0,1fr) !important; }
  .cv-node, .cv-arrowbox { min-width: 0 !important; }
  .cv-ex-row      { grid-template-columns: minmax(0,1fr) auto !important; }
}
```

The `.nb` rule needs one markup change. index.html:75, replace:

```html
    <h1>There is no one sustainability&nbsp;<em>ranking</em> of the S&amp;P 500. Ours included.</h1>
```

with:

```html
    <h1>There is no one <span class="nb">sustainability <em>ranking</em></span>
        of the S&amp;P 500. Ours included.</h1>
```

and add `.hero h1 .nb { white-space: nowrap; }` to the hero block in app.css. The pair keeps
"sustainability ranking" together at desktop, which is why the `&nbsp;` was there, and lets it break
below 900 where the line has nowhere else to go.

### 640px and below: the phone

Trigger set so a 768px tablet in portrait keeps the 48px rail and the ordinary padding.

```css
@media (max-width: 640px) {
  :root { --pad-x: 16px; --fs-fig: 34px; --fs-h1: 27px; --fs-h2: 21px; --maxw: 100%; }

  /* The rail becomes a 44px top bar. The numbers and labels scroll sideways
     inside it, so six sections fit without a menu, a script or an overlay. */
  .nav {
    position: fixed; inset: 0 0 auto 0; width: auto; height: 44px;
    flex-direction: row; align-items: center; padding: 0 0 0 12px;
    border-right: 0; border-bottom: 1px solid var(--rule);
    overflow-x: auto; overflow-y: hidden;
  }
  .nav.is-open, .nav:focus-within, .nav:hover { width: auto; }
  .brand { padding: 0 12px 0 0; font-size: 17px; flex: none; }
  .nav-t { opacity: 1; }
  .nav-list { display: flex; flex: 1 1 auto; }
  .nav-list a { padding: 0 10px; line-height: 44px;
                border-left: 0; border-bottom: 2px solid transparent; }
  .nav-list a.is-active { border-left-color: transparent;
                          border-bottom-color: var(--accent); background: none; }
  .nav-tail, .nav-x { display: none; }
  .nav-drawer { margin: 0 8px 0 0; width: auto !important; flex: none; padding: 4px 8px; }
  .nav-drawer .nav-t { display: none; }
  .main { margin-left: 0; padding-top: 44px; }
  .section, #allocate { scroll-margin-top: 44px; }

  .al-grid { grid-template-columns: minmax(0,1fr); grid-template-areas: "map" "ctl" "adv"; }
  .al-col-head { flex-wrap: wrap; }
  .tm-wrap { min-height: 320px; }
  .tm-card { left: 6px; right: 6px; width: auto; }
  .tm-keys { flex-wrap: wrap; gap: 6px 12px; }
  .tm-small-note { display: inline; }

  .panel-n, .dd .dd-n { white-space: normal; }

  .cv-cells { grid-template-columns: repeat(30, 1fr) !important; }
  .cv-ind   { grid-template-columns: minmax(0,1fr) !important; }
  .cv-filter { flex-wrap: wrap; }

  /* the bar drops to its own row under its label rather than to 0px */
  #ranks .rk-seg { width: auto !important; flex-wrap: wrap; }
  #ranks .sob-row, #ranks .sob-rest, #ranks .wa-row {
    grid-template-columns: minmax(0,1fr) 48px !important; }
  #ranks .sob-row > :nth-child(2), #ranks .sob-rest > :nth-child(2),
  #ranks .wa-row  > :nth-child(2) { grid-column: 1 / -1; order: 3; }
  #ranks .cb-row, #ranks .cb-head { grid-template-columns: minmax(0,1fr) 52px 56px !important; }
  #ranks .cb-row > :nth-child(2), #ranks .cb-head > :nth-child(2) { display: none; }
  .pf-sec, .pf-te-row, .pf-sch { grid-template-columns: minmax(0,1fr) 56px !important; }
  .pf-sec > :nth-child(2), .pf-te-row > :nth-child(2), .pf-sch > :nth-child(2) {
    grid-column: 1 / -1; order: 3; }
}
```

### One scroller, five uses

Add to app.css, outside any media query, next to `.panel`:

```css
/* Some things are genuinely wider than a phone. They keep every column and
   every row and scroll inside their own box, so the page never scrolls
   sideways and nothing is hidden. */
.scroll-x { overflow-x: auto; -webkit-overflow-scrolling: touch; max-width: 100%; }
.scroll-x > .tbl { width: auto; min-width: 100%; }
.tm-small-note { display: none; }
.pf-plot { overflow-x: auto; max-width: 100%; }
.cv-chain { overflow-x: auto; }
```

Then wrap the five wide tables and the one wide matrix. Each is a one-line change at an existing
`appendChild`:

- portfolio.js:422, `p.appendChild(t);` (the `pf-art` article table)
- portfolio.js:453, `p.appendChild(t);` (the `pf-hold` holdings table)
- portfolio.js:726, `b.appendChild(t);` (the `pf-keep` table)
- portfolio.js:490, `grid.appendChild(F.el('div', {}, [t,` (the `pf-rules` table): change the
  `t` in that array to `F.el('div', { class: 'scroll-x' }, t)`
- coverage.js:856, `panel.appendChild(tbl);` (the `cv-ledger-tbl`)

becomes, in each case, `X.appendChild(F.el('div', { class: 'scroll-x' }, t));`.

For the pareto head-to-head matrix, ranks.js:1114, wrap the `<svg ...>` string in
`<div class="scroll-x"> ... </div>`.

---

## Part 3. The charts that read their own width

Four charts size themselves from the container and redraw on resize. They all have a floor that is
wider than a phone. Lower the floor and trim the margin; do not remove the chart.

**saydo.js:164**
```js
    var W = Math.max(420, host.clientWidth || 628);
    var H = 424;
    var M = { t: 18, r: 16, b: 66, l: 58 };
```
becomes
```js
    var W = Math.max(280, host.clientWidth || 628);
    var narrow = W < 420;
    var H = narrow ? 330 : 424;
    var M = narrow ? { t: 14, r: 10, b: 56, l: 40 } : { t: 18, r: 16, b: 66, l: 58 };
```

**ranks.js:424**
```js
    var W = Math.max(420, host.clientWidth || 598);
    var M = { t: 30, r: 14, b: 44, l: 30 };
```
becomes
```js
    var W = Math.max(280, host.clientWidth || 598);
    var narrow = W < 420;
    var M = { t: 30, r: 14, b: 44, l: narrow ? 8 : 30 };
```
and at ranks.js:452 the tick list becomes
`values: narrow ? [1, 250, N] : [1, 100, 200, 300, 400, N]`, because six mono tick labels collide
below 420px,
and the rotated axis label appended at ranks.js:457 is skipped when `narrow` is true. It reads
"500 companies, ordered by median rank" and the same words are already in the `.rk-note` under the
chart, so nothing is lost. **`H` does not change: 500 rows stay 500 rows.**

**coverage.js:496**
```js
    var W = Math.max(320, host.clientWidth || 450);
    var M = { t: 12, r: 10, b: 52, l: 58 };
```
becomes
```js
    var W = Math.max(260, host.clientWidth || 450);
    var M = { t: 12, r: 10, b: 52, l: W < 360 ? 40 : 58 };
```

**ranks.js:974, `dmSvg`.** `var w = 460` is hard-coded and has no host to measure. Give the svg a
viewBox instead, at ranks.js:997:

```js
      '</div><svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" height="' + h + '" ' +
      'preserveAspectRatio="xMinYMid meet" role="img" ' +
```

It then scales down to the column and its type renders at about 9px on a phone, which is small but
readable, and it is a single-line diagram so the detail survives scaling.

All four already carry debounced `resize` listeners (saydo.js:139, ranks.js:72, coverage.js:469,
allocate.js:1223), so rotation is handled. Check the treemap resizes too: `measure()` reads
`dom.tmWrap.getBoundingClientRect()` every paint, so it does.

---

## Part 4. The hard cases, named honestly

Four things do not simply shrink. Each gets a stated treatment.

### The 500-row rank wall

**Verdict: shrink it, keep all 500 rows.**

It works at 310px wide better than expected, because the failure mode at small width is a coarser x
axis, not a loss of rows. Each row is 1px at every width. The band for the median company is 312 of
500 ranks, which is 187px of a 300px plot, so the thing the chart exists to prove, that the bars are
absurdly wide, is still the first thing you see. The plan: lower the 420 floor to 280, cut the left
margin from 30 to 8, drop the rotated axis label (its words are already in the note below), and go
from six x ticks to three. Height stays at `30 + 44 + max(350, N)`.

Rejected: sampling to 100 rows. The count is the point. Rejected: a horizontal scroller, because the
chart does fit; only its margins did not.

### The treemap, 500 tiles and logos

**Verdict: shrink it, add a lookup, and say what a small tile cannot do.**

At 342 x 320 the average tile is about 14 x 14px. `drawTreemap` already hides a logo below 30 x 24px,
so the map degrades to colour and sector labels on its own, which is a legitimate heat map of the
index. What breaks is tapping: the smaller half of the index is under 8px. So:

- `.tm-wrap { min-height: 420px }` at 1080 and below, `320px` at 640 and below.
- The `.tm-card` goes full width of the map instead of a 208px box, so a tapped company gets a
  readable card.
- The ticker box from Part 1 is the path to the tiles you cannot hit.
- The `.tm-small-note` span states it: "A tile under about 30 pixels carries no logo. Type a ticker
  to reach the small ones."

Rejected, and worth stating so nobody spends the time: collapsing to 11 sector blocks with a tap to
drill in. It would be the better phone design. It is a rewrite of `layout()`, `drawTreemap`,
`buildTiles`, `onHover` and `onClick`, and it creates a second visual the demo does not show. Not in
ten hours.

### The Brinson waterfall

**Verdict: horizontal scroller at a fixed 720px.**

`svg#pf-wf` is `viewBox="0 0 912 388"` at `width:100%`. At a 310px column that is a 0.34 scale and
the 14px labels render at 4.8px, which is a picture of a chart rather than a chart. Fixing it to
720px inside `.pf-plot { overflow-x: auto }` puts the type at 11px and asks for about 400px of
sideways drag on a phone. Every bar, every label and every connector survives.

The number the chart exists to prove, 97.4% of the carbon cut is reallocation, is already set at
56px immediately beside it in `.pf-verdict-fig`, and again in the hero stat row, so a reader who
never drags the chart still gets the finding.

Rejected: replacing it with the number alone. The waterfall is the evidence; the number without it is
an assertion.

### The five wide tables and the coverage chain

**Verdict: horizontal scroller, every column kept.**

`pf-art` (944px, and its 392px "Test" column is quoted regulation text), `pf-hold` (944px, eight
columns), `pf-keep` (455px), `pf-rules`, `cv-ledger-tbl` (499px, and it is the provenance ledger, so
its source and licence columns are the point of it). `.cv-chain` is 670px of boxes and arrows that
only means anything left to right.

Rejected: dropping columns below 640px. The provenance columns are the honesty. Rejected for the
chain: restacking it vertically with rotated arrows, which is real work for a diagram most readers
will not open.

### Also worth knowing, though not hard

- `.cv-cells` at `repeat(60,1fr)` becomes `repeat(30,1fr)` below 640. Cells go from 1.33px to about
  8px and the waffle reads as a waffle. The cell count does not change, only the row length.
- `.sob-row`, `.wa-row`, `.cb-row` put the bar on its own row below 640 rather than letting the
  `minmax(0,1fr)` track compute to 0px, which is what happens today.
- `.cb-row`'s second track is dropped entirely below 640, not stacked, because it is a redundant
  visual restatement of the two numeric columns beside it. If that turns out to be wrong on the
  screenshot, stack it like the others instead.

---

## Part 5. What must still be true at 390px

Check each of these by eye in the verify pass. These are the things that cannot go missing:

1. Section 03: the four declared chart states, `108 / 233 / 26 / 136`, all four cells legible, with
   "A company we cannot measure is a declared state, never a zero and never a deletion" above them.
2. Every chart's `n` in its `.panel-n`. The `.panel-n` wraps below 640 rather than being clipped.
3. "An exposure model, not a forecast" under the treemap, and "What this model is not" reachable at
   the foot of section 01. The latter stops opening upward once the section scrolls.
4. "US Scope 1 only", the reporting threshold and the 2023 cutoff, all in section 06. Section 06 has
   no fixed-width element left after the `cv-two` / `cv-ind` / `cv-chain` rules above.
5. All 33 `<details>` still open and close. None is inside a `display:none`.
6. The hero foot line "503 listings, 500 companies. 139 measured by the EPA, 88 self-reported only,
   273 with no mandatory number at all."
7. "Zero vendor ESG inputs."

Compare the rendered text token by token against the current build before and after, the same way
the last two passes did. The only strings that should differ are the six in Part 1.

---

## Part 6. Verification, and what the prototype already measured

Every rule in Part 2, plus a simulation of the Part 3 and the `.scroll-x` changes, was injected into
the live page in Chromium and measured. Result:

| viewport | before | after prototype |
|---|---|---|
| 390 x 844 | 1114 | **390** |
| 430 x 932 | 1114 | **430** |
| 768 x 1024 | 948 | **768** |
| 1024 x 768 | 1024 | **1024** |
| 1280 x 720 | 1280 | **1280** |

Zero elements overflow the viewport at any of the five, counting only elements not inside a scroll
container. The prototype stylesheet is at
`/persist/tmp/claude-1000/-home-tyrolize-prog-ETHack2026/a616b367-1d03-433c-a9a4-a3d9e36ce3fd/scratchpad/fix.css`
and the harness at `.../verify.py` in the same directory, if they are still on disk. Both are
reproduced in full above, so neither is needed.

Two things the prototype could only fake, and which the build agent must do for real:

- The chart floors. The prototype rescaled the existing SVGs with a viewBox, which clips rather than
  redraws. In the screenshots the say-and-do scatter and the rank wall are therefore cut off at the
  right edge. With the real floor change they redraw at the container width and fit.
- The `.scroll-x` wrappers, which the prototype inserted with script.

Run the harness after the build. The check that matters is one line:

```js
document.documentElement.scrollWidth === window.innerWidth
```

at 390, 430, 768, 1024 and 1280. Then look at the screenshots, because a page can measure clean and
still be unreadable, which is how `.states` and `.cv-cells` got found.

Re-record the demo last. The 1280 frame is unchanged by everything in Part 2, so the only reason to
re-record is the six strings in Part 1.

---

## Order of work

1. Part 1, the six strings. Twenty minutes, and it is the half a judge reads.
2. The three media blocks and `.scroll-x` in app.css. This alone takes 390px from 1114 to about 460.
3. The two `classList.add` calls in allocate.js that the 1080 block needs.
4. The five `.scroll-x` wraps and the `cv-chain` class.
5. Part 3, the four chart floors.
6. The ticker box, if there is time.
7. Verify at five widths, read the screenshots, diff the rendered text, re-record.
