#!/usr/bin/env python3
"""Build slides/FILED.pptx from the specification in slides/outline.md.

Five slides plus one appendix slide held back for questions. Every figure on
every slide comes from slides/outline.md, which derived it from site/data/*.json.
Nothing here computes a number; this file only sets type and places pictures.

Run:  nix develop --command .venv/bin/python src/build_deck.py

The layout is measured, not eyeballed. Every text box is wrapped with the real
font metrics of the face the deck declares, and the build fails if a block does
not fit the space it was given. That is the only way a slide cannot silently
overflow between here and a projector.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from dataclasses import dataclass

from PIL import Image, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "slides", "img")
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(ROOT, "slides", "FILED.pptx")

# ---------------------------------------------------------------- palette
# site/css/app.css, copied token for token so the deck and the recording are
# one product.
BG = RGBColor.from_string("0B0D10")   # --bg
INK = RGBColor.from_string("ECEEF1")  # --ink
INK2 = RGBColor.from_string("AAB3BF")  # --ink-2
INK3 = RGBColor.from_string("79838F")  # --ink-3
ACCENT = RGBColor.from_string("FF7A45")  # --accent
COOL = RGBColor.from_string("4FC3D9")  # --cool
MUTED = RGBColor.from_string("5A6470")  # --muted
RULE = RGBColor.from_string("212730")  # --rule

# ---------------------------------------------------------------- type
# The captures and docs/demo.mp4 were rendered by Chromium on this machine,
# which resolves the site's sans stack to a Helvetica clone and its mono stack
# to DejaVu Sans Mono. Declaring Arial (metric-compatible with Helvetica, and
# present on every machine that will ever open this file) and DejaVu Sans Mono
# keeps the slide's own type and the type inside every screenshot the same
# typeface. Inter and JetBrains Mono are installed on neither this machine nor
# the recording, so asking for them would leave the deck half and half.
SANS = "Arial"
MONO = "DejaVu Sans Mono"

FONT_FILE = {
    ("sans", False): "/nix/store/q073g38yhrjb3lh985r68k0553pmg2dd-liberation-fonts-2.1.5/share/fonts/truetype/LiberationSans-Regular.ttf",
    ("sans", True): "/nix/store/q073g38yhrjb3lh985r68k0553pmg2dd-liberation-fonts-2.1.5/share/fonts/truetype/LiberationSans-Bold.ttf",
    ("mono", False): "/nix/store/126jbw31r8ax06921rmrrphbk8m43raz-home-manager-path/share/fonts/truetype/DejaVuSansMono.ttf",
    ("mono", True): "/nix/store/126jbw31r8ax06921rmrrphbk8m43raz-home-manager-path/share/fonts/truetype/DejaVuSansMono-Bold.ttf",
}

SLIDE_W = 13.3333
SLIDE_H = 7.5
MX = 0.62                       # side margin
CW = SLIDE_W - 2 * MX           # content width, 12.093 in

TAGLINE = "FILED   the S&P 500 scored only on what it files under legal penalty"
URL = "github.com/CaiJimmy/ETHack2026"

_measure_cache: dict = {}
PROBLEMS: list[str] = []


# ---------------------------------------------------------------- metrics
def _pil(kind: str, bold: bool, size_pt: float) -> ImageFont.FreeTypeFont:
    key = (kind, bold, round(size_pt, 2))
    if key not in _measure_cache:
        _measure_cache[key] = ImageFont.truetype(FONT_FILE[(kind, bold)], int(round(size_pt * 8)))
    return _measure_cache[key]


def width_pt(text: str, kind: str, bold: bool, size_pt: float) -> float:
    return _pil(kind, bold, size_pt).getlength(text) / 8.0


def wrap(text: str, kind: str, bold: bool, size_pt: float, box_w_in: float) -> list[str]:
    """Greedy wrap with the real face, the way a renderer does it."""
    limit = box_w_in * 72.0
    lines: list[str] = []
    for hard in text.split("\n"):
        cur = ""
        for word in hard.split(" "):
            trial = word if not cur else cur + " " + word
            if width_pt(trial, kind, bold, size_pt) <= limit or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


@dataclass
class Para:
    text: str
    size: float
    kind: str = "sans"
    bold: bool = False
    color: RGBColor = INK
    ls: float = 1.20            # line spacing as a multiple of the size
    space_after: float = 0.0    # points
    align: str = "l"
    spc: int | None = None      # letter spacing, hundredths of a point


def block_height(paras: list[Para], box_w_in: float) -> float:
    """Height in inches the paragraphs need inside a box this wide."""
    total = 0.0
    for p in paras:
        n = len(wrap(p.text, p.kind, p.bold, p.size, box_w_in))
        total += n * p.size * p.ls + p.space_after
    return total / 72.0


ALIGN = {"l": PP_ALIGN.LEFT, "r": PP_ALIGN.RIGHT, "c": PP_ALIGN.CENTER}


CONTENT_BOTTOM = 6.74   # below this the source line starts


def textbox(slide, x, y, w, h, paras: list[Para], anchor="top", label="",
            limit=CONTENT_BOTTOM):
    """Place paragraphs and refuse to place them if they do not fit.

    Two checks, because a block sized to its own content always "fits" its own
    box: the paragraphs must fit the box, and the box must fit the slide."""
    need = block_height(paras, w)
    if limit is not None and y + max(h, need) > limit + 1e-6:
        raise SystemExit(
            f"OFF THE SLIDE in {label or 'a text box'}: bottom at "
            f"{y + max(h, need):.3f} in, limit {limit:.3f} in\n"
            f"  first line: {paras[0].text[:70]!r}"
        )
    for p in paras:
        for line in wrap(p.text, p.kind, p.bold, p.size, w):
            if width_pt(line, p.kind, p.bold, p.size) > w * 72.0 + 0.5:
                PROBLEMS.append(f"{label}: unbreakable line wider than its box: {line!r}")
    if need > h + 1e-6:
        raise SystemExit(
            f"OVERFLOW in {label or 'a text box'}: needs {need:.3f} in, has {h:.3f} in\n"
            f"  first line: {paras[0].text[:70]!r}"
        )
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "bottom": MSO_ANCHOR.BOTTOM,
                          "mid": MSO_ANCHOR.MIDDLE}[anchor]
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = ALIGN[p.align]
        para.line_spacing = Pt(p.size * p.ls)
        if p.space_after:
            para.space_after = Pt(p.space_after)
        run = para.add_run()
        run.text = p.text
        f = run.font
        f.name = MONO if p.kind == "mono" else SANS
        f.size = Pt(p.size)
        f.bold = p.bold
        f.color.rgb = p.color
        if p.spc is not None:
            run._r.get_or_add_rPr().set("spc", str(p.spc))
    return tb


def picture(slide, path_or_stream, x, y, w, h, fit="contain", align="l"):
    """Place a picture inside the box, aspect preserved, never stretched."""
    if hasattr(path_or_stream, "seek"):
        path_or_stream.seek(0)
        im = Image.open(path_or_stream)
        ar = im.width / im.height
        path_or_stream.seek(0)
    else:
        im = Image.open(path_or_stream)
        ar = im.width / im.height
    if w / h > ar:
        dh, dw = h, h * ar
    else:
        dw, dh = w, w / ar
    dx = x if align == "l" else (x + w - dw if align == "r" else x + (w - dw) / 2)
    dy = y + (h - dh) / 2
    return slide.shapes.add_picture(path_or_stream, Inches(dx), Inches(dy),
                                    Inches(dw), Inches(dh))


def rule(slide, x, y, w, thickness_pt=1.0, color=RULE):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                Inches(w), Pt(thickness_pt))
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


# ---------------------------------------------------------------- furniture
FOOTER_Y = 7.20
SRC_BOTTOM = 7.12


def furniture(slide, number: str):
    """Slide number top right, tagline and URL along the foot. Nothing else."""
    textbox(slide, SLIDE_W - MX - 1.2, 0.20, 1.2, 0.20,
            [Para(number, 10, "mono", False, INK3, 1.15, align="r")],
            label=f"{number} slide number", limit=None)
    textbox(slide, MX, FOOTER_Y, 7.2, 0.22,
            [Para(TAGLINE, 9, "sans", False, INK3, 1.20, spc=60)],
            label=f"{number} footer left", limit=None)
    textbox(slide, SLIDE_W - MX - 4.4, FOOTER_Y, 4.4, 0.22,
            [Para(URL, 9, "mono", False, INK3, 1.20, align="r")],
            label=f"{number} footer right", limit=None)


def source_line(slide, text: str, number: str, width=CW, x=MX, bottom=SRC_BOTTOM):
    """The 8pt provenance line, and it has to be exactly one line.

    A judge who notices primary sources is worth real points, so every slide
    keeps one. A judge who sees a paragraph at the foot of a slide reads none of
    it, so the rule is one line: name the regulation, the dataset or the file in
    the repo, and let that document restate itself. The build fails if a line
    wraps, which is the only way the rule survives an edit at 2am."""
    para = Para(text, 8, "sans", False, INK3, 1.25)
    lines = wrap(text, "sans", False, 8.0, width)
    if len(lines) != 1:
        raise SystemExit(
            f"SOURCE LINE WRAPS on slide {number}: {len(lines)} lines, "
            f"{width_pt(text, 'sans', False, 8.0):.0f}pt in {width * 72:.0f}pt. "
            f"Cut it.\n  {text}"
        )
    h = block_height([para], width)
    textbox(slide, x, bottom - h, width, h, [para],
            label=f"{number} source line", limit=None)


def new_slide(prs, number: str):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG
    furniture(slide, number)
    return slide


def notes(slide, paras: list[tuple[str, float, bool]]):
    tf = slide.notes_slide.notes_text_frame
    tf.clear()
    for i, (text, size, bold) in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.name = SANS
    return tf


# ---------------------------------------------------------------- sources
# One line each, 8pt, and source_line() fails the build if one wraps. The job
# of these is to let a judge go and check us, not to restate the method on the
# slide: where a document in the repo already says it, the document is named
# and the sentence is deleted.
SRC1 = ("n=108 S&P 500 companies with a numeric target and 4+ years of filed Scope 1. "
        "EPA GHGRP, 40 CFR Part 98, RY2010-2023; Net Zero Tracker; SBTi. Premise, not our "
        "result: Cohen, Rouen and Sachdeva, Nature Climate Change 2026.")

SRC2 = ("10,000 draws varying normalisation, trimming, pillar inclusion, missing data, "
        "aggregation, weights and the sector lens at once (OECD/JRC handbook). Band: 5th to "
        "95th percentile, median 312.5 ranks. EPA GHGRP, EPA CAMD, SEC XBRL.")

SRC3 = ("site/data/penalty.json, all 500 recomputed live: price -> cost -> earnings -> "
        "company value -> rank -> weight. The tilt runs on rank, so a uniform reprice cannot "
        "move a weight: the zero is an identity. NGFS Phase 5, Net Zero 2050, US 2030.")

SRC4 = ("Commission Delegated Regulation (EU) 2020/1818, articles 6, 11 and 12, encoded as 24 "
        "rules. Brinson decomposition of the intensity cut. Article 12 exclusions alone put the "
        "book 63.1% below the index, so the solver returned no tilt.")

SRC5 = ("139 of 500 carry a mandatory measured tonne. The other 361 are a declared category, "
        "never a zero: 88 self-reported, 273 with no source. Matching audited at 98% precision. "
        "docs/coverage_and_validation.md, docs/entity_resolution_audit.md.")

SRCA = ("site/data/water.json. WRI Aqueduct 4.0 annual water stress, July 2023, CC BY 4.0, joined "
        "to EPA GHGRP facility coordinates: 11,200 of 11,358 facilities, 142 of 503 tickers. "
        "A model, labelled as one, never an input. docs/water_risk.md.")


# ---------------------------------------------------------------- slide 1
def slide_1(prs):
    s = new_slide(prs, "01")

    # The live panel labels ten tickers permanently. outline.md says no company
    # names, so this is the label-free capture with its own title and lede
    # cropped away: the plot, the legend and the n, and nothing else.
    src = Image.open(os.path.join(IMG, "01_saydo_scatter_nolabels.png")).convert("RGB")
    buf = io.BytesIO()
    # Measured off the capture, not hardcoded: the panel's own title and lede are
    # the top 345px and its source line is the last 21. The capture got 138px
    # shorter when the site's chart footer lost a line, and a fixed bottom edge
    # then ran past the image and padded the slide with a black band.
    src.crop((33, 345, src.width - 33, src.height - 21)).save(buf, format="PNG")
    buf.seek(0)

    left_w = 5.00
    picture(s, buf, MX + left_w + 0.45, 0.62, CW - left_w - 0.45, 5.50, align="r")

    y = 0.66
    head = [Para("Four in five miss their own emissions promise.", 36, "sans", True, INK, 1.16)]
    hh = block_height(head, left_w)
    textbox(s, MX, y, left_w, hh, head, label="01 headline")
    y += hh + 0.34

    fig = [Para("77.8%", 96, "mono", True, ACCENT, 1.10)]
    fh = block_height(fig, left_w)
    textbox(s, MX, y, left_w, fh, fig, label="01 figure")
    y += fh + 0.06

    sub = [Para("84 of 108", 19, "mono", False, INK2, 1.30)]
    sh = block_height(sub, left_w)
    textbox(s, MX, y, left_w, sh, sub, label="01 figure sub")
    y += sh + 0.40

    # "%/yr" is a unit nobody reads at ten feet. Same three numbers, said out.
    lines = [
        Para("promised, median   5.92% a year", 18, "mono", False, INK2, 1.45),
        Para("delivered, median  1.87% a year", 18, "mono", False, INK2, 1.45),
        Para("33 of the 84 are emitting more", 18, "mono", False, ACCENT, 1.45),
    ]
    lh = block_height(lines, left_w)
    textbox(s, MX, y, left_w, lh, lines, label="01 mono lines")
    assert y + lh < 6.45, f"slide 1 left column runs to {y + lh:.2f}"

    source_line(s, SRC1, "01")

    notes(s, [
        ("BEAT 1 - SAY AND DO          [0:00 - 0:20]   20 s   43 words", 13, True),
        ("Slide 1 is up before you speak. No greeting, no title read, no \"we are a team of four\".", 11, False),
        ("", 11, False),
        ("SAY:", 12, True),
        ("Seventy-eight percent of the S&P 500 companies we can check are missing their own "
         "emissions promise. Their own target, our measured tonnage. No vendor estimate. They "
         "promised a 5.9 percent cut a year. They deliver 1.87. Thirty-three are emitting more "
         "while promising cuts.", 16, True),
        ("", 11, False),
        ("STAGE: \"their own target, our measured tonnage\" is the whole differentiator. Land it. "
         "The first number out of your mouth is about companies, not method.", 11, False),
        ("", 11, False),
        ("CLOCK: change to slide 2 on 0:20. Four changes at half a second each are already in the "
         "150.9 s total.", 11, False),
        ("", 11, False),
        ("IF A JUDGE ARRIVES LATE, the eight-second version: we rebuilt the sustainability ranking "
         "ten thousand defensible ways, the median company's rank is an interval 312 places wide "
         "out of 500, so we stopped ranking and priced the risk instead.", 11, False),
        ("", 11, False),
        ("IF ATTACKED on the boundary (a global promise against a US trend): we compare rates of "
         "change, not levels, so a fixed boundary difference cancels, and the direction of the "
         "bias runs against us. It holds on the flag-free subset too, 36 of 46 at 78.3 percent.", 11, False),
    ])


# ---------------------------------------------------------------- slide 2
def slide_2(prs):
    s = new_slide(prs, "02")

    band_bottom = 1.95

    # "identified" is an econometrics word, and a judge reads it as "we have not
    # found one yet", which is the opposite of the claim. The spoken line keeps
    # the term of art; the slide says it in one syllable.
    head = [Para("There is no one ranking. Ours included.", 36, "sans", True, INK, 1.16)]
    head_w = 6.33
    hh = block_height(head, head_w)
    textbox(s, MX, band_bottom - hh, head_w, hh, head, label="02 headline")

    fig = [Para("312", 96, "mono", True, ACCENT, 1.10)]
    fig_x, fig_w = 7.35, 2.50
    fh = block_height(fig, fig_w)
    textbox(s, fig_x, band_bottom - fh, fig_w, fh, fig, label="02 figure")

    cap = [Para("ranks wide, out of 500, for the median company", 18, "sans", False, INK2, 1.30)]
    cap_x = fig_x + 2.60
    cap_w = SLIDE_W - MX - cap_x
    ch = block_height(cap, cap_w)
    textbox(s, cap_x, band_bottom - ch, cap_w, ch, cap, label="02 figure caption")

    # Two panels. The wall is the argument, so it takes the left. Both are
    # flush to their own margin; the dark ground between them is the gutter.
    # The variance panel is the relabelled capture from src/capture_sobol.py:
    # the site's own bars and shares under words a judge can read. Its rows wrap
    # to two lines, so it is wider than the one the site shows and the two
    # pictures are sized off their measured aspects, not guessed.
    chart_top, chart_h = 2.08, 4.00
    wall_w = chart_h * 1.526
    picture(s, os.path.join(IMG, "02a_rank_wall.png"), MX, chart_top, wall_w, chart_h, align="l")
    sob_w = chart_h * 1.346
    picture(s, os.path.join(IMG, "02b_sobol_bars_plain.png"), SLIDE_W - MX - sob_w, chart_top,
            sob_w, chart_h, align="r")

    wall_line = [Para("497 of 500 companies have a band wider than 100 ranks", 18, "mono",
                      False, INK2, 1.40)]
    wl_h = block_height(wall_line, CW)
    textbox(s, MX, chart_top + chart_h + 0.12, CW, wl_h, wall_line, label="02 wall line")

    source_line(s, SRC2, "02")

    notes(s, [
        ("BEAT 2 - THERE IS NO IDENTIFIED RANKING          [0:20 - 0:48]   28 s   60 words", 13, True),
        ("", 11, False),
        ("SAY:", 12, True),
        ("We built FILED from mandatory filings only: EPA facility emissions, SEC financials. Then "
         "we tried to break it. Ten thousand runs over every defensible choice at once. The median "
         "company's rank band is 312 places wide out of 500. There is no identified ranking. Ours "
         "included. The weights everyone argues about are six percent of that. Missing data is "
         "twenty.", 16, True),
        ("", 11, False),
        ("STAGE: pause after \"ours included\". That sentence is what separates us from the five "
         "pitches before ours, and it needs air.", 11, False),
        ("", 11, False),
        ("WORDING: the slide reads \"There is no one ranking\" and you say \"no identified "
         "ranking\". Same claim. A judge who hears the term of art gets it; a judge who only "
         "reads the screen gets it too. If you prefer, say \"one\" and the two match exactly.", 11, False),
        ("", 11, False),
        ("CLOCK: start the demo on 0:48, on the word \"live\".", 11, False),
        ("", 11, False),
        ("ON SCREEN, left: 500 companies, one band each, sorted by median rank, coloured by "
         "coverage tier (measured 139, reported 88, not measurable 273). The accent bar above the "
         "plot is the median band, 312.5 ranks, drawn to the same scale. Right: first-order Sobol "
         "shares. The residual row, 47.5%, is interactions and what no single choice explains, and "
         "every bar is scaled to it.", 11, False),
        ("", 11, False),
        ("IF ASKED why we still have weights: someone has to choose them, and the industry argues "
         "about weights while never mentioning imputation. On the 139 we can measure, weights rise "
         "to 12.7 percent and become the largest single factor. We publish that too.", 11, False),
        ("", 11, False),
        ("SAY IT IF THERE IS ROOM: no vendor ESG score is an input to anything in this deck. It "
         "used to be the last sentence of the 8pt source line, where nobody read it. Inputs are "
         "EPA GHGRP under 40 CFR Part 98, EPA CAMD Part 75 and SEC XBRL.", 11, False),
    ])


# ---------------------------------------------------------------- slide 3
def slide_3(prs):
    s = new_slide(prs, "03")

    # One band of type across the top, then nothing but the recording. The
    # footnote used to float under the video, which put two text objects on a
    # slide whose whole job is to be a screen.
    strip = [Para("THE BONUS QUESTION: $1bn under a carbon price", 14, "mono",
                  False, INK2, 1.30, spc=90)]
    textbox(s, MX, 0.16, 7.0, block_height(strip, 7.0), strip, label="03 strip")

    # The most important caveat we own, and until now it was only inside a
    # screenshot. It gets 9pt of its own on the deck, on the slide the whole
    # model runs on.
    foot = [Para("An exposure model, not a forecast. $1bn is 0.00144% of the index.",
                 9, "sans", False, INK3, 1.30, align="r")]
    fw = 4.60
    textbox(s, SLIDE_W - MX - 1.35 - fw, 0.21, fw, block_height(foot, fw), foot,
            label="03 foot note")

    vx, vy, vw, vh = 1.19, 0.52, 10.95, 6.16   # 16:9, the recording's own ground
    # The GIF goes down first so it sits underneath the movie. If the movie
    # object does not survive the conference laptop, the animation is still on
    # the slide and still plays in slideshow.
    s.shapes.add_picture(os.path.join(DOCS, "demo.gif"), Inches(vx), Inches(vy),
                         Inches(vw), Inches(vh))
    s.shapes.add_movie(os.path.join(DOCS, "demo.mp4"), Inches(vx), Inches(vy),
                       Inches(vw), Inches(vh),
                       poster_frame_image=os.path.join(DOCS, "demo_poster.png"),
                       mime_type="video/mp4")

    source_line(s, SRC3, "03")

    notes(s, [
        ("BEAT 3 - THE DEMO          [0:48 - 1:38]   50.00 s   50 words spoken, 33 s silent", 13, True),
        ("Click the video to start it. Start it on the word \"live\".", 11, False),
        ("", 11, False),
        ("SAY over the opening frames  [0:48 - 0:51]:", 12, True),
        ("The bonus question, live. Watch the price. Then watch the weights.", 16, True),
        ("", 11, False),
        ("[0:51 - 1:08]  SILENT. HANDS STILL. Seventeen seconds, the longest silence in the "
         "talk and the one that earns the rest of it. The interface says it in its own words: "
         "the price moves nothing, the missing-data switch moves the money. Do not talk over it.",
         12, True),
        ("", 11, False),
        ("SAY over the last missing-data click and the tour  [1:08 - 1:22]:", 12, True),
        ("284 dollars a tonne to a thousand. Value at risk triples. Not one weight moves, because "
         "the allocation runs on rank. Switch how the 181 non-filers are treated and 123 million "
         "dollars moves.", 16, True),
        ("", 11, False),
        ("STAGE: \"because the allocation runs on rank\" is not optional. Eight words. The advice "
         "panel says the same thing on screen, and it takes the deck's one killable claim off the "
         "table before a judge can raise it.", 11, False),
        ("", 11, False),
        ("[1:22 - 1:38]  SILENT TO THE END. Sixteen seconds of the rank wall, the Paris-aligned "
         "waterfall and the coverage tiers, with no voice on them. Everything from 1:22 has "
         "already been said out loud. A demo that has to be explained is not a demo.",
         12, True),
        ("", 11, False),
        ("IF THE VIDEO DOES NOT PLAY:", 12, True),
        ("1. The animation is on this slide underneath the movie. Send the movie object behind, or "
         "delete it, and the GIF plays in slideshow on its own. It is also in the repo at "
         "docs/demo.gif, and docs/demo.mp4 will open in any player full screen.", 11, False),
        ("2. The site is live. Go to section 01 Allocate. The two states are one drag and one "
         "click apart: drag the carbon price to 1000 and nothing moves; click Leave them "
         "unscored under the 181 and the money moves.", 11, False),
        ("3. Play the file on the venue machine before the session, with the deck open behind it. "
         "A demo that will not start costs more than any slide.", 11, False),
        ("", 11, False),
        ("WHAT IS ON SCREEN, in order: 0:00 Allocate on Current Policies, 22 a tonne, under the "
         "question and the line that answers it. 0:03 the scenario goes to Net Zero 2050, 284 a "
         "tonne: the treemap lights up, share of value at risk goes 0.12% to 1.47%, and the "
         "panel prints \"Weights unchanged\", value at risk x12.61, largest weight change 0.00 "
         "bp. 0:07 the price is dragged to the floor and back to 284, the treemap goes dark and "
         "lights again, and the holdings never move. 0:11 one step to 1000 and the panel prints "
         "\"Weights unchanged\", value at risk x3.52, 0.00 bp, and its own sentence: the "
         "allocation runs on the rank of value at risk, and a scalar cannot reorder a ranking. "
         "Our book goes 1.47% to 5.20%, which is the tripling you say out loud. 0:16 the "
         "missing-data rule, three clicks: Treat them as zero, $141m to $244m and \"Weights "
         "moved\", 121 bp; Leave them unscored, $121m and priced falls 500 to 319; back to the "
         "sector median, $141m. 0:26 the argument and the three headline numbers. 0:29 say and "
         "do. 0:33 the rank wall. 0:38 the carbon-cut waterfall. 0:43 what we cannot see. 0:47 "
         "back to the opening frame, so the file loops.", 11, False),
        ("", 11, False),
        ("IF ASKED WHY $1bn: because it is the number the bonus question names. It is 0.00144% "
         "of the index, the book takes no price impact, and the method does not depend on the "
         "size of the book: every figure on the advice panel is a weight or a share.", 11, False),
        ("", 11, False),
        ("SAY THE $123m PRECISELY: what the 181 get moves by 123 million. Never \"123 million of "
         "the billion moves\". One-way turnover at the extreme is $107m, a different number.", 11, False),
        ("", 11, False),
        ("THE NUMBERS BEHIND THE CLAIM, which came off the 8pt line so it could be one line. "
         "Allocation sensitivity at a fixed tilt, over 3,000 runs: missing data 0.201, sector "
         "exemptions 0.051, Scope 3 coverage 0.007, price level 0.000. Prices are NGFS Phase 5 "
         "REMIND, Net Zero 2050, US, 2030, in US$2010 a tonne, deflated by 1.44. The full chain "
         "is price x deflator -> coverage -> abatement at the observed rate -> cost -> change in "
         "EBIT after sector pass-through -> change in EV at the company's own EV/EBITDA -> value "
         "at risk -> rank -> weight. Price DISPERSION across sectors does move weights; a uniform "
         "reprice cannot. slides/qa.md.", 11, False),
    ])


# ---------------------------------------------------------------- slide 4
def slide_4(prs):
    s = new_slide(prs, "04")

    head = [Para("A Paris-aligned fund sells the decarbonisers.", 36, "sans", True, INK, 1.16)]
    hh = block_height(head, CW)
    textbox(s, MX, 0.58, CW, hh, head, label="04 headline")

    top = 0.58 + hh + 0.30
    left_w = 4.25
    chart_bottom = 6.30

    # Centre the left column on the chart beside it. Top-aligning the figure
    # with the panel head left a quarter of the slide empty under the words
    # once the lambda line came off.
    fig_h = block_height([Para("97.4%", 96, "mono", True, ACCENT, 1.10)], left_w)
    cap_h = block_height([Para("of the carbon cut is money moving, not companies cutting",
                               19, "sans", False, INK2, 1.30)], left_w)
    l1_h = block_height([Para("Article 6 invites overweighting 19 companies cutting 7% a year. "
                              "Article 12 bans 9 of them.", 18, "mono", False, INK, 1.40)], left_w)
    left_h = fig_h + 0.06 + cap_h + 0.38 + l1_h

    y = top + (chart_bottom - top - left_h) / 2
    fig = [Para("97.4%", 96, "mono", True, ACCENT, 1.10)]
    fh = block_height(fig, left_w)
    textbox(s, MX, y, left_w, fh, fig, label="04 figure")
    y += fh + 0.06

    cap = [Para("of the carbon cut is money moving, not companies cutting",
                19, "sans", False, INK2, 1.30)]
    ch = block_height(cap, left_w)
    textbox(s, MX, y, left_w, ch, cap, label="04 figure caption")
    y += ch + 0.38

    # The one claim on this slide with no counter-example in it. It is what the
    # spoken script carries, so it is set at reading size, not as a footnote.
    l1 = [Para("Article 6 invites overweighting 19 companies cutting 7% a year. "
               "Article 12 bans 9 of them.", 18, "mono", False, INK, 1.40)]
    l1h = block_height(l1, left_w)
    textbox(s, MX, y, left_w, l1h, l1, label="04 mono line 1")
    assert y + l1h < 6.40, f"slide 4 left column runs to {y + l1h:.2f}"

    # The second mono line used to read "at lambda 120, an active share of
    # 70.5%, still 82.3% reallocation". Nobody in the room can read lambda 120.
    # It is a robustness answer and it lives in slides/qa.md, where it is asked.

    picture(s, os.path.join(IMG, "04_pab_waterfall_plain.png"),
            MX + left_w + 0.45, top, CW - left_w - 0.45, chart_bottom - top, align="r")

    source_line(s, SRC4, "04")

    notes(s, [
        ("BEAT 4 - A PARIS ALIGNED FUND SELLS THE DECARBONISERS          [1:38 - 2:02]   24 s   51 words", 13, True),
        ("", 11, False),
        ("SAY:", 12, True),
        ("The official answer is the EU Paris-Aligned Benchmark. We built it, article by article. "
         "97.4 percent of its carbon cut is reallocation, not companies cutting. [Article 6 "
         "invites you to overweight nineteen companies cutting seven percent a year. Article 12 "
         "bans nine of them.] It is a screen, not a strategy.", 16, True),
        ("", 11, False),
        ("CUT LINE: if you are behind at 1:38, drop the bracketed pair. It costs 8 seconds and "
         "nothing else, and the slide still carries it in print.", 12, True),
        ("", 11, False),
        ("IF ASKED whether the 97.4% survives a harder tilt: at lambda 120 the active share is "
         "70.5% and reallocation is still 82.3%. That line used to sit on the slide and nobody "
         "could read it at ten feet. It is in slides/qa.md.", 11, False),
        ("", 11, False),
        ("DO NOT SAY that the cross term is positive because a PAB sells the fastest cutters. It "
         "is true of the decomposition and it is the one sentence on this slide a judge can turn "
         "around: the compliant book's held names cut at 5.71 percent a year against the index's "
         "5.03. Article 6 against Article 12 is the same claim with no counter-example in it.", 11, False),
        ("", 11, False),
        ("ON SCREEN: the waterfall runs from the index in 2018 at 15.62 tCO2e per $m EVIC to the "
         "book in 2023 at 4.96. Improvement -2.18 (20.5% of the cut), reallocation -10.38 (97.4%), "
         "selection +0.01 (-0.1%), interaction +1.90 (-17.8%). The dashed line is the universe "
         "re-measured in 2023 at 13.44. Do not read the interaction term aloud either way; the "
         "sign convention is a trap and the bar shows it.", 11, False),
        ("", 11, False),
        ("IF ASKED why 97.4% is a finding rather than arithmetic: it is arithmetic nobody "
         "publishes, against a regulation whose Article 7 requires a 7 percent annual reduction a "
         "manager can satisfy entirely by trading. And if they point at our own book, 86.1% sector "
         "reallocation: correct, and we print it on our own page. The difference is the claim "
         "attached. We never say our book decarbonises anything.", 11, False),
        ("", 11, False),
        ("IF A SLIDE HAS TO GO, IT IS THIS ONE. Never slide 3, never slide 5.", 11, False),
    ])


# ---------------------------------------------------------------- slide 5
def slide_5(prs):
    s = new_slide(prs, "05")

    band_bottom = 1.78

    # The old headline read "What we cannot see, stated as a number." The number
    # is already set at 96pt beside it, so half that sentence described the
    # layout. Four words, and they are the four the speaker says.
    head = [Para("What we cannot see.", 36, "sans", True, INK, 1.16)]
    head_w = 5.20
    hh = block_height(head, head_w)
    textbox(s, MX, band_bottom - hh, head_w, hh, head, label="05 headline")

    fig = [Para("361", 96, "mono", True, MUTED, 1.10)]
    fig_x, fig_w = 5.95, 2.50
    fh = block_height(fig, fig_w)
    textbox(s, fig_x, band_bottom - fh, fig_w, fh, fig, label="05 figure")

    cap = [Para("companies file no emissions figure the law requires. We never invent one, "
                "and we never call it zero", 19, "sans", False, INK2, 1.28)]
    cap_x = fig_x + 2.71   # "361" at 96pt mono is 2.41 in wide
    cap_w = SLIDE_W - MX - cap_x
    ch = block_height(cap, cap_w)
    textbox(s, cap_x, band_bottom - ch, cap_w, ch, cap, label="05 figure caption")

    # Four rows, one per blind spot: the reporting floor, the border, the last
    # year of data, and the index churn. A fifth row used to repeat 361 of 500
    # under the 96pt 361, which is a slide restating itself.
    rows = [
        ("25,000 t", "below this, a US facility files nothing"),
        ("582.8", "million tonnes estimated abroad at 25 companies. We measure 375.7 here"),
        ("2023", "the last year EPA data covers. The next filing lands Oct 2026"),
        ("62 of 503", "left the index since Aug 2023. 37 still file with the SEC"),
    ]
    # The figures are right-aligned so the gutter is one width instead of four.
    num_w, gap = 3.05, 0.34
    lab_x = MX + num_w + gap
    lab_w = SLIDE_W - MX - lab_x
    y = 2.06
    row_h = 0.76
    for fign, label in rows:
        np_ = [Para(fign, 40, "mono", True, INK, 1.15, align="r")]
        nh = block_height(np_, num_w)
        textbox(s, MX, y, num_w, nh, np_, label=f"05 row figure {fign}")
        lp = [Para(label, 18, "sans", False, INK2, 1.32)]
        lh = block_height(lp, lab_w)
        textbox(s, lab_x, y, lab_w, max(lh, nh), lp, anchor="mid",
                label=f"05 row label {fign}")
        y += row_h

    y += 0.22
    rule(s, MX, y, CW)
    y += 0.30

    close = [Para("median rank 344 if we can measure you, 224 if we cannot", 26, "sans",
                  True, INK, 1.24)]
    clh = block_height(close, CW)
    textbox(s, MX, y, CW, clh, close, label="05 closing line")
    y += clh + 0.14

    sub = [Para("Rank 1 is best, so being measurable makes you look worse. That is the "
                "opposite of what vendors reward.", 18, "sans", False, INK2, 1.32)]
    sbh = block_height(sub, CW)
    textbox(s, MX, y, CW, sbh, sub, label="05 closing sub")
    assert y + sbh < 6.66, f"slide 5 runs to {y + sbh:.2f}"

    source_line(s, SRC5, "05")

    notes(s, [
        ("BEAT 5 - WHAT WE CANNOT SEE          [2:02 - 2:31]   29 s   60 words", 13, True),
        ("This is a scored criterion, not an apology. Same pace as everything else. Do not soften "
         "your voice.", 11, False),
        ("", 11, False),
        ("SAY:", 12, True),
        ("What we cannot see. US facilities only, above 25,000 tonnes. Twenty-five companies hold "
         "more emissions abroad than we measure here. EPA data stops at 2023. 139 of 500 carry a "
         "measured tonne. We impute nothing for the other 361. That costs us. In our index, being "
         "measurable makes your rank worse. That is the price of not making things up.", 16, True),
        ("", 11, False),
        ("STOP. Do not add \"thank you, any questions\". Let the last sentence sit.", 12, True),
        ("", 11, False),
        ("CLOCK: 150.9 s total at 130 words per minute, hard stop 3:00. 29 seconds of cushion. "
         "Even at 120 wpm this lands at 159 s.", 11, False),
        ("", 11, False),
        ("TWO LANES, DO NOT MIX THEM. 361 of 500 carry no mandatory tonnage: 88 tiered reported "
         "plus 273 unmeasurable. That is the score lane and it is the split the closing line is "
         "computed on. 181 of 500 carry no Scope 1 from any source: that is the allocation lane "
         "and it is the number in the demo caption. Rank 1 is best, so 344 is the worse position, "
         "and both the reported and unmeasurable tiers sit at 224.", 11, False),
        ("", 11, False),
        ("ROW 4 IS ABOUT THE INDEX, NOT ABOUT EXISTING. 62 of 503 left the index since Aug 2023 "
         "and 37 of them still file with the SEC. An overstated caveat is still a wrong number.", 11, False),
        ("", 11, False),
        ("THE AUDIT, IF PRESSED: 49 of 50 hand-checked matches correct, 98.0%, Wilson 95% "
         "interval 89.5% to 99.6%, on a tonnes-stratified random sample drawn with a fixed seed "
         "so a judge can redraw it. docs/entity_resolution_audit.md.", 11, False),
        ("", 11, False),
        ("ROW 2 IS AN ESTIMATE AND THE SLIDE SAYS SO. The 582.8 million tonnes abroad is sized "
         "with Climate TRACE, which is a model. It is never an input to a score or a weight, and "
         "it is on this slide only to size what we cannot see. The 375.7 beside it is measured. "
         "Chevron 9.1x, ExxonMobil 4.3x. docs/coverage_and_validation.md.", 11, False),
    ])


# ---------------------------------------------------------------- appendix
def slide_a(prs):
    s = new_slide(prs, "A")

    kick = [Para("APPENDIX   Q&A BACKUP   NOT PART OF THE 2:30", 14, "mono", False,
                 ACCENT, 1.30, spc=90)]
    textbox(s, MX, 0.46, 8.0, block_height(kick, 8.0), kick, label="A kicker")

    head = [Para("Water is a second axis, not a restatement of carbon.", 30, "sans",
                 True, INK, 1.18)]
    hh = block_height(head, CW)
    textbox(s, MX, 0.96, CW, hh, head, label="A headline")

    top = 0.96 + hh + 0.36
    left_w = 7.55

    body = [
        Para("Carbon explains 0.3% of the water ranking.", 20, "sans", False, INK, 1.34,
             space_after=4),
        Para("rank correlation 0.058, p = 0.51, n = 135", 16, "mono", False, ACCENT, 1.40,
             space_after=22),
        Para("Broadcom   7th percentile on carbon. Its one US facility sits in an Extremely "
             "High stress basin.", 18, "sans", False, INK2, 1.34, space_after=14),
        Para("Evergy   99th percentile on carbon, our most carbon-intense company. None of its "
             "24 facilities sit in a stressed basin.", 18, "sans", False, INK2, 1.34,
             space_after=22),
        Para("One number would put them in the same place. So water is a separate axis in the "
             "interface, and it is not in the score.", 18, "sans", False, INK3, 1.34),
    ]
    bh = block_height(body, left_w)
    # The crop is taller than the words, so the words sit on its middle rather
    # than leaving a quarter of the slide empty under them.
    textbox(s, MX, top + (CONTENT_BOTTOM - top - bh) / 2, left_w, bh, body, label="A body")

    # The full-page capture is a grey smear at slide size. Crop it to the one
    # thing a questioner asked about: the treemap with its CARBON / WATER
    # toggle and the high-stress ramp above it. The box is the bounding box of
    # the middle column in the 1280x720 capture, measured, not guessed. It moved
    # left and grew when the nav became a 48px rail.
    shot = Image.open(os.path.join(DOCS, "water_axis.png")).convert("RGB")
    buf = io.BytesIO()
    shot.crop((343, 70, 971, 682)).save(buf, format="PNG")
    buf.seek(0)
    pic_w = CW - left_w - 0.50
    picture(s, buf, SLIDE_W - MX - pic_w, top, pic_w, CONTENT_BOTTOM - top, align="r")

    source_line(s, SRCA, "A")

    notes(s, [
        ("APPENDIX. NOT PART OF THE 2:30. Do not advance to this slide during the pitch.", 13, True),
        ("", 11, False),
        ("Use it only if asked why water is not in the score.", 11, False),
        ("", 11, False),
        ("ANSWER: because it is a second axis, not a restatement. Spearman 0.058, p=0.51, n=135, "
         "so carbon explains 0.3 percent of the water ranking. 57.3 percent of US semiconductor "
         "reporting facilities sit in High or Extremely High stress while the sector is near the "
         "clean end on carbon. Broadcom and Evergy are the pair: Evergy is the most carbon-intense "
         "company in the covered set, 4,224 t CO2e per $m revenue, and has zero water exposure "
         "today; Broadcom is at 0.96, the 7th percentile on carbon, and is 100 percent exposed. "
         "Any score that reduces both to one number puts them in the same place. Across the 86 "
         "companies with 5 or more facilities, 25 have a water percentile and a carbon percentile "
         "more than 40 points apart.", 11, False),
        ("", 11, False),
        ("The picture is the site's own treemap with the CARBON / WATER toggle set to WATER, "
         "cropped out of the allocate view. It is the control a questioner can watch us move "
         "live, at #allocate.", 11, False),
        ("", 11, False),
        ("THE JOIN: 11,200 of 11,358 EPA reporting facilities matched an Aqueduct basin by "
         "point-in-polygon, 98.6%, giving 142 of 503 tickers a water score.", 11, False),
        ("", 11, False),
        ("Do companies that talk about water manage it better? No measurable difference: the 34 "
         "companies that name water most have 34.5 percent of facilities stressed, the quietest 34 "
         "have 31.8, Mann-Whitney p=0.44, and only 34 of 6,942 voluntary disclosure documents "
         "mention water in the title.", 11, False),
    ])


# ---------------------------------------------------------------- verify
def verify(path: str):
    prs = Presentation(path)
    errs, warns = [], []

    if len(prs.slides) != 6:
        errs.append(f"slide count is {len(prs.slides)}, expected 6 (5 + appendix)")

    w_in = prs.slide_width / 914400
    h_in = prs.slide_height / 914400
    if abs(w_in - 13.3333) > 0.01 or abs(h_in - 7.5) > 0.01:
        errs.append(f"slide size is {w_in:.3f} x {h_in:.3f} in, expected 13.333 x 7.5")

    pics = movies = 0
    for i, slide in enumerate(prs.slides, start=1):
        for sh in slide.shapes:
            if sh.shape_type == 13 or sh.__class__.__name__ == "Picture":
                pics += 1
                if sh.width <= 0 or sh.height <= 0:
                    errs.append(f"slide {i}: picture has zero size")
                if sh.left < -1 or sh.top < -1:
                    warns.append(f"slide {i}: picture starts off-canvas")
                if sh.left + sh.width > prs.slide_width + 1000 or \
                   sh.top + sh.height > prs.slide_height + 1000:
                    errs.append(f"slide {i}: picture runs off the slide")
            if sh.has_text_frame:
                tf = sh.text_frame
                for p in tf.paragraphs:
                    for r in p.runs:
                        if r.font.size is None:
                            warns.append(f"slide {i}: a run has no explicit size")
                # re-measure against the shape box
                box_w = sh.width / 914400
                box_h = sh.height / 914400
                need = 0.0
                for p in tf.paragraphs:
                    for r in p.runs:
                        size = r.font.size.pt
                        kind = "mono" if r.font.name == MONO else "sans"
                        n = len(wrap(r.text, kind, bool(r.font.bold), size, box_w))
                        ls = p.line_spacing.pt if p.line_spacing is not None else size * 1.2
                        need += n * ls
                        if p.space_after is not None:
                            need += p.space_after.pt
                if need / 72.0 > box_h + 0.02:
                    errs.append(f"slide {i}: text frame overflows its box "
                                f"({need / 72.0:.3f} in in {box_h:.3f} in): {tf.text[:50]!r}")
        if slide.has_notes_slide:
            txt = slide.notes_slide.notes_text_frame.text.strip()
            if i <= 5 and len(txt) < 200:
                errs.append(f"slide {i}: speaker notes are missing or too short")
        else:
            errs.append(f"slide {i}: no notes slide")
        movies += sum(1 for sh in slide.shapes if sh.element.find(
            "{http://schemas.openxmlformats.org/presentationml/2006/main}nvPicPr") is not None
            and "video" in sh.element.xml)

    # slide 3 has to carry a click-triggered movie with the GIF underneath it
    s3 = prs.slides[2]
    xml3 = s3.element.xml
    if "<p:video>" not in xml3:
        errs.append("slide 3: no movie timing node, the video will not play on click")
    if 'delay="indefinite"' not in xml3:
        warns.append("slide 3: the movie trigger is not the on-click one")
    shp = list(s3.shapes)
    gif_i = mov_i = None
    for i, sh in enumerate(shp):
        if "demo.gif" in (sh.name or "") or (sh._element.xml.count("descr=\"demo.gif\"")):
            gif_i = i
        if "videoFile" in sh._element.xml:
            mov_i = i
    if gif_i is None:
        errs.append("slide 3: docs/demo.gif is not on the slide")
    if mov_i is None:
        errs.append("slide 3: the movie shape is missing")
    if gif_i is not None and mov_i is not None:
        if gif_i > mov_i:
            errs.append("slide 3: the GIF sits above the movie instead of behind it")
        g, m = shp[gif_i], shp[mov_i]
        if (g.left, g.top, g.width, g.height) != (m.left, m.top, m.width, m.height):
            warns.append("slide 3: the GIF and the movie are not on the same rectangle")

    media = [p for p in prs.part.package.iter_parts()
             if "video" in str(p.content_type) or "gif" in str(p.content_type)]
    kinds = sorted({str(p.content_type) for p in media})
    if not any("video/mp4" in k for k in kinds):
        errs.append("no video/mp4 part in the package")
    if not any("gif" in k for k in kinds):
        errs.append("no image/gif part in the package")

    print(f"  slides        {len(prs.slides)}")
    print(f"  size          {w_in:.3f} x {h_in:.3f} in")
    print(f"  pictures      {pics}")
    print(f"  media parts   {kinds}")
    print(f"  bytes         {os.path.getsize(path):,}")
    for w in warns:
        print(f"  warn  {w}")
    for e in errs:
        print(f"  FAIL  {e}")
    return not errs


# ---------------------------------------------------------------- main
def main():
    prs = Presentation()
    prs.slide_width = Emu(12192000)
    prs.slide_height = Emu(6858000)

    slide_1(prs)
    slide_2(prs)
    slide_3(prs)
    slide_4(prs)
    slide_5(prs)
    slide_a(prs)

    prs.save(OUT)
    print(f"wrote {OUT}")
    if PROBLEMS:
        for p in PROBLEMS:
            print("  note  " + p)
    print("verifying")
    ok = verify(OUT)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
