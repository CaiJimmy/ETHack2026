"""Capture the slide imagery for slides/outline.md straight off the live site.

The deck and the demo recording have to look like one product, so nothing here
is redrawn: every image is the page's own panel, rendered by the page's own JS
out of site/data/*.json, photographed at a device scale factor that survives a
projector at the back of a room.

    cd /home/tyrolize/prog/ETHack2026
    nix develop --command .venv/bin/python src/capture_slides.py

Writes slides/img/*.png and slides/img/manifest.json.

Four things this script does on purpose.

  * It loads the page from file://, so nothing depends on a server being up on
    the day. That path reads site/data/bundle.js, so build_bundle.py runs first.
  * It hides interactive furniture, and only interactive furniture: the fixed
    nav, the search box, the sector filter, the tier toggles, the hover card,
    the site's own section numbering. Each panel keeps its own title and its n,
    because a chart on a slide has to state its n.
  * It trims two sentences that instruct the reader to hover or to filter. On a
    slide those controls do not exist, so the sentence is not a caveat, it is a
    dead end. Nothing else in any panel's copy is touched, and no figure
    anywhere is touched.
  * It forces prefers-reduced-motion, which makes portfolio.js paint the
    waterfall in one step instead of tweening it and switches off the Sobol
    bars' width transition, so a capture is the settled state and not a frame
    of an animation.

Panel widths are set in CSS, not by resizing the window: the charts size
themselves to their container and redraw on a resize event. The widths are
chosen twice over, for geometry and for the slot the panel lands in.

  * The say-do scatter gets a narrow frame. Its height is hardcoded at 424px,
    so widening it flattens the identity line, and the identity line is the
    entire slide. 700px keeps the line at the angle the demo recording shows.
  * The rank wall gets a wide one. Its height is fixed at 500 rows plus margins
    however wide it is, so width is the only lever on the aspect ratio, and
    1100px lands it in the two-thirds slot outline.md asks for.
  * The Sobol panel gets a narrow one, to stand up in the one-third slot beside
    that wall rather than lie down in it.
"""

import json
import pathlib
import subprocess
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / 'site'
OUT = ROOT / 'slides' / 'img'
CHROME = '/home/tyrolize/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'

# Applied to every capture. Everything that is a control rather than a finding
# lives here; anything panel-specific lives in the target's own `hide`.
BASE_CSS = """
  .nav { display: none !important; }
  .main { margin-left: 0 !important; }
  .tip { display: none !important; }
  /* --cap-pad keeps a glyph off the raster edge on the section-level
     captures. Panel-level captures sit inside it and are exactly --cap-w. */
  .section {
    padding: 6px var(--cap-pad) !important;
    border-top: 0 !important;
    width: calc(var(--cap-w) + 2 * var(--cap-pad)) !important;
  }
  .section > * { max-width: none !important; }
  /* the site's own section numbering. The deck carries its own, top right. */
  .sec-kicker { display: none !important; }
  /* a caret in a search field blinks, and a blinking pixel is a diff */
  input, select, button { caret-color: transparent !important; }
"""

