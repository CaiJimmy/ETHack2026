"""Record docs/demo.mp4, docs/demo.gif and docs/demo_poster.png off the site.

Fifty seconds, no voice, no cursor, no burned-in captions. The interface's own
copy is the caption, which is why the layout had to settle before this ran.

The arc, and why it is in this order.

  * It opens on section 01 under Current Policies, the cheap world, and holds
    long enough to read the question and the line that answers it.
  * The scenario goes to Net Zero 2050. Every number on the screen moves: the
    map lights up, the book's share of value at risk goes 0.12% to 1.47%. The
    advice column does not move and says so, "Weights unchanged, largest weight
    change 0.00 bp".
  * The price then sweeps to the floor, comes back, and jumps to the top of the
    slider. The jump is one discrete event, because the readout reports the
    change since the last one: a drag would make it compare two adjacent frames
    instead of printing the honest 1000/284. Still 0.00 bp.
  * Then the one control that does move money. The missing-data rule goes to
    zero-fill and to abstain, $244m and $121m on the same 500 companies, with
    "Weights moved, largest weight change 121 bp" under them, and back to the
    sector median.
  * Then a tour in page order at reading pace: the argument, say and do, the
    rank wall, the fund's carbon decomposition, and what we cannot see.
  * It ends on the opening frame. The last two changes are the same two changes
    the page was set up with, so the advice panel prints the same line it printed
    at the start and the file loops without a jump.

One timeline, two passes, because the two outputs want different sources.

  * The mp4 comes from Playwright's own video capture at 25 fps. Smooth scrolls,
    small file, and it is what the deck embeds.
  * The GIF comes from a second pass that writes one PNG per frame. A GIF only
    gets small if paletteuse can see that a still frame is still, and it cannot:
    every video codec leaves a little noise on every pixel, so off the mp4 this
    same recording came out at 46 MB against 11 MB off the frames. The frame
    pass paces itself to the playback clock, so CSS transitions are sampled at
    the speed a viewer will see them.

    cd /home/tyrolize/prog/ETHack2026
    nix develop --command .venv/bin/python src/record_demo.py
"""

import pathlib
import shutil
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / 'site'
DOCS = ROOT / 'docs'
CHROME = '/home/tyrolize/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
W, H = 1280, 720
FPS = 12.5
FRAME_MS = 1000.0 / FPS

# Nothing here is content. The scrollbar is chrome, and a focus ring on a
# control driven from script is a lie about what the viewer is seeing.
HIDE = """
  html { scrollbar-width: none; }
  ::-webkit-scrollbar { width: 0; height: 0; }
  *:focus, *:focus-visible { outline: none !important; }
"""

SET_PRICE = """(v) => {
  const e = document.querySelector('input.ac-range');
  e.value = v;
  e.dispatchEvent(new Event('input', { bubbles: true }));
}"""

# The first select.ac-sel is the scenario. The second is the pass-through preset
# and sits inside a closed disclosure.
SET_SCENARIO = """(v) => {
  const s = document.querySelector('select.ac-sel');
  s.value = v;
  s.dispatchEvent(new Event('change', { bubbles: true }));
}"""

SCROLL = """(sel) => {
  const e = document.querySelector(sel);
  window.scrollTo({ top: e.getBoundingClientRect().top + window.scrollY, behavior: 'smooth' });
}"""

SCROLL_CENTRE = """(sel) => {
  document.querySelector(sel).scrollIntoView({ behavior: 'smooth', block: 'center' });
}"""

# Where the pointer waits. The rail is 48px and the section gutter is empty out
# to x=144, so nothing under this point ever lights up on hover.
PARK = (60, 400)
SWEEP_STEPS = 20


def park(pg):
    pg.mouse.move(*PARK)


def play(pg, tick):
    """The demo, once. `tick(ms)` is what a pass does with the time in between."""

    def sweep(a, b, ms):
        step = (b - a) / SWEEP_STEPS
        for i in range(1, SWEEP_STEPS + 1):
            pg.evaluate(SET_PRICE, round(a + step * i))
            tick(ms / SWEEP_STEPS)

    def visit(sel, ms, centre=False):
        pg.evaluate(SCROLL_CENTRE if centre else SCROLL, sel)
        tick(900)
        tick(ms)

    # the opening frame, which is also demo_poster.png
    tick(3000)

    # the scenario moves every number on screen except the money
    pg.evaluate(SET_SCENARIO, 'Net Zero 2050')
    tick(4200)

    # so does the price. The slider is dragged down and back so the gesture is
    # visible, then thrown to the top in one event, because the readout reports
    # the change since the last one and a drag would make it compare two
    # adjacent frames instead of printing the honest 1000/284.
    sweep(284, 6, 1700)
    sweep(6, 284, 1200)
    tick(800)
    pg.evaluate(SET_PRICE, 1000)
    tick(5600)

    # the one control that does move money
    pg.click('.ac-opt:has-text("Treat them as zero")')
    tick(3500)
    pg.click('.ac-opt:has-text("Leave them unscored")')
    tick(3500)
    pg.click('.ac-opt:has-text("Charge their sector")')
    tick(2200)
    park(pg)

    # the tour, in page order, at reading pace
    visit('#hero', 2300)
    visit('#saydo', 3600)
    visit('#ranks', 3900)
    visit('#pf-wf', 3900, centre=True)
    visit('#coverage', 2700)

    # back to the opening frame. Same two changes as the setup, so the advice
    # panel prints the same line and the loop closes.
    pg.evaluate(SCROLL, '#allocate')
    tick(600)
    pg.evaluate(SET_SCENARIO, 'Net Zero 2050')
    tick(700)
    pg.evaluate(SET_SCENARIO, 'Current Policies')
    tick(1700)


