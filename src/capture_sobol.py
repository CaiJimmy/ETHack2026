#!/usr/bin/env python3
"""Recapture slide 2's variance panel with plain-language labels.

The deck and the site are one product, so this does not redraw the chart: it
loads the site's own page, lets the site's own JS paint the panel out of
site/data/scores.json, then rewrites the row labels in the DOM and photographs
the result. Every bar, every share and the n are the page's.

The rewrite exists because a slide is read in five seconds by someone who has
never heard of winsorisation. The site keeps its own vocabulary; the deck gets
the same numbers under words a judge can read at ten feet.

    cd /home/tyrolize/prog/ETHack2026
    nix develop --command .venv/bin/python src/capture_sobol.py

Writes slides/img/02b_sobol_bars_plain.png. Leaves the existing captures alone.
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

WIDTH = 820
SCALE = 3

BASE_CSS = """
  .nav { display: none !important; }
  .main { margin-left: 0 !important; }
  .tip { display: none !important; }
  .section {
    padding: 6px var(--cap-pad) !important;
    border-top: 0 !important;
    width: calc(var(--cap-w) + 2 * var(--cap-pad)) !important;
  }
  .section > * { max-width: none !important; }
  .sec-kicker { display: none !important; }
  input, select, button { caret-color: transparent !important; }
  #rk-seg, #rk-weights, #rk-sobol-note { display: none !important; }
  #ranks .rk-two { grid-template-columns: 1fr !important; }
"""

# data-k -> (row label, the small line under it). None keeps what the site says.
PLAIN = {
    'missing_data':     ('what we assume about missing data', None),
    'pillar_inclusion': ('which pillars are in', None),
    'sector_relative':  ('judged against its sector, or against everyone', None),
    'normalisation':    ('how scores are put on one scale', None),
    'weights':          ('the weights', 'every weighting, drawn at random'),
    'aggregation':      ('how the four pillars are combined', None),
    'winsorisation':    ('trimming the extremes', None),
    '_rest':            ('choices acting together, and what no one choice explains', None),
}

SUB = "How much of a rank's movement each choice explains on its own."

RELABEL_JS = """
(arg) => {
  document.documentElement.style.setProperty('--cap-w', arg.width + 'px');
  document.documentElement.style.setProperty('--cap-pad', '10px');
  let s = document.getElementById('cap-style');
  if (!s) { s = document.createElement('style'); s.id = 'cap-style'; document.head.appendChild(s); }
  s.textContent = arg.css;

  // the panel became a disclosure during the site redesign, so fall back to it
  const sob = document.getElementById('rk-sobol');
  const panel = sob.closest('.panel') || sob.closest('details');
  const sub = panel.querySelector('.panel-sub');
  if (!sub) throw new Error('no .panel-sub on the variance panel');
  sub.textContent = arg.sub;

  const seen = [];
  for (const [k, pair] of Object.entries(arg.plain)) {
    const row = panel.querySelector('[data-k="' + k + '"]');
    if (!row) throw new Error('no row for ' + k);
    const kd = row.querySelector('.sob-k');
    const opt = kd.querySelector('.opt');
    const optText = pair[1] !== null ? pair[1] : (opt ? opt.textContent : '');
    kd.textContent = pair[0];
    if (optText) {
      const sp = document.createElement('span');
      sp.className = 'opt';
      sp.textContent = optText;
      kd.appendChild(sp);
    }
    seen.push(k);
  }
  const rows = panel.querySelectorAll('.sob-row, .sob-rest');
  if (rows.length !== seen.length) {
    throw new Error('relabelled ' + seen.length + ' of ' + rows.length + ' rows');
  }
  window.dispatchEvent(new Event('resize'));
  return Array.prototype.map.call(rows, r =>
    r.querySelector('.sob-k').textContent + '  ' + r.querySelector('.sob-v').textContent);
}
"""


def main():
    r = subprocess.run([sys.executable, str(ROOT / 'src' / 'build_bundle.py')],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        raise SystemExit('build_bundle.py failed')

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=CHROME)
        pg = br.new_page(viewport={'width': 1600, 'height': 1000},
                         device_scale_factor=SCALE,
                         reduced_motion='reduce')
        errors = []
        pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        pg.goto((SITE / 'index.html').as_uri(), wait_until='load')
        pg.wait_for_selector('#rk-chart svg', timeout=30000)
        # The variance panel moved inside a disclosure. It is closed on load, so
        # the bars exist but are not visible and never paint; open it first.
        pg.evaluate("""() => {
          const d = document.getElementById('rk-sobol').closest('details');
          if (d) d.open = true;
        }""")
        pg.wait_for_selector('#rk-sobol .sob-row', timeout=30000)

        rows = pg.evaluate(RELABEL_JS, {'width': WIDTH, 'css': BASE_CSS,
                                        'plain': PLAIN, 'sub': SUB})
        pg.wait_for_timeout(400)
        el = (pg.query_selector('#rk-sobol >> xpath=ancestor::div[contains(@class,"panel")][1]')
              or pg.query_selector('#rk-sobol >> xpath=ancestor::details[1]'))
        path = OUT / '02b_sobol_bars_plain.png'
        el.screenshot(path=str(path))

        box = el.bounding_box()
        print(f'wrote {path}')
        print(f'  css px  {box["width"]:.0f} x {box["height"]:.0f}   scale {SCALE}')
        for line in rows:
            print('  ' + line)
        if errors:
            print('  console errors:')
            for e in errors:
                print('    ' + e)
        br.close()

    man = OUT / 'manifest.json'
    entries = json.loads(man.read_text()) if man.exists() else []
    entries = [e for e in entries if e['file'] != 'slides/img/02b_sobol_bars_plain.png']
    entries.append({
        'file': 'slides/img/02b_sobol_bars_plain.png',
        'slide': 2,
        'css_px': [round(box['width']), round(box['height'])],
        'scale': SCALE,
        'kb': round(path.stat().st_size / 1024),
        'shows': 'The same variance panel as 02b_sobol_bars, with every row label '
                 'rewritten in plain language for the deck. Numbers, bars and n are '
                 "the site's own, painted by the site's own JS.",
    })
    man.write_text(json.dumps(entries, indent=2) + '\n')
    print(f'updated {man}')


if __name__ == '__main__':
    main()