# name, the section's css width, the device scale factor, what to hide, what to
# trim, and the element to photograph. `pick` is evaluated in the page after the
# css and after the redraw, and must return the element.
TARGETS = [
    {
        'name': '01_saydo_scatter',
        'slide': 1,
        'width': 700,
        'scale': 3,
        'hide': ['#saydo-card', '#saydo .panel'],
        'css': '.saydo-grid { grid-template-columns: 1fr !important; }',
        'trim': [],
        'pick': "document.querySelector('#saydo')",
        'what': "Say-do scatter under the panel's own title and n. Promised on "
                "x, delivered on y, the identity line labelled 'delivered = "
                "promised', and the accent half-plane ABOVE it labelled "
                "EMITTING MORE THAN PROMISED.",
    },
    {
        'name': '01_saydo_scatter_nolabels',
        'slide': 1,
        'width': 700,
        'scale': 3,
        'hide': ['#saydo-card', '#saydo .panel',
                 "#saydo-chart text.pt-label:not([transform])",
                 '#saydo-chart .leader'],
        'css': '.saydo-grid { grid-template-columns: 1fr !important; }',
        'trim': [],
        'pick': "document.querySelector('#saydo')",
        'what': "The same thing with the ten ticker labels and their leader "
                "lines suppressed, for outline.md's 'No company names' rule. "
                "The 'delivered = promised' label survives.",
    },
    {
        'name': '01_saydo_plot_only',
        'slide': 1,
        'width': 700,
        'scale': 3,
        'hide': ['#saydo-card', '#saydo .panel'],
        'css': '.saydo-grid { grid-template-columns: 1fr !important; }',
        'trim': [],
        'pick': "document.querySelector('#saydo .chart-wrap')",
        'what': "The scatter alone, no section title: plot, legend, and the "
                "size key that states n = 108 plotted. outline.md's 'one "
                "scatter, nothing else'.",
    },
    {
        'name': '02a_rank_wall',
        'slide': 2,
        'width': 1100,
        'scale': 2,
        'hide': ['#rk-card', '#ranks .rk-ctl'],
        'css': '#ranks .rk-grid { grid-template-columns: 1fr !important; }',
        'trim': [['#ranks .rk-note', ' Filtering hides rows']],
        'pick': "document.querySelector('#ranks .chart-wrap')",
        'what': "The rank interval wall. 500 bands, one per company, sorted by "
                "median rank, coloured by coverage tier, with the 312.5-rank "
                "median band drawn to the same scale above them.",
    },
    {
        'name': '02b_sobol_bars',
        'slide': 2,
        'width': 620,
        'scale': 3,
        'hide': ['#rk-seg', '#rk-weights', '#rk-sobol-note'],
        'css': '#ranks .rk-two { grid-template-columns: 1fr !important; }',
        'trim': [],
        'pick': "document.getElementById('rk-sobol').closest('.panel')",
        'what': "Sobol first-order variance shares, one bar per modelling "
                "choice, the weights bar in accent and every other bar muted. "
                "The effective-weight audit that sits beside it on the site is "
                "hidden, per outline.md.",
    },
    {
        'name': '02b_sobol_bars_wide',
        'slide': 2,
        'width': 916,
        'scale': 2,
        'hide': ['#rk-seg', '#rk-weights', '#rk-sobol-note'],
        'css': '#ranks .rk-two { grid-template-columns: 1fr !important; }',
        'trim': [],
        'pick': "document.getElementById('rk-sobol').closest('.panel')",
        'what': "The same bars in a landscape frame, if the two slide-2 panels "
                "end up stacked rather than side by side.",
    },
    {
        'name': '04_pab_waterfall',
        'slide': 4,
        'width': 1012,
        'scale': 2,
        'hide': ['#pf-reveal-say'],
        'css': '',
        'trim': [],
        'pick': "document.querySelector('#portfolio .pf-reveal')",
        'what': "The Brinson decomposition of the PAB book's intensity cut. "
                "Every step prints its level and its signed share: improvement "
                "20.5%, reallocation 97.4%, selection -0.1%, interaction "
                "-17.8%. The closing paragraph that reads the cross term aloud "
                "is hidden, because outline.md and script.md both forbid that "
                "sentence.",
    },
    {
        'name': '04_pab_waterfall_plain',
        'slide': 4,
        'width': 1012,
        'scale': 2,
        'hide': ['#pf-reveal-say', '#portfolio .pf-verdict'],
        'css': '',
        'trim': [],
        'pick': "document.querySelector('#portfolio .pf-reveal')",
        'what': "The same waterfall without the 76px 97.4% block, for a slide "
                "that already sets 97.4% at 96pt.",
    },
    {
        'name': '05_coverage_partition',
        'slide': 5,
        'width': 916,
        'scale': 2,
        'hide': ['#coverage .cv-secbar', '#coverage .cv-secline',
                 '#coverage .cv-subhead', '#coverage .cv-inds',
                 '#coverage .cv-pillnote', '#coverage .note',
                 '#coverage .cv-prov'],
        'css': '',
        'trim': [['#coverage-body > .panel .panel-sub', ' Hover a sector']],
        'pick': "document.querySelector('#coverage-body > .panel')",
        'what': "The coverage partition: 139 measured, 88 reported, 273 not "
                "measurable, one cell per company. 88 + 273 is the 361 with no "
                "mandatory tonnage. Not specified by outline.md, which renders "
                "slide 5 as five typographic rows.",
    },
]