def open_page(ctx):
    pg = ctx.new_page()
    pg.goto((SITE / 'index.html').as_uri())
    pg.wait_for_timeout(2600)
    pg.add_style_tag(content=HIDE)
    park(pg)
    # The page loads at Net Zero 2050. Going to Current Policies here is the
    # same change the demo ends on, so the advice panel's readout at the first
    # frame is the one it holds at the last.
    pg.evaluate(SET_SCENARIO, 'Current Policies')
    pg.wait_for_timeout(900)
    return pg


def pass_video(tmp):
    """Playwright's own capture. Gives the mp4 and the poster frame."""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(
            viewport={'width': W, 'height': H},
            record_video_dir=str(tmp),
            record_video_size={'width': W, 'height': H},
        )
        t_ctx = time.perf_counter()
        pg = open_page(ctx)
        pg.screenshot(path=str(DOCS / 'demo_poster.png'))
        head = time.perf_counter() - t_ctx
        play(pg, pg.wait_for_timeout)
        body = time.perf_counter() - t_ctx - head
        path = pg.video.path()
        ctx.close()
        browser.close()
    # Playwright starts recording when the context opens, so the raw file leads
    # with the page loading and trails with the close. Neither is the demo.
    return pathlib.Path(path), head, body


def pass_frames(frames):
    """One PNG per frame, paced to the playback clock."""
    frames.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport={'width': W, 'height': H})
        pg = open_page(ctx)

        # The frame clock chases the wall clock, so the pass covers the time the
        # clicks and the scrolls take as well as the time the script asks for.
        # Counting frames off the script's own budget instead lost four seconds
        # over the fifty, and the GIF ran short against the mp4.
        state = {'n': 0, 't0': time.perf_counter()}

        def pump():
            while time.perf_counter() - state['t0'] >= state['n'] * FRAME_MS / 1000:
                pg.screenshot(path=str(frames / f"{state['n']:04d}.png"))
                state['n'] += 1

        def tick(ms):
            end = time.perf_counter() + ms / 1000.0
            while True:
                pump()
                nxt = state['t0'] + state['n'] * FRAME_MS / 1000
                stop = min(nxt, end)
                rest = stop - time.perf_counter()
                if rest > 0:
                    time.sleep(rest)
                if time.perf_counter() >= end:
                    break
            pump()

        play(pg, tick)
        ctx.close()
        browser.close()
    return state['n']


def ff(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *args], check=True)


def main():
    tmp = ROOT / '.demo_tmp'
    if tmp.exists():
        shutil.rmtree(tmp)
    frames = tmp / 'frames'

    webm, head, body = pass_video(tmp)
    print(f'capture  {webm.stat().st_size / 1e6:.1f} MB, {head:.2f}s of load trimmed')

    mp4 = DOCS / 'demo.mp4'
    ff('-ss', f'{head:.3f}', '-i', str(webm), '-t', f'{body:.3f}', '-r', '25',
       '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p',
       '-movflags', '+faststart', str(mp4))

    n = pass_frames(frames)
    print(f'frames   {n} at {FPS} fps')

    # The frame pass runs a little slower than real time, because a screenshot
    # occasionally overruns its slot. Playing the frames back over the mp4's own
    # length puts the two files on the same clock and lands inside 12-15 fps.
    out_fps = n / body
    if not 11.5 <= out_fps <= 15.5:
        raise SystemExit(f'{n} frames over {body:.1f}s is {out_fps:.1f} fps, outside 12-15')

    pal = tmp / 'pal.png'
    seq = str(frames / '%04d.png')
    vf = 'scale=1152:-1:flags=lanczos'
    ff('-framerate', f'{out_fps:.4f}', '-i', seq,
       '-vf', f'{vf},palettegen=max_colors=192:stats_mode=diff', str(pal))
    gif = DOCS / 'demo.gif'
    ff('-framerate', f'{out_fps:.4f}', '-i', seq, '-i', str(pal), '-lavfi',
       f'{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle',
       '-loop', '0', str(gif))

    shutil.rmtree(tmp)
    for f in (mp4, gif, DOCS / 'demo_poster.png'):
        print(f'{f.relative_to(ROOT)}  {f.stat().st_size / 1e6:.2f} MB')
    dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'default=nw=1:nk=1', str(mp4)],
                         capture_output=True, text=True).stdout.strip()
    print(f'mp4 duration {dur} s, gif {n} frames at {out_fps:.2f} fps = {n / out_fps:.2f} s')


if __name__ == '__main__':
    sys.exit(main())
