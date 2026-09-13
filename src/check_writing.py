#!/usr/bin/env python3
"""Grep the shipped corpus for AI-writing patterns and count them per file.

Run before and after an anti-AI-writing pass:

    nix develop --command .venv/bin/python src/check_writing.py

Add --verbose to print every hit with its line number, or pass file paths to
check something other than the default corpus.

The vocabulary list and the shape list both come from the project owner's
brief. Shapes matter more than vocabulary: a header reads as machine-written
because of its shape, not because of one word in it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CORPUS = [
    "slides/outline.md",
    "slides/script.md",
    "src/build_deck.py",
    "site/index.html",
    "site/js/allocate.js",
    "site/js/coverage.js",
    "site/js/data.js",
    "site/js/portfolio.js",
    "site/js/ranks.js",
    "site/js/saydo.js",
    "README.md",
    "data/README.md",
]

# --- vocabulary -----------------------------------------------------------
# Each entry matches the word and its inflected forms.
VOCAB = [
    r"leverag(?:e|es|ed|ing)",
    r"robust(?:ly|ness)?",
    r"comprehensiv(?:e|ely)",
    r"seamless(?:ly)?",
    r"delv(?:e|es|ed|ing)",
    r"utilis(?:e|es|ed|ing)|utiliz(?:e|es|ed|ing)",
    r"unlock(?:s|ed|ing)?",
    r"empower(?:s|ed|ing|ment)?",
    r"streamlin(?:e|es|ed|ing)",
    r"cutting[- ]edge",
    r"game[- ]chang(?:er|ers|ing)",
    r"pivotal",
    r"underscor(?:e|es|ed|ing)",
    r"testament to",
    r"meticulous(?:ly)?",
    r"holistic(?:ally)?",
    r"actionable",
    r"impactful",
    r"in today's world",
    r"it'?s worth noting",
    r"that being said",
    r"at the end of the day",
    r"deep dive|dive into|diving into",
]

# --- hollow intensifiers --------------------------------------------------
INTENSIFIERS = [
    r"genuine(?:ly)?",
    r"truly",
    r"\breal\b(?!\s+(?:Estate|estate|minus))(?=\s+[a-z]+\b)",
    r"\bactual(?:ly)?\b",
    r"\bsimply\b",
]

# --- shapes ---------------------------------------------------------------
# Patterns are (name, compiled regex, scope) where scope is "line" or "text".
SHAPES: list[tuple[str, str, str]] = [
    # "It is not X, it is Y" joined form, plus the bare "not X, but Y" pivot.
    ("not-x-but-y",
     r"\b(?:is|are|was|were|it'?s|that'?s|this is)\s+not\s+[^.!?\n]{1,60}?[,;]\s*(?:it'?s|it is|they are|but)\b",
     "line"),
    # "X, not Y" tail reveal: a clause closing on a negated counterpart.
    ("x-not-y-tail",
     r",\s+not\s+(?:a|an|the|what|how|companies|money|an?\s)?[^.!?\n]{0,40}[.!?]",
     "line"),
    # Split form across two sentences: a negation sentence followed by the reveal.
    ("split-negation",
     r"(?:is|are|was|were)\s+not\s+[^.!?\n]{1,70}[.!?]\s+(?:It|They|The real|What|Ours)\b",
     "text"),
    # Aphorism formula: "X is the language/currency/story of Y".
    ("aphorism-formula",
     r"\bis\s+the\s+(?:language|currency|story|architecture|art|heart|engine|backbone|essence|price)\s+of\b",
     "line"),
    # Self-negating definition aphorism: "A demo that has to be explained is not a demo."
    ("aphorism-self-negation",
     r"\b(?:A|An|The)\s+(\w+)\s+that\s+[^.!?\n]{3,60}\s+is\s+not\s+(?:a|an|the)\s+\1\b",
     "text"),
    # Participial headline: a heading whose main verb is a bare participle.
    ("participial-headline",
     r"^\s*(?:#{1,6}\s+|\*\*)?[A-Z][^.!?\n]{0,60},\s+\w+(?:ed|ing)\s+(?:on|by|for|with|in|to)\b",
     "line"),
    # Rhetorical-question section header.
    ("rhetorical-question-header",
     r"^\s*#{1,6}\s+[^\n]*\?\s*$",
     "line"),
    ("heres-whats-interesting",
     r"[Hh]ere'?s (?:what|the|why)\b[^.\n]{0,40}(?:interesting|matters|caught|stood out|the thing)",
     "line"),
    # Copula avoidance.
    ("copula-avoidance",
     r"\b(?:serves? as|serving as|boasts?|features\s+(?:a|an|the|two|three|four|five|\d))\b",
     "line"),
    # Em dashes, both the unicode dash and the double-hyphen substitute.
    # Em dash proper, plus the double-hyphen prose substitute. CSS custom
    # properties (var(--accent)), JS decrements and HTML comments are not
    # prose splices, so the substitute only counts with whitespace or word
    # characters on both sides.
    ("em-dash", r"\u2014|(?<=\s)--(?=\s)", "text"),
    # Manufactured staccato: three or more short fragments in a row.
    ("staccato-triple",
     r"(?:^|[.!?]\s)((?:[A-Z][^.!?\n]{2,34}[.!?]\s+){2}[A-Z][^.!?\n]{2,34}[.!?])",
     "text"),
    # Transition tics.
    ("transition-tic",
     r"^\s*(?:Moreover|Furthermore|Additionally|In conclusion|In summary|That said)\b",
     "line"),
]

SKIP_HTML_ATTR = re.compile(r"<[^>]+>")


def _strip_noise(path: Path, text: str) -> str:
    """Blank out spans where a hit is not prose: base64 blobs, long data URIs."""
    text = re.sub(r"data:[a-zA-Z0-9/;+=]{80,}", " ", text)
    # An em dash that is the whole of a quoted token is the "no data" glyph a
    # table cell prints, not a prose splice. BEM class names (al-col--assume)
    # and JS decrements are excluded by the em-dash pattern itself.
    text = re.sub(r"(['\"])\u2014\1", " ", text)
    return text


def scan(path: Path, verbose: bool = False):
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = _strip_noise(path, raw)
    lines = text.splitlines()
    counts: dict[str, int] = {}
    hits: list[tuple[str, int, str]] = []

    def record(name: str, lineno: int, snippet: str) -> None:
        counts[name] = counts.get(name, 0) + 1
        hits.append((name, lineno, snippet.strip()[:110]))

    for pat in VOCAB:
        rx = re.compile(rf"\b(?:{pat})\b", re.I)
        for i, line in enumerate(lines, 1):
            for m in rx.finditer(line):
                record(f"vocab:{m.group(0).lower()}", i, line)

    for pat in INTENSIFIERS:
        rx = re.compile(rf"\b(?:{pat})", re.I)
        for i, line in enumerate(lines, 1):
            for m in rx.finditer(line):
                record(f"intensifier:{m.group(0).lower()}", i, line)

    for name, pat, scope in SHAPES:
        rx = re.compile(pat, re.M)
        if scope == "line":
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    record(f"shape:{name}", i, line)
        else:
            for m in rx.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                record(f"shape:{name}", lineno, m.group(0).replace("\n", " "))

    if verbose:
        for name, lineno, snippet in sorted(hits, key=lambda h: h[1]):
            print(f"    {path.name}:{lineno}  [{name}]  {snippet}")

    return counts


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    targets = [Path(a) for a in args] if args else [ROOT / p for p in CORPUS]

    grand: dict[str, int] = {}
    total = 0
    print(f"{'file':<26} {'vocab':>6} {'intens':>7} {'shapes':>7} {'total':>6}")
    print("-" * 56)
    for path in targets:
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            print(f"{path.name:<26} {'MISSING':>29}")
            continue
        counts = scan(path, verbose=verbose)
        v = sum(n for k, n in counts.items() if k.startswith("vocab:"))
        i = sum(n for k, n in counts.items() if k.startswith("intensifier:"))
        s = sum(n for k, n in counts.items() if k.startswith("shape:"))
        rel = str(path.relative_to(ROOT)) if ROOT in path.parents else path.name
        print(f"{rel:<26} {v:>6} {i:>7} {s:>7} {v + i + s:>6}")
        total += v + i + s
        for k, n in counts.items():
            grand[k] = grand.get(k, 0) + n

    print("-" * 56)
    print(f"{'TOTAL':<26} {'':>6} {'':>7} {'':>7} {total:>6}")
    if grand:
        print("\nby pattern:")
        for k, n in sorted(grand.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {n:>4}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