# every section has to have rendered before anything is measured
READY = ['#saydo-chart svg', '#rk-chart svg', '#pf-wf', '#cv-waffle .cv-cell']

SETUP_JS = """
(arg) => {
  document.documentElement.style.setProperty('--cap-w', arg.width + 'px');
  document.documentElement.style.setProperty('--cap-pad', '10px');
  let s = document.getElementById('cap-style');
  if (!s) { s = document.createElement('style'); s.id = 'cap-style'; document.head.appendChild(s); }
  const hidden = arg.hide.map(sel => sel + ' { display: none !important; }').join('\\n');
  s.textContent = arg.base + '\\n' + hidden + '\\n' + arg.css;
  for (const [sel, marker] of arg.trim) {
    const el = document.querySelector(sel);
    if (!el) throw new Error('trim selector matched nothing: ' + sel);
    const i = el.textContent.indexOf(marker);
    if (i < 0) throw new Error('trim marker not found in ' + sel + ': ' + marker);
    el.textContent = el.textContent.slice(0, i).trim();
  }
  window.dispatchEvent(new Event('resize'));
}
"""


def build_bundle():
    r = subprocess.run([sys.executable, str(ROOT / 'src' / 'build_bundle.py')],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        raise SystemExit('build_bundle.py failed')


def main():
    build_bundle()
    OUT.mkdir(parents=True, exist_ok=True)
    url = (SITE / 'index.html').as_uri()
    manifest = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        try:
            for scale in sorted({t['scale'] for t in TARGETS}):
                ctx = browser.new_context(
                    viewport={'width': 1440, 'height': 1000},
                    device_scale_factor=scale,
                    reduced_motion='reduce',
                )
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                for t in [t for t in TARGETS if t['scale'] == scale]:
                    page.goto(url, wait_until='load')
                    for sel in READY:
                        page.wait_for_selector(sel, state='attached', timeout=20000)
                    page.evaluate(SETUP_JS, {
                        'width': t['width'], 'hide': t['hide'], 'css': t['css'],
                        'trim': t['trim'], 'base': BASE_CSS,
                    })
                    # the charts redraw off that resize event; this is layout
                    # plus the redraw, both of which are synchronous
                    page.wait_for_timeout(400)
                    el = page.evaluate_handle(t['pick']).as_element()
                    if el is None:
                        raise SystemExit(f"{t['name']}: {t['pick']} matched nothing")
                    # a headline that overflows its frame is cropped by the
                    # screenshot and nothing in the image says so
                    over = el.evaluate(
                        "e => [...e.querySelectorAll('*')]"
                        ".filter(n => n.namespaceURI === 'http://www.w3.org/1999/xhtml')"
                        ".filter(n => n.scrollWidth > n.clientWidth + 1 && n.clientWidth > 0)"
                        ".map(n => (n.className || n.tagName) + ' ' + n.scrollWidth + '>' + n.clientWidth)")
                    if over:
                        print(f"  overflow in {t['name']}: {over}", file=sys.stderr)
                    path = OUT / (t['name'] + '.png')
                    el.screenshot(path=str(path), animations='disabled')
                    box = el.bounding_box()
                    px = (round(box['width'] * scale), round(box['height'] * scale))
                    manifest.append({
                        'file': f'slides/img/{path.name}',
                        'slide': t['slide'],
                        'css_px': [round(box['width']), round(box['height'])],
                        'scale': scale,
                        'pixels': list(px),
                        'aspect': round(box['width'] / box['height'], 2),
                        'kb': round(path.stat().st_size / 1024),
                        'shows': t['what'],
                    })
                    print(f"{path.name:32s} {px[0]:5d} x {px[1]:5d}  "
                          f"{manifest[-1]['aspect']:4.2f}:1  "
                          f"{manifest[-1]['kb']:4d} KB  (@{scale}x)")
                ctx.close()
                if errors:
                    print('page errors:', errors, file=sys.stderr)
        finally:
            browser.close()

    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'\n{len(manifest)} images -> {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
